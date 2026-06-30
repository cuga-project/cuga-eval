"""Unit tests for the OpenCode runner's pure helpers.

Cover model resolution, system-prompt rendering, opencode.json generation, JSON usage parsing, and
the in-Python cost computation (used for models the endpoint doesn't price, e.g. Azure GPT-5.x).
All importable without the AppWorld/cuga environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APPWORLD_DIR = Path(__file__).resolve().parents[2]
if str(APPWORLD_DIR) not in sys.path:
    sys.path.insert(0, str(APPWORLD_DIR))

from opencode.runner import (  # noqa: E402
    DEFAULT_BASE_URL,
    PROVIDER_ID,
    build_opencode_config,
    compute_cost,
    model_price,
    parse_opencode_events,
    render_system_prompt,
    resolve_model,
)

APPS = {"spotify": "Music streaming.", "supervisor": "User credentials."}


# --------------------------------------------------------------------------- model
def test_resolve_model_uses_env(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "openai/gpt-oss-120b")
    assert resolve_model() == "openai/gpt-oss-120b"


def test_resolve_model_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("MODEL_NAME", raising=False)
    assert resolve_model() == "gpt-4o"


# -------------------------------------------------------------------------- prompt
def test_render_system_prompt_substitutes_apps():
    out = render_system_prompt(APPS)
    assert "{app_descriptions}" not in out
    assert "spotify" in out and "supervisor" in out
    assert "complete_task" in out


# --------------------------------------------------------------------------- config
def test_build_opencode_config_structure():
    cfg = build_opencode_config(
        model="Azure/gpt-5.2-chat-2025-12-11",
        base_url="https://gw.example.com",
        api_key="sk-test",
        bridge_url="http://127.0.0.1:5555/mcp/",
        system_prompt="SYS",
        mode="repl",
    )
    prov = cfg["provider"][PROVIDER_ID]
    assert prov["options"]["baseURL"] == "https://gw.example.com/v1"  # /v1 appended
    assert prov["options"]["apiKey"] == "sk-test"
    assert "headers" not in prov["options"]  # no proxy trace header anymore
    assert prov["models"]["Azure/gpt-5.2-chat-2025-12-11"]["name"] == "Azure/gpt-5.2-chat-2025-12-11"
    assert cfg["mcp"]["appworld"] == {"type": "remote", "url": "http://127.0.0.1:5555/mcp/", "enabled": True}
    assert cfg["tools"]["bash"] is False and cfg["tools"]["write"] is False
    agent = cfg["agent"]["appworld"]
    assert agent["prompt"] == "SYS"
    assert agent["tools"]["appworld*"] is True


def test_build_opencode_config_base_url_v1_idempotent():
    cfg = build_opencode_config(
        model="m", base_url="http://x:4000/v1", api_key="k", bridge_url="http://b/mcp/", system_prompt="S"
    )
    assert cfg["provider"][PROVIDER_ID]["options"]["baseURL"] == "http://x:4000/v1"  # not /v1/v1


def test_build_opencode_config_default_base_url_when_empty():
    cfg = build_opencode_config(
        model="m", base_url="", api_key="k", bridge_url="http://b/mcp/", system_prompt="S"
    )
    assert cfg["provider"][PROVIDER_ID]["options"]["baseURL"] == DEFAULT_BASE_URL


# ---------------------------------------------------------------------------- parse
def test_parse_events_collects_text():
    stdout = "\n".join(
        [
            '{"type": "text", "part": {"text": "Hello"}}',
            '{"type": "tool", "part": {"name": "execute_python"}}',
            '{"type": "text", "part": {"text": "world"}}',
        ]
    )
    answer, events, _usage = parse_opencode_events(stdout)
    assert answer == "Hello\nworld"
    assert len(events) == 3


def test_parse_events_aggregates_usage():
    stdout = "\n".join(
        [
            '{"type": "text", "part": {"text": "hi"}}',
            '{"type": "step", "tokens": {"input": 100, "output": 50}, "cost": 0.01}',
            '{"type": "step", "message": {"tokens": {"input": 10, "output": 5}}}',
        ]
    )
    _answer, _events, usage = parse_opencode_events(stdout)
    assert usage["input_tokens"] == 110
    assert usage["output_tokens"] == 55
    assert usage["total_tokens"] == 165
    assert usage["llm_calls"] == 2
    assert usage["cost"] == 0.01


def test_parse_events_ignores_non_json_lines():
    stdout = "not json\n{\"type\": \"text\", \"part\": {\"text\": \"ok\"}}\n   \n[garbage"
    answer, events, _usage = parse_opencode_events(stdout)
    assert answer == "ok"
    assert len(events) == 1


# ----------------------------------------------------------------------------- cost
def test_model_price_lenient_match():
    assert model_price("Azure/gpt-5.2-chat-2025-12-11") == pytest.approx((1.75 / 1e6, 14.0 / 1e6))
    assert model_price("azure/gpt-5.5") == pytest.approx((2.5 / 1e6, 15.0 / 1e6))
    assert model_price("gpt-4o") is None


def test_compute_cost_from_tokens():
    # 1M input + 1M output for gpt-5.2 -> $1.75 + $14.00
    assert compute_cost("Azure/gpt-5.2-chat-2025-12-11", 1_000_000, 1_000_000) == pytest.approx(15.75)
    # 1M input only for gpt-5.5 -> $2.50
    assert compute_cost("gpt-5.5", 1_000_000, 0) == pytest.approx(2.50)
    # unknown model -> None (let OpenCode's reported cost stand)
    assert compute_cost("gpt-4o", 100, 100) is None
