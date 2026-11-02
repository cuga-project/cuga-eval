"""Normalize external-agent answers using CUGA's AppWorld plain final-answer prompts."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Callable, Optional

from loguru import logger

from benchmarks.appworld.agents.tools import create_eval_llm


def skip_final_answer_format() -> bool:
    return os.getenv("APPWORLD_SKIP_FINAL_ANSWER_FORMAT", "").lower() in ("1", "true", "yes")


@lru_cache(maxsize=1)
def _load_appworld_plain_prompt() -> tuple[Any, Callable[[str], str]]:
    from cuga.backend.cuga_graph.nodes.answer.final_answer_agent.prompts.load_prompt import (
        load_appworld_plain_final_answer_prompt,
        parse_appworld_plain_completion,
    )

    return load_appworld_plain_final_answer_prompt(), parse_appworld_plain_completion


async def format_appworld_final_answer(
    intent: str,
    raw_answer: str,
    *,
    llm: Any | None = None,
    invoke_config: Optional[dict[str, Any]] = None,
) -> str:
    """Run CUGA's AppWorld plain final-answer formatter on a raw agent answer."""
    prompt_template, parse_completion = _load_appworld_plain_prompt()
    model = llm or create_eval_llm()

    messages = prompt_template.format_messages(
        input=intent.strip(),
        last_planner_answer=(raw_answer or "").strip(),
    )

    invoke_kwargs: dict[str, Any] = {}
    if invoke_config:
        invoke_kwargs["config"] = invoke_config

    response = await model.ainvoke(messages, **invoke_kwargs)
    content = response.content if hasattr(response, "content") else str(response)
    text = content if isinstance(content, str) else str(content)
    formatted = parse_completion(text)
    logger.info(f"AppWorld final-answer format: {raw_answer!r} -> {formatted!r}")
    return formatted


async def maybe_format_appworld_final_answer(
    intent: str,
    raw_answer: str,
    *,
    llm: Any | None = None,
    invoke_config: Optional[dict[str, Any]] = None,
) -> str:
    if skip_final_answer_format():
        return raw_answer
    if not (raw_answer or "").strip():
        return raw_answer
    try:
        return await format_appworld_final_answer(
            intent,
            raw_answer,
            llm=llm,
            invoke_config=invoke_config,
        )
    except Exception as exc:
        logger.warning(f"AppWorld final-answer formatting failed ({exc}); using raw answer")
        return raw_answer
