"""Regression test for issue #56 (react/cuga report.md parity).

``compare_report.py`` only renders the M3 grouped table (and, with it, the
Vakra dialogue/judge-score columns) for results that carry both
``m3_task_id`` and ``domain``. ``eval_m3.py`` (cuga SDK path) tags every
result with ``m3_task_id`` after ``evaluate_all`` returns, but
``M3ReactEvaluator.evaluate_task`` only copied ``domain``/``task_number``/
``uuid``/``intent``/``expected_output`` from the input test case onto the
result -- ``m3_task_id`` was dropped, so react bundles fell back to the
flat (non-grouped) report table with no Vakra columns.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from benchmarks.m3.eval_m3_react import M3ReactEvaluator


async def test_evaluate_task_propagates_m3_task_id():
    evaluator = M3ReactEvaluator()
    evaluator.agent = MagicMock()
    task = {
        "name": "uuid-1",
        "uuid": "uuid-1",
        "intent": "do the thing",
        "domain": "hockey",
        "m3_task_id": 2,
        "task_number": 1,
        "expected_output": {"response": "ok"},
    }

    with patch(
        "benchmarks.m3.eval_m3_react.evaluate_task_with_langfuse_react",
        new=AsyncMock(return_value={"success": True, "match_rate": 1.0}),
    ):
        result = await evaluator.evaluate_task(task, task_index=1)

    assert result["m3_task_id"] == 2
    assert result["domain"] == "hockey"
    assert result["task_number"] == 1


async def test_evaluate_task_does_not_overwrite_existing_m3_task_id():
    evaluator = M3ReactEvaluator()
    evaluator.agent = MagicMock()
    task = {"uuid": "uuid-1", "domain": "hockey", "m3_task_id": 2}

    with patch(
        "benchmarks.m3.eval_m3_react.evaluate_task_with_langfuse_react",
        new=AsyncMock(return_value={"success": True, "m3_task_id": 3}),
    ):
        result = await evaluator.evaluate_task(task, task_index=1)

    assert result["m3_task_id"] == 3
