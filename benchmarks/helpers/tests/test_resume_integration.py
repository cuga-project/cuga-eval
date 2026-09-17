"""Cross-cutting M1 resume tests.

* All four evaluators must expose the same ``--bundle-dir`` / ``--resume-task-ids``
  CLI surface (checked via AST so we don't trigger each module's heavy
  import-time side effects such as ``load_eval_config``).
* ``finalize_merged_results`` must merge on-disk partials into the canonical
  ``{"metrics": ..., "results": [...]}`` shape.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from benchmarks.helpers import incremental_results as ir

PROJECT_ROOT = Path(__file__).resolve().parents[3]

EVAL_FILES = {
    "bpo": "benchmarks/bpo/eval_bench_sdk.py",
    "oak": "benchmarks/oak_health_insurance/eval_bench_sdk.py",
    "appworld": "benchmarks/appworld/eval_appworld_sdk.py",
    "m3": "benchmarks/m3/eval_m3.py",
}


def _argparse_option_strings(source: str) -> set[str]:
    """Collect every option string passed to ``parser.add_argument(...)``."""
    tree = ast.parse(source)
    options: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if arg.value.startswith("-"):
                        options.add(arg.value)
    return options


@pytest.mark.regression
@pytest.mark.parametrize("benchmark,rel", sorted(EVAL_FILES.items()))
def test_evaluators_expose_resume_flags(benchmark, rel):
    source = (PROJECT_ROOT / rel).read_text()
    options = _argparse_option_strings(source)
    assert "--bundle-dir" in options, f"{benchmark} missing --bundle-dir"
    assert "--resume-task-ids" in options, f"{benchmark} missing --resume-task-ids"


@pytest.mark.regression
def test_finalize_merged_results_roundtrip(tmp_path):
    ir.write_task_result(tmp_path, "t1", {"task_name": "t1", "success": True, "error": None})
    ir.write_task_result(tmp_path, "t2", {"task_name": "t2", "success": False, "error": "boom"})

    out = ir.finalize_merged_results(tmp_path, prefix="bpo")
    assert out.exists()
    assert out.parent == tmp_path / "results"

    data = json.loads(out.read_text())
    assert data["metrics"]["total_tasks"] == 2
    assert data["metrics"]["passed"] == 1
    assert {r["task_name"] for r in data["results"]} == {"t1", "t2"}


@pytest.mark.regression
def test_finalize_reflects_retry_overwrite(tmp_path):
    # A task fails, then a retry succeeds: only the latest attempt is merged.
    ir.write_task_result(tmp_path, "t1", {"task_name": "t1", "success": False, "error": "boom"})
    ir.write_task_result(tmp_path, "t1", {"task_name": "t1", "success": True, "error": None})

    out = ir.finalize_merged_results(tmp_path, prefix="bpo")
    data = json.loads(out.read_text())
    assert data["metrics"]["total_tasks"] == 1
    assert data["metrics"]["passed"] == 1


@pytest.mark.regression
def test_appworld_evaluator_exposes_leaderboard_flags():
    source = (PROJECT_ROOT / EVAL_FILES["appworld"]).read_text()
    options = _argparse_option_strings(source)
    assert {"--leaderboard", "--force-retry"} <= options


@pytest.mark.regression
def test_appworld_task_id_accepts_many():
    source = (PROJECT_ROOT / EVAL_FILES["appworld"]).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args
            and getattr(node.args[0], "value", None) == "--task-id"
        ):
            kw = {k.arg: getattr(k.value, "value", None) for k in node.keywords}
            assert kw.get("nargs") == "+", "--task-id must accept several ids (eval.sh --task a b c)"
            return
    pytest.fail("--task-id argument not found")
