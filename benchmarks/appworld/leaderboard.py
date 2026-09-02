"""AppWorld leaderboard submission helpers.

Pure functions (no cuga / appworld imports at module level) so the evaluator,
eval.sh and the tests can all use them cheaply. CLI: ``python -m
benchmarks.appworld.leaderboard <subcommand>`` (added in later tasks).

Leaderboard rules mirrored here come from ``appworld/src/appworld/leaderboard.py``:
experiment names are ``<prefix>_<split>``; a submission is two experiments,
one per split, each with every task of the split on disk.
"""

from __future__ import annotations

import argparse
import contextlib
import filecmp
import io
import json
import os
import re
import sys
import tempfile
import tomllib
from collections.abc import Callable, Iterable, Mapping
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
        if self.ok():
            footer = "OK"
        elif self.ok(allow_low_interactions=True):
            footer = "SUBMITTABLE ONLY WITH --allow-low-interactions"
        else:
            footer = "NOT SUBMITTABLE"
        lines.append(footer)
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


@dataclass
class RunPlan:
    experiment_name: str
    task_ids: list[str]
    skipped: list[str]
    split: str | None
    prefix: str | None
    mode: str  # "plain" | "batch" | "retry"


def plan_run(
    *,
    task_ids: list[str],
    eval_key: str | None,
    leaderboard_prefix: str | None,
    bundle_dir: Path | None,
    completed_ids: set[str],
    force_retry: bool,
    root: Path,
    default_experiment_name: str,
) -> RunPlan:
    stored = load_leaderboard_metadata(bundle_dir) if bundle_dir is not None else None
    split: str | None = None
    prefix: str | None = None
    experiment_name = default_experiment_name

    if leaderboard_prefix:
        prefix = validate_prefix(leaderboard_prefix)
        split = infer_split(task_ids, root)
        if stored and (stored.get("prefix") != prefix or stored.get("split") != split):
            raise LeaderboardError(
                f"workspace is bound to prefix={stored.get('prefix')!r} split={stored.get('split')!r}; "
                f"got prefix={prefix!r} split={split!r}"
            )
        experiment_name = appworld_experiment_name(prefix, split)
    elif stored:
        prefix, split = stored["prefix"], stored["split"]
        allowed = set(load_split_ids(split, root))
        outside = [t for t in task_ids if t not in allowed]
        if outside:
            raise LeaderboardError(f"task ids not in {split}: {outside[:10]}")
        experiment_name = stored["appworld_experiment"]

    retry = force_retry or (eval_key is not None and is_retry_key(eval_key))
    if retry:
        mode = "retry"
        to_run, skipped = list(task_ids), []
    else:
        mode = "batch" if split else "plain"
        to_run = [t for t in task_ids if t not in completed_ids]
        skipped = [t for t in task_ids if t in completed_ids]
    return RunPlan(experiment_name, to_run, skipped, split, prefix, mode)


RETRY_KINDS = ("errored", "failed", "uncompleted")


def _partials_by_task(bundle_dir: Path) -> dict[str, dict]:
    from benchmarks.helpers.incremental_results import load_all_partial_results

    out: dict[str, dict] = {}
    for r in load_all_partial_results(Path(bundle_dir)):
        key = r.get("task_name") or r.get("task_id")
        if key:
            out[str(key)] = r
    return out


def retry_candidates(bundle_dir: Path, kind: str, expected_ids: list[str]) -> list[str]:
    if kind not in RETRY_KINDS:
        raise LeaderboardError(f"kind must be one of {', '.join(RETRY_KINDS)}; got {kind!r}")
    partials = _partials_by_task(bundle_dir)
    if kind == "uncompleted":
        return [t for t in expected_ids if t not in partials]
    if kind == "errored":
        return [t for t in expected_ids if t in partials and partials[t].get("error") is not None]
    return [
        t
        for t in expected_ids
        if t in partials and partials[t].get("error") is None and partials[t].get("success") is not True
    ]


def write_retry_key(
    toml_path: Path, bundle_dir: Path, kind: str, expected_ids: list[str], name: str | None = None
) -> tuple[str, list[str]]:
    ids = retry_candidates(bundle_dir, kind, expected_ids)
    key = name or f"{Path(bundle_dir).name}_{kind}"
    if not is_retry_key(key):
        raise LeaderboardError(f"retry key name must end with one of {RETRY_KEY_SUFFIXES}: {key!r}")
    write_toml_key(toml_path, key, ids, f"{len(ids)} tasks — {kind} in experiment {Path(bundle_dir).name}")
    return key, ids


def workspace_status(bundle_dir: Path, root: Path) -> dict:
    bundle_dir = Path(bundle_dir)
    stored = load_leaderboard_metadata(bundle_dir)
    partials = _partials_by_task(bundle_dir)
    split = stored["split"] if stored else None
    expected_ids = load_split_ids(split, root) if split else list(partials)
    completed = sum(1 for r in partials.values() if r.get("error") is None)
    errored = sum(1 for r in partials.values() if r.get("error") is not None)
    below = sum(1 for r in partials.values() if r.get("error") is None and r.get("success") is not True)
    return {
        "experiment": bundle_dir.name,
        "split": split,
        "expected": len(expected_ids),
        "completed": completed,
        "errored": errored,
        "score_below_1": below,
        "missing": len([t for t in expected_ids if t not in partials]),
    }


def format_status(status: dict) -> str:
    return (
        f"{status['experiment']}  split={status['split'] or '-'}  "
        f"completed {status['completed']}/{status['expected']}  errored {status['errored']}  "
        f"score<1: {status['score_below_1']}  missing {status['missing']}"
    )


OFFICIAL_SECTION = "## AppWorld official metrics"
_ROWS = ("aggregate", "difficulty_1", "difficulty_2", "difficulty_3")
_COLS = ("task_goal_completion", "scenario_goal_completion")


def _appworld_runner(
    *, experiment_name: str, root: Path, split: str | None, task_ids: list[str] | None
) -> dict:
    from appworld.common.path_store import path_store
    from appworld.evaluator import evaluate_dataset, evaluate_tasks

    path_store.update_root(str(root))
    if split:
        return evaluate_dataset(
            experiment_name,
            split,
            include_details=True,
            aggregate_only=False,
            save_reports=True,
            print_report=False,
        )
    return evaluate_tasks(
        task_ids or [], experiment_name=experiment_name, include_details=True, save_reports=False
    )


def evaluate_official(
    experiment_name: str,
    *,
    root: Path,
    split: str | None = None,
    task_ids: list[str] | None = None,
    runner: Callable[..., dict] | None = None,
) -> dict:
    if bool(split) == bool(task_ids):
        raise LeaderboardError("pass either split or task_ids (exactly one)")
    run = runner or _appworld_runner
    return run(experiment_name=experiment_name, root=root, split=split, task_ids=task_ids)


def official_table(evaluation_dict: dict) -> dict:
    from appworld.evaluator import Metric

    data = Metric.build_report(evaluation_dict)
    table: dict = {}
    for i, row in enumerate(data["type"]):
        table[row] = {col: data[col][i] for col in _COLS if col in data}
    return table


def format_official_table(table: dict) -> str:
    def cell(v: object) -> str:
        return "n/a" if v is None else str(v)

    lines = [f"{'type':<14}{'task_goal_completion':<24}scenario_goal_completion"]
    for row in _ROWS:
        vals = table.get(row, {})
        lines.append(f"{row:<14}{cell(vals.get(_COLS[0])):<24}{cell(vals.get(_COLS[1]))}")
    return "\n".join(lines)


def write_official_results(bundle_dir: Path, table: dict, *, split: str | None, task_ids_count: int) -> Path:
    from benchmarks.helpers.incremental_results import atomic_write_json

    bundle_dir = Path(bundle_dir)
    out = bundle_dir / "results" / "appworld_official.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out, {"split": split, "task_count": task_ids_count, "table": table})
    report = bundle_dir / "report.md"
    text = report.read_text() if report.is_file() else "# Evaluation report\n"

    # Find and remove the old section if it exists
    marker_pattern = re.compile(r"^## AppWorld official metrics\s*$", re.MULTILINE)
    match = marker_pattern.search(text)
    if match:
        # Find the start of the section (the marker line)
        section_start = match.start()
        # Find the end of the section (next ## heading or end of file)
        rest = text[match.end() :]
        next_section_match = re.search(r"^## ", rest, re.MULTILINE)
        if next_section_match:
            section_end = match.end() + next_section_match.start()
        else:
            section_end = len(text)
        # Remove the old section
        text = text[:section_start] + text[section_end:]

    section = (
        f"\n{OFFICIAL_SECTION}\n\n"
        f"scope: {'split ' + split if split else f'{task_ids_count} task ids'}\n\n"
        f"```\n{format_official_table(table)}\n```\n"
    )
    report.write_text(text.rstrip() + "\n" + section)
    return out


PACKED_EXTRA_FILES = ("metadata.json", "LICENSE", "README_BEFORE_SHARING.md")
EVALUATION_FILES = tuple(f"evaluations/{s}.{ext}" for s in SPLITS for ext in ("json", "txt"))
OPTIONAL_TASK_FILES = ("logs/lm_calls.jsonl", "logs/logger.jsonl", "logs/logger.log", "misc/usage.json")


def expected_bundle_files(exp_dir: Path, split_ids: list[str]) -> list[str]:
    exp_dir = Path(exp_dir)
    expected = list(PACKED_EXTRA_FILES)
    expected += [rel for rel in EVALUATION_FILES if (exp_dir / rel).is_file()]
    for tid in split_ids:
        t = exp_dir / "tasks" / tid
        expected += [f"tasks/{tid}/{rel}" for rel in REQUIRED_TASK_FILES]
        expected += [f"tasks/{tid}/{rel}" for rel in OPTIONAL_TASK_FILES if (t / rel).is_file()]
    return expected


def _appworld_packer(**kw) -> str:
    from appworld.common.path_store import path_store
    from appworld.leaderboard import pack_experiment

    path_store.update_root(str(kw.pop("root")))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pack_experiment(**kw)
    return buf.getvalue()


def _appworld_unpacker(bundle_path: Path, dest: Path) -> list[str]:
    from appworld.common.constants import PASSWORD, SALT
    from appworld.common.crypto import unpack_bundle

    return unpack_bundle(
        bundle_file_path=str(bundle_path), base_directory=str(dest), password=PASSWORD, salt=SALT
    )


def pack_and_verify(
    prefix: str,
    split: str,
    *,
    root: Path,
    method: str,
    method_tooltip: str,
    llm: str,
    llm_tooltip: str,
    url: str,
    allow_low_interactions: bool = False,
    packer: Callable[..., str] | None = None,
    unpacker: Callable[[Path, Path], list[str]] | None = None,
) -> Path:
    experiment_name = appworld_experiment_name(prefix, split)
    split_ids = load_split_ids(split, root)
    exp_dir = outputs_dir(root) / experiment_name
    report = validate_experiment(exp_dir, split_ids, split)
    if not report.ok(allow_low_interactions=allow_low_interactions):
        raise LeaderboardError(report.summary())
    if not (exp_dir / f"evaluations/{split}.json").is_file():
        raise LeaderboardError(
            f"{experiment_name}: evaluations/{split}.json missing — "
            f"run `leaderboard evaluate {experiment_name} --split {split}` first"
        )

    out = (packer or _appworld_packer)(
        experiment_name=experiment_name,
        dataset_name=split,
        method_name=method,
        method_tooltip=method_tooltip,
        llm_name=llm,
        llm_tooltip=llm_tooltip,
        url=url,
        root=root,
    )
    warnings = [line for line in out.splitlines() if "WARNING: Missing file path" in line]
    if warnings:
        raise LeaderboardError("appworld pack reported missing files:\n" + "\n".join(warnings))
    bundle_path = exp_dir / "leaderboard.bundle"
    if not bundle_path.is_file():
        raise LeaderboardError(f"pack did not produce {bundle_path}")

    with tempfile.TemporaryDirectory(prefix="lb_verify_") as tmp:
        dest = Path(tmp)
        names = (unpacker or _appworld_unpacker)(bundle_path, dest)
        actual = {n.replace(os.sep, "/").removeprefix(f"{experiment_name}/") for n in names}
        expected = set(expected_bundle_files(exp_dir, split_ids))
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if missing or unexpected:
            parts = []
            if missing:
                parts.append(f"missing from bundle ({len(missing)}): {' '.join(missing)}")
            if unexpected:
                parts.append(f"unexpected in bundle ({len(unexpected)}): {' '.join(unexpected)}")
            raise LeaderboardError("bundle contents don't match expected files:\n" + "\n".join(parts))
        unpacked_root = dest / experiment_name
        for rel in sorted(expected):
            if rel in ("LICENSE", "README_BEFORE_SHARING.md"):
                continue  # generated by the packer, not present in exp_dir
            a, b = exp_dir / rel, unpacked_root / rel
            if not b.is_file() or not filecmp.cmp(a, b, shallow=False):
                raise LeaderboardError(f"unpacked file differs or is missing: {rel}")
    return bundle_path


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.appworld.leaderboard")
    sub = parser.add_subparsers(dest="cmd", required=True)
    default_toml = PROJECT_ROOT / "benchmarks" / "appworld" / "eval_config.toml"

    p = sub.add_parser("split-key", help="Write <key>_b1..bN batch keys into eval_config.toml")
    p.add_argument("key")
    p.add_argument("--batch-size", type=int, default=100)
    p.add_argument("--toml", type=Path, default=default_toml)

    p = sub.add_parser(
        "retry-key", help="Write a retry key (errored|failed|uncompleted) from workspace partials"
    )
    p.add_argument("kind", choices=RETRY_KINDS)
    p.add_argument("--bundle-dir", type=Path, required=True)
    p.add_argument("--of-key", default=None, help="Expected ids: a toml key (default: the workspace's split)")
    p.add_argument("--name", default=None)
    p.add_argument("--toml", type=Path, default=default_toml)
    p.add_argument("--root", type=Path, default=None)

    p = sub.add_parser("status", help="Completed/errored/score<1 counts from a workspace")
    p.add_argument("--bundle-dir", type=Path, required=True)
    p.add_argument("--root", type=Path, default=None)

    p = sub.add_parser("validate", help="Check an AppWorld experiment dir is submittable")
    p.add_argument("prefix")
    p.add_argument("--split", choices=SPLITS, required=True)
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--allow-low-interactions", action="store_true")

    p = sub.add_parser("evaluate", help="Run the official appworld evaluate and record TGC/SGC")
    p.add_argument("experiment_name")
    p.add_argument("--split", choices=SPLITS, default=None)
    p.add_argument("--key", default=None, help="toml key with task ids (instead of --split)")
    p.add_argument(
        "--bundle-dir", type=Path, default=None, help="also write results/appworld_official.json + report.md"
    )
    p.add_argument("--toml", type=Path, default=default_toml)
    p.add_argument("--root", type=Path, default=None)

    p = sub.add_parser("pack", help="validate + appworld pack + unpack verification for one split")
    p.add_argument("prefix")
    p.add_argument("--split", choices=SPLITS, required=True)
    p.add_argument("--method", required=True)
    p.add_argument("--method-tooltip", default="")
    p.add_argument("--llm", required=True)
    p.add_argument("--llm-tooltip", default="")
    p.add_argument("--url", required=True)
    p.add_argument("--allow-low-interactions", action="store_true")
    p.add_argument("--root", type=Path, default=None)

    args = parser.parse_args(argv)
    root = Path(args.root) if getattr(args, "root", None) else appworld_root()
    try:
        if args.cmd == "split-key":
            for name in split_key(args.toml, args.key, args.batch_size):
                print(name)
            return 0
        if args.cmd == "retry-key":
            if args.of_key:
                expected = read_toml_keys(args.toml)[args.of_key]
            else:
                stored = load_leaderboard_metadata(args.bundle_dir)
                if not stored:
                    raise LeaderboardError("no leaderboard block in workspace; pass --of-key")
                expected = load_split_ids(stored["split"], root)
            name, ids = write_retry_key(args.toml, args.bundle_dir, args.kind, expected, args.name)
            print(f"{name} = {json.dumps(ids)}")
            return 0
        if args.cmd == "status":
            print(format_status(workspace_status(args.bundle_dir, root)))
            return 0
        if args.cmd == "validate":
            rep = validate_experiment(
                outputs_dir(root) / appworld_experiment_name(args.prefix, args.split),
                load_split_ids(args.split, root),
                args.split,
            )
            print(rep.summary())
            return 0 if rep.ok(allow_low_interactions=args.allow_low_interactions) else 1
        if args.cmd == "evaluate":
            if bool(args.split) == bool(args.key):
                raise LeaderboardError("pass exactly one of --split / --key")
            ids = None if args.split else read_toml_keys(args.toml)[args.key]
            result = evaluate_official(args.experiment_name, root=root, split=args.split, task_ids=ids)
            table = official_table(result)
            print(format_official_table(table))
            if args.bundle_dir:
                write_official_results(
                    args.bundle_dir, table, split=args.split, task_ids_count=len(ids or [])
                )
            return 0
        if args.cmd == "pack":
            bundle = pack_and_verify(
                args.prefix,
                args.split,
                root=root,
                method=args.method,
                method_tooltip=args.method_tooltip,
                llm=args.llm,
                llm_tooltip=args.llm_tooltip,
                url=args.url,
                allow_low_interactions=args.allow_low_interactions,
            )
            print(f"Bundle verified: {bundle}")
            return 0
    except LeaderboardError as e:
        print(f"Error: {e}", file=sys.stderr)
        print(str(e))  # also on stdout so shell callers can show it
        return 1
    parser.error(f"unknown command {args.cmd!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(cli())
