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
    _last_turn_judge_scores,
    _m3_capability_group,
    _parse_sdk_results,
    generate_eval_report,
    generate_report,
)

pytestmark = pytest.mark.regression


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
        "| Task | Domain | # | Result | Tokens | Cost | LLM Calls | Cache Tokens | Duration | Steps |"
        in report
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
    """Two agents × two models → labeled section per agent (issue #68)."""
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
    assert report.count("## Summary") == 2

    cuga_idx = report.index("## Agent: cuga")
    react_idx = report.index("## Agent: react")
    cuga_section = report[cuga_idx:react_idx]
    react_section = report[react_idx:]

    assert "GPT-OSS-120B" in cuga_section
    assert "GPT-4o" in cuga_section
    assert "react (" not in cuga_section

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
