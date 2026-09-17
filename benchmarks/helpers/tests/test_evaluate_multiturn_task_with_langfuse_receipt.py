"""evaluate_multiturn_task_with_langfuse sums InvokeResult.receipt across
turns instead of fetching Langfuse metrics, when receipts are available."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from benchmarks.helpers import sdk_eval_helpers

pytestmark = pytest.mark.unit


def _receipt(total_tokens, input_tokens, output_tokens):
    return SimpleNamespace(
        models=["gpt-oss-120b"],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cache_read_tokens=0,
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
async def test_receipt_accumulates_across_turns_without_langfuse():
    agent = AsyncMock()
    agent.invoke = AsyncMock(
        side_effect=[
            SimpleNamespace(answer="turn 1 answer", tool_calls=[], receipt=_receipt(10, 7, 3)),
            SimpleNamespace(answer="turn 2 answer", tool_calls=[], receipt=_receipt(20, 14, 6)),
        ]
    )
    turns = [{"query": "first"}, {"query": "second"}]

    with patch.object(sdk_eval_helpers, "should_trace_langfuse_task", return_value=False):
        result = await sdk_eval_helpers.evaluate_multiturn_task_with_langfuse(
            agent, turns, "task-1", 0, turn_delay=0.0
        )

    assert result["total_tokens"] == 30
    assert result["input_tokens"] == 21
    assert result["output_tokens"] == 9
    assert result["token_source"] == "receipt"


@pytest.mark.asyncio
async def test_langfuse_fetch_skipped_when_all_turns_have_receipts():
    agent = AsyncMock()
    fake_langfuse_module = SimpleNamespace(
        get_client=lambda: SimpleNamespace(
            create_trace_id=lambda seed: "trace-1",
            create_score=lambda **kw: None,
        )
    )

    with (
        patch.object(sdk_eval_helpers, "should_trace_langfuse_task", return_value=True),
        patch.object(sdk_eval_helpers, "build_langfuse_invoke_config", return_value={}),
        patch.object(sdk_eval_helpers, "_invoke_agent_for_eval", new_callable=AsyncMock) as mock_invoke,
        patch.object(
            sdk_eval_helpers, "fetch_langfuse_metrics_for_trace", new_callable=AsyncMock
        ) as mock_fetch,
        patch.object(sdk_eval_helpers, "record_harness_trace_output"),
        patch.dict("sys.modules", {"langfuse": fake_langfuse_module}),
    ):
        mock_invoke.return_value = SimpleNamespace(
            answer="turn answer", tool_calls=[], receipt=_receipt(10, 7, 3)
        )
        turns = [{"query": "only turn"}]
        result = await sdk_eval_helpers.evaluate_multiturn_task_with_langfuse(
            agent, turns, "task-1", 0, turn_delay=0.0
        )

    mock_fetch.assert_not_awaited()
    assert result["total_tokens"] == 10


@pytest.mark.asyncio
async def test_langfuse_fallback_used_when_a_middle_turn_lacks_a_receipt():
    """Regression for the accumulator sentinel bug: turn 1 has a receipt,
    turn 2 does not, turn 3 has one again. Before the fix, turn 3 saw
    ``acc is None`` and wrongly started a brand-new (turn-3-only) total, so
    the final result silently reported an undercounted receipt instead of
    falling back to Langfuse. Now the permanent-failure sentinel prevents
    that: the fallback must be used and the result must not claim
    ``token_source: "receipt"``.
    """
    agent = AsyncMock()
    fake_langfuse_module = SimpleNamespace(
        get_client=lambda: SimpleNamespace(
            create_trace_id=lambda seed: "trace-1",
            create_score=lambda **kw: None,
        )
    )
    fake_langfuse_metrics = SimpleNamespace(
        total_tokens=999,
        total_llm_calls=3,
        total_cost=0.01,
        full_execution_time=1.5,
        total_cache_input_tokens=0,
        generation_timings=[],
        llm_call_details=[],
        node_timings=[],
    )

    with (
        patch.object(sdk_eval_helpers, "should_trace_langfuse_task", return_value=True),
        patch.object(sdk_eval_helpers, "build_langfuse_invoke_config", return_value={}),
        patch.object(sdk_eval_helpers, "_invoke_agent_for_eval", new_callable=AsyncMock) as mock_invoke,
        patch.object(
            sdk_eval_helpers, "fetch_langfuse_metrics_for_trace", new_callable=AsyncMock
        ) as mock_fetch,
        patch.object(sdk_eval_helpers, "record_harness_trace_output"),
        patch.dict("sys.modules", {"langfuse": fake_langfuse_module}),
    ):
        mock_fetch.return_value = fake_langfuse_metrics
        mock_invoke.side_effect = [
            SimpleNamespace(answer="turn 1 answer", tool_calls=[], receipt=_receipt(10, 7, 3)),
            SimpleNamespace(answer="turn 2 answer", tool_calls=[], receipt=None),
            SimpleNamespace(answer="turn 3 answer", tool_calls=[], receipt=_receipt(20, 14, 6)),
        ]
        turns = [{"query": "first"}, {"query": "second"}, {"query": "third"}]
        result = await sdk_eval_helpers.evaluate_multiturn_task_with_langfuse(
            agent, turns, "task-1", 0, turn_delay=0.0
        )

    mock_fetch.assert_awaited()
    assert result.get("token_source") != "receipt"
    assert result["total_tokens"] == 999
