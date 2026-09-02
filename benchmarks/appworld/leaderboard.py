"""AppWorld leaderboard submission helpers.

Pure functions (no cuga / appworld imports at module level) so the evaluator,
eval.sh and the tests can all use them cheaply. CLI: ``python -m
benchmarks.appworld.leaderboard <subcommand>`` (added in later tasks).

Leaderboard rules mirrored here come from ``appworld/src/appworld/leaderboard.py``:
experiment names are ``<prefix>_<split>``; a submission is two experiments,
one per split, each with every task of the split on disk.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPLITS: tuple[str, str] = ("test_normal", "test_challenge")
_PREFIX_RE = re.compile(r"^[a-z0-9_-]+$")


class LeaderboardError(Exception):
    """User-facing error: bad name, ids outside the split, missing files."""


def appworld_root(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    raw = env.get("APPWORLD_ROOT")
    if raw:
        return Path(raw.strip('"').strip("'")).resolve()
    return PROJECT_ROOT / "benchmarks" / "appworld" / "appworld"


def outputs_dir(root: Path) -> Path:
    return Path(root) / "experiments" / "outputs"


def load_split_ids(split: str, root: Path) -> list[str]:
    if split not in SPLITS:
        raise LeaderboardError(f"split must be one of {', '.join(SPLITS)}; got {split!r}")
    path = Path(root) / "data" / "datasets" / f"{split}.txt"
    if not path.is_file():
        raise LeaderboardError(f"dataset file not found: {path} (run ./setup_appworld.sh)")
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def validate_prefix(prefix: str) -> str:
    if not prefix or not _PREFIX_RE.match(prefix):
        raise LeaderboardError(
            f"leaderboard prefix {prefix!r} must match [a-z0-9_-]+ (lowercase; AppWorld rule)"
        )
    return prefix


def appworld_experiment_name(prefix: str, split: str) -> str:
    if split not in SPLITS:
        raise LeaderboardError(f"split must be one of {', '.join(SPLITS)}; got {split!r}")
    return f"{validate_prefix(prefix)}_{split}"


def infer_split(task_ids: Iterable[str], root: Path) -> str:
    ids = list(task_ids)
    membership = {split: set(load_split_ids(split, root)) for split in SPLITS}
    hits = {split for split in SPLITS if any(t in membership[split] for t in ids)}
    if len(hits) > 1:
        raise LeaderboardError("task ids span both test_normal and test_challenge; use one split per run")
    if not hits:
        raise LeaderboardError(f"no task id belongs to a leaderboard split: {ids[:5]}")
    split = hits.pop()
    outside = [t for t in ids if t not in membership[split]]
    if outside:
        raise LeaderboardError(f"task ids not in {split}: {outside[:10]}")
    return split
