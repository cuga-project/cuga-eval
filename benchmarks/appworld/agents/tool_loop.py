"""Shared ReAct-style tool loop for agents without native tool binding."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from loguru import logger

from benchmarks.appworld.agents.base import AppWorldInvokeResult
from benchmarks.appworld.agents.tools import build_tools_prompt, execute_tool_by_name

TOOL_BLOCK_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def extract_tool_request(text: str) -> tuple[str, dict[str, Any]] | None:
    match = TOOL_BLOCK_RE.search(text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict) or payload.get("action") != "tool":
        return None

    name = payload.get("tool_name")
    if not isinstance(name, str) or not name:
        return None

    args = payload.get("args", {})
    if not isinstance(args, dict):
        args = {}
    return name, args


def extract_final_answer(text: str) -> str | None:
    marker = "Final Answer:"
    if marker in text:
        return text.split(marker, 1)[1].strip()
    return None


async def run_tool_react_loop(
    *,
    tools: list[Any],
    system_prompt: str,
    intent: str,
    user_context: str,
    call_llm: Callable[..., Any],
    max_steps: int = 12,
    track_tool_calls: bool = True,
    invoke_callbacks: Optional[list[Any]] = None,
) -> AppWorldInvokeResult:
    tools_prompt = build_tools_prompt(tools)
    user_message = (
        f"{intent.strip()}\n\n"
        f"Context:\n{user_context.strip()}\n\n"
        f"Available tools:\n{tools_prompt}\n\n"
        "Use tools by returning exactly one JSON block:\n"
        '```json\n{"action": "tool", "tool_name": "<name>", "args": {...}}\n```\n'
        "When done, respond with: Final Answer: <answer>"
    )

    convo = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    tool_calls: list[dict[str, Any]] = []

    for step in range(1, max_steps + 1):
        logger.info(f"[TOOL-REACT] Step {step}/{max_steps}")
        llm_text = await call_llm(convo, invoke_callbacks=invoke_callbacks)
        convo.append({"role": "assistant", "content": llm_text})

        final_answer = extract_final_answer(llm_text)
        if final_answer is not None:
            if not tool_calls:
                convo.append(
                    {
                        "role": "user",
                        "content": (
                            "You must call at least one tool before giving a final answer. "
                            "Call the most relevant tool now using the JSON format."
                        ),
                    }
                )
                continue
            return AppWorldInvokeResult(
                answer=final_answer,
                tool_calls=tool_calls if track_tool_calls else [],
                react_steps=step,
            )

        tool_request = extract_tool_request(llm_text)
        if tool_request is None:
            convo.append(
                {
                    "role": "user",
                    "content": (
                        "Invalid format. Return either a ```json tool call block or "
                        "'Final Answer: ...'."
                    ),
                }
            )
            continue

        tool_name, args = tool_request
        observation = await execute_tool_by_name(tools, tool_name, args)
        tool_call_record = {"name": tool_name, "arguments": args, "result": observation}
        tool_calls.append(tool_call_record)
        convo.append({"role": "user", "content": f"Tool result for {tool_name}:\n{observation}"})

    return AppWorldInvokeResult(
        answer="N/A",
        tool_calls=tool_calls if track_tool_calls else [],
        react_steps=max_steps,
        error="Max steps reached without final answer",
    )
