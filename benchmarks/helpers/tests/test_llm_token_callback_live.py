"""Live LLM smoke tests: TokenUsageCallback captures usage without Langfuse."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from benchmarks.helpers.token_usage import TokenUsageCallback

pytestmark = pytest.mark.regression

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

CACHE_PROMPT = (
    "Return exactly one word: pong. Do not add punctuation or explanation."
)


def _disable_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DYNACONF_ADVANCED_FEATURES__LANGFUSE_TRACING", "false")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)


def _require_reachable_base_url(env_key: str) -> str:
    from urllib.parse import urlparse

    base = (os.getenv(env_key) or os.getenv("OPENAI_BASE_URL") or "").strip().strip('"')
    if not base:
        pytest.skip(f"{env_key} or OPENAI_BASE_URL not set")
    host = urlparse(base).hostname
    if not host:
        pytest.skip(f"Invalid base URL: {base!r}")
    import socket

    try:
        socket.getaddrinfo(host, None)
    except OSError:
        pytest.skip(f"LiteLLM host unreachable from this environment: {host}")
    return base


def _assert_basic_usage(callback: TokenUsageCallback) -> None:
    assert callback.llm_calls >= 1, "expected at least one LLM call"
    assert callback.input_tokens > 0, "expected non-zero input tokens from callback"
    assert callback.output_tokens > 0, "expected non-zero output tokens from callback"
    assert callback.total_tokens == callback.input_tokens + callback.output_tokens


async def _call_llm_with_callback(setting: str) -> TokenUsageCallback:
    from benchmarks.appworld.agents.tools import create_eval_llm

    prev_setting = os.environ.get("AGENT_SETTING_CONFIG")
    os.environ["AGENT_SETTING_CONFIG"] = setting
    try:
        llm = create_eval_llm()
    finally:
        if prev_setting is None:
            os.environ.pop("AGENT_SETTING_CONFIG", None)
        else:
            os.environ["AGENT_SETTING_CONFIG"] = prev_setting

    callback = TokenUsageCallback()
    callback.reset()
    await llm.ainvoke([HumanMessage(content=CACHE_PROMPT)], config={"callbacks": [callback]})
    return callback


@pytest.mark.asyncio
async def test_groq_callback_tokens_without_langfuse(monkeypatch: pytest.MonkeyPatch):
    if not os.getenv("GROQ_API_KEY"):
        pytest.skip("GROQ_API_KEY not set")
    _disable_langfuse(monkeypatch)

    first = await _call_llm_with_callback("settings.groq.toml")
    _assert_basic_usage(first)

    second = await _call_llm_with_callback("settings.groq.toml")
    _assert_basic_usage(second)
    assert second.cache_input_tokens >= 0


@pytest.mark.asyncio
async def test_ete_litellm_callback_tokens_without_langfuse(monkeypatch: pytest.MonkeyPatch):
    base = _require_reachable_base_url("LITE_LLM_URL")
    if not base.startswith("https://ete"):
        pytest.skip("OPENAI_BASE_URL/LITE_LLM_URL must start with https://ete (IBM LiteLLM)")
    if not (os.getenv("LITE_LLM_KEY") or os.getenv("OPENAI_API_KEY")):
        pytest.skip("OPENAI_API_KEY or LITE_LLM_KEY required for LiteLLM live test")
    if not os.getenv("MODEL_NAME"):
        pytest.skip("MODEL_NAME required for LiteLLM live test")
    _disable_langfuse(monkeypatch)

    first = await _call_llm_with_callback("settings.openai.toml")
    _assert_basic_usage(first)

    second = await _call_llm_with_callback("settings.openai.toml")
    _assert_basic_usage(second)
    assert second.cache_input_tokens >= 0
