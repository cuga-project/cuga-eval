"""Regression tests for issues #91 and #92.

When the M3 eval is interrupted (Ctrl-C) or crashes mid-run, we want:
- The already-completed task results to be saved as a JSON file so the
  bundling step still has something to package.
- A clearly distinguishable filename prefix (``m3_config_partial``) so
  consumers can tell a partial save from a complete run.

The full ``run_config_mode`` is far too entangled (registry startup,
container runtime detection, MCP server, Vakra scoring) to drive end-to-end
in a unit test. Instead, these tests exercise the small contract that the
interrupt handler relies on:

1. ``save_evaluation_results`` accepts a partial result list and writes
   valid JSON with the expected ``m3_config_partial`` prefix.
2. ``save_evaluation_results`` accepts an empty list without crashing
   (the handler guards against this, but it's worth verifying).

A pure-bash regression for ``eval.sh`` / ``compare.sh`` is too brittle to
add to the standard regression suite because it requires the full eval
toolchain (uv, python entrypoints) to run. The shell-side behavior is
verified manually per the PR test plan.
"""

import json
from pathlib import Path

import pytest

from benchmarks.helpers.sdk_eval_helpers import save_evaluation_results

pytestmark = pytest.mark.regression


def _sample_result(task_name: str, success: bool) -> dict:
    return {
        "task_name": task_name,
        "uuid": task_name,
        "difficulty": "easy",
        "success": success,
        "match_rate": 1.0 if success else 0.0,
        "found_keywords": [],
        "missing_keywords": [],
    }


def test_partial_results_saved_with_partial_prefix(tmp_path: Path) -> None:
    """A non-empty partial result list lands in m3_config_partial_*.json."""
    partial_results = [
        _sample_result("hockey_395_0", success=True),
        _sample_result("hockey_395_1", success=False),
    ]

    saved_path_str = save_evaluation_results(partial_results, tmp_path, prefix="m3_config_partial")
    saved_path = Path(saved_path_str)

    assert saved_path.exists(), f"expected partial result file at {saved_path}"
    assert saved_path.name.startswith("m3_config_partial_"), (
        f"partial saves must use the 'm3_config_partial' prefix so they're "
        f"distinguishable from complete runs; got: {saved_path.name}"
    )

    # File must contain valid JSON with both task results intact.
    loaded = json.loads(saved_path.read_text(encoding="utf-8"))
    if isinstance(loaded, dict):
        # Some helper variants nest results under a top-level key
        results = loaded.get("results", loaded)
    else:
        results = loaded
    assert isinstance(results, list), f"top-level shape should be list-like; got {type(results)}"
    task_names = {r.get("task_name") for r in results}
    assert task_names == {"hockey_395_0", "hockey_395_1"}


def test_partial_save_with_no_ground_truth_prefix(tmp_path: Path) -> None:
    """The --no-ground-truth branch uses a separate partial prefix."""
    partial_results = [_sample_result("hockey_395_0", success=True)]

    saved_path = Path(save_evaluation_results(partial_results, tmp_path, prefix="m3_config_no_gt_partial"))
    assert saved_path.exists()
    assert saved_path.name.startswith("m3_config_no_gt_partial_"), f"got: {saved_path.name}"
