"""Lock-in tests for compare_report.

**Status note for issue #61**: when #61 was filed (2026-04-27), AppWorld
``compare.sh`` reports were said to be missing pass@k / pass^k. Running
``compare_report`` against actual AppWorld ``*_final_report.json`` files
at HEAD produces the expected pass@k / pass^k columns and footer, so the
bug appears to have already been fixed by earlier refactoring (both
AppWorld and SDK shapes now route through ``_parse_sdk_results`` and the
parser keys per-task tallies by ``task_name``, which matches across runs).

These tests therefore do **not** "fail before fix, pass after fix" — they
lock in the current correct behaviour so the bug can't silently come back.
The actual fix landed in some commit before the issue was filed; this PR
only adds the safety net. The issue should be re-verified with a real
``compare.sh`` run before being closed.

Covers:
- pass@k / pass^k columns appear in the multi-run summary.
- AppWorld-shape result files (``metrics`` + ``results`` with ``task_name``)
  produce the same comparison structure as SDK-shape ones.
"""

import json
from pathlib import Path

import pytest

from benchmarks.helpers.compare_report import generate_report

pytestmark = pytest.mark.regression


def _appworld_run(
    tmp_path: Path,
    name: str,
    task_passes: dict,
    difficulties: dict | None = None,
) -> str:
    """Write an AppWorld-shape ``*_final_report.json`` and return its path.

    task_passes maps task_name → bool (True = passed).
    difficulties (optional) maps task_name → difficulty string (e.g. "1", "2", "3").
    """
    difficulties = difficulties or {}
    results = [
        {
            "task_name": tid,
            "success": passed,
            "match_rate": 1.0 if passed else 0.0,
            "total_tokens": 1000,
            "total_llm_calls": 5,
            "full_execution_time": 12.5,
            **({"difficulty": difficulties[tid]} if tid in difficulties else {}),
        }
        for tid, passed in task_passes.items()
    ]
    payload = {
        "metrics": {
            "total_tasks": len(results),
            "passed": sum(1 for r in results if r["success"]),
            "failed": sum(1 for r in results if not r["success"]),
            "pass_rate": (sum(1 for r in results if r["success"]) / len(results)) if results else 0.0,
        },
        "results": results,
    }
    p = tmp_path / name
    p.write_text(json.dumps(payload))
    return str(p)


def test_appworld_compare_report_has_pass_at_k(tmp_path):
    # Two runs over the same task set. Task A passes in both runs (pass^2);
    # task B passes only in run 2 (pass@2 but not pass^2); task C never passes.
    run1 = _appworld_run(tmp_path, "run1.json", {"A": True, "B": False, "C": False})
    run2 = _appworld_run(tmp_path, "run2.json", {"A": True, "B": True, "C": False})

    report = generate_report({"gpt-oss:cuga": [run1, run2]})

    # Headers must include pass@2 and pass^2 — this is the precise regression.
    assert "pass@2" in report
    assert "pass^2" in report

    # Per-task footer at the bottom of the per-task section.
    assert "pass@k" in report
    assert "pass^k" in report

    # Sanity-check the numbers: 2/3 tasks pass at least once (pass@2 = 66.7%),
    # 1/3 tasks pass every run (pass^2 = 33.3%).
    assert "2/3" in report  # pass@k tally
    assert "1/3" in report  # pass^k tally


def test_sdk_shape_also_emits_pass_at_k(tmp_path):
    # SDK shape never lost pass@k; make sure that path keeps working too,
    # so the AppWorld test above isn't passing for a benign-but-wrong reason
    # (e.g. a hardcoded string).
    run1 = _appworld_run(tmp_path, "sdk1.json", {"T1": True, "T2": False})
    run2 = _appworld_run(tmp_path, "sdk2.json", {"T1": False, "T2": True})

    report = generate_report({"gpt-oss:cuga": [run1, run2]})
    assert "pass@2" in report
    assert "pass^2" in report
    # Both tasks pass at least once across the two runs; neither passes both.
    assert "2/2" in report  # pass@k
    assert "0/2" in report  # pass^k


def test_summary_emits_majority_and_consistency(tmp_path):
    """maj@k counts tasks passing > k/2 runs; Cons = pass^k / maj@k.

    Three tasks, three runs:
      A passes 3/3   → counts in pass^3, pass@3, maj@3
      B passes 2/3   → counts in pass@3, maj@3 (>1.5), but NOT pass^3
      C passes 0/3   → counts in nothing
    Expected: pass@3 = 2/3 (66.7%), pass^3 = 1/3 (33.3%), maj@3 = 2/3 (66.7%),
    Cons = 1/2 = 0.50.
    """
    run1 = _appworld_run(tmp_path, "r1.json", {"A": True, "B": True, "C": False})
    run2 = _appworld_run(tmp_path, "r2.json", {"A": True, "B": False, "C": False})
    run3 = _appworld_run(tmp_path, "r3.json", {"A": True, "B": True, "C": False})

    report = generate_report({"gpt-oss:cuga": [run1, run2, run3]})

    # Summary header carries maj@3 and Cons.
    assert "maj@3" in report
    assert "Cons" in report
    # Per-task footer's k-stats row carries maj@k and consistency.
    assert "maj@k" in report
    # 1/2 = 0.50, formatted to 2 dp.
    assert "0.50" in report
    # Glossary section explains the metrics.
    assert "Consistency" in report
    assert "pass^k / maj@k" in report


def test_consistency_dash_when_no_majority_pass(tmp_path):
    """When no task passes a majority of runs, Cons is `--` (avoid div by 0)."""
    # Two runs, two tasks, each passes only once → maj@2 needs > 1 pass, so zero.
    run1 = _appworld_run(tmp_path, "r1.json", {"X": True, "Y": False})
    run2 = _appworld_run(tmp_path, "r2.json", {"X": False, "Y": True})

    report = generate_report({"gpt-oss:cuga": [run1, run2]})
    # 0/2 majority → consistency undefined, shown as ``--``.
    # Search the maj@2 column / cons cell area for the dash.
    assert "0/2" in report  # both pass^k and maj@k tallies are 0/2
    # The glossary mentions the `--` fallback.
    assert "`--`" in report or "  --" in report


def test_per_difficulty_breakdown_appears_for_appworld(tmp_path):
    """When result files carry a `difficulty` field, a Per-Difficulty
    Breakdown section is emitted with one row per (config, difficulty)."""
    run1 = _appworld_run(
        tmp_path,
        "r1.json",
        {"A": True, "B": False, "C": True, "D": False},
        difficulties={"A": "1", "B": "1", "C": "2", "D": "2"},
    )
    run2 = _appworld_run(
        tmp_path,
        "r2.json",
        {"A": True, "B": True, "C": False, "D": False},
        difficulties={"A": "1", "B": "1", "C": "2", "D": "2"},
    )

    report = generate_report({"gpt-oss:cuga": [run1, run2]})
    assert "Per-Difficulty Breakdown" in report
    # Both difficulty levels show up as row labels.
    lines = report.splitlines()
    diff_rows = [ln for ln in lines if ln.startswith("cuga ")]
    # Two difficulty levels × one config = two rows
    assert len(diff_rows) >= 2


def test_per_difficulty_breakdown_suppressed_for_sdk(tmp_path):
    """SDK-shape results (no difficulty) get the original report unchanged."""
    run1 = _appworld_run(tmp_path, "r1.json", {"T1": True, "T2": False})
    run2 = _appworld_run(tmp_path, "r2.json", {"T1": False, "T2": True})

    report = generate_report({"gpt-oss:cuga": [run1, run2]})
    assert "Per-Difficulty Breakdown" not in report
