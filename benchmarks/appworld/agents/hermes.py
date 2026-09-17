"""Hermes adapter for AppWorld evaluation."""

from __future__ import annotations

import os
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig
from loguru import logger

from benchmarks.appworld.agents.base import APPWORLD_AGENT_PROMPT, AppWorldInvokeResult
from benchmarks.appworld.agents.tool_loop import run_tool_react_loop
from benchmarks.appworld.agents.tools import create_eval_llm


def _missing_hermes_error() -> RuntimeError:
    return RuntimeError("hermes is not installed. Install with: uv sync --group appworld --group hermes")


class HermesAppWorldAgent:
    """Hermes client with ReAct tool loop over AppWorld LangChain tools."""

    def __init__(
        self,
        tools: list[Any],
        *,
        model: str | None = None,
        max_steps: int = 12,
        system_prompt: str = APPWORLD_AGENT_PROMPT,
        prefer_eval_llm: bool = False,
    ) -> None:
        self.tools = tools
        self.model_name = model or os.getenv("APPWORLD_AGENT_MODEL") or os.getenv("MODEL_NAME", "hermes-3")
        self.max_steps = max_steps
        self.system_prompt = system_prompt
        self.prefer_eval_llm = prefer_eval_llm
        self._client: Any = None
        self._llm: Any = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from hermes.client import HermesClient
        except ImportError as exc:
            raise _missing_hermes_error() from exc

        self._client = HermesClient()
        return self._client

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
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

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

    async def _call_hermes_chat(
        self,
        convo: list[dict[str, str]],
        *,
        invoke_callbacks: Optional[list[Any]] = None,
    ) -> str:
        if self.prefer_eval_llm:
            return await self._call_eval_llm(convo, invoke_callbacks=invoke_callbacks)

        try:
            client = self._ensure_client()
            messages = [{"role": m["role"], "content": m["content"]} for m in convo]
            response = client.chat(model=self.model_name, messages=messages)
            content = getattr(response, "content", None) or getattr(response, "text", None)
            if content is None and isinstance(response, dict):
                content = response.get("content") or response.get("text")
            if content is not None:
                return content if isinstance(content, str) else str(content)
        except Exception as exc:
            logger.warning(f"Hermes chat failed, falling back to eval LLM: {exc}")

        return await self._call_eval_llm(convo, invoke_callbacks=invoke_callbacks)

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

        return await run_tool_react_loop(
            tools=self.tools,
            system_prompt=self.system_prompt,
            intent=intent,
            user_context=user_context,
            call_llm=self._call_hermes_chat,
            max_steps=self.max_steps,
            track_tool_calls=track_tool_calls,
            invoke_callbacks=invoke_callbacks,
        )
