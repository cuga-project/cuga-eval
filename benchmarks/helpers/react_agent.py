"""Generic lightweight ReAct agent utilities for benchmark evaluation.

This module provides a benchmark-agnostic ReAct-style agent that:
- loads tools from the existing CombinedToolProvider
- iteratively reasons, selects tool calls, and observes results
- returns an invoke-like result compatible with the existing evaluation helpers

The intent is to preserve the current benchmark result/evaluation/reporting flow
while swapping only the agent execution layer for `--agent react`.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from cuga.backend.cuga_graph.nodes.cuga_lite.combined_tool_provider import (
    CombinedToolProvider,
)
from langchain_core.messages import HumanMessage
from loguru import logger

TOOL_BLOCK_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
PROMPT_ROLE_RE = re.compile(r"(USER|ASSISTANT|SYSTEM):\n", re.IGNORECASE)
PROMPT_PATH = Path(__file__).with_name("react_agent_prompt.txt")


@dataclass
class ReactToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReactInvokeResult:
    answer: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw_messages: list[dict[str, str]] = field(default_factory=list)


class GenericReactAgent:
    """Prompt-template driven generic ReAct agent over benchmark tools."""

    def __init__(
        self,
        tool_provider: CombinedToolProvider,
        callbacks: Optional[list[Any]] = None,
        model: Optional[str] = None,
        max_steps: int = 8,
        special_instructions: Optional[str] = None,
    ) -> None:
        self.tool_provider = tool_provider
        self.callbacks = callbacks or []
        self.model = model or "gpt-4o-mini"
        self.max_steps = max_steps
        self.special_instructions = special_instructions or ""
        self._tools_cache: Optional[list[Any]] = None
        self.prompt_template = PROMPT_PATH.read_text(encoding="utf-8").lstrip()

    async def _get_tools(self) -> list[Any]:
        if self._tools_cache is None:
            self._tools_cache = await self.tool_provider.get_all_tools()
        return self._tools_cache

    async def _build_tools_prompt(self) -> str:
        tools = await self._get_tools()
        tool_lines: list[str] = []
        for tool in tools:
            name = getattr(tool, "name", "unknown_tool")
            description = getattr(tool, "description", "") or ""
            tool_lines.append(f"- {name}: {description}".strip())
        return "\n".join(tool_lines)

    def _text_to_messages(self, input_str: str) -> list[dict[str, str]]:
        messages_json: list[dict[str, str]] = []
        last_start = 0
        for match in PROMPT_ROLE_RE.finditer(input_str):
            last_end = match.span()[0]
            if not messages_json:
                if last_end != 0:
                    raise ValueError(f"Start of prompt has no assigned role: {input_str[:last_end]}")
            else:
                messages_json[-1]["content"] = input_str[last_start:last_end]
            role = match.group(1).lower()
            messages_json.append({"role": role, "content": ""})
            last_start = match.span()[1]
        if not messages_json:
            raise ValueError("Prompt template must contain at least one role marker.")
        messages_json[-1]["content"] = input_str[last_start:]
        return messages_json

    async def _build_initial_messages(
        self,
        user_query: str,
        user_context: str,
    ) -> list[dict[str, str]]:
        tools_prompt = await self._build_tools_prompt()
        prompt = self.prompt_template
        prompt = prompt.replace("{{ instruction }}", str(user_query).strip())
        prompt = prompt.replace("{{ tool_descriptions }}", tools_prompt.strip())

        benchmark_instructions = user_context.strip() if user_context else ""
        special_instructions = self.special_instructions.strip()

        if special_instructions:
            benchmark_instructions = (
                f"{benchmark_instructions}\n\n{special_instructions}".strip()
                if benchmark_instructions
                else special_instructions
            )

        prompt = prompt.replace(
            "{{ benchmark_instructions }}",
            benchmark_instructions if benchmark_instructions else "None.",
        )
        return self._text_to_messages(prompt)

    async def _call_llm(self, messages: list[dict[str, str]]) -> str:
        """Call LLM using LangChain wrappers for automatic Langfuse tracking."""
        settings_config = os.getenv("AGENT_SETTING_CONFIG", "").strip()

        # Convert messages to LangChain format
        from langchain_core.messages import AIMessage, SystemMessage
        from langchain_core.messages import HumanMessage as LCHumanMessage

        lc_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "user":
                lc_messages.append(LCHumanMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
            else:
                # Default to user message
                lc_messages.append(LCHumanMessage(content=content))

        if settings_config == "settings.groq.toml":
            try:
                from langchain_groq import ChatGroq
                from pydantic import SecretStr
            except ImportError as exc:
                raise RuntimeError(
                    "langchain-groq is required for React agent with Groq. "
                    "Install with: pip install langchain-groq"
                ) from exc

            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise RuntimeError("GROQ_API_KEY is required when AGENT_SETTING_CONFIG=settings.groq.toml")

            base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com").rstrip("/")

            llm = ChatGroq(
                model=self.model,
                temperature=0,
                api_key=SecretStr(api_key),
                base_url=base_url,
            )

        elif settings_config == "settings.openai.toml":
            try:
                from langchain_openai import ChatOpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "langchain-openai is required for React agent with OpenAI. "
                    "Install with: pip install langchain-openai"
                ) from exc

            # Handle SSL verification (matching CUGA's LLMManager)
            disable_ssl = os.getenv("CUGA_DISABLE_SSL", "").lower() in ("true", "1", "yes")
            ssl_verify = (
                os.getenv("OPENAI_SSL_VERIFY", "true").lower() not in ("false", "0", "no") and not disable_ssl
            )

            logger.info(
                f"SSL verification: {ssl_verify} (OPENAI_SSL_VERIFY={os.getenv('OPENAI_SSL_VERIFY')}, CUGA_DISABLE_SSL={os.getenv('CUGA_DISABLE_SSL')})"
            )

            # Get API configuration
            api_base = os.getenv("LITE_LLM_URL") or os.getenv("OPENAI_BASE_URL")
            api_key = os.getenv("LITE_LLM_KEY") or os.getenv("OPENAI_API_KEY")

            logger.info(f"OpenAI config: model={self.model}, api_base={api_base}, ssl_verify={ssl_verify}")

            # Build ChatOpenAI kwargs
            llm_kwargs: dict[str, Any] = {
                "model": self.model,
                "temperature": 0,
            }

            if api_base:
                llm_kwargs["base_url"] = api_base.rstrip("/")

            if api_key:
                llm_kwargs["api_key"] = api_key

            # Handle SSL verification
            if not ssl_verify:
                import httpx

                llm_kwargs["http_client"] = httpx.Client(verify=False)  # noqa: S501  # nosec B501 — opt-in for self-signed corporate endpoints
                llm_kwargs["http_async_client"] = httpx.AsyncClient(verify=False)  # noqa: S501  # nosec B501 — same
                logger.info("SSL verification disabled for ChatOpenAI")

            llm = ChatOpenAI(**llm_kwargs)

        else:
            raise RuntimeError(
                "Unsupported AGENT_SETTING_CONFIG for React agent. "
                "Expected 'settings.groq.toml' or 'settings.openai.toml'."
            )

        # Invoke LLM with callbacks for Langfuse tracking
        from langchain_core.runnables import RunnableConfig

        if self.callbacks:
            config = RunnableConfig(callbacks=self.callbacks)
            response = await llm.ainvoke(lc_messages, config=config)
        else:
            response = await llm.ainvoke(lc_messages)

        # Extract content from response
        content = response.content if hasattr(response, 'content') else str(response)
        return content if isinstance(content, str) else str(content)

    def _extract_tool_request(self, text: str) -> Optional[ReactToolCall]:
        match = TOOL_BLOCK_RE.search(text)
        if not match:
            return None
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

        if not isinstance(payload, dict):
            return None
        action = payload.get("action")
        if action != "tool":
            return None

        name = payload.get("tool_name")
        if not isinstance(name, str) or not name:
            return None

        args = payload.get("args", {})
        if not isinstance(args, dict):
            args = {}

        return ReactToolCall(name=name, args=args)

    def _extract_final_answer(self, text: str) -> Optional[str]:
        marker = "Final Answer:"
        if marker in text:
            return text.split(marker, 1)[1].strip()
        return None

    def _normalize_tool_args(self, args: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(args)
        for key in list(args.keys()):
            snake_key = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
            if snake_key not in normalized:
                normalized[snake_key] = args[key]
        return normalized

    def _summarize_observation(self, result: Any) -> str:
        if isinstance(result, dict):
            summary_candidates = []
            for key in (
                "answer",
                "result",
                "summary",
                "message",
                "lowest_source",
                "lowest_sla_source",
                "recommended_source",
            ):
                value = result.get(key)
                if value not in (None, "", [], {}):
                    summary_candidates.append(f"{key}={value}")
            if "data" in result and isinstance(result["data"], list) and result["data"]:
                preview = result["data"][:3]
                summary_candidates.append(f"data_preview={preview}")
            elif "data" in result and isinstance(result["data"], dict) and result["data"]:
                preview_items = list(result["data"].items())[:5]
                summary_candidates.append(f"data_preview={dict(preview_items)}")
            if summary_candidates:
                return " | ".join(summary_candidates)
        return ""

    async def _execute_tool(self, tool_name: str, args: dict[str, Any]) -> str:
        tools = await self._get_tools()
        tool = next((t for t in tools if getattr(t, "name", None) == tool_name), None)
        if tool is None:
            return f"Tool '{tool_name}' not found."

        normalized_args = self._normalize_tool_args(args)

        try:
            if hasattr(tool, "invoke"):
                result = tool.invoke(normalized_args)
                if asyncio.iscoroutine(result):
                    result = await result
            elif hasattr(tool, "ainvoke"):
                result = await tool.ainvoke(normalized_args)
            elif callable(tool):
                result = tool(**normalized_args)
                if asyncio.iscoroutine(result):
                    result = await result
            else:
                return f"Tool '{tool_name}' is not invokable."
        except Exception as exc:
            logger.warning(f"ReAct tool call failed for {tool_name}: {exc}")
            return f"Tool execution error for '{tool_name}': {exc}"

        summary = self._summarize_observation(result)
        try:
            payload = json.dumps(result, ensure_ascii=False, default=str)
        except TypeError:
            payload = str(result)

        if summary:
            return f"{summary}\n\nFull output:\n{payload}"
        return payload

    async def invoke(
        self,
        messages: list[HumanMessage],
        thread_id: str,
        user_context: str = "",
        track_tool_calls: bool = True,
    ) -> ReactInvokeResult:
        del thread_id

        user_query = messages[-1].content if messages else ""
        convo = await self._build_initial_messages(
            user_query=str(user_query),
            user_context=user_context,
        )
        tool_calls: list[dict[str, Any]] = []

        for step in range(1, self.max_steps + 1):
            logger.info(f"[REACT] Step {step}/{self.max_steps}")
            llm_text = await self._call_llm(convo)
            logger.info(f"[REACT] Model output at step {step}: {llm_text}")
            convo.append({"role": "assistant", "content": llm_text})

            final_answer = self._extract_final_answer(llm_text)
            if final_answer is not None:
                if not tool_calls:
                    logger.warning(
                        "[REACT] Final answer emitted before any tool call at step %s; rejecting and forcing tool usage.",
                        step,
                    )
                    convo.append(
                        {
                            "role": "user",
                            "content": (
                                "Output:\n```\n"
                                "Invalid response flow. You must use at least one listed tool before giving the final answer. "
                                "All benchmark facts are available only through tool outputs. Call the most relevant tool now.\n"
                                "```\n\n"
                            ),
                        }
                    )
                    continue
                logger.info(f"[REACT] Final answer emitted at step {step}: {final_answer}")
                return ReactInvokeResult(
                    answer=final_answer,
                    tool_calls=tool_calls if track_tool_calls else [],
                    raw_messages=convo,
                )

            tool_request = self._extract_tool_request(llm_text)
            if tool_request is None:
                logger.warning(
                    "[REACT] Invalid model output at step %s; expected exactly one fenced JSON tool call "
                    "or 'Final Answer: ...'. Feeding format error back to model.",
                    step,
                )
                convo.append(
                    {
                        "role": "user",
                        "content": (
                            "Output:\n```\n"
                            "Invalid response format. You must either:\n"
                            "1. return exactly one tool request inside ```json fences, or\n"
                            "2. return `Final Answer: ...`\n"
                            "Do not answer from prior knowledge. If you have not used the required tools yet, "
                            "call the next tool now.\n"
                            "```\n\n"
                        ),
                    }
                )
                continue

            logger.info(f"[REACT] Tool request at step {step}: {tool_request.name} args={tool_request.args}")
            if track_tool_calls:
                tool_calls.append({"name": tool_request.name, "arguments": dict(tool_request.args)})

            observation = await self._execute_tool(tool_request.name, tool_request.args)
            logger.info(f"[REACT] Observation at step {step}: {observation}")
            convo.append(
                {
                    "role": "user",
                    "content": f"Output:\n```\n{observation}\n```\n\n",
                }
            )

        return ReactInvokeResult(
            answer="Unable to complete within max steps.",
            tool_calls=tool_calls if track_tool_calls else [],
            raw_messages=convo,
        )


async def setup_react_agent_with_tools(
    special_instructions: Optional[str] = None,
) -> tuple[GenericReactAgent, Optional[Any]]:
    """Set up the generic ReAct agent with existing benchmark tools/Langfuse callback."""
    from .sdk_eval_helpers import setup_langfuse

    logger.info("Setting up generic ReAct evaluator...")

    tool_provider = CombinedToolProvider()
    await tool_provider.initialize()
    all_tools = await tool_provider.get_all_tools()
    logger.info(f"Loaded {len(all_tools)} tools for ReAct agent")

    langfuse_handler = setup_langfuse()
    callbacks = [langfuse_handler] if langfuse_handler else []

    agent = GenericReactAgent(
        tool_provider=tool_provider,
        callbacks=callbacks,
        model=os.getenv("MODEL_NAME"),
        special_instructions=special_instructions,
    )
    return agent, langfuse_handler


# Made with Bob
