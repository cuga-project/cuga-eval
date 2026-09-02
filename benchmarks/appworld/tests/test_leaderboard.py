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
