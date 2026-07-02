"""Token metric helpers used by the AppWorld external harness."""

from types import SimpleNamespace
from typing import Any

import pytest

from benchmarks.appworld.utils.appworld_harness import (
    _apply_token_metrics,
    _invoke_config_with_token_callback,
)
from benchmarks.helpers.token_usage import TokenUsageCallback


class _MockTool:
    def __init__(self, name: str, result: Any = "ok"):
        self.name = name
        self.description = f"Mock {name}"
        self._result = result

    async def ainvoke(self, args: dict[str, Any]) -> Any:
        return {"tool": self.name, "args": args, "result": self._result}


def test_invoke_config_appends_token_callback():
    cb = TokenUsageCallback()
    cfg = _invoke_config_with_token_callback(cb, {"callbacks": ["existing"]})
    assert cfg["callbacks"] == ["existing", cb]


def test_apply_token_metrics_uses_callback_by_default():
    cb = TokenUsageCallback()
    cb.on_llm_end(
        SimpleNamespace(
            llm_output={"usage": {"input_tokens": 12, "output_tokens": 3}},
            generations=[],
        )
    )
    result: dict = {}
    _apply_token_metrics(result, cb)
    assert result["total_tokens"] == 15
    assert result["total_llm_calls"] == 1
    assert result["input_tokens"] == 12
    assert result["output_tokens"] == 3


def test_apply_token_metrics_prefers_langfuse_when_nonzero():
    cb = TokenUsageCallback()
    cb.on_llm_end(
        SimpleNamespace(
            llm_output={"usage": {"input_tokens": 5, "output_tokens": 1}},
            generations=[],
        )
    )
    langfuse = SimpleNamespace(
        total_tokens=999,
        total_llm_calls=7,
        total_cost=0.42,
        full_execution_time=1.5,
        total_cache_input_tokens=100,
        generation_timings=[{"x": 1}],
        llm_call_details=[{"id": "g1"}],
        node_timings={"n": 0.1},
    )
    result: dict = {}
    _apply_token_metrics(result, cb, langfuse)
    assert result["total_tokens"] == 999
    assert result["total_llm_calls"] == 7
    assert result["total_cost"] == 0.42
    assert result["input_tokens"] == 5
    assert result["total_cache_input_tokens"] == 100


@pytest.mark.asyncio
async def test_tool_react_loop_with_token_callback():
    from benchmarks.appworld.agents.tool_loop import run_tool_react_loop

    cb = TokenUsageCallback()
    call_count = 0

    async def fake_llm(convo, invoke_callbacks=None):
        nonlocal call_count
        call_count += 1
        if invoke_callbacks:
            for handler in invoke_callbacks:
                handler.on_llm_end(
                    SimpleNamespace(
                        llm_output={"usage": {"input_tokens": 40, "output_tokens": 8}},
                        generations=[],
                    )
                )
        if call_count == 1:
            return '```json\n{"action": "tool", "tool_name": "ping", "args": {"message": "x"}}\n```'
        return "Final Answer: ok"

    result = await run_tool_react_loop(
        tools=[_MockTool("ping")],
        system_prompt="test",
        intent="do thing",
        user_context="ctx",
        call_llm=fake_llm,
        max_steps=3,
        invoke_callbacks=[cb],
    )
    assert result.answer == "ok"
    assert cb.total_tokens == 96
    assert cb.llm_calls == 2
