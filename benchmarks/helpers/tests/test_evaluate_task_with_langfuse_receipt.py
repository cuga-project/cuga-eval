"""evaluate_task_with_langfuse prefers InvokeResult.receipt over Langfuse
when the agent produced one (cuga-eval#95 / cuga-agent#467)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from benchmarks.helpers import sdk_eval_helpers

pytestmark = pytest.mark.unit


def _agent_returning(receipt):
    agent = AsyncMock()
    agent.invoke = AsyncMock(
        return_value=SimpleNamespace(answer="the answer", tool_calls=[], receipt=receipt)
    )
    return agent


def _receipt():
    return SimpleNamespace(
        models=["gpt-oss-120b"],
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        cache_read_tokens=2,
        reasoning_tokens=0,
        llm_calls=1,
        tool_call_count=0,
        llm_time_s=0.1,
        tool_time_s=0.0,
        wall_time_s=0.1,
        slowest_tool=None,
        tool_timings=[],
    )


@pytest.mark.asyncio
async def test_receipt_fields_land_in_result_when_langfuse_disabled():
    agent = _agent_returning(_receipt())
    task = {"name": "t1", "intent": "do the thing", "expected_output": {"keywords": []}}

    with patch.object(sdk_eval_helpers, "should_trace_langfuse_task", return_value=False):
        result = await sdk_eval_helpers.evaluate_task_with_langfuse(agent, task, 0)

    assert result["total_tokens"] == 15
    assert result["input_tokens"] == 10
    assert result["output_tokens"] == 5
    assert result["cache_read_tokens"] == 2
    assert result["token_source"] == "receipt"


@pytest.mark.asyncio
async def test_langfuse_fetch_skipped_when_receipt_present():
    agent = _agent_returning(_receipt())
    task = {"name": "t1", "intent": "do the thing", "expected_output": {"keywords": []}}

    fake_langfuse_module = SimpleNamespace(
        get_client=lambda: SimpleNamespace(
            create_trace_id=lambda seed: "trace-1",
            create_score=lambda **kw: None,
        )
    )

    with (
        patch.object(sdk_eval_helpers, "should_trace_langfuse_task", return_value=True),
        patch.object(sdk_eval_helpers, "build_langfuse_invoke_config", return_value={}),
        patch.object(
            sdk_eval_helpers, "fetch_langfuse_metrics_for_trace", new_callable=AsyncMock
        ) as mock_fetch,
        patch.dict("sys.modules", {"langfuse": fake_langfuse_module}),
    ):
        result = await sdk_eval_helpers.evaluate_task_with_langfuse(agent, task, 0)

    mock_fetch.assert_not_awaited()
    assert result["total_tokens"] == 15
    assert result["input_tokens"] == 10


@pytest.mark.asyncio
async def test_langfuse_fetch_still_used_when_no_receipt():
    agent = _agent_returning(None)  # no receipt: run_receipt off / old cuga-agent

    task = {"name": "t1", "intent": "do the thing", "expected_output": {"keywords": []}}

    fake_metrics = SimpleNamespace(
        total_tokens=99,
        total_llm_calls=4,
        total_cost=0.01,
        full_execution_time=1.0,
        total_cache_input_tokens=0,
        generation_timings=[],
        llm_call_details=[],
        node_timings={},
    )
    fake_langfuse_module = SimpleNamespace(
        get_client=lambda: SimpleNamespace(
            create_trace_id=lambda seed: "trace-1",
            create_score=lambda **kw: None,
        )
    )

    with (
        patch.object(sdk_eval_helpers, "should_trace_langfuse_task", return_value=True),
        patch.object(sdk_eval_helpers, "build_langfuse_invoke_config", return_value={}),
        patch.object(
            sdk_eval_helpers,
            "fetch_langfuse_metrics_for_trace",
            new_callable=AsyncMock,
            return_value=fake_metrics,
        ) as mock_fetch,
        patch.dict("sys.modules", {"langfuse": fake_langfuse_module}),
    ):
        result = await sdk_eval_helpers.evaluate_task_with_langfuse(agent, task, 0)

    mock_fetch.assert_awaited_once()
    assert result["total_tokens"] == 99
    assert "input_tokens" not in result  # Langfuse path never had this field
