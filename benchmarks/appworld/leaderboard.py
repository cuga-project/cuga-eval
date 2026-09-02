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
from dataclasses import dataclass, field
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


APP_NAMES: tuple[str, ...] = (
    "admin",
    "amazon",
    "api_docs",
    "file_system",
    "gmail",
    "phone",
    "simple_note",
    "splitwise",
    "spotify",
    "supervisor",
    "todoist",
    "venmo",
)
REQUIRED_TASK_FILES: tuple[str, ...] = tuple(
    [f"dbs/{app}.jsonl" for app in APP_NAMES]
    + [
        "dbs/model_hashes.json",
        "logs/environment_io.md",
        "logs/api_calls.jsonl",
        "version/code.txt",
        "version/data.txt",
        "evaluation/report.md",
        "evaluation/version.txt",
    ]
)
_INTERACTION_RE = re.compile(r"^### Environment Interaction \d+", re.MULTILINE)


def count_interactions(env_io_path: Path) -> int:
    p = Path(env_io_path)
    if not p.is_file():
        return 0
    return len(_INTERACTION_RE.findall(p.read_text(errors="replace")))


def count_api_calls(api_calls_path: Path) -> int:
    p = Path(api_calls_path)
    if not p.is_file():
        return 0
    return sum(1 for line in p.read_text(errors="replace").splitlines() if line.strip())


@dataclass
class ValidationReport:
    split: str
    expected: int
    present: int
    missing_tasks: list[str] = field(default_factory=list)
    missing_files: dict[str, list[str]] = field(default_factory=dict)
    low_interaction_tasks: list[str] = field(default_factory=list)
    incomplete_bases: list[str] = field(default_factory=list)

    def ok(self, allow_low_interactions: bool = False) -> bool:
        if self.missing_tasks or self.missing_files or self.incomplete_bases:
            return False
        return allow_low_interactions or not self.low_interaction_tasks

    def summary(self) -> str:
        lines = [f"{self.split}: {self.present}/{self.expected} task dirs present"]
        if self.missing_tasks:
            lines.append(f"missing tasks ({len(self.missing_tasks)}): {' '.join(self.missing_tasks)}")
        for tid, files in self.missing_files.items():
            lines.append(f"missing files in {tid}: {' '.join(files)}")
        if self.incomplete_bases:
            lines.append(f"bases missing a scenario: {' '.join(self.incomplete_bases)}")
        if self.low_interaction_tasks:
            lines.append(
                f"tasks with <=1 environment interaction ({len(self.low_interaction_tasks)}): "
                f"{' '.join(self.low_interaction_tasks)}  "
                "(CUGA API calls bypass world.execute — see issue; pass --allow-low-interactions to proceed)"
            )
        lines.append("OK" if self.ok(allow_low_interactions=True) else "NOT SUBMITTABLE")
        return "\n".join(lines)


def validate_experiment(exp_dir: Path, split_ids: list[str], split: str) -> ValidationReport:
    exp_dir = Path(exp_dir)
    rep = ValidationReport(split=split, expected=len(split_ids), present=0)
    present_ids: set[str] = set()
    for tid in split_ids:
        t = exp_dir / "tasks" / tid
        if not t.is_dir():
            rep.missing_tasks.append(tid)
            continue
        present_ids.add(tid)
        rep.present += 1
        missing = [rel for rel in REQUIRED_TASK_FILES if not (t / rel).is_file()]
        if missing:
            rep.missing_files[tid] = missing
        if count_interactions(t / "logs" / "environment_io.md") <= 1:
            rep.low_interaction_tasks.append(tid)
    bases: dict[str, set[str]] = {}
    for tid in split_ids:
        bases.setdefault(base_id(tid), set()).add(tid)
    for b, members in bases.items():
        if members & present_ids and not members <= present_ids:
            rep.incomplete_bases.append(b)
    rep.incomplete_bases.sort()
    return rep


def load_leaderboard_metadata(bundle_dir: Path) -> dict | None:
    meta_path = Path(bundle_dir) / "metadata.json"
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError):
        return None
    block = meta.get("leaderboard")
    return dict(block) if isinstance(block, dict) and block else None


def store_leaderboard_metadata(
    bundle_dir: Path,
    *,
    prefix: str,
    split: str,
    appworld_experiment: str,
    tracker_folder: str | None = None,
) -> dict:
    from benchmarks.helpers.incremental_results import atomic_write_json

    meta_path = Path(bundle_dir) / "metadata.json"
    meta: dict = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, ValueError):
            meta = {}
    existing = meta.get("leaderboard") or {}
    for key, value in (("prefix", prefix), ("split", split), ("appworld_experiment", appworld_experiment)):
        if existing.get(key) not in (None, value):
            raise LeaderboardError(
                f"workspace already bound to leaderboard {key}={existing[key]!r}; got {value!r}. "
                "Start a new --experiment for a different prefix/split."
            )
    block = {**existing, "prefix": prefix, "split": split, "appworld_experiment": appworld_experiment}
    if tracker_folder:
        block["tracker_folder"] = tracker_folder
    meta["leaderboard"] = block
    atomic_write_json(meta_path, meta)
    return block
