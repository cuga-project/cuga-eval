"""Unit tests for benchmarks/appworld/leaderboard.py (no appworld package needed)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.appworld import leaderboard as lb

pytestmark = pytest.mark.unit

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
