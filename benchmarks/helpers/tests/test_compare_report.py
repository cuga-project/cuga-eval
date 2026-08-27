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

from benchmarks.helpers.compare_report import (
    _aggregate_receipt_costs,
    _last_turn_judge_scores,
    _m3_capability_group,
    _parse_sdk_results,
    _stats_for_task,
    generate_eval_report,
    generate_report,
)

pytestmark = pytest.mark.regression


def _heading_count(report: str, heading: str) -> int:
    """Count *exact-level* occurrences of a markdown heading line.

    Plain substring containment (``heading in report``) false-positives on
    deeper headings: ``"## Summary"`` is a substring of ``"#### Summary"``
    since markdown headers share the ``#`` prefix. Comparing whole lines
    avoids that.
    """
    return sum(1 for line in report.splitlines() if line == heading)


def test_m3_capability_group_keys_on_task_id_without_domain():
    """The capability rollup is capability-only: a task with m3_task_id but no
    domain must still group under m3_task_<id>, not be dropped."""
    assert _m3_capability_group({"m3_task_id": 2, "domain": "hockey"}) == "m3_task_2"
    assert _m3_capability_group({"m3_task_id": 2}) == "m3_task_2"
    assert _m3_capability_group({"m3_task_id": 2, "domain": ""}) == "m3_task_2"
    assert _m3_capability_group({"domain": "hockey"}) is None
    assert _m3_capability_group({}) is None


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


def test_parse_sdk_results_includes_react_steps():
    parsed = _parse_sdk_results(
        {
            "metrics": {"total_tasks": 1, "passed": 1},
            "results": [{"task_name": "t1", "success": True, "steps": 3}],
        }
    )
    assert parsed["tasks"]["t1"]["steps"] == 3


def _m3_run(tmp_path: Path, name: str, tasks) -> str:
    """Write an M3-shape ``*_final_report.json`` and return its path.

    ``tasks`` may be either a dict mapping task_name -> spec dict, or a list of
    spec dicts each carrying its own ``task_name``. Each spec dict has keys:
      - m3_task_id, domain, task_number: M3 grouping tags.
      - success (bool).
      - match_rate (optional float): Vakra aggregated dialogue score.
      - judge_scores (optional dict): exactmatch/answer/groundedness -> float,
        written as the metadata of the last ``vakra.details.per_turn`` entry.
    """
    items = list(tasks.items()) if isinstance(tasks, dict) else [(s["task_name"], s) for s in tasks]
    results = []
    for tid, spec in items:
        r = {
            "task_name": tid,
            "success": spec["success"],
            "total_tokens": 1000,
            "total_llm_calls": 5,
            "full_execution_time": 12.5,
            "m3_task_id": spec.get("m3_task_id"),
            "domain": spec.get("domain"),
            "task_number": spec.get("task_number", 1),
        }
        if "match_rate" in spec:
            r["match_rate"] = spec["match_rate"]
        judge_scores = spec.get("judge_scores")
        if judge_scores is not None:
            r["vakra"] = {
                "score": spec.get("match_rate", 0.0),
                "details": {"per_turn": [{"metadata": {f"{k}_score": v for k, v in judge_scores.items()}}]},
            }
        results.append(r)
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


def test_last_turn_judge_scores_skips_missing_judges():
    """Only judges that ran on the *last* scored turn are reported."""
    vakra = {
        "score": 1.0,
        "details": {
            "per_turn": [
                {"metadata": {"exactmatch_score": 0.0, "answer_score": 1.0, "groundedness_score": 1.0}},
                # Last turn: exactmatch passed, so answer/groundedness were skipped.
                {"metadata": {"exactmatch_score": 1.0}},
            ]
        },
    }
    assert _last_turn_judge_scores(vakra) == {"exactmatch": 1.0}


def test_last_turn_judge_scores_empty_without_per_turn():
    assert _last_turn_judge_scores({}) == {}
    assert _last_turn_judge_scores({"score": 1.0, "details": {}}) == {}


def test_eval_report_m3_vakra_columns(tmp_path):
    """generate_eval_report adds Dialogue/ExactMatch/Answer/Groundedness columns
    for M3 results carrying Vakra `match_rate` + per-judge scores."""
    result_file = _m3_run(
        tmp_path,
        "m3_vakra.json",
        {
            "uuid-pass": {
                "m3_task_id": 2,
                "domain": "hockey",
                "task_number": 1,
                "success": True,
                "match_rate": 1.0,
                "judge_scores": {"exactmatch": 1.0},
            },
            "uuid-fail": {
                "m3_task_id": 2,
                "domain": "hockey",
                "task_number": 2,
                "success": False,
                "match_rate": 0.0,
                "judge_scores": {"exactmatch": 0.0, "answer": 0.0, "groundedness": 1.0},
            },
        },
    )

    report = generate_eval_report(result_file)

    assert "Dialogue | ExactMatch | Answer | Groundedness" in report
    # Passing task: dialogue=1.00, exactmatch=1.00; answer/groundedness judges
    # were skipped (exactmatch already passed), shown as `--`.
    assert "| 1.00 | 1.00 | -- | -- |" in report
    # Failing task: all three judges scored.
    assert "| 0.00 | 0.00 | 0.00 | 1.00 |" in report


def test_eval_report_m3_without_vakra_omits_columns(tmp_path):
    """M3 results without `match_rate` keep the original (no-Vakra) table shape."""
    result_file = _m3_run(
        tmp_path,
        "m3_no_vakra.json",
        {
            "uuid-a": {"m3_task_id": 2, "domain": "hockey", "task_number": 1, "success": True},
            "uuid-b": {"m3_task_id": 2, "domain": "hockey", "task_number": 2, "success": False},
        },
    )

    report = generate_eval_report(result_file)
    assert "Dialogue" not in report
    assert "ExactMatch" not in report
    assert (
        "| Task | Domain | # | Result | Tokens | Cost | LLM Calls | Cache Tokens "
        "| Input | Output | Reasoning | Duration | Steps |" in report
    )


def test_compare_report_m3_vakra_columns(tmp_path):
    """generate_report's Per-Task Details table gains mean Dialogue/judge
    columns for M3 results carrying Vakra `match_rate` across runs."""
    common = {
        "uuid-A": {"m3_task_id": 2, "domain": "hockey", "task_number": 1},
        "uuid-B": {"m3_task_id": 2, "domain": "hockey", "task_number": 2},
    }
    run1 = _m3_run(
        tmp_path,
        "cmp_run1.json",
        {
            "uuid-A": {
                **common["uuid-A"],
                "success": True,
                "match_rate": 1.0,
                "judge_scores": {"exactmatch": 1.0},
            },
            "uuid-B": {
                **common["uuid-B"],
                "success": False,
                "match_rate": 0.0,
                "judge_scores": {"exactmatch": 0.0, "answer": 0.0, "groundedness": 1.0},
            },
        },
    )
    run2 = _m3_run(
        tmp_path,
        "cmp_run2.json",
        {
            "uuid-A": {
                **common["uuid-A"],
                "success": True,
                "match_rate": 1.0,
                "judge_scores": {"exactmatch": 1.0},
            },
            "uuid-B": {
                **common["uuid-B"],
                "success": True,
                "match_rate": 1.0,
                "judge_scores": {"exactmatch": 1.0},
            },
        },
    )

    report = generate_report({"gpt-oss:cuga": [run1, run2]})

    assert "Dialog" in report
    assert "ExctM" in report
    assert "Answer" in report
    assert "Ground" in report
    # Task A: mean dialogue=1.00, mean exactmatch=1.00 (answer/groundedness never scored).
    assert "1.00" in report
    # Task B: mean dialogue=0.50, mean exactmatch=0.50, answer=0.00 (1 run), groundedness=1.00 (1 run).
    assert "0.50" in report


def test_compare_report_m3_without_vakra_omits_columns(tmp_path):
    """M3 comparison reports without `match_rate` keep the original layout."""
    run1 = _m3_run(
        tmp_path,
        "cmp_no_vakra1.json",
        {"uuid-A": {"m3_task_id": 2, "domain": "hockey", "task_number": 1, "success": True}},
    )
    run2 = _m3_run(
        tmp_path,
        "cmp_no_vakra2.json",
        {"uuid-A": {"m3_task_id": 2, "domain": "hockey", "task_number": 1, "success": False}},
    )

    report = generate_report({"gpt-oss:cuga": [run1, run2]})
    assert "Dialog" not in report
    assert "ExctM" not in report


def test_eval_report_m3_vakra_columns_plain_text(tmp_path):
    """Plain-text rendering also gets the Vakra columns."""
    result_file = _m3_run(
        tmp_path,
        "m3_vakra_plain.json",
        {
            "uuid-pass": {
                "m3_task_id": 3,
                "domain": "trains",
                "task_number": 1,
                "success": True,
                "match_rate": 1.0,
                "judge_scores": {"exactmatch": 1.0},
            },
        },
    )

    report = generate_eval_report(result_file, markdown=False)
    assert "Dialog" in report
    assert "ExctM" in report
    assert "1.00" in report


def _appworld_eval_run(tmp_path: Path, name: str, task_results: dict) -> str:
    """Write an appworld-shape (``task_results`` dict) single-run result file."""
    payload = {
        "tasks_total": len(task_results),
        "tasks_completed": sum(1 for t in task_results.values() if t.get("success")),
        "task_results": task_results,
    }
    p = tmp_path / name
    p.write_text(json.dumps(payload))
    return str(p)


def test_compare_report_cost_summary_section(tmp_path):
    """Cost Summary shows per-config totals AND per-task averages for
    tokens / LLM calls / time (issue #51)."""
    run1 = _appworld_run(tmp_path, "r1.json", {"A": True, "B": False, "C": True})

    report = generate_report({"gpt-oss:cuga": [run1]})

    assert "Cost Summary" in report
    assert "Avg/Task" in report
    # 3 tasks at 1000 tokens / 5 LLM calls / 12.5s each -> per-task averages.
    assert "1,000.0" in report
    assert "12.5s" in report


def test_per_test_set_breakdown_appears_for_appworld(tmp_path):
    """AppWorld task ids that appear in appworld/eval_config.toml's
    test_challenge_*/test_normal_all_* lists get grouped into "challenge" /
    "normal" rows (issue #51 item 3)."""
    run1 = _appworld_run(tmp_path, "r1.json", {"e775c78_1": True, "fd1f8fa_1": False})

    report = generate_report({"gpt-oss:cuga": [run1]})

    assert "Per-Test-Set Breakdown (AppWorld)" in report
    assert "challenge" in report
    assert "normal" in report


def test_per_capability_domain_breakdown_appears_for_m3(tmp_path):
    """M3 tasks (m3_task_id + domain) get grouped into capability/domain rows
    in compare reports, alongside pass@k/pass^k/maj@k (issue #51 item 3)."""
    run1 = _m3_run(
        tmp_path,
        "r1.json",
        [
            {"task_name": "t1", "success": True, "m3_task_id": 2, "domain": "hockey", "task_number": 1},
            {"task_name": "t2", "success": False, "m3_task_id": 2, "domain": "hockey", "task_number": 2},
            {"task_name": "t3", "success": True, "m3_task_id": 3, "domain": "books", "task_number": 1},
        ],
    )

    report = generate_report({"gpt4o:react": [run1]})

    assert "Per-Capability/Domain Breakdown (M3)" in report
    assert "m3_task_2/hockey" in report
    assert "m3_task_3/books" in report


def test_eval_report_pass1_and_avg_per_task_bullets(tmp_path):
    """Single-run eval report renames "Pass Rate" to "Pass@1" and adds
    avg-per-task bullets alongside the pre-existing totals (issue #51 item 1)."""
    run = _m3_run(
        tmp_path,
        "eval.json",
        [
            {"task_name": "t1", "success": True, "m3_task_id": 2, "domain": "hockey", "task_number": 1},
            {"task_name": "t2", "success": False, "m3_task_id": 2, "domain": "hockey", "task_number": 2},
        ],
    )

    report = generate_eval_report(run)

    assert "**Pass@1**: 1/2 (50.0%)" in report
    assert "Pass Rate" not in report
    assert "**Avg Tokens / Task**" in report
    assert "**Avg LLM Calls / Task**" in report
    assert "**Avg Duration / Task**" in report
    # validate_bundle_report.py keys off these exact bullet labels.
    assert "**Total Tokens**" in report
    assert "**Total LLM Calls**" in report
    assert "**Total Duration**" in report


def test_eval_report_capability_domain_breakdown(tmp_path):
    """Single-run M3 eval report gets a Capability/Domain Breakdown table
    (issue #51 item 3)."""
    run = _m3_run(
        tmp_path,
        "eval.json",
        [
            {"task_name": "t1", "success": True, "m3_task_id": 2, "domain": "hockey", "task_number": 1},
            {"task_name": "t2", "success": False, "m3_task_id": 2, "domain": "hockey", "task_number": 2},
            {"task_name": "t3", "success": True, "m3_task_id": 3, "domain": "books", "task_number": 1},
        ],
    )

    report = generate_eval_report(run)

    assert "Capability/Domain Breakdown" in report
    assert "m3_task_2/hockey" in report
    assert "m3_task_3/books" in report


def test_eval_report_capability_rollup_above_domain_breakdown(tmp_path):
    """Single-run M3 eval report gets a coarse per-Capability rollup table
    placed ABOVE the per-(capability, domain) breakdown, and both render as
    markdown tables (consistent with the Per-Task Results table)."""
    run = _m3_run(
        tmp_path,
        "eval.json",
        [
            {"task_name": "t1", "success": True, "m3_task_id": 2, "domain": "hockey", "task_number": 1},
            {"task_name": "t2", "success": False, "m3_task_id": 2, "domain": "books", "task_number": 1},
            {"task_name": "t3", "success": True, "m3_task_id": 3, "domain": "books", "task_number": 1},
        ],
    )

    report = generate_eval_report(run)

    # Coarse rollup present, one row per capability (no "/domain").
    assert "## Capability Breakdown" in report
    cap_idx = report.index("## Capability Breakdown")
    capdom_idx = report.index("## Capability/Domain Breakdown")
    assert cap_idx < capdom_idx  # rollup above the detail table

    # Rollup is a markdown table with a markdown header row.
    cap_section = report[cap_idx:capdom_idx]
    assert "| Capability | Tasks | Pass@1 |" in cap_section
    assert "| m3_task_2 |" in cap_section  # capability-only label, not m3_task_2/hockey
    assert "| m3_task_3 |" in cap_section

    # Detail table is now markdown too (consistency aside).
    assert "| Capability/Domain | Tasks | Pass@1 |" in report
    assert "| m3_task_2/hockey |" in report


def test_eval_report_appworld_difficulty_and_test_set_breakdowns(tmp_path):
    """Single-run AppWorld eval report gets Difficulty and Test-Set (normal vs.
    challenge, via appworld/eval_config.toml) breakdown tables (issue #51 item 3)."""
    run = _appworld_eval_run(
        tmp_path,
        "eval.json",
        {
            "e775c78_1": {  # test_challenge_easy
                "success": True,
                "total_tokens": 1000,
                "total_llm_calls": 5,
                "full_execution_time": 12.5,
                "difficulty": 1,
            },
            "fd1f8fa_1": {  # test_normal_all_easy
                "success": False,
                "total_tokens": 800,
                "total_llm_calls": 4,
                "full_execution_time": 10.0,
                "difficulty": 1,
            },
        },
    )

    report = generate_eval_report(run)

    assert "Difficulty Breakdown" in report
    assert "Test-Set Breakdown (AppWorld)" in report
    assert "challenge" in report
    assert "normal" in report


def test_compare_group_breakdown_includes_cost_columns(tmp_path):
    """Compare-report per-group sections carry per-task cost columns, not just
    pass metrics, so cost can be compared across groups (issue #51 review)."""
    run1 = _m3_run(
        tmp_path,
        "r1.json",
        [
            {"task_name": "t1", "success": True, "m3_task_id": 2, "domain": "hockey", "task_number": 1},
            {"task_name": "t2", "success": False, "m3_task_id": 3, "domain": "books", "task_number": 1},
        ],
    )

    report = generate_report({"gpt4o:react": [run1]})

    # Per-group sections now expose per-task cost alongside pass@k/pass^k.
    assert "Tok/Task" in report
    assert "LLM/Task" in report
    assert "Dur/Task" in report
    # And the underlying per-task values still render (1000 tokens / task).
    assert "1,000" in report


def test_eval_group_breakdown_includes_per_task_averages(tmp_path):
    """Single-eval per-group breakdown shows per-task averages next to totals,
    so groups of different sizes are comparable (issue #51 review)."""
    run = _m3_run(
        tmp_path,
        "eval.json",
        [
            {"task_name": "t1", "success": True, "m3_task_id": 2, "domain": "hockey", "task_number": 1},
            {"task_name": "t2", "success": False, "m3_task_id": 2, "domain": "hockey", "task_number": 2},
            {"task_name": "t3", "success": True, "m3_task_id": 3, "domain": "books", "task_number": 1},
        ],
    )

    report = generate_eval_report(run)

    assert "Tok/Task" in report
    assert "LLM/Task" in report
    assert "Dur/Task" in report
    # Raw totals are still present alongside the averages.
    assert "Tokens" in report
    assert "LLM Calls" in report


def test_load_appworld_categories_warns_when_config_missing(tmp_path, capsys):
    """A missing appworld/eval_config.toml warns on stderr instead of silently
    dropping the test-set breakdown (issue #51 review)."""
    from benchmarks.helpers.compare_report import _load_appworld_categories

    missing = tmp_path / "nope" / "eval_config.toml"
    assert _load_appworld_categories(config_path=missing) == {}
    err = capsys.readouterr().err
    assert "AppWorld category config not found" in err


def test_multi_axis_compare_report_groups_by_agent(tmp_path):
    """Two agents × two models → nested Agent -> Model sections (issue #68).

    Both axes vary, so the report nests two levels deep: "## Agent: <x>"
    headings each contain a "### Model: <y>" heading per model, and the
    actual content sections (Summary, Cost Summary, ...) are pushed to
    "#### " so the outline reflects the two-level grouping instead of
    looking flat (issue #68 review — header hierarchy)."""
    run_a = _appworld_run(tmp_path, "a.json", {"T1": True, "T2": False})
    run_b = _appworld_run(tmp_path, "b.json", {"T1": False, "T2": True})

    report = generate_report(
        {
            "gpt-oss:cuga": [run_a],
            "gpt4o:cuga": [run_b],
            "gpt-oss:react": [run_b],
            "gpt4o:react": [run_a],
        }
    )

    assert "## Agent: cuga" in report
    assert "## Agent: react" in report
    # Content sections are nested two levels deep (agent, then model), so
    # they render at #### rather than ## — one per (agent, model) combo.
    assert _heading_count(report, "## Summary") == 0
    assert _heading_count(report, "#### Summary") == 4
    # The Metrics glossary sits outside all grouping, at the original level.
    assert report.count("## Metrics") == 1
    # It's also the very last section, regardless of how deep the last
    # group's content nested (issue #68 review — misplacement inside a
    # group would still pass a bare count check but display badly).
    assert report.rstrip().endswith(report[report.rindex("## Metrics") :].rstrip())

    cuga_idx = report.index("## Agent: cuga")
    react_idx = report.index("## Agent: react")
    cuga_section = report[cuga_idx:react_idx]
    react_section = report[react_idx:]

    assert "### Model: gpt-oss" in cuga_section
    assert "### Model: gpt4o" in cuga_section
    assert "react (" not in cuga_section

    assert "### Model: gpt-oss" in react_section
    assert "### Model: gpt4o" in react_section
    assert "react (GPT-OSS-120B)" in react_section or "react (GPT-4o)" in react_section
    assert "cuga (" not in react_section


def test_single_axis_compare_report_unchanged(tmp_path):
    """Only models vary → flat single-table layout (no dimension grouping)."""
    run1 = _appworld_run(tmp_path, "r1.json", {"A": True, "B": False})
    run2 = _appworld_run(tmp_path, "r2.json", {"A": True, "B": True})

    report = generate_report({"gpt-oss:cuga": [run1, run2], "gpt4o:cuga": [run1, run2]})

    assert "## Agent:" not in report
    assert "## Model:" not in report
    assert "## Policy:" not in report
    assert report.count("## Summary") == 1
    assert report.count("## Cost Summary") == 1
    assert report.count("## Per-Task Details") == 1
    assert report.count("## Metrics") == 1
    assert "pass@2" in report
    assert "cuga (GPT-OSS-120B)" in report
    assert "cuga (GPT-4o)" in report


def test_policy_axis_grouping_flat_when_single_axis_varies(tmp_path):
    """1 agent x 1 model x 2 policies: only the policy axis varies, so the
    report must stay flat (no "## Policy:" heading) — pins the "flat when a
    single axis varies" contract (issue #68 review, test-coverage gap)."""
    run1 = _appworld_run(tmp_path, "r1.json", {"A": True, "B": False})
    run2 = _appworld_run(tmp_path, "r2.json", {"A": True, "B": True})

    report = generate_report(
        {
            "gpt-oss:cuga:policies": [run1],
            "gpt-oss:cuga:no-policies": [run2],
        }
    )

    assert "## Agent:" not in report
    assert "## Model:" not in report
    assert "## Policy:" not in report
    assert report.count("## Summary") == 1
    assert report.count("## Metrics") == 1
    assert "cuga — policies (GPT-OSS-120B)" in report
    assert "cuga — no-policies (GPT-OSS-120B)" in report


def test_model_and_policy_axis_grouping_when_agent_constant(tmp_path):
    """1 agent x 2 models x 2 policies: agent is constant, so per the agent >
    model > policy priority the report nests by model, then by policy inside
    each model (issue #68 review, test-coverage gap — previously only the
    single-axis-picks-agent path was tested)."""
    run1 = _appworld_run(tmp_path, "r1.json", {"A": True, "B": False})
    run2 = _appworld_run(tmp_path, "r2.json", {"A": True, "B": True})

    report = generate_report(
        {
            "gpt-oss:cuga:policies": [run1],
            "gpt-oss:cuga:no-policies": [run2],
            "gpt4o:cuga:policies": [run2],
            "gpt4o:cuga:no-policies": [run1],
        }
    )

    # Agent never varies here, so it must not become a grouping level.
    assert "## Agent:" not in report
    assert "## Model: gpt-oss" in report
    assert "## Model: gpt4o" in report
    # Policy nests one level deeper than model.
    assert "### Policy: policies" in report
    assert "### Policy: no-policies" in report
    # Content is pushed to the third nesting level (model, then policy).
    assert _heading_count(report, "## Summary") == 0
    assert _heading_count(report, "### Summary") == 0
    assert _heading_count(report, "#### Summary") == 4
    assert report.count("## Metrics") == 1

    oss_idx = report.index("## Model: gpt-oss")
    gpt4o_idx = report.index("## Model: gpt4o")
    oss_section = report[oss_idx:gpt4o_idx]
    assert "### Policy: policies" in oss_section
    assert "### Policy: no-policies" in oss_section


def test_three_axis_compare_report_nests_agent_model_policy(tmp_path):
    """2 agents x 2 models x 2 policies (8 combos): all three axes vary, so
    the report nests three levels deep — Agent -> Model -> Policy — with
    content pushed correspondingly deeper (issue #68 review, test-coverage
    gap: "assert which axis wins ... if nested grouping is added, assert
    sub-headings"). Also pins the Metrics glossary as the report's final
    section regardless of how deep the grouping goes."""
    run1 = _appworld_run(tmp_path, "r1.json", {"A": True, "B": False})
    run2 = _appworld_run(tmp_path, "r2.json", {"A": True, "B": True})

    configs = {}
    for agent in ("cuga", "react"):
        for model in ("gpt-oss", "gpt4o"):
            for policy in ("policies", "no-policies"):
                configs[f"{model}:{agent}:{policy}"] = [run1 if policy == "policies" else run2]

    report = generate_report(configs)

    assert "## Agent: cuga" in report
    assert "## Agent: react" in report
    assert report.count("### Model: gpt-oss") == 2  # once per agent
    assert report.count("### Model: gpt4o") == 2
    assert report.count("#### Policy: policies") == 4  # once per (agent, model)
    assert report.count("#### Policy: no-policies") == 4
    # Content sections are pushed 3 levels deep (agent, model, policy).
    assert _heading_count(report, "## Summary") == 0
    assert _heading_count(report, "### Summary") == 0
    assert _heading_count(report, "#### Summary") == 0
    assert _heading_count(report, "##### Summary") == 8  # one per (agent, model, policy) combo

    # The glossary is outside all grouping and is the report's last section.
    assert report.count("## Metrics") == 1
    metrics_idx = report.rindex("## Metrics")
    assert report.rstrip().endswith(report[metrics_idx:].rstrip())


def test_multi_axis_grouping_works_for_sdk_shape_results(tmp_path):
    """Grouping isn't AppWorld-specific: an SDK-parsed run (M3-shape, via
    ``_parse_sdk_results``) in a multi-axis comparison also gets grouped
    (issue #68 review, test-coverage gap — only AppWorld-shape fixtures were
    exercised previously)."""
    run_a = _m3_run(
        tmp_path,
        "sdk_a.json",
        [{"task_name": "t1", "success": True, "m3_task_id": 2, "domain": "hockey", "task_number": 1}],
    )
    run_b = _m3_run(
        tmp_path,
        "sdk_b.json",
        [{"task_name": "t1", "success": False, "m3_task_id": 2, "domain": "hockey", "task_number": 1}],
    )

    report = generate_report(
        {
            "gpt-oss:cuga": [run_a],
            "gpt4o:cuga": [run_b],
            "gpt-oss:react": [run_b],
            "gpt4o:react": [run_a],
        }
    )

    assert "## Agent: cuga" in report
    assert "## Agent: react" in report
    assert "### Model: gpt-oss" in report
    assert "### Model: gpt4o" in report
    assert _heading_count(report, "#### Summary") == 4


def test_vakra_scores_stay_attributed_within_grouped_sections(tmp_path):
    """Per-task metadata (here: Vakra dialogue/judge scores) must survive the
    parse-and-regroup path attributed to the right group, not leak across
    groups or get dropped (issue #68 review, test-coverage gap).

    Note: the review comment that prompted this asked for a test pinning
    ``failure_reason`` (the PR #108 content-filter marker) surviving
    regrouping specifically. PR #108 (branch fix/issue-60-content-filter-
    reporting) is still open and hasn't merged into this branch, so
    ``compare_report.py`` here has no ``failure_reason`` field at all yet —
    there's nothing to pin without pulling in that unrelated, unmerged work.
    Grouping (``_group_model_data``) only repartitions whole parsed run
    dicts by config key; it never touches per-task fields, so this test
    exercises the same risk (does per-task data survive+stay correctly
    attributed through grouping) with a field that already exists today.
    Once #108 lands, the same pattern applies directly to ``failure_reason``.
    """
    run1 = _m3_run(
        tmp_path,
        "vakra_cuga.json",
        {
            "uuid-A": {
                "m3_task_id": 2,
                "domain": "hockey",
                "task_number": 1,
                "success": True,
                "match_rate": 1.0,
                "judge_scores": {"exactmatch": 1.0},
            }
        },
    )
    run2 = _m3_run(
        tmp_path,
        "vakra_react.json",
        {
            "uuid-A": {
                "m3_task_id": 2,
                "domain": "hockey",
                "task_number": 1,
                "success": False,
                "match_rate": 0.0,
                "judge_scores": {"exactmatch": 0.0, "answer": 0.0, "groundedness": 1.0},
            }
        },
    )

    report = generate_report(
        {
            "gpt-oss:cuga": [run1],
            "gpt4o:cuga": [run1],
            "gpt-oss:react": [run2],
            "gpt4o:react": [run2],
        }
    )

    cuga_idx = report.index("## Agent: cuga")
    react_idx = report.index("## Agent: react")
    cuga_section = report[cuga_idx:react_idx]
    react_section = report[react_idx:]

    # cuga's runs all passed with dialogue=1.00/exactmatch=1.00; react's all
    # failed with dialogue=0.00 and all three judges scored 0/0/1.
    assert "Dialog" in cuga_section
    assert "1.00" in cuga_section
    assert "Dialog" in react_section
    assert "0.00" in react_section


def test_parse_sdk_results_extracts_receipt_fields():
    data = {
        "metrics": {"total_tasks": 1, "passed": 1},
        "results": [
            {
                "task_name": "t1",
                "success": True,
                "total_tokens": 150,
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_tokens": 20,
                "reasoning_tokens": 5,
                "tool_call_count": 2,
                "llm_time_s": 1.5,
                "tool_time_s": 0.5,
                "wall_time_s": 2.5,
            }
        ],
    }
    parsed = _parse_sdk_results(data)

    assert parsed["input_tokens"] == 100
    assert parsed["output_tokens"] == 50
    assert parsed["cache_read_tokens"] == 20
    assert parsed["reasoning_tokens"] == 5
    assert parsed["tool_call_count"] == 2
    assert parsed["llm_time_s"] == 1.5
    assert parsed["tool_time_s"] == 0.5
    assert parsed["wall_time_s"] == 2.5
    assert parsed["tasks"]["t1"]["input_tokens"] == 100


def test_parse_sdk_results_defaults_receipt_fields_to_zero_when_absent():
    data = {
        "metrics": {"total_tasks": 1, "passed": 1},
        "results": [{"task_name": "t1", "success": True, "total_tokens": 50}],
    }
    parsed = _parse_sdk_results(data)

    assert parsed["input_tokens"] == 0
    assert parsed["tasks"]["t1"]["input_tokens"] == 0


def test_aggregate_receipt_costs_totals_and_averages():
    tasks = {
        "t1": {
            "token_source": "receipt",
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_tokens": 20,
            "reasoning_tokens": 5,
            "tool_call_count": 2,
            "llm_time_s": 1.0,
            "tool_time_s": 0.5,
            "wall_time_s": 1.5,
        },
        "t2": {
            "token_source": "receipt",
            "input_tokens": 200,
            "output_tokens": 100,
            "cache_read_tokens": 0,
            "reasoning_tokens": 0,
            "tool_call_count": 4,
            "llm_time_s": 2.0,
            "tool_time_s": 1.0,
            "wall_time_s": 3.0,
        },
    }
    agg = _aggregate_receipt_costs(tasks)

    assert agg["total_input_tokens"] == 300
    assert agg["avg_input_tokens"] == 150
    assert agg["total_output_tokens"] == 150
    assert agg["total_tool_call_count"] == 6
    assert agg["avg_wall_time_s"] == 2.25


def test_aggregate_receipt_costs_all_none_when_no_receipt_data():
    tasks = {"t1": {"tokens": 50}}  # legacy shape, no receipt fields at all
    agg = _aggregate_receipt_costs(tasks)

    assert agg["total_input_tokens"] is None
    assert agg["avg_input_tokens"] is None


def test_aggregate_receipt_costs_detects_nontoken_receipt_data():
    """When a task has zero token-related fields but nonzero non-token fields
    (tool_call_count, llm_time_s, tool_time_s, wall_time_s, cache_read_tokens,
    reasoning_tokens), _aggregate_receipt_costs must recognize this as receipt
    data and return real numbers, not None."""
    tasks = {
        "t1": {
            "token_source": "receipt",
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "reasoning_tokens": 0,
            "tool_call_count": 3,  # nonzero non-token field
            "llm_time_s": 1.5,  # nonzero non-token field
            "tool_time_s": 0.0,
            "wall_time_s": 2.0,  # nonzero non-token field
        }
    }
    agg = _aggregate_receipt_costs(tasks)

    # All fields should have real numbers, not None
    assert agg["total_tool_call_count"] == 3
    assert agg["avg_tool_call_count"] == 3
    assert agg["total_llm_time_s"] == 1.5
    assert agg["avg_llm_time_s"] == 1.5
    assert agg["total_wall_time_s"] == 2.0
    assert agg["avg_wall_time_s"] == 2.0
    # Token fields are still 0, not None
    assert agg["total_input_tokens"] == 0
    assert agg["avg_input_tokens"] == 0


def test_aggregate_receipt_costs_detects_genuine_all_zero_receipt():
    """A task marked token_source == "receipt" whose every receipt field is
    legitimately 0 (e.g. a call that used 0 output tokens) must still be
    detected as carrying receipt data — the marker, not field truthiness,
    decides this (cuga-eval#182 CodeRabbit review)."""
    tasks = {
        "t1": {
            "token_source": "receipt",
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "reasoning_tokens": 0,
            "tool_call_count": 0,
            "llm_time_s": 0.0,
            "tool_time_s": 0.0,
            "wall_time_s": 0.0,
        }
    }
    agg = _aggregate_receipt_costs(tasks)

    assert agg["total_input_tokens"] == 0
    assert agg["avg_input_tokens"] == 0
    assert agg["total_wall_time_s"] == 0.0
    assert agg["avg_wall_time_s"] == 0.0


def test_aggregate_receipt_costs_averages_only_over_receipt_tagged_tasks():
    """A run with a mix of receipt-tagged tasks and legacy/non-receipt tasks
    (no token_source, everything defaulted to 0) must average only over the
    receipt-tagged subset — dividing by the full task count would silently
    dilute the average toward zero (cuga-eval#182 CodeRabbit review)."""
    tasks = {
        "t1": {
            "token_source": "receipt",
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_tokens": 0,
            "reasoning_tokens": 0,
            "tool_call_count": 1,
            "llm_time_s": 1.0,
            "tool_time_s": 0.0,
            "wall_time_s": 1.0,
        },
        "t2": {
            "token_source": "receipt",
            "input_tokens": 200,
            "output_tokens": 100,
            "cache_read_tokens": 0,
            "reasoning_tokens": 0,
            "tool_call_count": 1,
            "llm_time_s": 1.0,
            "tool_time_s": 0.0,
            "wall_time_s": 1.0,
        },
        "t3_legacy": {
            # No token_source at all: pre-migration task, never opted in.
            "input_tokens": 0,
            "output_tokens": 0,
        },
    }
    agg = _aggregate_receipt_costs(tasks)

    # Average must divide by 2 (the receipt-tagged count), not 3.
    assert agg["total_input_tokens"] == 300
    assert agg["avg_input_tokens"] == 150
    assert agg["total_output_tokens"] == 150
    assert agg["avg_output_tokens"] == 75


def _write_sdk_result_file(tmp_path, results, name="results.json"):
    path = tmp_path / name
    path.write_text(
        json.dumps({"metrics": {"total_tasks": len(results), "passed": len(results)}, "results": results})
    )
    return str(path)


def test_generate_eval_report_includes_receipt_breakdown_when_present(tmp_path):
    results = [
        {
            "task_name": "t1",
            "success": True,
            "total_tokens": 150,
            "token_source": "receipt",
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_tokens": 20,
            "reasoning_tokens": 5,
            "tool_call_count": 2,
            "llm_time_s": 1.5,
            "tool_time_s": 0.5,
            "wall_time_s": 2.5,
        }
    ]
    report = generate_eval_report(_write_sdk_result_file(tmp_path, results))

    assert "Run Receipt Breakdown" in report
    assert "Input Tokens" in report
    assert "100" in report


def test_generate_eval_report_omits_receipt_breakdown_when_absent(tmp_path):
    results = [{"task_name": "t1", "success": True, "total_tokens": 150}]
    report = generate_eval_report(_write_sdk_result_file(tmp_path, results))

    assert "Run Receipt Breakdown" not in report


def test_generate_report_includes_receipt_breakdown_when_present(tmp_path):
    results = [
        {
            "task_name": "t1",
            "success": True,
            "total_tokens": 150,
            "token_source": "receipt",
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_tokens": 20,
            "reasoning_tokens": 5,
            "tool_call_count": 2,
            "llm_time_s": 1.5,
            "tool_time_s": 0.5,
            "wall_time_s": 2.5,
        }
    ]
    result_file = _write_sdk_result_file(tmp_path, results)
    report = generate_report({"gpt-oss-120b": [result_file]})

    assert "Run Receipt Breakdown" in report
    assert "In Tok" in report


def test_generate_report_omits_receipt_breakdown_when_absent(tmp_path):
    results = [{"task_name": "t1", "success": True, "total_tokens": 150}]
    result_file = _write_sdk_result_file(tmp_path, results)
    report = generate_report({"gpt-oss-120b": [result_file]})

    assert "Run Receipt Breakdown" not in report


def test_generate_report_detects_nontoken_receipt_data(tmp_path):
    """Same class of bug as test_aggregate_receipt_costs_detects_nontoken_receipt_data,
    but for _render_compare_report_sections's own any_receipt_data gate: a run
    with zero input_tokens/output_tokens but nonzero tool_call_count/wall_time_s
    must still trigger the "Run Receipt Breakdown" section (cuga-eval#95 final
    review finding — the gate previously only looked at 2 of 8 receipt fields)."""
    results = [
        {
            "task_name": "t1",
            "success": True,
            "total_tokens": 0,
            "token_source": "receipt",
            "input_tokens": 0,
            "output_tokens": 0,
            "tool_call_count": 3,
            "wall_time_s": 2.0,
        }
    ]
    result_file = _write_sdk_result_file(tmp_path, results)
    report = generate_report({"gpt-oss-120b": [result_file]})

    assert "Run Receipt Breakdown" in report


def test_generate_report_detects_genuine_all_zero_receipt(tmp_path):
    """A run whose single task has token_source == "receipt" but every
    receipt field is legitimately 0 must still trigger the "Run Receipt
    Breakdown" section — field truthiness alone would wrongly treat this as
    "no receipt data" (cuga-eval#182 CodeRabbit review)."""
    results = [
        {
            "task_name": "t1",
            "success": True,
            "total_tokens": 0,
            "token_source": "receipt",
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "reasoning_tokens": 0,
            "tool_call_count": 0,
            "llm_time_s": 0.0,
            "tool_time_s": 0.0,
            "wall_time_s": 0.0,
        }
    ]
    result_file = _write_sdk_result_file(tmp_path, results)
    report = generate_report({"gpt-oss-120b": [result_file]})
    eval_report = generate_eval_report(result_file)

    assert "Run Receipt Breakdown" in report
    assert "Run Receipt Breakdown" in eval_report


def test_generate_report_shows_dash_for_config_without_receipt_data(tmp_path):
    """A/B comparison between a baseline bundle predating the receipt feature
    (no receipt fields at all) and a new one that has them: the baseline's row
    in the Run Receipt Breakdown table must render "--", not "0" (cuga-eval#95
    final review finding — a config with no receipt data looked identical to
    one that measured real zeros)."""
    with_receipt = [
        {
            "task_name": "t1",
            "success": True,
            "total_tokens": 150,
            "token_source": "receipt",
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_tokens": 20,
            "reasoning_tokens": 5,
            "tool_call_count": 2,
            "llm_time_s": 1.5,
            "tool_time_s": 0.5,
            "wall_time_s": 2.5,
        }
    ]
    without_receipt = [{"task_name": "t1", "success": True, "total_tokens": 150}]

    file_with = _write_sdk_result_file(tmp_path, with_receipt, name="with.json")
    file_without = _write_sdk_result_file(tmp_path, without_receipt, name="without.json")

    report = generate_report({"model-with-receipt": [file_with], "model-without-receipt": [file_without]})

    assert "Run Receipt Breakdown" in report

    breakdown = report.split("Run Receipt Breakdown", 1)[1]
    with_line = next(line for line in breakdown.splitlines() if "model-with-receipt" in line)
    without_line = next(line for line in breakdown.splitlines() if "model-without-receipt" in line)

    assert "100" in with_line
    assert "--" not in with_line

    assert "--" in without_line
    assert "0" not in without_line


# ---------------------------------------------------------------------------
# Per-task Input/Output/Reasoning columns (cuga-eval#95 follow-up).
#
# These are distinct from the "Run Receipt Breakdown" summary section tested
# above: the columns added here appear unconditionally on the genuinely
# per-task tables (Per-Task Results in generate_eval_report, Per-Task Details
# in generate_report), the same way `Cache Tokens` already does — they are
# not gated behind "does this result carry receipt data".
# ---------------------------------------------------------------------------


def test_eval_report_grouped_per_task_table_shows_input_output_reasoning(tmp_path):
    """generate_eval_report's grouped (M3), non-Vakra per-task table gains
    Input/Output/Reasoning columns with correct per-task values."""
    result_file = _m3_run(
        tmp_path,
        "m3_receipt.json",
        {
            "uuid-a": {"m3_task_id": 2, "domain": "hockey", "task_number": 1, "success": True},
            "uuid-b": {"m3_task_id": 2, "domain": "hockey", "task_number": 2, "success": False},
        },
    )
    # _m3_run doesn't plumb receipt fields, so patch them into the raw file.
    payload = json.loads(Path(result_file).read_text())
    payload["results"][0].update({"input_tokens": 111, "output_tokens": 22, "reasoning_tokens": 3})
    payload["results"][1].update({"input_tokens": 444, "output_tokens": 55, "reasoning_tokens": 6})
    Path(result_file).write_text(json.dumps(payload))

    report = generate_eval_report(result_file)

    assert (
        "| Task | Domain | # | Result | Tokens | Cost | LLM Calls | Cache Tokens "
        "| Input | Output | Reasoning | Duration | Steps |" in report
    )
    assert "| 111 | 22 | 3 |" in report
    assert "| 444 | 55 | 6 |" in report


def test_eval_report_legacy_per_task_table_shows_input_output_reasoning(tmp_path):
    """generate_eval_report's non-grouped/legacy per-task table (e.g. AppWorld)
    gains Input/Output/Reasoning columns with correct per-task values."""
    results = [
        {
            "task_name": "t1",
            "success": True,
            "total_tokens": 150,
            "input_tokens": 100,
            "output_tokens": 50,
            "reasoning_tokens": 5,
        }
    ]
    report = generate_eval_report(_write_sdk_result_file(tmp_path, results))

    assert (
        "| Task | Result | Tokens | Cost | LLM Calls | Cache Tokens "
        "| Input | Output | Reasoning | Duration | Steps |" in report
    )
    assert "| 100 | 50 | 5 |" in report


def test_eval_report_per_task_table_shows_zero_when_receipt_fields_absent(tmp_path):
    """Legacy/non-receipt result files (no input_tokens/output_tokens/
    reasoning_tokens at all) still render the per-task table without crashing;
    the new columns are unconditional so they show 0 (matching the existing
    `.get(field, 0)` default from `_parse_sdk_results`), not `--`."""
    results = [{"task_name": "t1", "success": True, "total_tokens": 150}]
    report = generate_eval_report(_write_sdk_result_file(tmp_path, results))

    assert (
        "| Task | Result | Tokens | Cost | LLM Calls | Cache Tokens "
        "| Input | Output | Reasoning | Duration | Steps |" in report
    )
    assert "| 0 | 0 | 0 |" in report


def test_stats_for_task_computes_mean_input_output_reasoning():
    task_runs = [
        {"token_source": "receipt", "input_tokens": 100, "output_tokens": 20, "reasoning_tokens": 2},
        {"token_source": "receipt", "input_tokens": 200, "output_tokens": 40, "reasoning_tokens": 6},
    ]
    stats = _stats_for_task(task_runs)

    assert stats["mean_input"] == 150
    assert stats["mean_output"] == 30
    assert stats["mean_reasoning"] == 4


def test_compare_report_per_task_details_shows_input_output_reasoning_and_average(tmp_path):
    """generate_report's Per-Task Details table gains Input/Output/Reasoning
    columns, correctly averaged per task and in the AVERAGE row."""
    results_r1 = [
        {
            "task_name": "t1",
            "success": True,
            "total_tokens": 150,
            "token_source": "receipt",
            "input_tokens": 100,
            "output_tokens": 20,
        },
        {
            "task_name": "t2",
            "success": True,
            "total_tokens": 150,
            "token_source": "receipt",
            "input_tokens": 300,
            "output_tokens": 60,
        },
    ]
    results_r2 = [
        {
            "task_name": "t1",
            "success": True,
            "total_tokens": 150,
            "token_source": "receipt",
            "input_tokens": 200,
            "output_tokens": 40,
        },
        {
            "task_name": "t2",
            "success": True,
            "total_tokens": 150,
            "token_source": "receipt",
            "input_tokens": 300,
            "output_tokens": 60,
        },
    ]
    run1 = _write_sdk_result_file(tmp_path, results_r1, name="r1.json")
    run2 = _write_sdk_result_file(tmp_path, results_r2, name="r2.json")

    report = generate_report({"gpt-oss:cuga": [run1, run2]})

    assert "Input" in report
    assert "Output" in report
    assert "Reason" in report
    # t1: mean input = (100+200)/2 = 150.0, mean output = (20+40)/2 = 30.0.
    # t2: mean input = 300.0, mean output = 60.0 (constant across both runs).
    # AVERAGE row: mean input across tasks = (150+300)/2 = 225.0, mean output = (30+60)/2 = 45.0.
    lines = report.splitlines()
    t1_line = next(ln for ln in lines if ln.strip().startswith("t1 "))
    t2_line = next(ln for ln in lines if ln.strip().startswith("t2 "))
    avg_line = next(ln for ln in lines if "AVERAGE" in ln)
    assert "150.0" in t1_line
    assert "300.0" in t2_line
    assert "225.0" in avg_line
    assert "45.0" in avg_line


def test_eval_report_appworld_task_results_shape_defaults_receipt_fields_to_zero(tmp_path):
    """Legacy AppWorld `task_results`-shaped result files (still produced today by
    appworld_eval.py / appworld_eval_react.py / appworld_eval_codeact.py, parsed by
    `_parse_appworld_results` rather than `_parse_sdk_results`) carry no
    input_tokens/output_tokens/reasoning_tokens on their per-task dicts. These must
    default to 0 (mirroring the existing `cache_tokens` default on the very next
    line), not be left absent -- an absent key renders `--` in the per-task table,
    which would sit inconsistently next to a `0` Cache Tokens on the same row
    (cuga-eval#95 follow-up review finding)."""
    result_file = _appworld_eval_run(
        tmp_path,
        "appworld_no_receipt.json",
        {
            "t1": {
                "success": True,
                "total_tokens": 150,
                "total_llm_calls": 3,
                "cache_input_tokens": 0,
                "full_execution_time": 5.0,
                "steps": 4,
            }
        },
    )

    report = generate_eval_report(result_file)

    assert (
        "| Task | Result | Tokens | Cost | LLM Calls | Cache Tokens "
        "| Input | Output | Reasoning | Duration | Steps |" in report
    )
    row = next(ln for ln in report.splitlines() if ln.startswith("| t1 "))
    # Cache Tokens, Input, Output, Reasoning are all genuinely absent from the
    # source data and must all render as 0, not `--`.
    assert "| 0 | 0 | 0 | 0 |" in row
    assert "--" not in row
