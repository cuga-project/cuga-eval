"""invoke_and_score_appworld prefers InvokeResult.receipt over a Langfuse
fetch when the agent produced one (cuga-eval#95 / cuga-agent#467)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from benchmarks.appworld import eval_appworld_sdk

pytestmark = pytest.mark.unit


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


def _world():
    world = MagicMock()
    world.task.instruction = "do the appworld thing"
    world.evaluate.return_value = MagicMock()
    return world


@pytest.mark.asyncio
async def test_receipt_fields_populate_result_without_langfuse_handler():
    agent = AsyncMock()
    agent.invoke = AsyncMock(return_value=SimpleNamespace(answer="done", tool_calls=[], receipt=_receipt()))
    world = _world()

    with patch.object(
        eval_appworld_sdk, "evaluation_task_info", return_value={"success": True, "pass_percentage": 100}
    ):
        result = await eval_appworld_sdk.invoke_and_score_appworld(
            agent, None, world, "task-1", 0, "easy", None
        )

    assert result["total_tokens"] == 15
    assert result["input_tokens"] == 10
    assert result["token_source"] == "receipt"


@pytest.mark.asyncio
async def test_langfuse_fetch_skipped_when_receipt_present_even_with_handler():
    agent = AsyncMock()
    agent.invoke = AsyncMock(return_value=SimpleNamespace(answer="done", tool_calls=[], receipt=_receipt()))
    world = _world()
    fake_langfuse_module = SimpleNamespace(
        get_client=lambda: SimpleNamespace(
            create_trace_id=lambda seed: "trace-1",
            create_score=lambda **kw: None,
        )
    )

    with (
        patch.object(
            eval_appworld_sdk, "evaluation_task_info", return_value={"success": True, "pass_percentage": 100}
        ),
        patch(
            "benchmarks.helpers.sdk_eval_helpers.fetch_langfuse_metrics_for_trace",
            new_callable=AsyncMock,
        ) as mock_fetch,
        patch.dict("sys.modules", {"langfuse": fake_langfuse_module}),
    ):
        result = await eval_appworld_sdk.invoke_and_score_appworld(
            agent, "handler", world, "task-1", 0, "easy", None
        )

    mock_fetch.assert_not_awaited()
    assert result["total_tokens"] == 15
