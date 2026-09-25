"""Deep Agents adapter for AppWorld evaluation."""

from __future__ import annotations

import copy
import hashlib
import os
import re
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger

from benchmarks.appworld.agents.base import APPWORLD_AGENT_PROMPT, AppWorldInvokeResult
from benchmarks.appworld.agents.tool_loop import run_tool_react_loop
from benchmarks.appworld.agents.tools import create_eval_llm, max_llm_bound_tools


def _missing_deepagents_error() -> RuntimeError:
    return RuntimeError(
        "deepagents is not installed. Install with: uv sync --group appworld --group deepagents"
    )


BEDROCK_TOOL_NAME_MAX_LENGTH = 64
_BEDROCK_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _bedrock_safe_tool_name(name: str, *, hash_length: int = 10) -> str:
    """Return a deterministic Bedrock-compatible name for a tool."""
    if len(name) <= BEDROCK_TOOL_NAME_MAX_LENGTH and _BEDROCK_TOOL_NAME_RE.fullmatch(name):
        return name
    normalized = re.sub(r"[^A-Za-z0-9_-]", "_", name)
    digest = hashlib.sha256(name.encode()).hexdigest()[:hash_length]
    prefix_length = BEDROCK_TOOL_NAME_MAX_LENGTH - hash_length - 1
    return f"{normalized[:prefix_length]}_{digest}"


def _copy_tool_with_name(tool: Any, name: str) -> Any:
    """Copy a LangChain-compatible tool while preserving its implementation."""
    if getattr(tool, "name", None) == name:
        return tool
    if hasattr(tool, "model_copy"):
        return tool.model_copy(update={"name": name})
    cloned = copy.copy(tool)
    cloned.name = name
    return cloned


def _alias_tools_for_bedrock(tools: list[Any]) -> tuple[list[Any], dict[str, str]]:
    """Alias provider-invalid tool names and return alias-to-original mapping."""
    aliased_tools: list[Any] = []
    alias_to_original: dict[str, str] = {}
    used_names: set[str] = set()
    for tool in tools:
        original_name = str(getattr(tool, "name", "unknown_tool"))
        hash_length = 10
        alias = _bedrock_safe_tool_name(original_name, hash_length=hash_length)
        while alias in used_names and alias_to_original.get(alias) != original_name:
            hash_length += 2
            alias = _bedrock_safe_tool_name(original_name, hash_length=hash_length)
        used_names.add(alias)
        alias_to_original[alias] = original_name
        aliased_tools.append(_copy_tool_with_name(tool, alias))
    return aliased_tools, alias_to_original


def _extract_tool_calls_from_messages(
    messages: list[Any], alias_to_original: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    tool_results: dict[str, str] = {}

    for msg in messages:
        if isinstance(msg, ToolMessage):
            call_id = getattr(msg, "tool_call_id", None)
            if call_id:
                tool_results[str(call_id)] = str(msg.content)

    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue
        for tc in getattr(msg, "tool_calls", None) or []:
            if isinstance(tc, dict):
                call_id = str(tc.get("id", ""))
                name = tc.get("name", "unknown")
                args = tc.get("args", {})
            else:
                call_id = str(getattr(tc, "id", ""))
                name = getattr(tc, "name", "unknown")
                args = getattr(tc, "args", {})
            original_name = (alias_to_original or {}).get(name, name)
            tool_calls.append(
                {
                    "name": original_name,
                    "arguments": args,
                    "result": tool_results.get(call_id),
                }
            )
    return tool_calls


def _last_assistant_content(messages: list[Any]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [p.get("text", "") for p in content if isinstance(p, dict)]
                return "\n".join(p for p in parts if p)
    if messages:
        last = messages[-1]
        content = getattr(last, "content", last)
        return content if isinstance(content, str) else str(content)
    return ""


class DeepAgentsAppWorldAgent:
    """Wraps LangChain Deep Agents with AppWorld registry tools."""

    def __init__(
        self,
        tools: list[Any],
        *,
        model: str | None = None,
        max_steps: int = 12,
        system_prompt: str = APPWORLD_AGENT_PROMPT,
        max_bound_tools: int | None = None,
        prefer_tool_react: bool = False,
        shortlist_size: int | None = None,
    ) -> None:
        self.tools = tools
        self.model_name = model or os.getenv("APPWORLD_AGENT_MODEL") or os.getenv("MODEL_NAME")
        self.max_steps = max_steps
        self.system_prompt = system_prompt
        self.max_bound_tools = max_bound_tools if max_bound_tools is not None else max_llm_bound_tools()
        requested_size = (
            shortlist_size
            if shortlist_size is not None
            else int(os.getenv("APPWORLD_DEEPAGENTS_MAX_TOOLS", "128"))
        )
        if requested_size < 1 or self.max_bound_tools < 1:
            raise ValueError("Deep Agents tool limits must be positive integers")
        self.shortlist_size = min(requested_size, self.max_bound_tools)
        self.prefer_tool_react = prefer_tool_react
        self._agent: Any = None
        self._llm: Any = None
        self._alias_to_original: dict[str, str] = {}

    def set_tools(self, tools: list[Any]) -> None:
        self.tools = tools
        self._agent = None
        self._alias_to_original = {}

    def _should_use_tool_react(self) -> bool:
        # The selector caps tools before model binding, even for large catalogs.
        return self.prefer_tool_react

    def _ensure_llm(self) -> Any:
        if self._llm is None:
            self._llm = create_eval_llm(self.model_name)
        return self._llm

    async def _call_eval_llm(
        self,
        convo: list[dict[str, str]],
        *,
        invoke_callbacks: Optional[list[Any]] = None,
    ) -> str:
        from langchain_core.messages import AIMessage as LCAIMessage
        from langchain_core.messages import HumanMessage as LCHumanMessage
        from langchain_core.messages import SystemMessage

        lc_messages = []
        for msg in convo:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "assistant":
                lc_messages.append(LCAIMessage(content=content))
            else:
                lc_messages.append(LCHumanMessage(content=content))

        llm = self._ensure_llm()
        invoke_kwargs: dict[str, Any] = {}
        if invoke_callbacks:
            invoke_kwargs["config"] = RunnableConfig(callbacks=invoke_callbacks)
        response = await llm.ainvoke(lc_messages, **invoke_kwargs)
        content = response.content if hasattr(response, "content") else str(response)
        return content if isinstance(content, str) else str(content)

    def _ensure_agent(self) -> Any:
        if self._agent is not None:
            return self._agent
        try:
            from deepagents import create_deep_agent
        except ImportError as exc:
            raise _missing_deepagents_error() from exc

        from langchain.agents.middleware import LLMToolSelectorMiddleware

        llm = self._ensure_llm()
        native_tools, self._alias_to_original = _alias_tools_for_bedrock(self.tools)

        # Use the configured model instance so selection keeps the same proxy/key.
        # No always_include tools: the cap includes DeepAgents' built-in tools.
        def selector() -> LLMToolSelectorMiddleware:
            return LLMToolSelectorMiddleware(model=llm, max_tools=self.shortlist_size)

        self._agent = create_deep_agent(
            model=llm,
            tools=native_tools,
            system_prompt=self.system_prompt,
            middleware=[selector()],
            # Custom main-agent middleware is not inherited by the default
            # general-purpose subagent. Override it explicitly with a selector.
            subagents=[
                {
                    "name": "general-purpose",
                    "description": "Delegate an AppWorld subtask to an agent with the same tool catalog.",
                    "system_prompt": self.system_prompt,
                    "model": llm,
                    "tools": native_tools,
                    "middleware": [selector()],
                }
            ],
        )
        logger.info(
            f"Deep Agents agent created with {len(native_tools)} available AppWorld tools "
            f"({sum(alias != original for alias, original in self._alias_to_original.items())} "
            "provider-safe aliases); "
            f"LLM tool selector binds at most {self.shortlist_size} tools per model call"
        )
        return self._agent

    async def invoke(
        self,
        *,
        intent: str,
        thread_id: str,
        user_context: str = "",
        track_tool_calls: bool = True,
        config: Optional[dict[str, Any]] = None,
    ) -> AppWorldInvokeResult:
        invoke_callbacks = (config or {}).get("callbacks")

        if self._should_use_tool_react():
            return await run_tool_react_loop(
                tools=self.tools,
                system_prompt=self.system_prompt,
                intent=intent,
                user_context=user_context,
                call_llm=self._call_eval_llm,
                max_steps=self.max_steps,
                track_tool_calls=track_tool_calls,
                invoke_callbacks=invoke_callbacks,
            )

        agent = self._ensure_agent()
        user_content = intent.strip()
        if user_context.strip():
            user_content = f"{user_content}\n\nContext:\n{user_context.strip()}"

        invoke_config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        if config:
            invoke_config.update(config)

        try:
            if hasattr(agent, "ainvoke"):
                result = await agent.ainvoke(
                    {"messages": [HumanMessage(content=user_content)]},
                    config=invoke_config,
                )
            else:
                result = agent.invoke(
                    {"messages": [HumanMessage(content=user_content)]},
                    config=invoke_config,
                )

            messages = result.get("messages", []) if isinstance(result, dict) else []
            answer = _last_assistant_content(messages)
            tool_calls = (
                _extract_tool_calls_from_messages(messages, self._alias_to_original)
                if track_tool_calls
                else []
            )
            react_steps = sum(1 for m in messages if isinstance(m, AIMessage))

            return AppWorldInvokeResult(
                answer=answer or "N/A",
                tool_calls=tool_calls,
                react_steps=react_steps or None,
            )
        except Exception as exc:
            err = str(exc)
            if "tools" in err.lower() and "too long" in err.lower():
                logger.warning(f"Deep Agents tool binding failed ({err}); falling back to ReAct loop")
                return await run_tool_react_loop(
                    tools=self.tools,
                    system_prompt=self.system_prompt,
                    intent=intent,
                    user_context=user_context,
                    call_llm=self._call_eval_llm,
                    max_steps=self.max_steps,
                    track_tool_calls=track_tool_calls,
                    invoke_callbacks=invoke_callbacks,
                )
            logger.error(f"Deep Agents invoke failed: {exc}")
            return AppWorldInvokeResult(answer="N/A", error=err)
