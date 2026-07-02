"""TokenUsageCallback wiring in shared SDK eval helpers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from benchmarks.helpers.sdk_eval_helpers import evaluate_task_with_langfuse
from benchmarks.helpers.token_usage import TokenUsageCallback, apply_token_metrics

pytestmark = pytest.mark.unit


def _llm_result(*, llm_output=None, generations=None):
    return SimpleNamespace(llm_output=llm_output, generations=generations or [])


@pytest.mark.asyncio
async def test_evaluate_task_records_callback_tokens_without_langfuse():
    token_callback = TokenUsageCallback()

    async def fake_invoke(**kwargs):
        callbacks = (kwargs.get("config") or {}).get("callbacks") or kwargs.get("invoke_callbacks") or []
        for handler in callbacks:
            if hasattr(handler, "on_llm_end"):
                handler.on_llm_end(
                    SimpleNamespace(
                        llm_output={"usage": {"input_tokens": 11, "output_tokens": 4}},
                        generations=[],
                    )
                )
        return SimpleNamespace(answer="hello world", tool_calls=[], react_steps=1)

    agent = MagicMock()
    agent.invoke = AsyncMock(side_effect=fake_invoke)

    with patch("benchmarks.helpers.sdk_eval_helpers.should_trace_langfuse_task", return_value=False):
        result = await evaluate_task_with_langfuse(
            agent=agent,
            task={
                "name": "t1",
                "intent": "say hello",
                "difficulty": "easy",
                "expected_output": {"keywords": ["hello"]},
            },
            task_index=0,
            langfuse_handler=None,
        )

    assert result["input_tokens"] == 11
    assert result["output_tokens"] == 4
    assert result["total_tokens"] == 15
    assert result["total_llm_calls"] == 1
    assert token_callback.total_tokens == 0  # local instance in helper, not shared


def test_apply_token_metrics_langfuse_overrides_totals():
    cb = TokenUsageCallback()
    cb.on_llm_end(
        _llm_result(
            llm_output={
                "usage": {
                    "input_tokens": 50,
                    "output_tokens": 10,
                    "input_tokens_details": {"cached_tokens": 20},
                }
            }
        )
    )
    langfuse = SimpleNamespace(
        total_tokens=999,
        total_llm_calls=3,
        total_cost=0.5,
        full_execution_time=2.0,
        total_cache_input_tokens=888,
        generation_timings=[],
        llm_call_details=[],
        node_timings={},
    )
    result: dict = {}
    apply_token_metrics(result, cb, langfuse)
    assert result["input_tokens"] == 50
    assert result["output_tokens"] == 10
    assert result["total_tokens"] == 999
    assert result["total_llm_calls"] == 3
    assert result["total_cache_input_tokens"] == 888
