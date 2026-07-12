"""Tests for scoping Vakra prediction/groundtruth files under the workspace bundle.

Two concurrent `eval.sh` runs for different experiments/capabilities (e.g.
`cap2-guard-test` and `cap3-guard-test`) can evaluate the same domain name.
Before this fix, both wrote to the shared `benchmarks/m3/results/_vakra/
prediction/<domain>.json` path and could clobber each other; stale files
from old runs also never got cleared there. `evaluate_single_task` now
passes `bundle_dir/results` (when a workspace bundle exists) instead,
mirroring the same fallback pattern `_finalize_and_save_results` already
uses.
"""

import inspect
import json

import pytest

from benchmarks.m3 import eval_m3

pytestmark = pytest.mark.regression


def _result(uuid: str, domain: str, answer: str) -> dict:
    return {
        "uuid": uuid,
        "domain": domain,
        "intent": "some question",
        "answer": answer,
        "tool_calls": [],
    }


def test_write_predictions_no_gt_isolated_by_output_dir(tmp_path):
    """Two 'runs' targeting the same domain, scoped to different output_dirs
    (as bundle_dir/results would be for two different --experiment names),
    must not see or overwrite each other's prediction file."""
    run_a_dir = tmp_path / "cap2-guard-test" / "results"
    run_b_dir = tmp_path / "cap3-guard-test" / "results"

    path_a = eval_m3.write_predictions_no_gt(
        [_result("task-a-1", "hockey", "answer from run A")],
        output_dir=run_a_dir,
        domain="hockey",
    )
    path_b = eval_m3.write_predictions_no_gt(
        [_result("task-b-1", "hockey", "answer from run B")],
        output_dir=run_b_dir,
        domain="hockey",
    )

    assert path_a != path_b
    data_a = json.loads(path_a.read_text())
    data_b = json.loads(path_b.read_text())
    assert data_a[0]["uuid"] == "task-a-1"
    assert data_b[0]["uuid"] == "task-b-1"
    assert path_a.is_relative_to(run_a_dir)
    assert path_b.is_relative_to(run_b_dir)


def test_evaluate_single_task_uses_bundle_scoped_output_dir():
    """Guards against regressing to the hardcoded shared results/ path.

    Both prediction-write call sites in `evaluate_single_task` must pass the
    bundle-aware `vakra_output_dir`, not `Path(__file__).parent / "results"`
    directly — that's the actual fix; losing it reintroduces the cross-run
    collision this test file is named after.
    """
    source = inspect.getsource(eval_m3.evaluate_single_task)
    assert source.count("output_dir=vakra_output_dir") == 2, (
        "expected both write_predictions_no_gt and vakra_score_results_async "
        "call sites to use the bundle-scoped output_dir"
    )
    # The only place the hardcoded shared path may still appear is the
    # legacy (no bundle_dir) fallback assignment.
    assert source.count('Path(__file__).parent / "results"') == 1
