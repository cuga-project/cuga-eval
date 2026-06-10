"""Unit tests for benchmarks/m3/scripts/generate_eval_split.py (issue #44).

Builds a tiny synthetic M3DataLoader-compatible directory (2 capabilities x 2
domains x 6 samples = 24 total) and exercises the split generator against it,
checking disjointness, full coverage, reproducibility, and --ratio handling.
"""

import tomllib
from pathlib import Path

import pytest

from benchmarks.m3.scripts.generate_eval_split import main, render_toml, split_ids

pytestmark = pytest.mark.sanity

# (task_id, domain, num_samples)
_GROUPS = [
    (2, "domain_a", 6),
    (2, "domain_b", 6),
    (3, "domain_c", 6),
]


def _make_corpus(root: Path) -> Path:
    """Write a minimal M3DataLoader-compatible corpus under `root`."""
    for task_id, domain, n in _GROUPS:
        cap_dir = root / f"capability_{task_id}_test"
        input_dir = cap_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        samples = [
            {
                "uuid": f"task{task_id}-{domain}-{i:02d}",
                "domain": domain,
                "dialogue": {"turns": []},
            }
            for i in range(n)
        ]
        (input_dir / f"{domain}.json").write_text(__import__("json").dumps(samples))
    return root


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    return _make_corpus(tmp_path / "data")


def test_split_is_disjoint_and_covers_all_ids(corpus: Path) -> None:
    train_ids, test_ids, counts = split_ids(corpus, ratio=0.5, seed=42)

    train_set, test_set = set(train_ids), set(test_ids)
    assert not (train_set & test_set), "train/test must be disjoint"

    all_ids = {f"task{tid}-{dom}-{i:02d}" for tid, dom, n in _GROUPS for i in range(n)}
    assert train_set | test_set == all_ids

    # 50/50 split of 6 samples per group -> 3/3 each, stratified.
    assert counts == {(2, "domain_a"): (3, 3), (2, "domain_b"): (3, 3), (3, "domain_c"): (3, 3)}
    assert len(train_ids) == 9
    assert len(test_ids) == 9


def test_split_is_reproducible_for_same_seed(corpus: Path) -> None:
    train_a, test_a, _ = split_ids(corpus, ratio=0.5, seed=42)
    train_b, test_b, _ = split_ids(corpus, ratio=0.5, seed=42)
    assert train_a == train_b
    assert test_a == test_b


def test_different_seeds_produce_different_splits(corpus: Path) -> None:
    train_a, _test_a, _ = split_ids(corpus, ratio=0.5, seed=42)
    train_b, _test_b, _ = split_ids(corpus, ratio=0.5, seed=7)
    assert train_a != train_b


def test_ratio_changes_split_sizes(corpus: Path) -> None:
    train_ids, test_ids, counts = split_ids(corpus, ratio=0.6, seed=42)

    # round(6 * 0.6) == 4 train / 2 test per group.
    assert counts == {(2, "domain_a"): (4, 2), (2, "domain_b"): (4, 2), (3, "domain_c"): (4, 2)}
    assert len(train_ids) == 12
    assert len(test_ids) == 6


def test_render_toml_is_valid_and_round_trips(corpus: Path) -> None:
    train_ids, test_ids, counts = split_ids(corpus, ratio=0.5, seed=42)
    text = render_toml(train_ids, test_ids, counts, source="data", ratio=0.5, seed=42, eval_key="train")

    config = tomllib.loads(text)
    assert set(config["train"]) == set(train_ids)
    assert set(config["test"]) == set(test_ids)
    assert config["eval_key"] == "train"


def test_render_toml_omits_eval_key_when_not_set(corpus: Path) -> None:
    train_ids, test_ids, counts = split_ids(corpus, ratio=0.5, seed=42)
    text = render_toml(train_ids, test_ids, counts, source="data", ratio=0.5, seed=42, eval_key=None)

    config = tomllib.loads(text)
    assert "eval_key" not in config


def test_main_writes_output_file(corpus: Path, tmp_path: Path) -> None:
    output = tmp_path / "eval_config.toml"
    rc = main(["--m3-data", str(corpus), "--ratio", "0.5", "--seed", "42", "--output", str(output)])

    assert rc == 0
    assert output.exists()

    config = tomllib.loads(output.read_text())
    assert len(config["train"]) == 9
    assert len(config["test"]) == 9
    assert "eval_key" not in config


def test_main_rejects_invalid_ratio(corpus: Path, tmp_path: Path) -> None:
    output = tmp_path / "eval_config.toml"
    with pytest.raises(SystemExit):
        main(["--m3-data", str(corpus), "--ratio", "1.5", "--output", str(output)])
