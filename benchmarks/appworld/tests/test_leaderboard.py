"""Unit tests for benchmarks/appworld/leaderboard.py (no appworld package needed)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from benchmarks.appworld import leaderboard as lb
from benchmarks.helpers import incremental_results as ir

pytestmark = [pytest.mark.unit, pytest.mark.sanity]

NORMAL = ["fd1f8fa_1", "fd1f8fa_2", "fd1f8fa_3", "29a7b7e_1", "29a7b7e_2", "29a7b7e_3"]
CHALLENGE = ["5238afc_1", "5238afc_2", "5238afc_3", "0d22252_1", "0d22252_2", "0d22252_3"]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A fake APPWORLD_ROOT with two tiny dataset files and per-task metadata."""
    ds = tmp_path / "data" / "datasets"
    ds.mkdir(parents=True)
    (ds / "test_normal.txt").write_text("\n".join(NORMAL) + "\n")
    (ds / "test_challenge.txt").write_text("\n".join(CHALLENGE))  # no trailing newline on purpose
    for i, tid in enumerate(NORMAL + CHALLENGE):
        meta = tmp_path / "data" / "tasks" / tid / "ground_truth"
        meta.mkdir(parents=True)
        (meta / "metadata.json").write_text(json.dumps({"difficulty": 1 + (i % 3)}))
    (tmp_path / "experiments" / "outputs").mkdir(parents=True)
    return tmp_path


def test_appworld_root_prefers_env(tmp_path):
    assert lb.appworld_root({"APPWORLD_ROOT": str(tmp_path)}) == tmp_path


def test_appworld_root_default_is_repo_clone():
    assert lb.appworld_root({}).as_posix().endswith("benchmarks/appworld/appworld")


def test_load_split_ids_handles_missing_trailing_newline(root):
    assert lb.load_split_ids("test_normal", root) == NORMAL
    assert lb.load_split_ids("test_challenge", root) == CHALLENGE


def test_load_split_ids_rejects_unknown_split(root):
    with pytest.raises(lb.LeaderboardError, match="test_normal, test_challenge"):
        lb.load_split_ids("dev", root)


@pytest.mark.parametrize("bad", ["", "Cuga", "cuga v1", "cuga.v1", "cuga/v1"])
def test_validate_prefix_rejects(bad):
    with pytest.raises(lb.LeaderboardError):
        lb.validate_prefix(bad)


def test_experiment_name():
    assert lb.appworld_experiment_name("cuga_v1", "test_challenge") == "cuga_v1_test_challenge"
    with pytest.raises(lb.LeaderboardError):
        lb.appworld_experiment_name("cuga_v1", "dev")


def test_infer_split(root):
    assert lb.infer_split(NORMAL[:2], root) == "test_normal"
    assert lb.infer_split(CHALLENGE, root) == "test_challenge"


def test_infer_split_rejects_mixed_and_unknown(root):
    with pytest.raises(lb.LeaderboardError, match="both"):
        lb.infer_split([NORMAL[0], CHALLENGE[0]], root)
    with pytest.raises(lb.LeaderboardError, match="zzz_9"):
        lb.infer_split([NORMAL[0], "zzz_9"], root)


TOML = '''[eval_config]
headless = true

# 6 tasks — demo
test_normal_all = ["fd1f8fa_1", "fd1f8fa_2", "fd1f8fa_3", "29a7b7e_1", "29a7b7e_2", "29a7b7e_3"]

eval_key = "test_easy"
'''


@pytest.fixture
def toml_path(tmp_path: Path) -> Path:
    p = tmp_path / "eval_config.toml"
    p.write_text(TOML)
    return p


def test_read_toml_keys_only_string_lists(toml_path):
    keys = lb.read_toml_keys(toml_path)
    assert keys == {"test_normal_all": NORMAL}


def test_base_id():
    assert lb.base_id("5238afc_2") == "5238afc"


def test_batch_ids_keeps_scenarios_together():
    ids = NORMAL + CHALLENGE  # 4 bases x 3
    batches = lb.batch_ids(ids, batch_size=4)
    # 4 would cut a base in half -> the batch grows to the base boundary (6)
    assert batches == [NORMAL, CHALLENGE]
    assert [t for b in batches for t in b] == ids


def test_batch_ids_last_batch_is_remainder():
    batches = lb.batch_ids(NORMAL + CHALLENGE, batch_size=9)
    assert [len(b) for b in batches] == [9, 3]


def test_write_toml_key_appends_and_keeps_comments(toml_path):
    assert lb.write_toml_key(toml_path, "retry_1", ["a_1", "b_2"], "2 tasks — retry") is True
    text = toml_path.read_text()
    assert "# 6 tasks — demo" in text  # existing comment survives
    assert text.rstrip().endswith('retry_1 = ["a_1", "b_2"]')
    assert lb.read_toml_keys(toml_path)["retry_1"] == ["a_1", "b_2"]


def test_write_toml_key_empty_list_is_idempotent(toml_path):
    assert lb.write_toml_key(toml_path, "empty_retry", [], "0 tasks — retry") is True
    assert lb.write_toml_key(toml_path, "empty_retry", [], "0 tasks — retry") is False
    assert toml_path.read_text().count("empty_retry = ") == 1
    assert lb.read_toml_keys(toml_path)["empty_retry"] == []


def test_write_toml_key_idempotent_and_conflict(toml_path):
    lb.write_toml_key(toml_path, "k", ["a_1"], "c")
    assert lb.write_toml_key(toml_path, "k", ["a_1"], "c") is False
    assert toml_path.read_text().count("k = ") == 1
    with pytest.raises(lb.LeaderboardError, match="already exists"):
        lb.write_toml_key(toml_path, "k", ["b_1"], "c")


def test_split_key_writes_batches(toml_path):
    names = lb.split_key(toml_path, "test_normal_all", batch_size=3)
    assert names == ["test_normal_all_b1", "test_normal_all_b2"]
    keys = lb.read_toml_keys(toml_path)
    assert keys["test_normal_all_b1"] == NORMAL[:3]
    assert keys["test_normal_all_b2"] == NORMAL[3:]
    # idempotent
    assert lb.split_key(toml_path, "test_normal_all", batch_size=3) == names
    assert toml_path.read_text().count("test_normal_all_b1 = ") == 1


def test_split_key_unknown_source(toml_path):
    with pytest.raises(lb.LeaderboardError, match="nope"):
        lb.split_key(toml_path, "nope", batch_size=3)


def test_cuga_viz_paste_line_loads(toml_path):
    line = 'test_hard_01_09__20h12m07s062ms_uncompleted_tasks = ["042a9fc_1", "0a9d82a_1"]\n'
    toml_path.write_text(toml_path.read_text() + "\n" + line)
    assert lb.read_toml_keys(toml_path)["test_hard_01_09__20h12m07s062ms_uncompleted_tasks"] == [
        "042a9fc_1",
        "0a9d82a_1",
    ]


@pytest.mark.parametrize(
    "key,expected",
    [
        ("test_hard_01_09__20h12m07s062ms_uncompleted_tasks", True),
        ("x_failed_tasks", True),
        ("cuga_v1_errored", True),
        ("cuga_v1_failed", True),
        ("test_challenge_all_b2", False),
        ("test_easy", False),
    ],
)
def test_is_retry_key(key, expected):
    assert lb.is_retry_key(key) is expected


ENV_IO_TWO = (
    "\n### Environment Interaction 1\n---\n```python\nx\n```\n\n```\nok\n```\n\n"
    "\n### Environment Interaction 2\n---\n```python\ny\n```\n\n```\nok\n```\n\n"
)


def make_task_dir(exp_dir: Path, tid: str, interactions: int = 2) -> Path:
    t = exp_dir / "tasks" / tid
    for rel in lb.REQUIRED_TASK_FILES:
        p = t / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}\n")
    body = "".join(
        f"\n### Environment Interaction {i}\n---\n```python\nz\n```\n\n```\nok\n```\n\n"
        for i in range(1, interactions + 1)
    )
    (t / "logs" / "environment_io.md").write_text(body)
    (t / "logs" / "api_calls.jsonl").write_text("{}\n" * interactions)
    return t


def make_evaluations(exp_dir: Path, split: str) -> None:
    d = exp_dir / "evaluations"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{split}.json").write_text("{}\n")
    (d / f"{split}.txt").write_text("report\n")


def test_required_task_files_count():
    assert len(lb.REQUIRED_TASK_FILES) == 19
    assert "dbs/model_hashes.json" in lb.REQUIRED_TASK_FILES
    assert "evaluation/report.md" in lb.REQUIRED_TASK_FILES


def test_count_interactions_and_api_calls(tmp_path):
    p = tmp_path / "environment_io.md"
    p.write_text(ENV_IO_TWO)
    assert lb.count_interactions(p) == 2
    a = tmp_path / "api_calls.jsonl"
    a.write_text('{"a":1}\n\n{"b":2}\n')
    assert lb.count_api_calls(a) == 2
    assert lb.count_interactions(tmp_path / "missing.md") == 0


def test_validate_complete_experiment(root):
    exp = lb.outputs_dir(root) / "cuga_v1_test_normal"
    for tid in NORMAL:
        make_task_dir(exp, tid)
    rep = lb.validate_experiment(exp, NORMAL, "test_normal")
    assert rep.ok()
    assert rep.present == 6 and rep.expected == 6
    assert "6/6" in rep.summary()


def test_validate_reports_every_problem(root):
    exp = lb.outputs_dir(root) / "cuga_v1_test_normal"
    make_task_dir(exp, "fd1f8fa_1")
    make_task_dir(exp, "fd1f8fa_2", interactions=1)  # low interactions
    make_task_dir(exp, "fd1f8fa_3")
    (exp / "tasks" / "fd1f8fa_3" / "dbs" / "gmail.jsonl").unlink()  # missing file
    make_task_dir(exp, "29a7b7e_1")  # base 29a7b7e incomplete
    rep = lb.validate_experiment(exp, NORMAL, "test_normal")
    assert not rep.ok()
    assert rep.missing_tasks == ["29a7b7e_2", "29a7b7e_3"]
    assert rep.missing_files == {"fd1f8fa_3": ["dbs/gmail.jsonl"]}
    assert rep.low_interaction_tasks == ["fd1f8fa_2"]
    assert rep.incomplete_bases == ["29a7b7e"]
    s = rep.summary()
    assert "29a7b7e_2" in s and "dbs/gmail.jsonl" in s and "fd1f8fa_2" in s


def test_validate_low_interactions_can_be_allowed(root):
    exp = lb.outputs_dir(root) / "cuga_v1_test_normal"
    for tid in NORMAL:
        make_task_dir(exp, tid, interactions=1)
    rep = lb.validate_experiment(exp, NORMAL, "test_normal")
    assert not rep.ok()
    assert rep.ok(allow_low_interactions=True)


def test_validate_missing_experiment_dir(root):
    rep = lb.validate_experiment(lb.outputs_dir(root) / "nope_test_normal", NORMAL, "test_normal")
    assert rep.present == 0 and rep.missing_tasks == NORMAL


def test_store_and_load_leaderboard_metadata(tmp_path):
    (tmp_path / "metadata.json").write_text(json.dumps({"experiment_name": "cuga_v1_chal"}))
    got = lb.store_leaderboard_metadata(
        tmp_path, prefix="cuga_v1", split="test_challenge", appworld_experiment="cuga_v1_test_challenge"
    )
    assert got == {
        "prefix": "cuga_v1",
        "split": "test_challenge",
        "appworld_experiment": "cuga_v1_test_challenge",
    }
    assert lb.load_leaderboard_metadata(tmp_path) == got
    # tracker folder is additive and overwrites the previous one
    lb.store_leaderboard_metadata(
        tmp_path,
        prefix="cuga_v1",
        split="test_challenge",
        appworld_experiment="cuga_v1_test_challenge",
        tracker_folder="b1_03-09--10h02m11s",
    )
    assert lb.load_leaderboard_metadata(tmp_path)["tracker_folder"] == "b1_03-09--10h02m11s"
    meta = json.loads((tmp_path / "metadata.json").read_text())
    assert meta["experiment_name"] == "cuga_v1_chal"  # untouched


def test_store_leaderboard_metadata_rejects_conflict(tmp_path):
    (tmp_path / "metadata.json").write_text("{}")
    lb.store_leaderboard_metadata(
        tmp_path, prefix="a", split="test_normal", appworld_experiment="a_test_normal"
    )
    with pytest.raises(lb.LeaderboardError, match="already"):
        lb.store_leaderboard_metadata(
            tmp_path, prefix="b", split="test_normal", appworld_experiment="b_test_normal"
        )


def test_load_leaderboard_metadata_none_when_absent(tmp_path):
    assert lb.load_leaderboard_metadata(tmp_path) is None
    (tmp_path / "metadata.json").write_text("{}")
    assert lb.load_leaderboard_metadata(tmp_path) is None


def test_summary_footer_reflects_strict_verdict():
    # Clean: strict ok() is True
    clean = lb.ValidationReport(split="test_normal", expected=6, present=6)
    assert clean.summary().splitlines()[-1] == "OK"

    # Only low interactions: strict ok() is False, allow_low_interactions=True is True
    only_low = lb.ValidationReport(split="test_normal", expected=1, present=1, low_interaction_tasks=["a_1"])
    assert only_low.summary().splitlines()[-1] == "SUBMITTABLE ONLY WITH --allow-low-interactions"

    # Missing tasks: both False
    missing = lb.ValidationReport(split="test_normal", expected=2, present=1, missing_tasks=["b_1"])
    assert missing.summary().splitlines()[-1] == "NOT SUBMITTABLE"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    w = tmp_path / "ws"
    w.mkdir()
    (w / "metadata.json").write_text("{}")
    return w


def test_plan_plain_run_skips_completed(root, ws):
    plan = lb.plan_run(
        task_ids=NORMAL[:3],
        eval_key="test_easy",
        leaderboard_prefix=None,
        bundle_dir=ws,
        completed_ids={NORMAL[0]},
        force_retry=False,
        root=root,
        default_experiment_name="test_easy",
    )
    assert plan.mode == "plain"
    assert plan.experiment_name == "test_easy"
    assert plan.task_ids == NORMAL[1:3] and plan.skipped == [NORMAL[0]]


def test_plan_leaderboard_first_batch(root, ws):
    plan = lb.plan_run(
        task_ids=CHALLENGE[:3],
        eval_key="test_challenge_all_b1",
        leaderboard_prefix="cuga_v1",
        bundle_dir=ws,
        completed_ids=set(),
        force_retry=False,
        root=root,
        default_experiment_name="x",
    )
    assert plan.mode == "batch"
    assert plan.experiment_name == "cuga_v1_test_challenge"
    assert plan.split == "test_challenge" and plan.prefix == "cuga_v1"


def test_plan_resume_uses_stored_name_and_split(root, ws):
    lb.store_leaderboard_metadata(
        ws, prefix="cuga_v1", split="test_challenge", appworld_experiment="cuga_v1_test_challenge"
    )
    plan = lb.plan_run(
        task_ids=CHALLENGE[3:],
        eval_key="test_challenge_all_b2",
        leaderboard_prefix=None,
        bundle_dir=ws,
        completed_ids=set(CHALLENGE[:3]),
        force_retry=False,
        root=root,
        default_experiment_name="x",
    )
    assert plan.experiment_name == "cuga_v1_test_challenge"
    assert plan.task_ids == CHALLENGE[3:]
    with pytest.raises(lb.LeaderboardError, match="not in test_challenge"):
        lb.plan_run(
            task_ids=NORMAL[:1],
            eval_key="oops",
            leaderboard_prefix=None,
            bundle_dir=ws,
            completed_ids=set(),
            force_retry=False,
            root=root,
            default_experiment_name="x",
        )


def test_plan_rejects_prefix_conflict(root, ws):
    lb.store_leaderboard_metadata(
        ws, prefix="cuga_v1", split="test_challenge", appworld_experiment="cuga_v1_test_challenge"
    )
    with pytest.raises(lb.LeaderboardError, match="prefix"):
        lb.plan_run(
            task_ids=CHALLENGE[:3],
            eval_key="k",
            leaderboard_prefix="cuga_v2",
            bundle_dir=ws,
            completed_ids=set(),
            force_retry=False,
            root=root,
            default_experiment_name="x",
        )


def test_plan_recorded_retry_key_reruns_completed(root, ws):
    lb.store_leaderboard_metadata(
        ws, prefix="cuga_v1", split="test_challenge", appworld_experiment="cuga_v1_test_challenge"
    )
    key = "test_challenge_all_b1_03_09__10h02m11s_uncompleted_tasks"
    lb.record_retry_key(ws, key)
    plan = lb.plan_run(
        task_ids=CHALLENGE[:2],
        eval_key=key,
        leaderboard_prefix=None,
        bundle_dir=ws,
        completed_ids=set(CHALLENGE),
        force_retry=False,
        root=root,
        default_experiment_name="x",
    )
    assert plan.mode == "retry" and plan.task_ids == CHALLENGE[:2] and plan.skipped == []


def test_plan_unrecorded_retry_shaped_key_does_not_rerun(root, ws):
    """A key that merely *looks* like a retry key must not clear the completed set.

    Retry-ness is recorded per workspace by ``retry-key``; inferring it from the
    suffix silently turned an ordinary resume into a full re-run.
    """
    lb.store_leaderboard_metadata(
        ws, prefix="cuga_v1", split="test_challenge", appworld_experiment="cuga_v1_test_challenge"
    )
    plan = lb.plan_run(
        task_ids=CHALLENGE[:2],
        eval_key="smoke_failed",
        leaderboard_prefix=None,
        bundle_dir=ws,
        # One still to do, so this exercises the skip logic rather than the
        # separate "nothing would run" guard below.
        completed_ids={CHALLENGE[0]},
        force_retry=False,
        root=root,
        default_experiment_name="x",
    )
    assert plan.mode == "batch" and plan.task_ids == [CHALLENGE[1]] and plan.skipped == [CHALLENGE[0]]


def test_plan_force_retry_on_batch_key(root, ws):
    plan = lb.plan_run(
        task_ids=NORMAL[:2],
        eval_key="test_normal_all_b1",
        leaderboard_prefix="cuga_v1",
        bundle_dir=ws,
        completed_ids=set(NORMAL),
        force_retry=True,
        root=root,
        default_experiment_name="x",
    )
    assert plan.mode == "retry" and plan.task_ids == NORMAL[:2]


def test_plan_no_bundle_dir_is_plain(root):
    plan = lb.plan_run(
        task_ids=NORMAL[:1],
        eval_key=None,
        leaderboard_prefix=None,
        bundle_dir=None,
        completed_ids=set(),
        force_retry=False,
        root=root,
        default_experiment_name="appworld_sdk_evaluation",
    )
    assert plan.mode == "plain" and plan.experiment_name == "appworld_sdk_evaluation"


def test_evaluator_uses_plan_run_and_stores_metadata():
    """Static guard: the evaluator must route naming through plan_run and persist the block."""
    src = (Path(lb.PROJECT_ROOT) / "benchmarks" / "appworld" / "eval_appworld_sdk.py").read_text()
    assert "plan_run(" in src
    assert "store_leaderboard_metadata(" in src
    assert "tracker.experiment_folder" in src


def _seed_partials(ws: Path) -> None:
    # `response` matters: it is one of the signs of real work that
    # incremental_results._looks_completed (and so --resume) looks for. A task
    # that ran and scored below 1.0 always has one; a hollow partial does not.
    ir.write_task_result(
        ws,
        NORMAL[0],
        {"task_name": NORMAL[0], "success": True, "error": None, "match_rate": 1.0, "response": "ok"},
    )
    ir.write_task_result(
        ws,
        NORMAL[1],
        {"task_name": NORMAL[1], "success": False, "error": None, "match_rate": 0.4, "response": "partial"},
    )
    ir.write_task_result(
        ws, NORMAL[2], {"task_name": NORMAL[2], "success": False, "error": "ReadTimeout", "match_rate": 0.0}
    )


def test_retry_candidates(ws):
    _seed_partials(ws)
    assert lb.retry_candidates(ws, "errored", NORMAL) == [NORMAL[2]]
    assert lb.retry_candidates(ws, "failed", NORMAL) == [NORMAL[1]]
    assert lb.retry_candidates(ws, "uncompleted", NORMAL) == NORMAL[3:]
    with pytest.raises(lb.LeaderboardError):
        lb.retry_candidates(ws, "bogus", NORMAL)


def test_write_retry_key(ws, toml_path):
    _seed_partials(ws)
    name, ids = lb.write_retry_key(toml_path, ws, "errored", NORMAL)
    assert name == "ws_errored" and ids == [NORMAL[2]]
    assert lb.read_toml_keys(toml_path)["ws_errored"] == [NORMAL[2]]
    assert lb.is_retry_key(name)


def test_workspace_status_leaderboard(root, ws):
    lb.store_leaderboard_metadata(
        ws, prefix="cuga_v1", split="test_normal", appworld_experiment="cuga_v1_test_normal"
    )
    _seed_partials(ws)
    st = lb.workspace_status(ws, root)
    assert st == {
        "experiment": "ws",
        "split": "test_normal",
        "expected": 6,
        "completed": 2,
        "errored": 1,
        "score_below_1": 1,
        "hollow": 0,
        "missing": 3,
    }
    line = lb.format_status(st)
    assert "completed 2/6" in line and "errored 1" in line and "score<1: 1" in line and "missing 3" in line


def test_workspace_status_plain(root, ws):
    _seed_partials(ws)
    st = lb.workspace_status(ws, root)
    assert st["split"] is None and st["expected"] == 3 and st["missing"] == 0


FAKE_EVAL = {
    "aggregate": {"task_goal_completion": 50.0, "scenario_goal_completion": 25.0},
    "individual": {
        "a_1": {"difficulty": 1, "success": True},
        "a_2": {"difficulty": 1, "success": False},
    },
}


def test_evaluate_official_uses_runner_and_root(tmp_path):
    seen = {}

    def runner(**kw):
        seen.update(kw)
        return FAKE_EVAL

    out = lb.evaluate_official("cuga_v1_test_normal", root=tmp_path, task_ids=["a_1", "a_2"], runner=runner)
    assert out is FAKE_EVAL
    assert seen == {
        "experiment_name": "cuga_v1_test_normal",
        "root": tmp_path,
        "split": None,
        "task_ids": ["a_1", "a_2"],
    }
    with pytest.raises(lb.LeaderboardError, match="either split or task_ids"):
        lb.evaluate_official("x", root=tmp_path, runner=runner)


def test_write_official_results_and_report(ws):
    table = {
        "aggregate": {"task_goal_completion": 50.0, "scenario_goal_completion": 25.0},
        "difficulty_1": {"task_goal_completion": 50.0, "scenario_goal_completion": 25.0},
        "difficulty_2": {"task_goal_completion": None, "scenario_goal_completion": None},
        "difficulty_3": {"task_goal_completion": None, "scenario_goal_completion": None},
    }
    (ws / "report.md").write_text("# Eval report\n\nsomething\n")
    out = lb.write_official_results(ws, table, split="test_normal", task_ids_count=2)
    assert out == ws / "results" / "appworld_official.json"
    data = json.loads(out.read_text())
    assert data["split"] == "test_normal" and data["table"]["aggregate"]["scenario_goal_completion"] == 25.0
    rep = (ws / "report.md").read_text()
    assert "## AppWorld official metrics" in rep and "scenario_goal_completion" in rep and "something" in rep
    # second write replaces the section instead of appending a second copy
    lb.write_official_results(ws, table, split="test_normal", task_ids_count=2)
    assert (ws / "report.md").read_text().count("## AppWorld official metrics") == 1


def test_write_official_results_preserves_following_sections(ws):
    table = {
        "aggregate": {"task_goal_completion": 50.0, "scenario_goal_completion": 25.0},
        "difficulty_1": {"task_goal_completion": 50.0, "scenario_goal_completion": 25.0},
        "difficulty_2": {"task_goal_completion": None, "scenario_goal_completion": None},
        "difficulty_3": {"task_goal_completion": None, "scenario_goal_completion": None},
    }
    initial_report = (
        "# Eval report\n\nintro\n\n## AppWorld official metrics\n\nold\n\n## Another section\n\nkeep me\n"
    )
    (ws / "report.md").write_text(initial_report)
    lb.write_official_results(ws, table, split="test_normal", task_ids_count=2)
    rep = (ws / "report.md").read_text()
    # Verify old section content is gone
    assert "old" not in rep
    # Verify following sections and content are preserved
    assert "## Another section" in rep
    assert "keep me" in rep
    assert "intro" in rep
    # Verify new table is present
    assert "scenario_goal_completion" in rep
    # Verify marker occurs exactly once
    assert rep.count("## AppWorld official metrics") == 1
    # Second write still preserves everything
    lb.write_official_results(ws, table, split="test_normal", task_ids_count=2)
    rep2 = (ws / "report.md").read_text()
    assert "## Another section" in rep2
    assert "keep me" in rep2
    assert "intro" in rep2
    assert rep2.count("## AppWorld official metrics") == 1


def test_format_official_table():
    table = {
        "aggregate": {"task_goal_completion": 50.0, "scenario_goal_completion": 25.0},
        "difficulty_1": {"task_goal_completion": 50.0, "scenario_goal_completion": 25.0},
        "difficulty_2": {"task_goal_completion": None, "scenario_goal_completion": None},
        "difficulty_3": {"task_goal_completion": None, "scenario_goal_completion": None},
    }
    text = lb.format_official_table(table)
    lines = text.splitlines()
    assert lines[0].split() == ["type", "task_goal_completion", "scenario_goal_completion"]
    assert lines[1].split() == ["aggregate", "50.0", "25.0"]
    assert lines[3].split() == ["difficulty_2", "n/a", "n/a"]


def _fake_packer_factory(root: Path, warn: bool = False):
    """Simulate appworld pack: copy the 19 files per task + metadata.json into a 'bundle' dir."""

    def packer(
        *, experiment_name, dataset_name, method_name, method_tooltip, llm_name, llm_tooltip, url, root
    ):
        exp = lb.outputs_dir(root) / experiment_name
        (exp / "metadata.json").write_text(
            json.dumps({"dataset": dataset_name, "method": {"name": method_name}})
        )
        staging = root / "_staging" / experiment_name
        if staging.exists():
            shutil.rmtree(staging)
        for t in (exp / "tasks").iterdir():
            for rel in lb.REQUIRED_TASK_FILES + lb.OPTIONAL_TASK_FILES:
                src = t / rel
                if src.is_file():
                    dst = staging / "tasks" / t.name / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
        for rel in lb.EVALUATION_FILES:
            src = exp / rel
            if src.is_file():
                dst = staging / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        shutil.copy2(exp / "metadata.json", staging / "metadata.json")
        (staging / "LICENSE").write_text("license")
        (staging / "README_BEFORE_SHARING.md").write_text("readme")
        (exp / "leaderboard.bundle").write_text(str(staging))
        return (
            "WARNING: Missing file path (x)\n"
            if warn
            else f"Leaderboard bundle ready at '{exp / 'leaderboard.bundle'}'.\n"
        )

    return packer


def _fake_unpacker(bundle_path: Path, dest: Path) -> list[str]:
    staging = Path(bundle_path.read_text())
    names = []
    for p in staging.rglob("*"):
        if p.is_file():
            rel = p.relative_to(staging.parent)
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest / rel)
            names.append(str(rel))
    return names


def test_pack_and_verify_roundtrip(root):
    exp = lb.outputs_dir(root) / "cuga_v1_test_normal"
    for tid in NORMAL:
        make_task_dir(exp, tid)
    make_evaluations(exp, "test_normal")
    (exp / "tasks" / NORMAL[0] / "logs" / "lm_calls.jsonl").write_text("{}\n")
    bundle = lb.pack_and_verify(
        "cuga_v1",
        "test_normal",
        root=root,
        method="CUGA",
        method_tooltip="lite",
        llm="gpt",
        llm_tooltip="",
        url="u",
        packer=_fake_packer_factory(root),
        unpacker=_fake_unpacker,
    )
    assert bundle == exp / "leaderboard.bundle"


def test_pack_refuses_incomplete_experiment(root):
    exp = lb.outputs_dir(root) / "cuga_v1_test_normal"
    for tid in NORMAL[:3]:
        make_task_dir(exp, tid)
    with pytest.raises(lb.LeaderboardError, match="NOT SUBMITTABLE"):
        lb.pack_and_verify(
            "cuga_v1",
            "test_normal",
            root=root,
            method="m",
            method_tooltip="",
            llm="l",
            llm_tooltip="",
            url="u",
            packer=_fake_packer_factory(root),
            unpacker=_fake_unpacker,
        )


def test_pack_refuses_low_interactions_unless_allowed(root):
    exp = lb.outputs_dir(root) / "cuga_v1_test_normal"
    for tid in NORMAL:
        make_task_dir(exp, tid, interactions=1)
    make_evaluations(exp, "test_normal")
    kw = dict(
        root=root,
        method="m",
        method_tooltip="",
        llm="l",
        llm_tooltip="",
        url="u",
        packer=_fake_packer_factory(root),
        unpacker=_fake_unpacker,
    )
    with pytest.raises(lb.LeaderboardError, match="interaction"):
        lb.pack_and_verify("cuga_v1", "test_normal", **kw)
    assert lb.pack_and_verify("cuga_v1", "test_normal", allow_low_interactions=True, **kw).is_file()


def test_pack_fails_on_appworld_warning(root):
    exp = lb.outputs_dir(root) / "cuga_v1_test_normal"
    for tid in NORMAL:
        make_task_dir(exp, tid)
    make_evaluations(exp, "test_normal")
    with pytest.raises(lb.LeaderboardError, match="Missing file path"):
        lb.pack_and_verify(
            "cuga_v1",
            "test_normal",
            root=root,
            method="m",
            method_tooltip="",
            llm="l",
            llm_tooltip="",
            url="u",
            packer=_fake_packer_factory(root, warn=True),
            unpacker=_fake_unpacker,
        )


def test_pack_detects_unpack_mismatch(root):
    exp = lb.outputs_dir(root) / "cuga_v1_test_normal"
    for tid in NORMAL:
        make_task_dir(exp, tid)
    make_evaluations(exp, "test_normal")

    def bad_unpacker(bundle_path, dest):
        names = _fake_unpacker(bundle_path, dest)
        (dest / "cuga_v1_test_normal" / "tasks" / NORMAL[0] / "dbs" / "gmail.jsonl").write_text("tampered")
        return names

    with pytest.raises(lb.LeaderboardError, match="differs"):
        lb.pack_and_verify(
            "cuga_v1",
            "test_normal",
            root=root,
            method="m",
            method_tooltip="",
            llm="l",
            llm_tooltip="",
            url="u",
            packer=_fake_packer_factory(root),
            unpacker=bad_unpacker,
        )


def test_pack_requires_evaluations_file(root):
    exp = lb.outputs_dir(root) / "cuga_v1_test_normal"
    for tid in NORMAL:
        make_task_dir(exp, tid)
    with pytest.raises(lb.LeaderboardError, match="evaluations/test_normal.json missing"):
        lb.pack_and_verify(
            "cuga_v1",
            "test_normal",
            root=root,
            method="m",
            method_tooltip="",
            llm="l",
            llm_tooltip="",
            url="u",
            packer=_fake_packer_factory(root),
            unpacker=_fake_unpacker,
        )


def test_expected_bundle_files_includes_optional_when_present(root):
    exp = lb.outputs_dir(root) / "cuga_v1_test_normal"
    for tid in NORMAL:
        make_task_dir(exp, tid)
    make_evaluations(exp, "test_normal")
    (exp / "tasks" / NORMAL[0] / "logs" / "lm_calls.jsonl").write_text("{}\n")
    expected = lb.expected_bundle_files(exp, NORMAL)
    assert f"tasks/{NORMAL[0]}/logs/lm_calls.jsonl" in expected
    assert f"tasks/{NORMAL[1]}/logs/lm_calls.jsonl" not in expected
    assert "evaluations/test_normal.json" in expected
    assert "evaluations/test_normal.txt" in expected


def test_cli_split_key_and_status(root, toml_path, ws, capsys):
    assert lb.cli(["split-key", "test_normal_all", "--batch-size", "3", "--toml", str(toml_path)]) == 0
    assert "test_normal_all_b2" in capsys.readouterr().out
    lb.store_leaderboard_metadata(
        ws, prefix="cuga_v1", split="test_normal", appworld_experiment="cuga_v1_test_normal"
    )
    assert lb.cli(["status", "--bundle-dir", str(ws), "--root", str(root)]) == 0
    assert "completed 0/6" in capsys.readouterr().out


def test_cli_validate_exit_codes(root, capsys):
    exp = lb.outputs_dir(root) / "cuga_v1_test_normal"
    for tid in NORMAL[:3]:
        make_task_dir(exp, tid)
    assert lb.cli(["validate", "cuga_v1", "--split", "test_normal", "--root", str(root)]) == 1
    assert "missing tasks (3)" in capsys.readouterr().out
    for tid in NORMAL[3:]:
        make_task_dir(exp, tid)
    assert lb.cli(["validate", "cuga_v1", "--split", "test_normal", "--root", str(root)]) == 0


# --- workspace guard (a typo'd --bundle-dir must not look like "nothing ran") ---


def test_retry_candidates_rejects_missing_workspace(tmp_path):
    with pytest.raises(lb.LeaderboardError, match="workspace directory not found"):
        lb.retry_candidates(tmp_path / "typo", "uncompleted", NORMAL)


def test_retry_candidates_rejects_dir_without_metadata(tmp_path):
    d = tmp_path / "not_a_workspace"
    d.mkdir()
    with pytest.raises(lb.LeaderboardError, match="not an eval workspace"):
        lb.retry_candidates(d, "uncompleted", NORMAL)


def test_write_retry_key_on_typod_dir_does_not_write_whole_split(tmp_path):
    """The bug this guards: a silent empty read turned every id into a retry id."""
    toml_path = tmp_path / "eval_config.toml"
    toml_path.write_text("[eval_config]\n")
    with pytest.raises(lb.LeaderboardError):
        lb.write_retry_key(toml_path, tmp_path / "typo", "uncompleted", NORMAL)
    assert "uncompleted" not in toml_path.read_text()


def test_workspace_status_rejects_missing_workspace(tmp_path, root):
    with pytest.raises(lb.LeaderboardError, match="workspace directory not found"):
        lb.workspace_status(tmp_path / "typo", root)


def test_write_retry_key_records_key_in_workspace(tmp_path, ws):
    toml_path = tmp_path / "eval_config.toml"
    toml_path.write_text("[eval_config]\n")
    key, ids = lb.write_retry_key(toml_path, ws, "uncompleted", NORMAL[:2])
    assert ids == NORMAL[:2]
    assert lb.load_retry_keys(ws) == {key}


# --- status / retry-key must agree with what --resume would re-run ---


def test_hollow_partial_is_not_completed(ws, root):
    """`error is None` alone is not completion — resume re-runs these.

    A middleware guard returning early leaves {error: None, success: False,
    response: None}. Counting it completed hid the task from both `status` and
    the `uncompleted` retry key while resume kept re-running it.
    """
    ir.write_task_result(ws, NORMAL[0], {"task_name": NORMAL[0], "success": True, "response": "ok"})
    ir.write_task_result(
        ws, NORMAL[1], {"task_name": NORMAL[1], "success": False, "error": None, "response": None}
    )
    assert lb.retry_candidates(ws, "uncompleted", NORMAL[:2]) == [NORMAL[1]]

    lb.store_leaderboard_metadata(
        ws, prefix="cuga_v1", split="test_normal", appworld_experiment="cuga_v1_test_normal"
    )
    st = lb.workspace_status(ws, root)
    assert st["completed"] == 1 and st["hollow"] == 1
    assert "hollow 1" in lb.format_status(st)


def test_status_completed_matches_resume_skip_set(ws, root):
    """The two views of one workspace must never disagree."""
    _seed_partials(ws)
    lb.store_leaderboard_metadata(
        ws, prefix="cuga_v1", split="test_normal", appworld_experiment="cuga_v1_test_normal"
    )
    st = lb.workspace_status(ws, root)
    assert st["completed"] == len(ir.load_completed_task_ids(ws))


# --- CLI errors stay CLI errors ---


def test_toml_key_ids_unknown_key_is_leaderboard_error(toml_path):
    with pytest.raises(lb.LeaderboardError, match="not found"):
        lb.toml_key_ids(toml_path, "test_normal_alll")


def test_toml_key_ids_empty_key_is_leaderboard_error(toml_path):
    lb.write_toml_key(toml_path, "empty_k", [], "0 tasks")
    with pytest.raises(lb.LeaderboardError, match="is empty"):
        lb.toml_key_ids(toml_path, "empty_k")


@pytest.mark.parametrize("cmd", ["retry-key", "evaluate"])
def test_cli_typod_key_exits_1_without_traceback(tmp_path, toml_path, ws, capsys, cmd):
    argv = (
        ["retry-key", "uncompleted", "--bundle-dir", str(ws), "--of-key", "nope", "--toml", str(toml_path)]
        if cmd == "retry-key"
        else ["evaluate", "x_test_normal", "--key", "nope", "--toml", str(toml_path)]
    )
    assert lb.cli(argv) == 1
    stderr = capsys.readouterr().err
    assert "Error:" in stderr
    assert "Traceback" not in stderr


def test_unrecorded_retry_shaped_key_that_would_noop_raises(root, ws):
    """Pre-fix retry keys have no `retry_keys` record — don't burn a silent no-op run."""
    lb.store_leaderboard_metadata(
        ws, prefix="cuga_v1", split="test_normal", appworld_experiment="cuga_v1_test_normal"
    )
    with pytest.raises(lb.LeaderboardError, match="looks like a retry key"):
        lb.plan_run(
            task_ids=NORMAL[:2],
            eval_key="cuga_v1_chal_errored",
            leaderboard_prefix=None,
            bundle_dir=ws,
            completed_ids=set(NORMAL),
            force_retry=False,
            root=root,
            default_experiment_name="x",
        )


def test_unrecorded_retry_shaped_key_with_work_left_is_a_plain_resume(root, ws):
    """Only the would-be-no-op case errors; a partly-done key still resumes."""
    lb.store_leaderboard_metadata(
        ws, prefix="cuga_v1", split="test_normal", appworld_experiment="cuga_v1_test_normal"
    )
    plan = lb.plan_run(
        task_ids=NORMAL[:2],
        eval_key="cuga_v1_chal_errored",
        leaderboard_prefix=None,
        bundle_dir=ws,
        completed_ids={NORMAL[0]},
        force_retry=False,
        root=root,
        default_experiment_name="x",
    )
    assert plan.mode == "batch" and plan.task_ids == [NORMAL[1]]


def test_force_retry_rescues_an_unrecorded_retry_key(root, ws):
    lb.store_leaderboard_metadata(
        ws, prefix="cuga_v1", split="test_normal", appworld_experiment="cuga_v1_test_normal"
    )
    plan = lb.plan_run(
        task_ids=NORMAL[:2],
        eval_key="cuga_v1_chal_errored",
        leaderboard_prefix=None,
        bundle_dir=ws,
        completed_ids=set(NORMAL),
        force_retry=True,
        root=root,
        default_experiment_name="x",
    )
    assert plan.mode == "retry" and plan.task_ids == NORMAL[:2]
