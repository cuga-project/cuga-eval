"""Template adapter. Copy this file to add another agent to the comparison.

Run it as-is to check your harness before you write any agent code:

    ./benchmarks/appworld/eval.sh --agent stub --task 82e2fac_1

That exercises the whole path — AppWorld servers, registry, CombinedToolProvider,
tool execution, scoring — using the shared eval LLM and the shared ReAct tool
loop. If `--agent stub` scores and `--agent <yours>` does not, the problem is in
your adapter, not in the harness.

To add your own agent:

1. Copy this file to `benchmarks/appworld/agents/<yours>.py` and rename the class.
2. Replace `_call_llm` with a call into your framework. That is the only method
   that has to change; everything else is harness plumbing you should leave alone.
3. Register it in `factory.py`: add the name to `EXTERNAL_AGENT_NAMES` and a
   branch to `create_appworld_agent`.
4. Add the name to `is_external_agent` in `benchmarks/appworld/eval.sh`.
5. Run `--agent <yours> --task 82e2fac_1` and compare against `--agent stub`.

What you must NOT change, because it is what makes the comparison fair:

- Tools come from `CombinedToolProvider` via `setup_appworld_tools`. Do not build
  your own tool list, do not call the AppWorld APIs directly, and do not hand your
  agent a hand-picked subset. `benchmarks/appworld/tests/test_tool_provider_parity.py`
  asserts this and will fail if you do.
- The system prompt is `APPWORLD_AGENT_PROMPT`. Take it as a parameter, as here,
  so a caller can override it for an ablation — but do not bake a different
  default into your adapter.
- Return an `AppWorldInvokeResult`. The evaluator reads `answer` for scoring and
  `tool_calls` for the trajectory; a missing `tool_calls` list makes the run look
  like the agent never acted.

If your framework does its own tool calling (native function calling, its own
ReAct loop), skip `run_tool_react_loop` entirely and hand it the `self.tools`
list directly — see `deepagents.py` for that shape. Use this file's shape only
when your agent is a plain chat model that has to be told about tools in text.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from benchmarks.appworld.agents.base import APPWORLD_AGENT_PROMPT, AppWorldInvokeResult
from benchmarks.appworld.agents.tool_loop import run_tool_react_loop
from benchmarks.appworld.agents.tools import create_eval_llm


class StubAppWorldAgent:
    """A plain chat model driving the shared ReAct tool loop. No framework."""

    def __init__(
        self,
        tools: list[Any],
        *,
        model: str | None = None,
        max_steps: int = 12,
        system_prompt: str = APPWORLD_AGENT_PROMPT,
    ) -> None:
        self.tools = tools
        self.model_name = model or os.getenv("APPWORLD_AGENT_MODEL") or os.getenv("MODEL_NAME")
        self.max_steps = max_steps
        self.system_prompt = system_prompt
        self._llm: Any = None

    async def _call_llm(
        self,
        convo: list[dict[str, str]],
        *,
        invoke_callbacks: Optional[list[Any]] = None,
    ) -> str:
        """Replace this with a call into your framework.

        `convo` is a list of {"role", "content"} dicts, oldest first. Return the
        assistant's reply as a string; the shared loop parses the tool request or
        the final answer out of it.

        Pass `invoke_callbacks` through to whatever actually calls the model.
        They carry the TokenUsageCallback, so dropping them silently zeroes this
        agent's token and cost columns in the comparison.
        """
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        if self._llm is None:
            self._llm = create_eval_llm(self.model_name)

        role_to_message = {"system": SystemMessage, "assistant": AIMessage}
        lc_messages = [
            role_to_message.get(msg.get("role", "user"), HumanMessage)(content=msg.get("content", ""))
            for msg in convo
        ]

        invoke_kwargs: dict[str, Any] = {}
        if invoke_callbacks:
            invoke_kwargs["config"] = RunnableConfig(callbacks=invoke_callbacks)
        response = await self._llm.ainvoke(lc_messages, **invoke_kwargs)

        content = response.content if hasattr(response, "content") else str(response)
        return content if isinstance(content, str) else str(content)

    async def invoke(
        self,
        *,
        intent: str,
        thread_id: str,
        user_context: str = "",
        track_tool_calls: bool = True,
        config: Optional[dict[str, Any]] = None,
    ) -> AppWorldInvokeResult:
        """Harness plumbing. Leave this as it is.

        `thread_id` is unused here: the shared loop keeps the conversation in
        memory for one task and nothing is resumed across tasks.
        """
        del thread_id

        return await run_tool_react_loop(
            tools=self.tools,
            system_prompt=self.system_prompt,
            intent=intent,
            user_context=user_context,
            call_llm=self._call_llm,
            max_steps=self.max_steps,
            track_tool_calls=track_tool_calls,
            invoke_callbacks=(config or {}).get("callbacks"),
        )
