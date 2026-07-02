#!/usr/bin/env python3
"""Smoke-test external agents (deepagents, openclaw, hermes) against configured LLM.

No CUGA agent, no AppWorld servers, no MCP registry — only verifies that each
adapter can call the model from .env (AGENT_SETTING_CONFIG + MODEL_NAME + keys).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv(project_root / ".env")

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from loguru import logger

from benchmarks.appworld.agents.factory import EXTERNAL_AGENT_NAMES, create_appworld_agent
from benchmarks.appworld.agents.tools import create_eval_llm
from benchmarks.helpers.token_usage import TokenUsageCallback

SMOKE_SYSTEM_PROMPT = (
    "You are running a connectivity smoke test. Follow instructions exactly. "
    "When asked to use a tool, emit one JSON tool call block, then after seeing "
    "the tool result respond with a line starting with 'Final Answer:'."
)


@tool
def ping(message: str) -> str:
    """Echo test tool. Returns pong with the given message."""
    return f"pong:{message}"


SMOKE_INTENT = (
    "Smoke test: call the ping tool with message 'hello'. "
    "After you see the tool result, respond with exactly: Final Answer: success"
)


def _validate_llm_env() -> None:
    setting = os.getenv("AGENT_SETTING_CONFIG", "").strip()
    model = os.getenv("MODEL_NAME", "").strip()
    if not setting:
        raise RuntimeError("AGENT_SETTING_CONFIG is not set (e.g. settings.openai.toml)")
    if not model:
        raise RuntimeError("MODEL_NAME is not set")

    if setting == "settings.openai.toml":
        key = os.getenv("LITE_LLM_KEY") or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY or LITE_LLM_KEY is required for settings.openai.toml")
        base = os.getenv("LITE_LLM_URL") or os.getenv("OPENAI_BASE_URL")
        logger.info(f"OpenAI-compatible LLM: model={model!r} base_url={base!r}")
    elif setting == "settings.groq.toml":
        if not os.getenv("GROQ_API_KEY"):
            raise RuntimeError("GROQ_API_KEY is required for settings.groq.toml")
        logger.info(f"Groq LLM: model={model!r}")
    else:
        raise RuntimeError(
            f"Unsupported AGENT_SETTING_CONFIG={setting!r}. "
            "Use settings.openai.toml or settings.groq.toml"
        )


async def check_llm_only() -> str:
    """Direct ChatOpenAI/ChatGroq call — fastest way to verify model + keys."""
    llm = create_eval_llm()
    response = await llm.ainvoke([HumanMessage(content="Reply with exactly: OK")])
    content = response.content if hasattr(response, "content") else str(response)
    text = content if isinstance(content, str) else str(content)
    logger.info(f"LLM direct response: {text[:200]}")
    return text


async def smoke_agent(
    agent_name: str,
    *,
    prefer_eval_llm: bool,
    max_steps: int,
) -> dict:
    tools = [ping]
    kwargs: dict = {"max_steps": max_steps, "system_prompt": SMOKE_SYSTEM_PROMPT}
    if agent_name in ("openclaw", "hermes"):
        kwargs["prefer_eval_llm"] = prefer_eval_llm

    agent = create_appworld_agent(agent_name, tools=tools, **kwargs)
    thread_id = f"smoke_{agent_name}_{uuid.uuid4().hex[:8]}"
    token_callback = TokenUsageCallback()
    token_callback.reset()

    logger.info(f"--- Smoke: {agent_name} (prefer_eval_llm={prefer_eval_llm}) ---")
    result = await agent.invoke(
        intent=SMOKE_INTENT,
        thread_id=thread_id,
        user_context="Smoke test context.",
        track_tool_calls=True,
        config={"callbacks": [token_callback]},
    )

    ok = (
        result.error is None
        and "success" in (result.answer or "").lower()
        and len(result.tool_calls or []) >= 1
        and token_callback.total_tokens > 0
        and token_callback.llm_calls >= 1
    )
    return {
        "agent": agent_name,
        "ok": ok,
        "answer": result.answer,
        "tool_calls": len(result.tool_calls or []),
        "steps": result.react_steps,
        "error": result.error,
        "total_tokens": token_callback.total_tokens,
        "total_llm_calls": token_callback.llm_calls,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test deepagents/openclaw/hermes against configured LLM (no CUGA/AppWorld)"
    )
    parser.add_argument(
        "--agents",
        default="deepagents,openclaw,hermes",
        help=f"Comma-separated agents (default: deepagents,openclaw,hermes). Choices: {', '.join(sorted(EXTERNAL_AGENT_NAMES))}",
    )
    parser.add_argument(
        "--native-sdk",
        action="store_true",
        help="Try OpenClaw/Hermes native SDK (default: use eval LLM only)",
    )
    parser.add_argument(
        "--skip-llm-check",
        action="store_true",
        help="Skip direct LLM connectivity check",
    )
    parser.add_argument("--max-steps", type=int, default=6, help="Max ReAct steps per agent")
    args = parser.parse_args()

    prefer_eval_llm = not args.native_sdk

    try:
        _validate_llm_env()
    except RuntimeError as exc:
        logger.error(str(exc))
        return 1

    agent_names = [a.strip().lower() for a in args.agents.split(",") if a.strip()]
    unknown = set(agent_names) - EXTERNAL_AGENT_NAMES
    if unknown:
        logger.error(f"Unknown agents: {unknown}")
        return 1

    if not args.skip_llm_check:
        try:
            text = await check_llm_only()
            if "OK" not in text.upper():
                logger.warning("Direct LLM check returned unexpected text (continuing anyway)")
            else:
                logger.info("Direct LLM check passed")
        except Exception as exc:
            logger.error(f"Direct LLM check failed: {exc}")
            return 1

    results = []
    failed = 0
    for name in agent_names:
        try:
            row = await smoke_agent(name, prefer_eval_llm=prefer_eval_llm, max_steps=args.max_steps)
        except Exception as exc:
            row = {"agent": name, "ok": False, "error": str(exc), "answer": "", "tool_calls": 0, "steps": None}
        results.append(row)
        status = "PASS" if row["ok"] else "FAIL"
        logger.info(
            f"[{status}] {name}: answer={row.get('answer', '')!r} "
            f"tools={row.get('tool_calls', 0)} tokens={row.get('total_tokens', 0)} "
            f"llm_calls={row.get('total_llm_calls', 0)} error={row.get('error')}"
        )
        if not row["ok"]:
            failed += 1

    print("\n=== Smoke summary ===")
    for row in results:
        mark = "✓" if row["ok"] else "✗"
        print(f"  {mark} {row['agent']}: {row.get('answer', '')[:80]}")
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
