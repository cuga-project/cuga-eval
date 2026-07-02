"""OpenClaw adapter for AppWorld evaluation."""

from __future__ import annotations

import os
from typing import Any, Optional

from loguru import logger

from benchmarks.appworld.agents.base import APPWORLD_AGENT_PROMPT, AppWorldInvokeResult
from benchmarks.appworld.agents.tool_loop import run_tool_react_loop
from benchmarks.appworld.agents.tools import create_eval_llm, execute_tool_by_name


def _missing_openclaw_error() -> RuntimeError:
    return RuntimeError(
        "openclaw is not installed. Install with: uv sync --group appworld --group openclaw"
    )


class OpenClawAppWorldAgent:
    """OpenClaw agent with LangChain tool bridge for AppWorld MCP tools."""

    def __init__(
        self,
        tools: list[Any],
        *,
        model: str | None = None,
        max_steps: int = 12,
        system_prompt: str = APPWORLD_AGENT_PROMPT,
        agent_name: str = "AppWorld_Agent",
        prefer_eval_llm: bool = False,
    ) -> None:
        self.tools = tools
        self.model_name = model or os.getenv("APPWORLD_AGENT_MODEL") or os.getenv("MODEL_NAME", "gpt-4o-mini")
        self.max_steps = max_steps
        self.system_prompt = system_prompt
        self.agent_name = agent_name
        self.prefer_eval_llm = prefer_eval_llm
        self._client: Any = None
        self._agent_id: str | None = None
        self._llm: Any = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openclaw import OpenClawClient
        except ImportError as exc:
            raise _missing_openclaw_error() from exc

        self._client = OpenClawClient()
        return self._client

    def _ensure_openclaw_agent(self) -> str:
        if self._agent_id is not None:
            return self._agent_id

        client = self._ensure_client()
        tool_names = [getattr(t, "name", str(i)) for i, t in enumerate(self.tools)]
        agent = client.agents.create(
            name=self.agent_name,
            model=self.model_name,
            description="AppWorld benchmark agent using registry MCP tools.",
            tools=tool_names,
        )
        self._agent_id = agent.id
        logger.info(f"OpenClaw agent created: {self._agent_id} with {len(tool_names)} tools")
        return self._agent_id

    def _ensure_llm(self) -> Any:
        if self._llm is None:
            self._llm = create_eval_llm(self.model_name)
        return self._llm

    async def _call_llm_via_openclaw(
        self,
        convo: list[dict[str, str]],
        *,
        invoke_callbacks: Optional[list[Any]] = None,
    ) -> str:
        del invoke_callbacks
        client = self._ensure_client()
        agent_id = self._ensure_openclaw_agent()
        task = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in convo)
        execution = client.agents.run(agent_id=agent_id, task=task)
        content = getattr(execution, "output", None) or getattr(execution, "result", None)
        if content is None and isinstance(execution, dict):
            content = execution.get("output") or execution.get("result")
        if content is None:
            content = str(execution)
        return content if isinstance(content, str) else str(content)

    async def _call_llm_fallback(
        self,
        convo: list[dict[str, str]],
        *,
        invoke_callbacks: Optional[list[Any]] = None,
    ) -> str:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        from langchain_core.runnables import RunnableConfig

        lc_messages = []
        for msg in convo:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
            else:
                lc_messages.append(HumanMessage(content=content))

        llm = self._ensure_llm()
        invoke_kwargs: dict[str, Any] = {}
        if invoke_callbacks:
            invoke_kwargs["config"] = RunnableConfig(callbacks=invoke_callbacks)
        response = await llm.ainvoke(lc_messages, **invoke_kwargs)
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
        del thread_id
        invoke_callbacks = (config or {}).get("callbacks")

        if self.prefer_eval_llm:
            return await run_tool_react_loop(
                tools=self.tools,
                system_prompt=self.system_prompt,
                intent=intent,
                user_context=user_context,
                call_llm=self._call_llm_fallback,
                max_steps=self.max_steps,
                track_tool_calls=track_tool_calls,
                invoke_callbacks=invoke_callbacks,
            )

        try:
            self._ensure_client()
            openclaw_result = await self._call_llm_via_openclaw(
                [
                    {"role": "system", "content": self.system_prompt},
                    {
                        "role": "user",
                        "content": f"{intent}\n\nContext:\n{user_context}".strip(),
                    },
                ],
                invoke_callbacks=invoke_callbacks,
            )

            from benchmarks.appworld.agents.tool_loop import extract_final_answer, extract_tool_request

            final_answer = extract_final_answer(openclaw_result)
            tool_request = extract_tool_request(openclaw_result)
            if final_answer is not None or tool_request is not None:
                tool_calls: list[dict[str, Any]] = []
                if tool_request:
                    name, args = tool_request
                    observation = await execute_tool_by_name(self.tools, name, args)
                    tool_calls.append({"name": name, "arguments": args, "result": observation})
                return AppWorldInvokeResult(
                    answer=final_answer or openclaw_result,
                    tool_calls=tool_calls if track_tool_calls else [],
                    react_steps=1,
                )
        except Exception as exc:
            logger.warning(f"OpenClaw direct run failed, falling back to tool ReAct loop: {exc}")

        return await run_tool_react_loop(
            tools=self.tools,
            system_prompt=self.system_prompt,
            intent=intent,
            user_context=user_context,
            call_llm=self._call_llm_fallback,
            max_steps=self.max_steps,
            track_tool_calls=track_tool_calls,
            invoke_callbacks=invoke_callbacks,
        )
