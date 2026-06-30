"""Tests for the --eval-key train/test split feature (issue #44).

Covers:
- The committed benchmarks/m3/eval_config.toml (train/test disjoint, full
  coverage of the 200-sample small_train.zip corpus, both non-empty).
- benchmarks/m3/eval_config_loader.py (load_eval_key_ids,
  filter_samples_by_eval_key).
- Static checks that --eval-key is wired into eval_m3.py / eval_m3_react.py
  and documented in eval.sh --help.
"""

import subprocess
import tomllib
from pathlib import Path

import pytest

from benchmarks.m3.eval_config_loader import filter_samples_by_eval_key, load_eval_key_ids

pytestmark = pytest.mark.sanity

_M3_DIR = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _M3_DIR / "eval_config.toml"


def test_eval_config_toml_exists() -> None:
    assert _CONFIG_PATH.exists(), f"missing {_CONFIG_PATH}"


def test_train_and_test_are_disjoint_and_non_empty() -> None:
    config = tomllib.loads(_CONFIG_PATH.read_text())
    train, test = set(config["train"]), set(config["test"])

    assert train, "train split must not be empty"
    assert test, "test split must not be empty"
    assert not (train & test), "train/test splits must be disjoint"


def test_train_and_test_cover_the_full_corpus() -> None:
    config = tomllib.loads(_CONFIG_PATH.read_text())
    train, test = set(config["train"]), set(config["test"])

    # small_train.zip has 200 samples (20 domains x 10 each across the two
    # capabilities); the committed split is 100/100.
    assert len(train) == 100
    assert len(test) == 100
    assert len(train | test) == 200


def test_no_default_eval_key_committed() -> None:
    """The committed config must not set a default eval_key, so omitting
    --eval-key preserves the historical "run everything" behavior."""
    config = tomllib.loads(_CONFIG_PATH.read_text())
    assert "eval_key" not in config


def test_load_eval_key_ids_explicit_key() -> None:
    config = tomllib.loads(_CONFIG_PATH.read_text())
    ids = load_eval_key_ids("train")
    assert set(ids) == set(config["train"])


def test_load_eval_key_ids_no_key_and_no_default_returns_none() -> None:
    assert load_eval_key_ids(None) is None


def test_load_eval_key_ids_unknown_key_raises() -> None:
    with pytest.raises(KeyError):
        load_eval_key_ids("nonexistent-split")


def test_load_eval_key_ids_missing_config_file(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.toml"
    assert load_eval_key_ids(None, config_path=missing) is None
    with pytest.raises(FileNotFoundError):
        load_eval_key_ids("train", config_path=missing)


def test_load_eval_key_ids_uses_default_from_config(tmp_path: Path) -> None:
    config_path = tmp_path / "eval_config.toml"
    config_path.write_text('train = ["a", "b"]\ntest = ["c", "d"]\neval_key = "train"\n')

    assert load_eval_key_ids(None, config_path=config_path) == ["a", "b"]
    # An explicit --eval-key overrides the config default.
    assert load_eval_key_ids("test", config_path=config_path) == ["c", "d"]


def test_filter_samples_by_eval_key() -> None:
    samples = [{"sample_id": "AAA"}, {"sample_id": "bbb"}, {"uuid": "CCC"}]

    assert filter_samples_by_eval_key(samples, None) == samples
    assert filter_samples_by_eval_key(samples, {"aaa", "ccc"}) == [
        {"sample_id": "AAA"},
        {"uuid": "CCC"},
    ]
    assert filter_samples_by_eval_key(samples, {"zzz"}) == []


def test_filter_samples_by_eval_key_normalizes_caller_case() -> None:
    """The helper lower-cases ``eval_key_ids`` defensively, so a caller that
    forgets to normalize still matches (no silent zero-match)."""
    samples = [{"sample_id": "AAA"}, {"uuid": "bbb"}]
    assert filter_samples_by_eval_key(samples, {"AAA", "BBB"}) == samples
    # Empty set is an explicit empty split: keep nothing (distinct from None).
    assert filter_samples_by_eval_key(samples, set()) == []


@pytest.mark.parametrize("module", ["eval_m3.py", "eval_m3_react.py"])
def test_eval_key_flag_wired_into_evaluators(module: str) -> None:
    src = (_M3_DIR / module).read_text()
    assert '"--eval-key"' in src
    assert 'dest="eval_key"' in src
    assert "load_eval_key_ids" in src


def test_eval_m3_filters_preloaded_data_by_eval_key() -> None:
    src = (_M3_DIR / "eval_m3.py").read_text()
    assert "filter_samples_by_eval_key" in src


def test_eval_m3_react_filters_merged_samples_by_eval_key() -> None:
    src = (_M3_DIR / "eval_m3_react.py").read_text()
    # Assert the wiring (helper called on the loaded samples with the stored id
    # set) without pinning the exact call expression, so harmless refactors of
    # the surrounding code don't break the test.
    assert "self.eval_key_ids" in src
    assert "filter_samples_by_eval_key" in src
    assert "merged_samples" in src


def test_eval_sh_help_documents_eval_key() -> None:
    result = subprocess.run(  # noqa: S603
        ["bash", str(_M3_DIR / "eval.sh"), "--help"],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "--eval-key" in result.stdout


def test_eval_sh_rejects_eval_key_without_m3_data() -> None:
    result = subprocess.run(  # noqa: S603
        ["bash", str(_M3_DIR / "eval.sh"), "--eval-key", "train"],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    # eval.sh merges stderr into stdout (via `exec > >(tee ...) 2>&1`) before
    # this validation runs, so the message lands in stdout.
    assert "--eval-key requires --m3-data" in result.stdout
