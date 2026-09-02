"""AppWorld leaderboard submission helpers.

Pure functions (no cuga / appworld imports at module level) so the evaluator,
eval.sh and the tests can all use them cheaply. CLI: ``python -m
benchmarks.appworld.leaderboard <subcommand>`` (added in later tasks).

Leaderboard rules mirrored here come from ``appworld/src/appworld/leaderboard.py``:
experiment names are ``<prefix>_<split>``; a submission is two experiments,
one per split, each with every task of the split on disk.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
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


RETRY_KEY_SUFFIXES = ("_uncompleted_tasks", "_failed_tasks", "_uncompleted", "_failed", "_errored")


def read_toml_keys(toml_path: Path) -> dict[str, list[str]]:
    with open(toml_path, "rb") as fh:
        data = tomllib.load(fh)

    result = {}

    def extract_lists(obj):
        """Recursively extract string lists from nested dicts."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, list) and v and all(isinstance(x, str) for x in v):
                    result[k] = [str(x) for x in v]
                elif isinstance(v, dict):
                    extract_lists(v)

    extract_lists(data)
    return result


def base_id(task_id: str) -> str:
    return task_id.rsplit("_", 1)[0]


def batch_ids(ids: list[str], batch_size: int) -> list[list[str]]:
    if batch_size < 1:
        raise LeaderboardError("batch_size must be >= 1")
    batches: list[list[str]] = []
    current: list[str] = []
    for tid in ids:
        # Close the batch only at a base boundary so _1/_2/_3 of a base stay together.
        if len(current) >= batch_size and base_id(tid) != base_id(current[-1]):
            batches.append(current)
            current = []
        current.append(tid)
    if current:
        batches.append(current)
    return batches


def write_toml_key(toml_path: Path, key: str, ids: list[str], comment: str) -> bool:
    existing = read_toml_keys(toml_path) if Path(toml_path).is_file() else {}
    if key in existing:
        if existing[key] == list(ids):
            return False
        raise LeaderboardError(f"toml key {key!r} already exists with different ids in {toml_path}")
    text = Path(toml_path).read_text() if Path(toml_path).is_file() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    text += f"\n# {comment}\n{key} = {json.dumps(list(ids))}\n"
    Path(toml_path).write_text(text)
    return True


def split_key(toml_path: Path, key: str, batch_size: int) -> list[str]:
    keys = read_toml_keys(toml_path)
    if key not in keys:
        raise LeaderboardError(f"toml key {key!r} not found in {toml_path}")
    names: list[str] = []
    for i, batch in enumerate(batch_ids(keys[key], batch_size), 1):
        name = f"{key}_b{i}"
        write_toml_key(toml_path, name, batch, f"{len(batch)} tasks — batch {i} of {key}")
        names.append(name)
    return names


def is_retry_key(key: str) -> bool:
    return key.endswith(RETRY_KEY_SUFFIXES)
