"""The harness: the known numbers from saved files, old result files, what is not graded, the baseline prompt, the ledger.

Code that needs ``cuga`` runs in the gate repo's Python, as ``test_runtime_golden`` does. No agent and no model call.
"""

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

POLICY_EVAL = Path(__file__).resolve().parents[1]
BENCHMARKS = POLICY_EVAL.parent
sys.path.insert(0, str(BENCHMARKS))
import policy_pilot_costs as costs  # noqa: E402
from policy_eval.envs.compose_env import TAU2_AGENT, compose, merge, parse_runner  # noqa: E402
from policy_eval.harness import report as rp  # noqa: E402
from policy_eval.harness import run as hr  # noqa: E402
from policy_eval.harness.adapters.base import BenchmarkAdapter, with_note  # noqa: E402
from policy_eval.harness.adapters.handbook import sop_text_of  # noqa: E402
from policy_eval.harness.result import NotAResult, Result, Score, all_from_legacy, from_legacy  # noqa: E402

GATE_PYTHON = os.environ.get("POLICY_GATE_PYTHON") or str(
    Path.home() / "dev/cuga-agent-gate/.venv/bin/python"
)
GATE_SRC = Path(GATE_PYTHON).parents[2] / "src"
AB_PYTHON = BENCHMARKS / "automationbench" / ".venv" / "bin" / "python"
TAU2_PYTHON = Path.home() / "dev/cuga-eval-tau2/.venv/bin/python"
TAU2_ROOT = Path.home() / "dev/cuga-eval-tau2/benchmarks/tau2"
AB_RESULTS = BENCHMARKS / "automationbench" / "results"
HB_RESULTS = BENCHMARKS / "handbook" / "results"
ITSM_RESULTS = BENCHMARKS / "enterpriseops_gym" / "results"
ARCHIVE = POLICY_EVAL / "launchers" / "archive"


def arms(*specs):
    return rp.compare({s: rp.load_arm(s) for s in specs})


def missing_input(reason):
    """Saved folders and venvs are not in git, so on another machine these tests would pass by skipping. With
    ``EVAL_NO_SKIP=1`` a missing input is a failure."""
    if os.environ.get("EVAL_NO_SKIP"):
        pytest.fail(f"EVAL_NO_SKIP is set: {reason}")
    pytest.skip(reason)


def need(*folders):
    missing = [str(f) for f in folders if not f.is_dir()]
    if missing:
        missing_input(f"saved files are missing: {missing}")


# -- the known numbers, from saved files only ------------------------------------------------------------------------------


def test_held_out_automationbench_b4tf():
    need(*(AB_RESULTS / f"ph_{a}_t{t}" for a in ("AF", "B4TF") for t in (1, 2)))
    base, b4tf = arms("ph_AF", "ph_B4TF")["ph: automationbench"]
    assert (base.results, b4tf.results, b4tf.common) == (70, 70, 35)
    assert round(100 * base.mean, 1) == 23.8 and round(100 * b4tf.mean, 1) == 42.7
    assert round(100 * b4tf.diff, 1) == 18.9
    assert (b4tf.better, b4tf.worse, b4tf.same) == (24, 6, 5)
    assert round(b4tf.p, 3) == 0.001


def test_second_held_out_automationbench_and_note_placement():
    need(*(AB_RESULTS / f"pq_{a}_t{t}" for a in ("AF", "B4TF", "B4TFM") for t in (1, 2)))
    _, b4tf, b4tfm = arms("pq_AF", "pq_B4TF", "pq_B4TFM")["pq: automationbench"]
    assert round(100 * b4tf.diff, 1) == 8.8
    assert (b4tf.better, b4tf.worse, b4tf.same) == (14, 6, 11)
    assert round(b4tf.p, 3) == 0.115
    assert round(100 * b4tfm.diff, 1) == 4.6
    assert (b4tfm.better, b4tfm.worse, b4tfm.same) == (13, 9, 9)


def test_handbook_rubric_items_of_three_arms():
    need(
        *(
            HB_RESULTS / f"hbq_{t}_{a}_t{n}"
            for t in ("ci", "cw", "vg")
            for a in ("A", "GR", "GW")
            for n in (1, 2, 3)
        )
    )
    alone, raw_gate, graph_gate = arms("hbq_A", "hbq_GR", "hbq_GW")["hbq: handbook"]
    assert [a.items_passed for a in (alone, raw_gate, graph_gate)] == [49, 51, 54]
    assert {a.items_total for a in (alone, raw_gate, graph_gate)} == {153}
    assert {a.results for a in (alone, raw_gate, graph_gate)} == {9}


def test_telecom_sop_tracker_counts_each_task_once():
    need(*(TAU2_ROOT / f"logging_test{r}_{a}_s{s}" for r in (1, 2) for a in "AT" for s in range(5)))
    alone, tracker = arms("test1_A,test2_A", "test1_T,test2_T")["test1: tau2-telecom"]
    assert (alone.results, tracker.results, tracker.common) == (80, 80, 40)
    assert alone.mean == pytest.approx(51 / 80) and tracker.mean == pytest.approx(61 / 80)
    assert rp._percent(alone.mean) == "63.8%" and rp._percent(tracker.mean) == "76.2%"
    assert (tracker.better, tracker.worse) == (9, 3)
    assert round(tracker.p, 3) == 0.146  # counting runs and not tasks gave a false 0.041 (change 86)


def test_the_setting_turns_a_skip_into_a_failure(monkeypatch, tmp_path):
    monkeypatch.delenv("EVAL_NO_SKIP", raising=False)
    with pytest.raises(pytest.skip.Exception):
        need(tmp_path / "gone")
    monkeypatch.setenv("EVAL_NO_SKIP", "1")
    with pytest.raises(pytest.fail.Exception, match="gone"):
        need(tmp_path / "gone")


def test_the_numbers_of_pass_and_guardrails_are_per_task():
    need(*(AB_RESULTS / f"ph_{a}_t{t}" for a in ("AF", "B4TF") for t in (1, 2)))
    base, b4tf = arms("ph_AF", "ph_B4TF")["ph: automationbench"]
    # 2 trials on all 35 tasks: the count over 70 results and the mean over tasks are the same number
    assert base.guardrails_broken == pytest.approx(37 / 70) and b4tf.guardrails_broken == pytest.approx(
        34 / 70
    )
    assert b4tf.common == 35


def test_sign_test():
    assert rp.sign_p(9, 12) == pytest.approx(2 * 299 / 4096)
    assert rp.sign_p(3, 12) == rp.sign_p(9, 12)
    assert rp.sign_p(0, 0) == 1.0


# -- old result files ---------------------------------------------------------------------------------------------------


def one_file(folder, pattern="*.json"):
    files = sorted(folder.glob(pattern)) if folder.is_dir() else []
    if not files:
        missing_input(f"saved files are missing: {folder}")
    return files[0]


def test_each_old_format_gives_a_result_and_stays_as_it_is():
    path = one_file(AB_RESULTS / "ph_B4TF_t1")
    before = path.read_bytes()
    ab = from_legacy(path)
    assert path.read_bytes() == before
    assert ab.benchmark == "automationbench" and ab.trial == 1 and ab.run == "ph_B4TF_t1"
    assert ab.score.primary == json.loads(before)["partial_credit"]
    assert ab.score.guardrails_broken == json.loads(before)["guards_broken"]
    assert ab.agent_model == "aws/gpt-oss-120b" and ab.profile == "legacy:B4T-F"
    assert ab.usage_by_component["agent"]["model"] == "aws/gpt-oss-120b"
    assert ab.code_sha

    hb = from_legacy(one_file(HB_RESULTS / "hbq_ci_GW_t1"))
    assert hb.benchmark == "handbook" and hb.agent_model == "aws/gpt-oss-120b"
    assert hb.score.detail["items_total"] == 17 and hb.score.primary == hb.score.detail["items_passed"] / 17

    itsm = from_legacy(one_file(ITSM_RESULTS / "ds2u_t1", "A_*.json"))
    assert itsm.benchmark == "itsm" and itsm.task.startswith("task_")
    assert itsm.score.partial == itsm.score.detail["verifiers_passed"] / itsm.score.detail["verifiers_total"]
    assert itsm.score.guardrails_broken is None

    shard = one_file(TAU2_ROOT / "logging_test1_T_s0" / "results", "tau2_*.json")
    rows = all_from_legacy(shard)
    assert len(rows) == 8 and {r.benchmark for r in rows} == {"tau2-telecom"} and rows[0].run == "test1_T_s0"
    assert from_legacy(shard, task=rows[0].task).task == rows[0].task
    with pytest.raises(NotAResult):
        from_legacy(shard)


def test_an_old_result_with_no_grade_has_no_score(tmp_path):
    cases = {
        "ab.json": {"task": "a.b", "toolset": "full", "error": "x"},
        "itsm.json": {"task_id": "t", "arm": "B", "error": "x"},
        "hb.json": {"task": "h", "container": "c", "error": "infra: x", "rubrics_total": None},
        "tau.json": {"task_id": "t", "domain": "telecom", "reward": None, "error": "x"},
    }
    for name, raw in cases.items():
        (tmp_path / name).write_text(json.dumps(raw))
        result = from_legacy(tmp_path / name)
        assert result.score is None and result.error


def test_a_file_that_is_no_result_says_so(tmp_path):
    (tmp_path / "review.json").write_text(json.dumps({"330260d34d0b9ece": 1}))
    with pytest.raises(NotAResult):
        from_legacy(tmp_path / "review.json")


def test_a_new_result_reads_back(tmp_path):
    result = Result(
        benchmark="itsm",
        task="t",
        profile="itsm-rules",
        trial=2,
        run="r_t2",
        code_sha="abc",
        score=Score(1.0, 0.5, True, None, {"verifiers_total": 2}),
        usage_by_component={"agent": {"model": "m", "input_tokens": 1}},
    )
    path = tmp_path / "t.json"
    result.write(path)
    assert json.loads(path.read_text())["score"]["pass"] is True
    assert from_legacy(path) == result


# -- what the report counts ---------------------------------------------------------------------------------------------


def write_run(root, run, scores, benchmark="itsm"):
    folder = root / run
    folder.mkdir(parents=True)
    for task, value in scores.items():
        score = None if value is None else Score(value, value, value == 1.0)
        Result(
            benchmark=benchmark,
            task=task,
            run=run,
            score=score,
            error=None if score else "wiring: no package",
        ).write(folder / f"{task}.json")


def test_a_result_with_no_score_is_listed_and_is_not_a_zero(tmp_path):
    write_run(tmp_path, "x_A_t1", {"t1": 1.0, "t2": 0.0, "t3": 1.0})
    write_run(tmp_path, "x_B_t1", {"t1": 1.0, "t2": 1.0, "t3": None})
    where = {"roots": [tmp_path], "tau2_root": tmp_path / "none"}
    base, other = rp.compare({s: rp.load_arm(s, **where) for s in ("x_A", "x_B")})["x: itsm"]
    assert other.results == 2 and other.mean == 1.0 and len(other.not_graded) == 1
    assert "wiring" in other.not_graded[0]
    assert other.common == 2 and (other.better, other.worse, other.same) == (1, 0, 1)


def test_an_arm_with_nothing_graded_shows_no_number(tmp_path):
    write_run(tmp_path, "w_A_t1", {"t1": 1.0})
    write_run(tmp_path, "w_B_t1", {"t1": None})
    where = {"roots": [tmp_path], "tau2_root": tmp_path / "none"}
    _, other = rp.compare({s: rp.load_arm(s, **where) for s in ("w_A", "w_B")})["w: itsm"]
    assert other.mean is None and other.diff is None and other.p is None and other.common == 0
    assert rp._percent(other.mean) == ""


def write_result(root, run, task, primary, passed, broken):
    folder = root / run
    folder.mkdir(parents=True, exist_ok=True)
    Result(
        benchmark="automationbench", task=task, run=run, score=Score(primary, primary, passed, broken)
    ).write(folder / f"{task}.json")


def test_pass_and_guardrails_do_not_weigh_a_task_by_its_trials(tmp_path):
    for trial in (1, 2, 3):  # t1 ran three times and t2 once
        write_result(tmp_path, f"v_A_t{trial}", "t1", 0.0, False, 2)
    write_result(tmp_path, "v_A_t1", "t2", 1.0, True, 0)
    arm = rp.summarize("v_A", rp.load_arm("v_A", roots=[tmp_path], tau2_root=tmp_path / "none"))
    assert arm.results == 4 and arm.pass_rate == 0.5  # 1 of 4 results, 1 of 2 tasks
    assert arm.guardrails_broken == 1.0  # 6 over 4 results, 2 and 0 over the 2 tasks


def test_the_report_prints_the_pairs_behind_the_diff(tmp_path):
    write_run(tmp_path, "u_A_t1", {"t1": 0.0, "t2": 0.0, "t3": 0.0})
    write_run(tmp_path, "u_B_t1", {"t1": 1.0, "t2": 1.0})
    text = rp.render(["u_A", "u_B"], roots=[tmp_path], tau2_root=tmp_path / "none")
    header, _, base_row, other_row = [line for line in text.splitlines() if line.startswith("|")]
    columns = [c.strip() for c in header.split("|")]
    other = dict(zip(columns, (c.strip() for c in other_row.split("|"))))
    assert other["Pairs"] == "2" and other["Tasks"] == "2"
    assert dict(zip(columns, (c.strip() for c in base_row.split("|"))))["Tasks"] == "3"
    assert other["Diff vs u_A (pts)"] == "+100.0"


def test_one_count_per_task_over_trials(tmp_path):
    write_run(tmp_path, "y_A_t1", {"t1": 0.0, "t2": 1.0})
    write_run(tmp_path, "y_A_t2", {"t1": 1.0, "t2": 1.0})
    write_run(tmp_path, "y_B_t1", {"t1": 1.0, "t2": 1.0})
    write_run(tmp_path, "y_B_t2", {"t1": 1.0, "t2": 1.0})
    where = {"roots": [tmp_path], "tau2_root": tmp_path / "none"}
    _, other = rp.compare({s: rp.load_arm(s, **where) for s in ("y_A", "y_B")})["y: itsm"]
    assert other.results == 4 and other.common == 2 and (other.better, other.worse, other.same) == (1, 0, 1)


def test_a_run_name_that_finds_nothing_two_places_or_two_arms_raises(tmp_path):
    where = {"roots": [tmp_path / "a", tmp_path / "b"], "tau2_root": tmp_path / "none"}
    with pytest.raises(rp.ReportError, match="no run matches"):
        rp.load_arm("z_A", **where)
    write_run(tmp_path / "a", "z_A_t1", {"t1": 1.0})
    write_run(tmp_path / "b", "z_A_t1", {"t1": 1.0})
    with pytest.raises(rp.ReportError, match="2 places"):
        rp.load_arm("z_A", **where)
    both = tmp_path / "c" / "two_t1"
    both.mkdir(parents=True)
    for name in ("A_task_1.json", "B_task_1.json"):
        (both / name).write_text(json.dumps({"task_id": "task_1", "passed": True, "verifiers_total": 1}))
    with pytest.raises(rp.ReportError, match="two_t1:<arm>"):
        rp.load_arm("two", roots=[tmp_path / "c"], tau2_root=tmp_path / "none")
    assert len(rp.load_arm("two_t1:A", roots=[tmp_path / "c"], tau2_root=tmp_path / "none")) == 1


def test_arms_of_two_benchmarks_are_two_groups(tmp_path):
    write_run(tmp_path, "s_a_t1", {"t1": 1.0})
    write_run(tmp_path, "s_b_t1", {"h1": 0.5}, benchmark="handbook")
    where = {"roots": [tmp_path], "tau2_root": tmp_path / "none"}
    groups = rp.compare({s: rp.load_arm(s, **where) for s in ("s_a", "s_b")})
    assert sorted(groups) == ["s: handbook", "s: itsm"]
    assert all(arms[0].diff is None for arms in groups.values())


def test_a_timeout_that_holds_the_digits_of_a_gateway_error_is_no_gateway_error():
    for error in (
        "timeout after 1429s",
        "timeout after 429s",
        "timeout after 500s",
        "timeout after 1503s",
        None,
        "",
    ):
        assert not hr.is_infra(error), error


@pytest.mark.parametrize(
    "error",
    [
        "429 too many requests",
        "OpenAIRateLimitError: slow down",
        "APIConnectionError: x",
        "Connection error.",
        "Error code: 403 - Forbidden",
        "team_model_access_denied",
        "Error code: 500 - upstream",
        "Error code: 502",
        "Server error '503 Service Unavailable' for url",
        "Error code: 504",
        "litellm.InternalServerError: down",
        "litellm.ServiceUnavailableError: down",
        "Request timed out.",
        "httpx.ReadTimeout",
        "Error code: 401 - {'error': 'invalid key'}",
        "Error code: 408 - request timeout",
        "litellm.Timeout: Connection timed out. Timeout passed=600.0",
        "Server disconnected without sending a response.",
    ],
)
def test_a_gateway_error_is_known(error):
    assert hr.is_infra(error)


@pytest.mark.parametrize(
    "error",
    [
        "timeout after 500s",
        "ValueError: bad state",
        "Error: no plan",
        "Recursion limit of 135 reached without hitting a stop condition.",
    ],
)
def test_an_error_of_the_agent_is_no_gateway_error(error):
    assert not hr.is_infra(error)


def test_each_benchmark_keeps_the_time_it_has_used(monkeypatch):
    assert {name: cls().default_timeout for name, cls in hr.ADAPTERS.items()} == {
        "automationbench": 1800.0,
        "handbook": 3600.0,
        "itsm": 1200.0,
        "tau2": 1800.0,
    }
    seen = {}

    async def fake_run_many(tasks, adapter, args):
        seen[args.bench] = args.timeout
        return 0

    monkeypatch.setattr(hr, "run_many", fake_run_many)
    monkeypatch.setattr(hr, "snapshot_src", lambda name: Path("/snap/src"))
    monkeypatch.setattr(hr.ADAPTERS["handbook"], "python", Path(sys.executable))
    base = ["run.py", "--profile", "baseline", "--snapshot", "s", "--run", "r", "--bench"]
    monkeypatch.setattr(sys, "argv", [*base, "handbook", "--set", "handbook-public3"])
    assert hr.main() == 0 and seen["handbook"] == 3600.0
    monkeypatch.setattr(sys, "argv", [*base, "handbook", "--set", "handbook-public3", "--timeout", "60"])
    assert hr.main() == 0 and seen["handbook"] == 60.0


def test_each_group_says_the_label_of_its_task_set_and_what_its_model_has_run():
    need(
        AB_RESULTS / "ph_AF_t1",
        AB_RESULTS / "ph_B4TF_t1",
        AB_RESULTS / "pq_AF_t1",
        HB_RESULTS / "hbq_ci_A_t1",
    )
    text = rp.render(["ph_AF", "ph_B4TF"])
    assert "set ab-policy-types-holdout (seen; aws/gpt-oss-120b ran 35 of 35)" in text
    assert "held-out" not in text  # a held-out set that a model has run is seen
    text = rp.render(["pq_AF", "pq_B4TF"])
    assert "set ab-policy-types-holdout2 (seen; aws/gpt-oss-120b ran 31 of 31)" in text
    assert "set handbook-public3 (tuning; " in rp.render(["hbq_A", "hbq_GW"])


def test_a_set_no_model_has_run_is_held_out_and_a_new_model_on_a_seen_set_ran_none(tmp_path):
    path = tmp_path / "registry.json"
    common = {"benchmark": "itsm", "ids": ["t1", "t2"], "n": 2, "status": "heldout"}
    fresh = {**common, "id": "fresh", "seen_n": {}}
    path.write_text(json.dumps({"sets": [fresh]}))
    assert rp.task_set_of("itsm", {"t1"}, path, ["m1"]) == "fresh (held-out; m1 ran 0 of 2)"
    path.write_text(json.dumps({"sets": [{**fresh, "seen_n": {"m2": 2}}]}))
    assert rp.task_set_of("itsm", {"t1"}, path, ["m1"]) == "fresh (seen; m1 ran 0 of 2)"
    assert rp.task_set_of("itsm", {"t1"}, path, ["m1", "m2"]) == "fresh (seen; m1 ran 0 of 2; m2 ran 2 of 2)"
    assert rp.task_set_of("itsm", {"t1"}, path) == "fresh (seen)"
    tuning = {**fresh, "status": "tuning", "seen_n": {"m1": 1}}
    path.write_text(json.dumps({"sets": [tuning]}))
    assert rp.task_set_of("itsm", {"t1"}, path, ["m1"]) == "fresh (tuning; m1 ran 1 of 2)"


# -- one code and one profile in a run folder --------------------------------------------------------------------------


def versioned(path, score=1.0, code_sha="abc", profile_hash="p1"):
    Result(
        benchmark="itsm",
        task=path.stem,
        run=path.parent.name,
        code_sha=code_sha,
        profile_hash=profile_hash,
        score=None if score is None else Score(score, score, score == 1.0),
    ).write(path)
    return path


def test_a_result_of_this_code_and_profile_is_done(tmp_path):
    path = versioned(tmp_path / "t.json")
    assert hr.is_done(path, "abc", "p1") is True
    assert hr.is_done(tmp_path / "none.json", "abc", "p1") is False
    assert hr.is_done(versioned(tmp_path / "u.json", score=None), "abc", "p1") is False  # no score: run it


@pytest.mark.parametrize(
    "sha, phash, named",
    [("new", "p1", "code_sha abc"), ("abc", "p2", "profile_hash p1"), ("new", "p2", "code_sha abc")],
)
def test_a_result_of_another_code_or_profile_stops_the_run_unless_the_flag_says_rerun(
    tmp_path, sha, phash, named
):
    path = versioned(tmp_path / "t.json")
    with pytest.raises(hr.HarnessError, match=named) as stop:
        hr.is_done(path, sha, phash)
    assert "--rerun-mismatch" in str(stop.value) and str(path) in str(stop.value)
    assert hr.is_done(path, sha, phash, rerun_mismatch=True) is False


def test_a_result_with_no_score_of_another_code_is_run_again_with_no_flag(tmp_path):
    assert hr.is_done(versioned(tmp_path / "t.json", score=None), "new", "p1") is False


def test_an_old_result_with_no_such_field_is_done_as_before(tmp_path):
    path = versioned(tmp_path / "t.json", code_sha=None, profile_hash=None)
    raw = json.loads(path.read_text())
    del raw["code_sha"], raw["profile_hash"]
    path.write_text(json.dumps(raw))
    assert hr.is_done(path, "new", "p2") is True


def test_a_mismatch_stops_main_with_code_2_before_any_task_starts(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(hr, "RESULTS", tmp_path)
    source = tmp_path / "snap" / "SOURCE.txt"
    (source.parent / "src").mkdir(parents=True)
    source.write_text("newsha 0\n")
    monkeypatch.setattr(hr, "snapshot_src", lambda name: source.parent / "src")
    monkeypatch.setattr(hr, "child_env", lambda *a: pytest.fail("a child would start"))
    monkeypatch.setattr(hr, "profile_hash", lambda path: "p1")

    class Adapter:
        python = Path(sys.executable)
        default_timeout = 1.0

        def __init__(self, set_id):
            pass

        def task_ids(self, set_id):
            return ["t"]

    monkeypatch.setitem(hr.ADAPTERS, "itsm", Adapter)
    (tmp_path / "x_t1").mkdir()
    versioned(tmp_path / "x_t1" / "t.json", code_sha="oldsha")
    argv = "run --bench itsm --profile baseline --set itsm-tune --snapshot s --run x".split()
    monkeypatch.setattr(sys, "argv", argv)
    assert hr.main() == 2
    assert "code_sha oldsha, and this run has newsha" in capsys.readouterr().err


def test_the_report_prints_the_versions_of_each_arm_and_marks_a_mixed_one(tmp_path):
    for run, shas in (("v_A_t1", {"t1": "abc", "t2": "abc"}), ("v_B_t1", {"t1": "abc", "t2": "def"})):
        (tmp_path / run).mkdir()
        for task, sha in shas.items():
            versioned(tmp_path / run / f"{task}.json", code_sha=sha, profile_hash="p1")
    text = rp.render(["v_A", "v_B"], roots=[tmp_path], tau2_root=tmp_path / "none")
    assert "v_A: code_sha abc; profile_hash p1.\n" in text
    assert "v_B: code_sha abc, def; profile_hash p1. **MIXED: more than one code_sha in this arm.**" in text


def test_the_report_marks_two_profiles_and_a_file_with_nothing_recorded(tmp_path):
    (tmp_path / "w_A_t1").mkdir()
    versioned(tmp_path / "w_A_t1" / "t1.json", profile_hash="p1")
    versioned(tmp_path / "w_A_t1" / "t2.json", profile_hash="p2")
    (tmp_path / "w_B_t1").mkdir()
    versioned(tmp_path / "w_B_t1" / "t1.json", code_sha=None, profile_hash=None)
    versioned(tmp_path / "w_B_t1" / "t2.json", code_sha="abc", profile_hash=None)
    text = rp.render(["w_A", "w_B"], roots=[tmp_path], tau2_root=tmp_path / "none")
    assert (
        "w_A: code_sha abc; profile_hash p1, p2. **MIXED: more than one profile_hash in this arm.**" in text
    )
    assert (
        "w_B: code_sha abc, not recorded; profile_hash not recorded. **MIXED: more than one code_sha" in text
    )


# -- the ledger -----------------------------------------------------------------------------------------------------------


def ledger(monkeypatch, tmp_path):
    path = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(costs, "LEDGER", path)
    monkeypatch.delenv("POLICY_MODEL_NAME", raising=False)
    return path


def test_usage_with_no_model_name_is_refused_and_nothing_is_written(monkeypatch, tmp_path):
    path = ledger(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="names no model"):
        costs.record("k", "n", policy={"input_tokens": 10, "output_tokens": 1})
    with pytest.raises(ValueError, match="names no model"):
        costs.record("k", "n", agent={"input_tokens": 10, "output_tokens": 1, "models": []})
    with pytest.raises(ValueError, match="names no model"):
        costs.record("k", "n", policy={"calls": 1, "cost": 0.5})
    assert not path.exists()


def test_old_callers_that_name_a_model_keep_working(monkeypatch, tmp_path):
    path = ledger(monkeypatch, tmp_path)
    c = costs.record(
        "k",
        "n",
        agent={"input_tokens": 1_000_000, "output_tokens": 0, "models": ["aws/gpt-oss-120b"]},
        policy={"input_tokens": 1_000_000, "output_tokens": 0, "model": "gcp/gemini-3.8-flash"},
    )
    assert c == pytest.approx(0.15 + 0.75)
    assert costs.record("empty", "n", agent=None, policy={}) == 0.0  # no usage: nothing to price
    monkeypatch.setenv(
        "POLICY_MODEL_NAME", "aws/gpt-oss-120b"
    )  # what the old launchers exported; an offline replay may
    assert costs.record("k", "n", policy={"input_tokens": 1_000_000}) == pytest.approx(0.15)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 3 and "component" not in rows[0]


def test_usage_is_recorded_per_component(monkeypatch, tmp_path):
    path = ledger(monkeypatch, tmp_path)
    result = Result(
        benchmark="tau2-telecom",
        task="t",
        run="r_t1",
        usage_by_component={
            "agent": {"model": "aws/gpt-oss-120b", "input_tokens": 1_000_000, "output_tokens": 0},
            "user_simulator": {
                "model": "openai/Azure/gpt-4.1",
                "input_tokens": 1_000_000,
                "output_tokens": 0,
            },
            "navigator": {"model": "jaredpalmer/kev-4b", "calls": 2, "errors": 0, "cost": 0.5},
        },
    )
    assert hr.record_costs(result, "harness_tau2") == pytest.approx(0.15 + 2.0 + 0.5)
    rows = {r["component"]: r for r in map(json.loads, path.read_text().splitlines())}
    assert set(rows) == {"agent", "user_simulator", "navigator"}
    assert rows["navigator"]["model"] == "jaredpalmer/kev-4b" and rows["navigator"]["cost_usd"] == 0.5
    assert rows["agent"]["agent_in"] == 1_000_000 and rows["user_simulator"]["policy_in"] == 1_000_000


# -- what a run stands on -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bench, profile, set_id",
    [
        ("automationbench", "baseline", "ab-tune"),
        ("itsm", "baseline", "itsm-tune"),
        ("handbook", "baseline", "handbook-public3"),
        ("tau2", "baseline", "tau2-telecom-test"),
    ],
)
def test_a_missing_snapshot_is_refused_for_every_benchmark(bench, profile, set_id):
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            str(POLICY_EVAL / "harness" / "run.py"),
            "--bench",
            bench,
            "--profile",
            profile,
            "--set",
            set_id,
            "--snapshot",
            "no-such-snapshot",
            "--run",
            "never",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 2 and "no snapshot" in done.stderr
    assert not (POLICY_EVAL / "harness" / "results" / "never_t1").exists()


def test_the_snapshot_is_required_on_the_command_line():
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            str(POLICY_EVAL / "harness" / "run.py"),
            "--bench",
            "itsm",
            "--profile",
            "baseline",
            "--set",
            "itsm-tune",
            "--run",
            "never",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode != 0 and "--snapshot" in done.stderr


def test_two_packages_of_one_policy_have_two_package_versions():
    root = POLICY_EVAL / "packages/itsm/e2891a7b98"
    versions = {}
    for build in ("builds", "builds_v4"):
        path = root / build / "package.json"
        pkg = type("P", (), {"version": json.loads(path.read_text())["version"]})()
        versions[build] = hr.package_version(path, pkg)
    assert versions["builds"].split("+")[0] == versions["builds_v4"].split("+")[0]  # the policy text
    assert versions["builds"] != versions["builds_v4"]


def test_code_sha_comes_from_the_snapshot(tmp_path):
    src = tmp_path / "s" / "src"
    src.mkdir(parents=True)
    assert hr.snapshot_src("s", root=tmp_path) == src
    with pytest.raises(hr.HarnessError, match="SOURCE.txt"):
        hr.code_sha(src)
    (tmp_path / "s" / "SOURCE.txt").write_text("abc123\n0\n")
    assert hr.code_sha(src) == "abc123"
    (tmp_path / "s" / "SOURCE.txt").write_text("abc123\n4\n")
    assert hr.code_sha(src) == "abc123+4"


USE_SNAPSHOT = r"""
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from policy_eval.harness.run import HarnessError, use_snapshot
try:
    use_snapshot(Path(sys.argv[2]))
except HarnessError as exc:
    print("REFUSED", exc)
else:
    import importlib.util
    print("OK", importlib.util.find_spec("cuga").origin)
"""


@pytest.mark.parametrize(
    "python", [GATE_PYTHON, AB_PYTHON, TAU2_PYTHON], ids=["gate", "automationbench", "tau2"]
)
def test_every_venv_imports_cuga_from_the_snapshot_or_refuses(python, tmp_path):
    if not Path(python).exists():
        missing_input(f"no venv at {python}")

    def check(src):
        done = subprocess.run(
            [str(python), "-I", "-c", USE_SNAPSHOT, str(BENCHMARKS), str(src)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert done.returncode == 0, done.stderr[-2000:]
        return done.stdout

    assert check(GATE_SRC).startswith(
        f"OK {GATE_SRC}"
    )  # a copy of the code that is not where the venv points
    empty = tmp_path / "src"
    empty.mkdir()
    out = check(empty)
    if Path(python) == Path(GATE_PYTHON):
        assert out.startswith("REFUSED") and "not from the snapshot" in out
    else:
        assert (
            out.startswith("REFUSED") and "dev/cuga-agent/" in out
        )  # the τ² venv's cuga is the one to refuse


def test_the_harness_reads_profile_files_only():
    harness = POLICY_EVAL / "harness"
    for path in harness.rglob("*.py"):
        if "results" in path.parts:
            continue
        text = path.read_text()
        assert "config_from_env" not in text, path
        assert not re.search(r'environ.*"(POLICY|SOP|HOOKS|HB)_', text), path


def imported_modules(path):
    """The last part of every name that the file imports, at any depth, and each name on a ``from`` line."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names |= {alias.name.rsplit(".", 1)[-1] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            names |= {alias.name for alias in node.names}
            if node.module:
                names.add(node.module.rsplit(".", 1)[-1])
    return names


def archived_modules():
    return {p.stem for p in ARCHIVE.glob("*.py")}


def test_no_adapter_imports_an_archived_path():
    archived = archived_modules()
    assert {"run_cuga", "run_cuga_eog", "run_cuga_handbook", "guide_hooks", "run_arm_a"} <= archived
    harness = POLICY_EVAL / "harness"
    files = [p for p in harness.rglob("*.py") if "results" not in p.parts]
    assert len(files) >= 8
    for path in files:
        assert not imported_modules(path) & archived, path
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):  # an import by name or by path
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        assert arg.value.rsplit("/", 1)[-1].removesuffix(".py") not in archived, path
    # the benchmark logic is in modules that stay
    for name, module in (("automationbench", "ab_env"), ("handbook", "hb_env"), ("itsm", "eog_env")):
        assert module in imported_modules(harness / "adapters" / f"{name}.py")
    for module in ("automationbench/ab_env.py", "handbook/hb_env.py", "enterpriseops_gym/eog_env.py"):
        assert (BENCHMARKS / module).is_file()


def test_no_live_script_needs_an_archived_path():
    """Saved results and the archive itself aside, a script that stays must not start or import what left. τ²'s runner stays in
    its worktree, and its launchers are archived, so nothing here starts it."""
    archived = archived_modules()
    scripts = {p.name for p in ARCHIVE.glob("*.sh")} | {f"{m}.py" for m in archived}
    skip = {"results", "logging", ".venv", "vendor", "AutomationBench", "archive", "__pycache__"}
    roots = [BENCHMARKS / n for n in ("automationbench", "enterpriseops_gym", "handbook", "policy_eval")]
    seen = 0
    for root in roots:
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in skip]
            for name in files:
                path = Path(folder) / name
                if name.endswith(".py"):
                    seen += 1
                    assert not imported_modules(path) & archived, path
                elif name.endswith(".sh"):
                    seen += 1
                    assert not [s for s in scripts if s in path.read_text()], path
    assert seen > 30


def test_the_old_env_files_left():
    for bench in ("automationbench", "enterpriseops_gym", "handbook"):
        assert not list((BENCHMARKS / bench).glob("cuga*.env")), bench
        assert list((ARCHIVE / "envs" / bench).glob("cuga*.env")), bench


def test_a_policy_switch_does_not_reach_the_child(monkeypatch):
    import dotenv

    monkeypatch.setattr(
        dotenv, "dotenv_values", lambda path: {"OPENROUTER_API_KEY": "fake", "OPENAI_API_KEY": "fake"}
    )
    for name in ("POLICY_MODEL_NAME", "SOP_LOOP", "HOOKS_MODULE", "HB_BUILDS", "LANGFUSE_HOST"):
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv("POLICY_PILOT_BUDGET", "2000")
    for name in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    args = type("A", (), {"proxy": None, "model": "gptoss"})()
    env = hr.child_env(hr.ADAPTERS["automationbench"](), args, Path("/snap/src"))
    assert not {"POLICY_MODEL_NAME", "SOP_LOOP", "HOOKS_MODULE", "HB_BUILDS", "LANGFUSE_HOST"} & set(env)
    assert env["POLICY_PILOT_BUDGET"] == "2000"
    assert env["OPENROUTER_API_KEY"] == "fake"
    assert env["PYTHONPATH"] == "/snap/src" == env["CUGA_SRC"]
    assert env["MODEL_NAME"] == "aws/gpt-oss-120b"
    assert env["DYNACONF_ADVANCED_FEATURES__CUGA_LITE_FC_DYNAMIC_TOOLS"] == "apps"
    assert Path(env["ENV_FILE"]).read_text().count("MODEL_NAME=aws/gpt-oss-120b") == 1


def test_the_tau2_layer_gives_the_settings_the_tau2_runner_used():
    """What the old ``run_arm_a.py`` set over tau2-bench's config, against the composed file. The one difference is stated."""
    config = Path.home() / "dev/cuga-eval-tau2/benchmarks/tau2/config/tau2.env"
    if not config.exists():
        missing_input("the τ² worktree is missing")
    tree = ast.parse((ARCHIVE / "run_arm_a.py").read_text())
    fc = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "FC"
    )
    old = {
        **parse_runner(config.read_text()),
        **fc,
        "MODEL_NAME": "aws/gpt-oss-120b",
        "AGENT_SETTING_CONFIG": "settings.openai.gptoss-default.toml",
    }
    new, _ = merge("gptoss", "tau2", TAU2_AGENT)
    ignored = {"LOGURU_LEVEL", "CUGA_LOGGING_DIR"}  # not settings of the agent; each child has its own folder
    stricter = {
        "DYNACONF_ADVANCED_FEATURES__RELAXED_EXECUTION"
    }  # false: the sandbox stays on; no code runs in this mode
    assert {k: v for k, v in old.items() if k not in ignored} == {
        k: v for k, v in new.items() if k not in ignored | stricter
    }


# -- adapters --------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(hr.ADAPTERS))
def test_adapters_match_the_protocol(name):
    adapter = hr.ADAPTERS[name]()
    assert isinstance(adapter, BenchmarkAdapter)
    assert str(adapter.python).endswith("bin/python") and adapter.grace > 0
    merge("gptoss", adapter.env_bench, adapter.env_extra)  # its layers exist


@pytest.mark.parametrize(
    "name, set_id, n",
    [
        ("automationbench", "ab-policy-types-holdout", 35),
        ("itsm", "itsm-unseen", 10),
        ("handbook", "handbook-public3", 3),
        ("tau2", "tau2-telecom-test", 40),
    ],
)
def test_task_ids_come_from_the_registry(name, set_id, n):
    assert len(hr.ADAPTERS[name](set_id=set_id).task_ids(set_id)) == n


def test_a_set_of_another_benchmark_is_refused():
    with pytest.raises(ValueError, match="is for itsm"):
        hr.ADAPTERS["automationbench"]().task_ids("itsm-tune")
    with pytest.raises(ValueError, match="is for itsm"):
        hr.ADAPTERS["tau2"](set_id="itsm-tune")


def test_tau2_results_name_the_domain():
    assert hr.ADAPTERS["tau2"](set_id="tau2-airline-test").benchmark == "tau2-airline"


def test_handbook_with_no_sop_file_raises(tmp_path):
    workspace = tmp_path / "task_x" / "environment/initial_workspace"
    workspace.mkdir(parents=True)
    (workspace / "notes.txt").write_text("not it")
    with pytest.raises(ValueError, match="task_x has no file named as an SOP"):
        sop_text_of(tmp_path / "task_x")
    (workspace / "SOP_small.txt").write_text("small")
    (workspace / "main_sop.html").write_text(
        "<html><h2>Steps</h2><p>Check <b>it</b></p><script>x()</script></html>"
    )
    assert sop_text_of(tmp_path / "task_x") == "\n## Steps\nCheck it"


def test_the_shared_parser_is_the_only_one():
    for path in (BENCHMARKS / "handbook/hb_env.py", POLICY_EVAL / "tools/golden_hooks.py"):
        assert "HTMLParser" not in path.read_text(), path


def test_with_no_note_the_prompt_is_the_same_bytes():
    prompt = "Role text.\n\nRules  with  spaces\n"
    assert with_note(prompt, "") == prompt
    assert with_note(prompt, "Note.") == prompt + "\n\nNote."


def test_a_task_name_is_a_safe_and_stable_file_name():
    long = "[mms_issue]" + "|".join(["airplane_mode_on"] * 30) + "[PERSONA:Hard]"
    assert hr.safe_name("finance.bank_fee_analysis") == "finance.bank_fee_analysis"
    name = hr.safe_name(long)
    assert len(name) < 200 and re.fullmatch(r"[A-Za-z0-9._-]+", name) and name == hr.safe_name(long)
    assert name != hr.safe_name(long + "x")


# -- the child, in the gate repo's Python -----------------------------------------------------------------------------------


COMMON = r"""
import argparse, asyncio, json, sys, types
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from policy_eval.harness import run as H
from policy_eval.harness.adapters import base
from policy_eval.harness.result import Score
from cuga.policy_layer.runtime import RunContext, RuntimeParts, RuntimeWiringError

class Fake:
    benchmark = "itsm"
    def __init__(self, ctx=None, raw=None, raises=None):
        self.calls, self.ctx, self.raw, self.raises = [], ctx, raw, raises
    async def prepare(self, task_id):
        self.calls.append("prepare")
        return self.ctx or RunContext(task_id=task_id, system_prompt="p")
    async def run(self, parts, ctx, timeout):
        self.calls.append("run")
        if self.raises:
            raise self.raises
        return self.raw or base.RawOutcome()
    async def grade(self):
        self.calls.append("grade")
        return Score(0.0, 0.0, False)
    def close(self):
        self.calls.append("close")

def go(adapter, profile="baseline", task="t"):
    args = argparse.Namespace(child=task, profile=profile, trial=1, run="r", timeout=1.0)
    return asyncio.run(H.run_task(args, adapter, Path(sys.argv[2]), "abc"))
"""


def gate(code, tmp_path, *args):
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", COMMON + code, str(BENCHMARKS), str(tmp_path), *args],
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "OPENROUTER_API_KEY": "dry-run"},
    )
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-3000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_a_policy_version_with_no_package_is_no_score_and_no_run(tmp_path):
    tasks = json.loads((BENCHMARKS / "enterpriseops_gym/tasks/itsm_oracle.json").read_text())
    task = next(t for t in tasks if t["_policy_hash"] == "80cd3ebb50")["task_id"]
    out = gate(
        r"""
a = Fake(RunContext(task_id=sys.argv[3], system_prompt="p", tool_specs=[{"name": "x"}], policy_version="80cd3ebb50"))
r = go(a, "itsm-rules", sys.argv[3])
print(json.dumps({"calls": a.calls, "error": r.error, "score": r.score is None, "sha": r.code_sha, "hash": r.profile_hash}))
""",
        tmp_path,
        task,
    )
    assert out["calls"] == ["prepare", "close"]  # never run, never graded
    assert out["error"].startswith("wiring:") and "80cd3ebb50" in out["error"] and task in out["error"]
    assert out["score"] is True and out["sha"] == "abc" and len(out["hash"]) == 12


def test_a_wiring_error_is_not_graded(tmp_path):
    out = gate(
        r"""
rows = {}
a = Fake(raises=RuntimeWiringError("task t, component x: cannot"))
r = go(a)
rows["in run"] = [a.calls, r.error, r.score is None]
a = Fake(RunContext(task_id="t", system_prompt="p", policy_version="v"))  # the guide on no package
r = go(a, "handbook-gptoss-loop-guide-evidence")
rows["in build"] = [a.calls, r.error, r.score is None]
a = Fake(RunContext(task_id="t", system_prompt="p", policy_version="airline"))
r = go(a, "tau2-telecom-gptoss-navigator")
rows["other policy"] = [a.calls, r.error, r.score is None]
print(json.dumps(rows))
""",
        tmp_path,
    )
    assert out["in run"][0] == ["prepare", "run", "close"]
    assert out["in run"][1].startswith("wiring:") and out["in run"][2] is True
    assert out["in build"][0] == ["prepare", "close"]
    assert out["in build"][1].startswith("wiring:") and out["in build"][2] is True
    assert out["other policy"][0] == ["prepare", "close"]
    assert "for another policy" in out["other policy"][1] and out["other policy"][2] is True


def test_the_agent_model_reaches_the_level_switch_and_a_table_with_no_model_is_refused(tmp_path):
    out = gate(
        r"""
import os
import cuga.policy_layer.runtime as runtime
profile = Path(sys.argv[2]) / "levels.yaml"
profile.write_text("policy: {control: {by_model: {m/a: 2}}}\n")  # a profile with a level table, nothing else on
H.profile_path = lambda name: profile
seen = []
runtime.build_runtime = lambda cfg, pkg, ctx, **kw: seen.append(ctx.agent_model) or RuntimeParts()
rows = {}
for model in ("m/a", "m/unknown", ""):
    os.environ["MODEL_NAME"] = model
    a = Fake()
    r = go(a, "levels")
    rows[model or "none"] = [a.calls, r.error]
rows["seen"] = seen
print(json.dumps(rows))
""",
        tmp_path,
    )
    assert out["seen"] == [
        "m/a",
        "m/unknown",
    ]  # a model that is not in the table is not refused: the audit says so
    assert out["m/a"][0] == ["prepare", "run", "grade", "close"]
    assert out["none"][0] == ["prepare", "close"]  # never run, never graded
    assert out["none"][1].startswith("wiring:") and "MODEL_NAME" in out["none"][1]


def test_an_agent_error_is_graded_and_a_gateway_error_is_not(tmp_path):
    out = gate(
        r"""
rows = {}
a = Fake(raw=base.RawOutcome(error="timeout after 1s"))
r = go(a)
rows["agent"] = [a.calls, r.error, r.score.primary]
a = Fake(raw=base.RawOutcome(error="APIConnectionError: Connection error."))
r = go(a)
rows["gateway"] = [a.calls, r.error, r.score is None]
class NoGrade(Fake):
    async def grade(self):
        raise RuntimeError("the grader broke")
a = NoGrade()
r = go(a)
rows["grader"] = [r.error, r.score is None]
class NoPrepare(Fake):
    async def prepare(self, task_id):
        raise ValueError("task x has no file named as an SOP")
a = NoPrepare()
r = go(a)
rows["prepare"] = [a.calls, r.error, r.score is None]
print(json.dumps(rows))
""",
        tmp_path,
    )
    assert out["agent"] == [["prepare", "run", "grade", "close"], "timeout after 1s", 0.0]
    assert out["gateway"][0] == ["prepare", "run", "close"] and out["gateway"][1].startswith("gateway:")
    assert out["gateway"][2] is True
    assert out["grader"][0].startswith("grader:") and out["grader"][1] is True
    assert out["prepare"][0] == ["close"] and "no file named as an SOP" in out["prepare"][1]
    assert out["prepare"][2] is True


def test_usage_rows_name_the_model_of_each_component(tmp_path):
    out = gate(
        r"""
raw = base.RawOutcome(
    receipts=[{"models": ["aws/gpt-oss-120b"], "input_tokens": 10, "output_tokens": 1},
              {"models": ["aws/gpt-oss-120b"], "input_tokens": 5, "output_tokens": 1}],
    usage={"user_simulator": {"model": "openai/Azure/gpt-4.1", "input_tokens": 3, "output_tokens": 1}},
)
r = go(Fake(raw=raw))
print(json.dumps([r.usage_by_component, r.cost_usd, r.agent_model]))
""",
        tmp_path,
    )
    rows, cost, _ = out
    assert rows["agent"] == {"model": "aws/gpt-oss-120b", "calls": 2, "input_tokens": 15, "output_tokens": 2}
    assert set(rows) == {"agent", "user_simulator"} and cost > 0


def test_a_result_holds_the_hash_of_the_composed_env_file(tmp_path):
    out = gate(
        r"""
import os
env = Path(sys.argv[2]) / "cuga.env"
env.write_text("MODEL_NAME=one\n")
os.environ["ENV_FILE"] = str(env)
first = go(Fake()).env_hash
env.write_text("MODEL_NAME=two\n")
second = go(Fake()).env_hash
del os.environ["ENV_FILE"]
print(json.dumps([first, second, go(Fake()).env_hash]))
""",
        tmp_path,
    )
    assert len(out[0]) == 12 and out[0] != out[1] and out[2] is None


TURN_ERRORS = r"""
def answer(text, error=None):
    return types.SimpleNamespace(answer=text, error=error, receipt=None)

class Agent:
    def __init__(self, script):
        self.script, self.prompts = list(script), []
    async def invoke(self, prompt, thread_id=None):
        self.prompts.append(prompt)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

def drive(agent, parts):
    return asyncio.run(base.drive_one_request(agent, parts, "Do it.", "t", 5.0, [], [], []))

rows = {}
checked = []
def after_reply(answer_text, turns, live):
    checked.append(answer_text)
    return "again"
# the first turn fails: the text of the error is not checked and no later turn clears the error
agent = Agent([answer("Error: Error code: 503", "Error code: 503"), answer("fine")])
out = drive(agent, RuntimeParts(after_reply=after_reply))
rows["reply"] = [out.error, agent.prompts, checked]
# the loop goes on after a turn fails, and the answer of its last turn is fine
async def loop_run(agent, request, thread, timeout):
    await agent.invoke("explore", thread_id=thread)
    await agent.invoke("case 1", thread_id=thread)
    return await agent.invoke("finish", thread_id=thread)
agent = Agent([answer("ok"), answer("Error: 429", "Error code: 429"), answer("done")])
out = drive(agent, RuntimeParts(run=loop_run))
rows["loop"] = [out.error, out.answer, len(agent.prompts)]
# and when the loop then stops on a timeout, the first error is the one that counts
agent = Agent([answer("Error: 429", "Error code: 429"), asyncio.TimeoutError()])
out = drive(agent, RuntimeParts(run=loop_run))
rows["loop timeout"] = out.error
agent = Agent([RuntimeWiringError("task t, component x: cannot")])
try:
    drive(agent, RuntimeParts())
    rows["wiring"] = "no error"
except RuntimeWiringError as exc:
    rows["wiring"] = str(exc)
agent = Agent([ValueError("bad state")])
rows["other"] = drive(agent, RuntimeParts()).error
print(json.dumps(rows))
"""


def test_an_error_of_any_turn_stays_and_ends_the_turns(tmp_path):
    out = gate(TURN_ERRORS, tmp_path)
    assert out["reply"] == ["Error code: 503", ["Do it."], []]
    assert out["loop"] == ["Error code: 429", "done", 3]
    assert out["loop timeout"] == "Error code: 429"
    assert out["wiring"] == "task t, component x: cannot"
    assert out["other"] == "ValueError: bad state"


def test_a_method_choice_file_is_found_from_the_folder_of_a_child(tmp_path):
    """A child runs in its own folder. The verifier by model of a method choice is built from the file it names."""
    profile = hr.PROFILES / "itsm-rules.yaml"
    out = gate(
        r"""
import os, yaml
from cuga.policy_layer.policy_config import load_config, PolicyConfig
from cuga.policy_layer import runtime
data = yaml.safe_load(open(sys.argv[3]))
data["policy"]["checkers"]["method_choice"] = "policy_eval/method_choice.json"
data["policy"]["package"] = "packages/itsm/{policy}/builds/package.json"
H.PROFILES = Path(sys.argv[2])
(H.PROFILES / "choice.yaml").write_text(yaml.safe_dump(data))
os.chdir(sys.argv[2])
seen = {}
real = runtime.build_runtime
def spy(cfg, pkg, ctx):
    parts = real(cfg, pkg, ctx, models=__import__("cuga.policy_layer.dry_run", fromlist=["x"]).RecordingModels())
    seen["choice"] = parts.hooks[0].method_choice is not None
    seen["verifier_for"] = parts.hooks[0].verifier_for is not None
    return parts
runtime.build_runtime = spy
a = Fake(RunContext(task_id="t", system_prompt="p", policy_version="e2891a7b98",
                    tool_specs=json.load(open(sys.argv[4]))))
r = go(a, "choice")
print(json.dumps([seen, r.error, r.score is not None, r.package_version, r.policy]))
""",
        tmp_path,
        str(profile),
        str(BENCHMARKS / "enterpriseops_gym/tasks/itsm_tools.json"),
    )
    assert out[:3] == [{"choice": True, "verifier_for": True}, None, True]
    assert re.fullmatch(r"3f8382b04c91277c\+[0-9a-f]{12}", out[3])
    assert (
        out[4] == "e2891a7b98"
    )  # the result names the policy of the task, so an audit need not guess it from the package


def test_the_audit_is_in_the_task_folder_and_names_the_package_version_of_the_result(tmp_path):
    out = gate(
        r"""
from cuga.policy_layer import runtime
from cuga.policy_layer.dry_run import RecordingModels

class Quiet(RecordingModels):
    def json_model(self, *args, **kwargs):
        recorded = super().json_model(*args, **kwargs)
        def call(system, user):
            recorded.usage["calls"] += 1
            return '{"violations": []}'
        call.usage, call.model_name = recorded.usage, recorded.model_name
        return call

real = runtime.build_runtime
runtime.build_runtime = lambda cfg, pkg, ctx: real(cfg, pkg, ctx, models=Quiet())

class Decides(Fake):
    async def run(self, parts, ctx, timeout):
        self.calls.append("run")
        bad = {"impact": "low", "urgency": "low", "priority": "critical", "title": "x"}
        parts.hooks[0].before_tool_call("create_problem", bad)
        return base.RawOutcome()

a = Decides(RunContext(task_id="t", system_prompt="p", policy_version="e2891a7b98",
                       tool_specs=json.load(open(sys.argv[3]))))
r = go(a, "itsm-rules")
lines = [json.loads(x) for x in (Path(sys.argv[2]) / "work" / "t" / "audit.jsonl").read_text().splitlines()]
traj = json.load(open(r.trajectory))
print(json.dumps([r.package_version, sorted({x["package_version"] for x in lines}),
                  [x["rule_id"] for x in lines if x["verdict"] == "deny"],
                  traj["audit_lines"] == len(lines), traj["audit_file"]]))
""",
        tmp_path,
        str(BENCHMARKS / "enterpriseops_gym/tasks/itsm_tools.json"),
    )
    version = out[0]
    assert re.fullmatch(r"3f8382b04c91277c\+[0-9a-f]{12}", version)
    # one version, the result's own; the file is named relative to the run folder, with no absolute path
    assert out[1:] == [[version], ["r_87aab8e4"], True, "work/t/audit.jsonl"]


def test_a_baseline_task_leaves_no_audit_in_its_folder(tmp_path):
    out = gate(
        r"""
a = Fake()
r = go(a, "baseline")
print(json.dumps([a.calls, r.error, (Path(sys.argv[2]) / "work").exists(), "audit_file" in json.load(open(r.trajectory))]))
""",
        tmp_path,
    )
    assert out == [["prepare", "run", "grade", "close"], None, False, False]


def test_what_components_know_goes_with_the_trajectory(tmp_path):
    out = gate(
        r"""
from cuga.policy_layer.dry_run import RecordingModels
from cuga.policy_layer.policy_config import load_config
from cuga.policy_layer.runtime import build_runtime

cfg = load_config(H.PROFILES / "automationbench-gptoss-b4tf.yaml")
ctx = RunContext(task_id="t", policy_version="v", tool_specs=[{"name": "x"}], data_search=[("x", print)])
parts = build_runtime(cfg, None, ctx, models=RecordingModels())
facts = H.component_facts(parts)
others = RuntimeParts(components={"navigator": types.SimpleNamespace(blocks=2),
                                  "procedure_tools": types.SimpleNamespace(calls=[{"tool": "get_procedure"}])})
print(json.dumps([sorted(facts), H.component_facts(others), H.component_facts(RuntimeParts())]))
""",
        tmp_path,
    )
    assert out[0] == [
        "audit_file",
        "audit_lines",
        "overlay",
        "policy_trace_summary",
    ]  # no out_dir here: no file
    assert out[1] == {"navigator_blocks": 2, "procedure_store_calls": [{"tool": "get_procedure"}]}
    assert out[2] == {}


AGENT_STAND_IN = r"""
seen = {}
class Agent:
    def __init__(self, **kwargs):
        seen.update(kwargs)
    async def invoke(self, prompt, **kwargs):
        seen.setdefault("prompts", []).append(prompt)
        return types.SimpleNamespace(answer="done", error=None, receipt=None, tool_calls=[])
class Provider:
    def __init__(self, tools, app_of, app_descriptions=None):
        self.tools = tools
sys.modules["cuga.sdk"] = types.SimpleNamespace(CugaAgent=Agent)
sys.modules["helpers"] = types.ModuleType("helpers"); sys.modules["helpers"].__path__ = []
sys.modules["helpers.app_tools_provider"] = types.SimpleNamespace(AppToolsProvider=Provider)
from policy_eval.harness.adapters.automationbench import AutomationBenchAdapter
from policy_eval.harness.adapters.handbook import HandbookAdapter
from policy_eval.harness.adapters.itsm import ItsmAdapter
from cuga.policy_layer.policy_config import load_config
from cuga.policy_layer.runtime import build_runtime

PROMPT = "You are the role.\n\n  Keep   these  spaces.\n"
def adapter(name):
    a = {"ab": AutomationBenchAdapter, "itsm": ItsmAdapter, "hb": HandbookAdapter}[name](run_dir=Path(sys.argv[2]), run="r")
    a.task_id, a.tools, a.app_by_tool = "task", [], {}
    a.env = types.SimpleNamespace(langchain_tools=lambda: [], app_name=lambda: "itsm")
    return a
def run(name, parts):
    seen.clear()
    ctx = RunContext(task_id="task", request="Do it.", system_prompt=PROMPT)
    out = asyncio.run(adapter(name).run(parts, ctx, 5.0))
    return {"instructions": seen["special_instructions"], "hooks": "hooks" in seen, "prompts": seen["prompts"], "error": out.error}
"""


def test_a_baseline_prompt_is_unchanged_byte_for_byte_in_each_adapter(tmp_path):
    out = gate(
        AGENT_STAND_IN
        + r"""
baseline = build_runtime(load_config(H.PROFILES / "baseline.yaml"), None, RunContext(task_id="t"))
rows = {name: run(name, baseline) for name in ("ab", "itsm", "hb")}
print(json.dumps({"prompt": PROMPT, "rows": rows}))
""",
        tmp_path,
    )
    for row in out["rows"].values():
        assert row["instructions"].encode() == out["prompt"].encode()
        assert row["hooks"] is False and row["prompts"] == ["Do it."] and row["error"] is None


def test_a_note_is_added_when_there_is_one(tmp_path):
    out = gate(
        AGENT_STAND_IN
        + r"""
parts = RuntimeParts(system_note="The note.", hooks=[object()])
print(json.dumps({name: run(name, parts) for name in ("ab", "itsm", "hb")}))
""",
        tmp_path,
    )
    for row in out.values():
        assert row["instructions"].endswith("Keep   these  spaces.\n\n\nThe note.") and row["hooks"] is True


def test_one_request_uses_the_note_and_after_reply_slots(tmp_path):
    out = gate(
        AGENT_STAND_IN
        + r"""
replies = ["[Policy note]\nnot yet", None]
seen_by_slot = []
def after_reply(answer, turns, live):
    seen_by_slot.append(turns[0]["text"])
    return replies.pop(0)
parts = RuntimeParts(turn_note=lambda turns: "PROGRESS", after_reply=after_reply)
row = run("itsm", parts)
wrong = RuntimeParts(run=lambda *a: None, after_reply=after_reply)
try:
    asyncio.run(adapter("itsm").run(wrong, RunContext(task_id="task", request="x", system_prompt="p"), 1.0))
    raised = False
except RuntimeWiringError:
    raised = True
print(json.dumps({"prompts": row["prompts"], "seen": seen_by_slot, "raised": raised}))
""",
        tmp_path,
    )
    assert out["prompts"] == ["Do it.\n\nPROGRESS", "[Policy note]\nnot yet"]
    assert out["seen"] == ["Do it.", "Do it."]
    assert out["raised"] is True


TAU2_CONVERSATION = r"""
from policy_eval.harness.adapters.tau2 import Tau2Adapter

class Bridge:
    tau2_tools = []
    def __init__(self):
        self.sent, self.replies, self.closed = [], ["The light is on.", None], False
    def bind_loop(self, loop):
        pass
    def first_observation(self):
        return "My phone is broken."
    async def register_message(self, text):
        self.sent.append(text)
        return self.replies.pop(0)
    def close(self):
        self.closed = True

prompts = []
built = {}
class Agent:
    def __init__(self, **kwargs):
        built.update(kwargs)
    async def invoke(self, prompt, **kwargs):
        prompts.append(prompt)
        built["kwargs"] = kwargs
        answer = {
            0: "Is the light on?",
            1: "I have transferred to a human agent.",
            2: "Please restart it. Fixed?",
        }[len(prompts) - 1]
        return types.SimpleNamespace(
            answer=answer, error=None, receipt=None,
            tool_calls=[{"name": "get_line", "arguments": {"n": len(prompts)}, "result": "ok"}],
        )

def wrapped(tools, turns, live):
    built["lists"] = (turns, live)
    return tools + ["guarded"]
notes, checks = [], []
def turn_note(turns):
    notes.append([t["role"] for t in turns])
    return "SOP progress"
def after_reply(answer, turns, live):
    checks.append(answer)
    if "human" in answer:
        return "[Policy note — your hand-off message was not sent]\nDo the steps."
    return None

adapter = Tau2Adapter(run=None)
adapter.bridge = Bridge()
adapter.domain, adapter.task_id = "telecom", "t1"
ctx = RunContext(task_id="t1", system_prompt="The policy.\n", message_tool="send_message_to_user")
out = base.RawOutcome()
parts = RuntimeParts(turn_note=turn_note, wrap_tools=wrapped, after_reply=after_reply)
asyncio.run(adapter._conversation(Agent, lambda tools, bridge: ["decoy"], parts, ctx, out))
print(json.dumps({
    "prompts": prompts, "sent": adapter.bridge.sent, "notes": notes, "checks": checks, "closed": adapter.bridge.closed,
    "tools": built["tools"], "instructions": built["special_instructions"], "hooks": "hooks" in built,
    "kwargs": built["kwargs"], "turns": [t["role"] for t in built["lists"][0]], "log": len(out.tool_calls or adapter.log),
}))
"""


def test_the_tau2_conversation_uses_each_slot(tmp_path):
    out = gate(TAU2_CONVERSATION, tmp_path)
    # the blocked reply does not reach the customer, and the agent gets the note with no tracker note on it
    assert out["prompts"] == [
        "My phone is broken.\n\nSOP progress",
        "The light is on.\n\nSOP progress",
        "[Policy note — your hand-off message was not sent]\nDo the steps.",
    ]
    assert out["sent"] == ["Is the light on?", "Please restart it. Fixed?"]
    assert out["checks"] == [
        "Is the light on?",
        "I have transferred to a human agent.",
        "Please restart it. Fixed?",
    ]
    assert out["closed"] is True
    assert out["tools"] == ["decoy", "guarded"]
    assert out["instructions"] == "The policy.\n" and out["hooks"] is False  # baseline text: unchanged
    assert out["kwargs"]["track_tool_calls"] is True and out["kwargs"]["thread_id"] == "tau2-telecom-t1"
    assert out["turns"][:3] == ["customer", "tool", "agent"] and "note" in out["turns"]


TAU2_REAL_RUN = r"""
# The real Tau2Adapter, bridge, decoys, tasks and tools of tau2-bench, and the real run_task. Stand-ins: the agent and
# tau2's run_single_task. A socket that tries to connect raises, so nothing here can reach a model.
import argparse, asyncio, json, socket, sys, types
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from policy_eval.harness import run as H

H.use_snapshot(Path(sys.argv[3]))


def no_network(*_, **__):
    raise ConnectionRefusedError("a network connection was attempted")  # as a closed network looks to a library


socket.socket.connect = no_network


class OpenAIRateLimitError(Exception):
    pass


CANCEL, NODE_CANCEL = object(), object()
class NodeCancelledError(Exception):
    pass


def answer(text, error=None):
    return types.SimpleNamespace(answer=text, error=error, receipt=None, tool_calls=[])


FIRST = answer("Is it fixed?")
SCENARIOS = {
    "clean": [FIRST, answer("Good, done.")],
    "invoke raises 429": [FIRST, OpenAIRateLimitError("Error code: 429 - slow down")],
    "invoke raises a timeout": [FIRST, RuntimeError("APITimeoutError: Request timed out.")],
    "error answer": [FIRST, answer("Error: Error code: 503 - upstream", "Error code: 503 - upstream")],
    "agent bug": [FIRST, ValueError("bad state")],
    "agent error answer": [FIRST, answer("Error: no plan", "no plan")],
    "tau2 ends in a tool call": [FIRST, CANCEL],
    "tau2 ends in a tool call, langgraph": [FIRST, NODE_CANCEL],
    "wiring": [FIRST, None],
}
state = {}


class Agent:
    def __init__(self, tools=None, special_instructions=None, **kwargs):
        self.tool = next(t for t in tools if t.name != "send_message_to_user")

    async def invoke(self, prompt, thread_id=None, track_tool_calls=False):
        script = state["script"]
        item = script.pop(0) if script else answer("")
        if item is CANCEL:
            await self.tool.coroutine()
        if item is NODE_CANCEL:
            try:
                await self.tool.coroutine()
            except asyncio.CancelledError:
                raise NodeCancelledError("cancelled") from None
        if item is None:
            from cuga.policy_layer.runtime import RuntimeWiringError

            raise RuntimeWiringError("task t, component x: cannot")
        if isinstance(item, BaseException):
            raise item
        return item


sys.modules["cuga.sdk"] = types.SimpleNamespace(CugaAgent=Agent)


def run_single_task(config, task):
    from benchmarks.tau2.tau2_bridge import ToolAction
    from benchmarks.tau2.tau2_proxy import get_current_bridge

    bridge = get_current_bridge()
    bridge.deliver_observation("My phone is broken.")
    while True:
        action = bridge.wait_for_action()
        if action is None:
            break
        if isinstance(action, ToolAction):  # the step limit, in the middle of a tool call
            bridge.close()
            break
        state["sent"].append(action.text)
        bridge.complete_pending("I tried it.")
    return types.SimpleNamespace(
        reward_info=types.SimpleNamespace(reward=0.0),
        termination_reason=types.SimpleNamespace(value="agent_stop"),
        messages=[],
    )


import tau2.runner.batch  # noqa: E402

tau2.runner.batch.run_single_task = run_single_task
rows = {}
run_dir = Path(sys.argv[2])
for name, script in SCENARIOS.items():
    state.update(script=list(script), sent=[])
    adapter = H.ADAPTERS["tau2"](run_dir=run_dir, set_id="tau2-telecom-test", run="r_t1")
    task = adapter.task_ids("tau2-telecom-test")[0]
    args = argparse.Namespace(child=task, profile="baseline", trial=1, run="r", timeout=60.0)
    result = asyncio.run(H.run_task(args, adapter, run_dir, "abc"))
    rows[name] = [result.error, None if result.score is None else result.score.primary, state["sent"]]
print(json.dumps(rows))
"""


def test_the_real_tau2_adapter_does_not_grade_a_gateway_failure(tmp_path):
    """An error in the middle of a conversation used to end as a graded 0 with no error, because τ² scores what is left."""
    if not TAU2_PYTHON.exists() or not TAU2_ROOT.is_dir():
        missing_input("the τ² worktree or its venv is missing")
    env_file = compose("gptoss", "tau2", TAU2_AGENT, out_dir=tmp_path)
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR") if k in os.environ}
    env.update(parse_runner(env_file.read_text()))
    env.update(
        ENV_FILE=str(env_file), OPENAI_API_KEY="not-used", OPENAI_BASE_URL="http://127.0.0.1:9/not-used"
    )
    env["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"  # litellm fetches its price list at import otherwise
    done = subprocess.run(
        [str(TAU2_PYTHON), "-I", "-c", TAU2_REAL_RUN, str(BENCHMARKS), str(tmp_path), str(GATE_SRC)],
        capture_output=True,
        text=True,
        timeout=400,
        cwd=tmp_path,
        env=env,
    )
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-3000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    first = ["Is it fixed?"]
    assert out["clean"] == [None, 0.0, ["Is it fixed?", "Good, done."]]
    # a gateway failure: no score, and the customer never reads the error
    for name in ("invoke raises 429", "invoke raises a timeout", "error answer"):
        assert out[name][0].startswith("gateway:") and out[name][1:] == [None, first], (name, out[name])
    assert "429" in out["invoke raises 429"][0] and "503" in out["error answer"][0]
    # an error that is the agent's own: it stays in the result, and the state is graded
    assert out["agent bug"] == ["ValueError: bad state", 0.0, first]
    assert out["agent error answer"] == ["no plan", 0.0, first]
    # τ² ended the conversation: no failure
    assert out["tau2 ends in a tool call"] == [None, 0.0, first]
    assert out["tau2 ends in a tool call, langgraph"] == [None, 0.0, first]
    assert out["wiring"][0].startswith("wiring:") and out["wiring"][1] is None


AB_DRY_RUN = r"""
import asyncio, json, sys
from pathlib import Path

sys.path[:0] = [sys.argv[2], sys.argv[1]]
from policy_eval.harness import run as H

adapter = H.ADAPTERS["automationbench"](run_dir=Path(sys.argv[3]), set_id="ab-policy-types-holdout", run="r_t1")
task = adapter.task_ids("ab-policy-types-holdout")[0]


async def main():
    ctx = await adapter.prepare(task)
    score = await adapter.grade()
    return {"specs": len(ctx.tool_specs), "tools": len(adapter.tools), "apps": len(set(adapter.app_by_tool.values())),
            "version": ctx.policy_version == task, "request": bool(ctx.request), "score": score.partial is not None}


print(json.dumps(asyncio.run(main())))
"""


def test_the_automationbench_adapter_prepares_and_grades_with_its_own_module(tmp_path):
    """The task, the world, all tools and the rubric, in the benchmark's venv: no agent and no model call."""
    if not AB_PYTHON.exists():
        missing_input("the AutomationBench venv is missing")
    env_file = compose("gptoss", "automationbench", {}, out_dir=tmp_path)
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR") if k in os.environ}
    env.update(parse_runner(env_file.read_text()))
    env.update(
        ENV_FILE=str(env_file), OPENAI_API_KEY="not-used", OPENAI_BASE_URL="http://127.0.0.1:9/not-used"
    )
    done = subprocess.run(
        [str(AB_PYTHON), "-I", "-c", AB_DRY_RUN, str(BENCHMARKS), str(GATE_SRC), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=tmp_path,
        env=env,
    )
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-3000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out == {
        "specs": 549,
        "tools": 549,
        "apps": out["apps"],
        "version": True,
        "request": True,
        "score": True,
    }
    assert out["apps"] > 40


def test_the_handbook_module_has_what_the_adapter_calls():
    code = (
        "import sys; sys.path[:0] = [sys.argv[1], sys.argv[2] + '/handbook']; import hb_env\n"
        "assert all(callable(getattr(hb_env, n)) for n in ('start_container', 'logged_tools', 'specs_of', 'grade', 'sh'))\n"
        "assert hb_env.unwrap([{'type': 'text', 'text': 'a'}, {'type': 'text', 'text': 'b'}]) == 'a\\nb'\n"
        "assert hb_env.image('Task_' + 'x' * 80) == 'handbook_task:' + ('task_' + 'x' * 80)[:60]\n"
        "assert hb_env.sh(['true']).returncode == 0\n"
    )
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", code, str(GATE_SRC), str(BENCHMARKS)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-3000:]


SCAN = POLICY_EVAL / "tools" / "scan_run.py"


def scan_folder(root, name, trajectory=None, log=""):
    folder = root / name
    (folder / "trajectories").mkdir(parents=True)
    (folder / "logs").mkdir()
    (folder / "trajectories" / "t.json").write_text(json.dumps(trajectory or {"steps": [], "tool_calls": []}))
    (folder / "logs" / "t.log").write_text(log)
    return subprocess.run(
        [sys.executable, "-I", str(SCAN), str(folder)], capture_output=True, text=True, timeout=60
    )


@pytest.mark.parametrize(
    "text",
    [
        "inspect.getsource(run)",
        "sys.modules['x']",
        "subprocess.run(['ls'])",
        "__import__('os')",
        "grep -r answer .",
        "cat /Users/someone/file",
        "ls ~/dev",
        "open('automationbench/domains/x')",
        "sed tasks.py",
        "cat rubrics.json",
        "cat results.json",
        "python sop_verifier.py",
        "ls /tests",
        "unzip -p sheet.xlsx | grep -i Navarro",
        "cat Rubric.md",
        "open('answer_key.csv')",
        "cat answers.json",
        "ls solution/",
        "bash solve.sh",
        "cat solution.sh",
        "read ground_truth",
        "less gold_answers",
        "ls enterpriseops_gym/tasks",
        "open('itsm_oracle.json')",
        "ls AutomationBench/",
        "cat handbook-sample/tasks/x",
        "cat tests/test.sh",
        "cat task_prompt.txt",
        "ls tau2-bench",
        "cat data/tau2/domains/telecom/tasks.json",
        "print(task.evaluation_criteria)",
        "open('expected_answer.json')",
        "cat correct_answers.csv",
        "cat solutions.json",
        "python reference_solution.py",
        "print(task.answer)",
        "task['solution']",
        'row["answer"]',
        "python grader.py",
        "cat oracle.json",
        "ls tests/",
        "cd tests",
        "cat /tests_hidden/x",
    ],
)
def test_the_scan_finds_each_leak_pattern_in_what_the_agent_did(tmp_path, text):
    trajectory = {"steps": [{"name": "Assistant_tool_calls", "data": text, "prompts": []}], "tool_calls": []}
    done = scan_folder(tmp_path, "run", trajectory)
    assert done.returncode == 1 and "hits" in done.stdout


@pytest.mark.parametrize(
    "text",
    [
        "The answer is that the ticket is closed, and the solution is to reset the SIM.",
        "Here are the answers to your questions. I will check the test results and the expected output.",
        "Your solution file is ready: see the answer sheet in the attachment.",
        "Updated the ticket for E-1014, status resolved. Handbook section 4 applies.",
        "I tested the roaming settings and the data saver, then the line worked.",
        "The customer has a Gold plan, so the discount applies.",
        "GET /users/12 returned the user, and the unit tests/integration tests all passed.",
        "The expected answer to the customer is that the line is active; the solution was to reset it.",
    ],
)
def test_the_scan_does_not_fire_on_the_ordinary_words_of_an_agent(tmp_path, text):
    trajectory = {"steps": [{"name": "Assistant_nl", "data": text, "prompts": []}], "tool_calls": []}
    done = scan_folder(tmp_path, "run", trajectory)
    assert done.returncode == 0 and "0 hits" in done.stdout


def test_a_real_hit_is_printed_even_when_there_are_more_than_twenty_greps(tmp_path):
    greps = [
        {"name": "Assistant_tool_calls", "data": f"grep -i name{i} /workdir/f.xlsx", "prompts": []}
        for i in range(25)
    ]
    leak = {"name": "Assistant_tool_calls", "data": "cat /tests/rubrics.json", "prompts": []}
    done = scan_folder(tmp_path, "many", {"steps": [*greps, leak], "tool_calls": []})
    assert done.returncode == 1 and "cat /tests/rubrics.json" in done.stdout and "[rubric]" in done.stdout
    assert "and 5 more grep hits" in done.stdout  # 25 greps: 20 shown, 5 not


def test_the_scan_reads_tool_calls_and_logs_and_leaves_out_prompts_and_the_codes_own_lines(tmp_path):
    called = {"steps": [], "tool_calls": [{"tool": "bash", "args": {"command": "grep -r answers ~/dev"}}]}
    assert scan_folder(tmp_path, "called", called).returncode == 1
    assert scan_folder(tmp_path, "logged", log="agent code: inspect.getsource(x)\n").returncode == 1
    clean = {
        "steps": [{"name": "x", "prompts": [{"value": "see /tests and /Users/x"}], "data": "ok"}],
        "tool_calls": [],
    }
    own = "2026-11-05 | INFO | cuga.config:<module>:327 - Models config path: /Users/x/settings.toml\n"
    done = scan_folder(tmp_path, "clean", clean, own)
    assert done.returncode == 0 and "0 hits" in done.stdout
