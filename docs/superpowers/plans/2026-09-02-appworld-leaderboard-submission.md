# AppWorld Leaderboard Submission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `--sdk` AppWorld run on the full `test_normal` / `test_challenge` splits, driven batch-by-batch from `eval_config.toml`, resumable and retryable into ONE AppWorld experiment directory per split, ending in a validated `leaderboard.bundle` plus the official AppWorld TGC/SGC numbers.

**Architecture:** All new logic lives in one pure-Python module, `benchmarks/appworld/leaderboard.py`, exposed as `python -m benchmarks.appworld.leaderboard <subcommand>`. The SDK evaluator (`eval_appworld_sdk.py`) and `eval.sh` call into it for three decisions only: which AppWorld `experiment_name` to use, which ids to run, and what to write into the workspace `metadata.json`. `validate`/`evaluate`/`pack` are post-run commands over the AppWorld output directory. Nothing in the batch/retry flow needs new CLI selectors: the task list is always a key in `eval_config.toml`.

**Tech Stack:** Python 3.12+, `tomllib` (read) + text append (write, to keep the toml's comments), pytest (`unit` / `regression` markers), bash tests in the `test_model_config.sh` style, the `appworld` package (`appworld.evaluator`, `appworld.common.crypto`) behind `pytest.importorskip`.

**Spec:** `scratch/appworld-leaderboard-submission-issue.md` (issue draft; sections "User flow", "Proposed Solution", "Testing"). Note: the draft says `resume_history` gets `n_tasks`; the plan records `eval_key` only (the count is derivable from the toml, YAGNI).

## Global Constraints

- AppWorld experiment names: `^[a-z0-9_-]+$`, must end with `_test_normal` or `_test_challenge` (enforced by `appworld.leaderboard.prepare_metadata`). Prefix therefore: `^[a-z0-9_-]+$`.
- Split sizes: `test_normal` = 168 ids, `test_challenge` = 417 ids, read from `<APPWORLD_ROOT>/data/datasets/<split>.txt` (one id per line).
- 19 packed files per task: 12 app `dbs/<app>.jsonl` (`admin amazon api_docs file_system gmail phone simple_note splitwise spotify supervisor todoist venmo`) + `dbs/model_hashes.json` + `logs/environment_io.md` + `logs/api_calls.jsonl` + `version/code.txt` + `version/data.txt` + `evaluation/report.md` + `evaluation/version.txt`.
- `appworld pack` never fails on missing files: it prints `WARNING: Missing file path (...)` and says nothing about absent task dirs. Our wrapper must fail on either.
- Interaction logging for CUGA SDK paths (spec item 2) is done in-eval: after `world.close_all()`, `benchmarks/appworld/interaction_logs.py` copies `invoke_result.tool_calls` into `environment_io.md` / `api_calls.jsonl` without re-executing the APIs. `validate` still reports tasks with ≤1 interaction; `pack` refuses unless `--allow-low-interactions` is passed.
- cuga-viz "Failed = score == 0.0" fix is a **cuga-viz** change and is NOT in this plan; the harness's own `retry-key failed` covers it.
- Do not commit `uv.lock` or the `verify_check`/`reflection_ab` hunks already sitting uncommitted in `benchmarks/appworld/eval_config.toml` (they belong to another branch). Stage files explicitly; never `git add -A`.
- Run `just format` (ruff) before every commit.
- Existing conventions: partial results at `<bundle>/results/partial/<task>.json` with fields `task_name`, `success`, `error`, `match_rate`; completed = `_looks_completed()` in `benchmarks/helpers/incremental_results.py`.

---

## File map

| File | Responsibility |
|---|---|
| `benchmarks/appworld/leaderboard.py` (new) | Pure helpers + CLI: split ids, experiment naming, run planning (batch vs retry), toml key writing, validation, official evaluate, pack + verify, status. |
| `benchmarks/appworld/tests/test_leaderboard.py` (new) | Unit tests for everything above that needs no AppWorld package (tmp "appworld root" fixture). |
| `benchmarks/appworld/tests/test_leaderboard_integration.py` (new) | `regression` tests with the real `appworld` package: run stub tasks, merge, evaluate, pack, unpack, compare. |
| `benchmarks/appworld/tests/test_eval_sh_leaderboard.sh` (new) | Bash dry-run tests for flag plumbing in `eval.sh`. |
| `benchmarks/helpers/bundle.py` (`create_workspace_bundle`) | `resume_history` entries carry `eval_key`. |
| `benchmarks/appworld/eval_appworld_sdk.py` (`main`, `evaluate_all`) | Wire `--leaderboard`, `--force-retry`, multi `--task-id`, stored experiment name on resume, tracker folder into metadata. |
| `benchmarks/appworld/eval.sh` | Parse/forward the new flags, `--dry-run`, post-run official evaluate, `--status` delegation. |
| `benchmarks/appworld/pack_leaderboard.sh` (new) | validate → evaluate → pack → verify for both splits, print PR instructions. |
| `.claude/skills/appworld-leaderboard/SKILL.md` (new) | Skill that walks a Claude agent (and a human) through the batch/inspect/retry/pack flow. |
| `benchmarks/appworld/README.md` | Leaderboard section. |

---

### Task 1: Split ids, prefix validation, experiment name, split inference

**Files:**
- Create: `benchmarks/appworld/leaderboard.py`
- Create: `benchmarks/appworld/tests/test_leaderboard.py`

**Interfaces:**
- Produces:
  - `class LeaderboardError(Exception)`
  - `SPLITS: tuple[str, str] = ("test_normal", "test_challenge")`
  - `appworld_root(env: Mapping[str, str] | None = None) -> Path` — `APPWORLD_ROOT` or `benchmarks/appworld/appworld`.
  - `outputs_dir(root: Path) -> Path` — `root / "experiments" / "outputs"`.
  - `load_split_ids(split: str, root: Path) -> list[str]`
  - `validate_prefix(prefix: str) -> str`
  - `appworld_experiment_name(prefix: str, split: str) -> str`
  - `infer_split(task_ids: Iterable[str], root: Path) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# benchmarks/appworld/tests/test_leaderboard.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest benchmarks/appworld/tests/test_leaderboard.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'benchmarks.appworld.leaderboard'`

- [ ] **Step 3: Write the implementation**

```python
# benchmarks/appworld/leaderboard.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest benchmarks/appworld/tests/test_leaderboard.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
just format
git add benchmarks/appworld/leaderboard.py benchmarks/appworld/tests/test_leaderboard.py
git commit -m "feat(appworld): leaderboard helpers — split ids, prefix and experiment-name rules"
```

---

### Task 2: `eval_config.toml` batch keys and retry keys

**Files:**
- Modify: `benchmarks/appworld/leaderboard.py`
- Test: `benchmarks/appworld/tests/test_leaderboard.py`

**Interfaces:**
- Consumes: `LeaderboardError`, `load_split_ids` (Task 1).
- Produces:
  - `read_toml_keys(toml_path: Path) -> dict[str, list[str]]` — every top-level key whose value is a list of strings.
  - `base_id(task_id: str) -> str` — `"5238afc_2" -> "5238afc"`.
  - `batch_ids(ids: list[str], batch_size: int) -> list[list[str]]` — never splits a base across batches.
  - `write_toml_key(toml_path: Path, key: str, ids: list[str], comment: str) -> bool` — appends `# comment\nkey = [...]`; returns False (no-op) if the key exists with identical ids; raises if it exists with different ids.
  - `split_key(toml_path: Path, key: str, batch_size: int) -> list[str]` — writes `<key>_b1..bN`, returns the names.
  - `is_retry_key(key: str) -> bool`
  - `RETRY_KEY_SUFFIXES = ("_uncompleted_tasks", "_failed_tasks", "_uncompleted", "_failed", "_errored")`

- [ ] **Step 1: Write the failing tests**

```python
# append to benchmarks/appworld/tests/test_leaderboard.py

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest benchmarks/appworld/tests/test_leaderboard.py -q -k "toml or batch or split_key or retry_key or base_id"`
Expected: FAIL with `AttributeError: module ... has no attribute 'read_toml_keys'`

- [ ] **Step 3: Write the implementation**

```python
# add to benchmarks/appworld/leaderboard.py (after infer_split)
import json
import tomllib

RETRY_KEY_SUFFIXES = ("_uncompleted_tasks", "_failed_tasks", "_uncompleted", "_failed", "_errored")


def read_toml_keys(toml_path: Path) -> dict[str, list[str]]:
    with open(toml_path, "rb") as fh:
        data = tomllib.load(fh)
    return {
        k: [str(x) for x in v]
        for k, v in data.items()
        if isinstance(v, list) and v and all(isinstance(x, str) for x in v)
    }


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest benchmarks/appworld/tests/test_leaderboard.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
just format
git add benchmarks/appworld/leaderboard.py benchmarks/appworld/tests/test_leaderboard.py
git commit -m "feat(appworld): eval_config batch keys (split-key) and retry-key detection"
```

---

### Task 3: Validation of an AppWorld experiment directory

**Files:**
- Modify: `benchmarks/appworld/leaderboard.py`
- Test: `benchmarks/appworld/tests/test_leaderboard.py`

**Interfaces:**
- Consumes: `load_split_ids`, `outputs_dir`, `base_id`.
- Produces:
  - `APP_NAMES: tuple[str, ...]` (12 apps), `REQUIRED_TASK_FILES: tuple[str, ...]` (19 relative paths).
  - `count_interactions(env_io_path: Path) -> int` — number of `### Environment Interaction` headers.
  - `count_api_calls(api_calls_path: Path) -> int` — non-empty lines.
  - `@dataclass ValidationReport(split, expected, present, missing_tasks, missing_files: dict[str, list[str]], low_interaction_tasks: list[str], incomplete_bases: list[str])` with `ok(allow_low_interactions: bool = False) -> bool` and `summary() -> str`.
  - `validate_experiment(exp_dir: Path, split_ids: list[str], split: str) -> ValidationReport`

- [ ] **Step 1: Write the failing tests**

```python
# append to benchmarks/appworld/tests/test_leaderboard.py

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
    make_task_dir(exp, "fd1f8fa_2", interactions=1)          # low interactions
    make_task_dir(exp, "fd1f8fa_3")
    (exp / "tasks" / "fd1f8fa_3" / "dbs" / "gmail.jsonl").unlink()  # missing file
    make_task_dir(exp, "29a7b7e_1")                            # base 29a7b7e incomplete
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest benchmarks/appworld/tests/test_leaderboard.py -q -k "validate or required or count_"`
Expected: FAIL with `AttributeError ... REQUIRED_TASK_FILES`

- [ ] **Step 3: Write the implementation**

```python
# add to benchmarks/appworld/leaderboard.py
from dataclasses import dataclass, field

APP_NAMES: tuple[str, ...] = (
    "admin", "amazon", "api_docs", "file_system", "gmail", "phone",
    "simple_note", "splitwise", "spotify", "supervisor", "todoist", "venmo",
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
                "(pass --allow-low-interactions if the agent really made no API calls besides complete_task)"
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest benchmarks/appworld/tests/test_leaderboard.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
just format
git add benchmarks/appworld/leaderboard.py benchmarks/appworld/tests/test_leaderboard.py
git commit -m "feat(appworld): validate an AppWorld experiment dir against a leaderboard split"
```

---

### Task 4: Workspace metadata — `leaderboard` block and `eval_key` in `resume_history`

**Files:**
- Modify: `benchmarks/helpers/bundle.py` (`create_workspace_bundle`, around the `history.append(...)` line)
- Modify: `benchmarks/appworld/leaderboard.py`
- Test: `benchmarks/helpers/tests/test_bundle_workspace.py` (append), `benchmarks/appworld/tests/test_leaderboard.py` (append)

**Interfaces:**
- Produces:
  - `create_workspace_bundle(...)` history entries become `{"started_at", "model_profile", "eval_key"}`.
  - `store_leaderboard_metadata(bundle_dir: Path, *, prefix: str, split: str, appworld_experiment: str, tracker_folder: str | None = None) -> dict` — merges into `metadata.json["leaderboard"]`; raises `LeaderboardError` if a different prefix/split is already stored.
  - `load_leaderboard_metadata(bundle_dir: Path) -> dict | None`

- [ ] **Step 1: Write the failing tests**

```python
# append to benchmarks/helpers/tests/test_bundle_workspace.py
def test_resume_history_records_eval_key(tmp_path):
    from benchmarks.helpers.bundle import create_workspace_bundle

    create_workspace_bundle(tmp_path, "appworld", experiment_name="x", args={"eval_key": "b1"})
    create_workspace_bundle(tmp_path, "appworld", experiment_name="x", args={"eval_key": "b1_uncompleted_tasks"})
    meta = json.loads((tmp_path / "metadata.json").read_text())
    assert [h["eval_key"] for h in meta["resume_history"]] == ["b1", "b1_uncompleted_tasks"]
```

```python
# append to benchmarks/appworld/tests/test_leaderboard.py
def test_store_and_load_leaderboard_metadata(tmp_path):
    (tmp_path / "metadata.json").write_text(json.dumps({"experiment_name": "cuga_v1_chal"}))
    got = lb.store_leaderboard_metadata(
        tmp_path, prefix="cuga_v1", split="test_challenge", appworld_experiment="cuga_v1_test_challenge"
    )
    assert got == {"prefix": "cuga_v1", "split": "test_challenge", "appworld_experiment": "cuga_v1_test_challenge"}
    assert lb.load_leaderboard_metadata(tmp_path) == got
    # tracker folder is additive and overwrites the previous one
    lb.store_leaderboard_metadata(
        tmp_path, prefix="cuga_v1", split="test_challenge",
        appworld_experiment="cuga_v1_test_challenge", tracker_folder="b1_03-09--10h02m11s",
    )
    assert lb.load_leaderboard_metadata(tmp_path)["tracker_folder"] == "b1_03-09--10h02m11s"
    meta = json.loads((tmp_path / "metadata.json").read_text())
    assert meta["experiment_name"] == "cuga_v1_chal"  # untouched


def test_store_leaderboard_metadata_rejects_conflict(tmp_path):
    (tmp_path / "metadata.json").write_text("{}")
    lb.store_leaderboard_metadata(tmp_path, prefix="a", split="test_normal", appworld_experiment="a_test_normal")
    with pytest.raises(lb.LeaderboardError, match="already"):
        lb.store_leaderboard_metadata(tmp_path, prefix="b", split="test_normal", appworld_experiment="b_test_normal")


def test_load_leaderboard_metadata_none_when_absent(tmp_path):
    assert lb.load_leaderboard_metadata(tmp_path) is None
    (tmp_path / "metadata.json").write_text("{}")
    assert lb.load_leaderboard_metadata(tmp_path) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest benchmarks/helpers/tests/test_bundle_workspace.py benchmarks/appworld/tests/test_leaderboard.py -q -k "eval_key or leaderboard_metadata"`
Expected: FAIL (`KeyError: 'eval_key'`, `AttributeError ... store_leaderboard_metadata`)

- [ ] **Step 3: Write the implementation**

In `benchmarks/helpers/bundle.py`, `create_workspace_bundle`, replace
`history.append({"started_at": now, "model_profile": model_profile})` with:

```python
    history.append(
        {
            "started_at": now,
            "model_profile": model_profile,
            "eval_key": (args or {}).get("eval_key"),
        }
    )
```

In `benchmarks/appworld/leaderboard.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest benchmarks/helpers/tests/test_bundle_workspace.py benchmarks/appworld/tests/test_leaderboard.py -q`
Expected: all PASS (existing workspace tests included)

- [ ] **Step 5: Commit**

```bash
just format
git add benchmarks/helpers/bundle.py benchmarks/helpers/tests/test_bundle_workspace.py benchmarks/appworld/leaderboard.py benchmarks/appworld/tests/test_leaderboard.py
git commit -m "feat(appworld): persist leaderboard prefix/split/experiment in workspace metadata; record eval_key per resume"
```

---

### Task 5: Run planning — batch vs retry semantics, stored name on resume

**Files:**
- Modify: `benchmarks/appworld/leaderboard.py`
- Test: `benchmarks/appworld/tests/test_leaderboard.py`

**Interfaces:**
- Consumes: `infer_split`, `appworld_experiment_name`, `load_split_ids`, `is_retry_key`, `load_leaderboard_metadata`.
- Produces:
  - `@dataclass RunPlan(experiment_name: str, task_ids: list[str], skipped: list[str], split: str | None, prefix: str | None, mode: str)` — `mode` in `{"batch", "retry", "plain"}`.
  - `plan_run(*, task_ids: list[str], eval_key: str | None, leaderboard_prefix: str | None, bundle_dir: Path | None, completed_ids: set[str], force_retry: bool, root: Path, default_experiment_name: str) -> RunPlan`

Rules (from the spec):
1. No `--leaderboard` and no stored block → `mode="plain"`, `experiment_name=default_experiment_name`, skip `completed_ids` unless retry key / force.
2. `--leaderboard P` → `split=infer_split(ids)`, name `P_<split>`; if the workspace has a stored block, prefix/split must match (else `LeaderboardError`).
3. No `--leaderboard` but stored block → use stored `appworld_experiment`, and every id must belong to the stored split.
4. Retry key or `force_retry` → `mode="retry"`, run every id (ignore `completed_ids`); otherwise `mode="batch"`: skip ids in `completed_ids`.

- [ ] **Step 1: Write the failing tests**

```python
# append to benchmarks/appworld/tests/test_leaderboard.py
@pytest.fixture
def ws(tmp_path: Path) -> Path:
    w = tmp_path / "ws"
    w.mkdir()
    (w / "metadata.json").write_text("{}")
    return w


def test_plan_plain_run_skips_completed(root, ws):
    plan = lb.plan_run(
        task_ids=NORMAL[:3], eval_key="test_easy", leaderboard_prefix=None, bundle_dir=ws,
        completed_ids={NORMAL[0]}, force_retry=False, root=root, default_experiment_name="test_easy",
    )
    assert plan.mode == "plain"
    assert plan.experiment_name == "test_easy"
    assert plan.task_ids == NORMAL[1:3] and plan.skipped == [NORMAL[0]]


def test_plan_leaderboard_first_batch(root, ws):
    plan = lb.plan_run(
        task_ids=CHALLENGE[:3], eval_key="test_challenge_all_b1", leaderboard_prefix="cuga_v1",
        bundle_dir=ws, completed_ids=set(), force_retry=False, root=root, default_experiment_name="x",
    )
    assert plan.mode == "batch"
    assert plan.experiment_name == "cuga_v1_test_challenge"
    assert plan.split == "test_challenge" and plan.prefix == "cuga_v1"


def test_plan_resume_uses_stored_name_and_split(root, ws):
    lb.store_leaderboard_metadata(ws, prefix="cuga_v1", split="test_challenge", appworld_experiment="cuga_v1_test_challenge")
    plan = lb.plan_run(
        task_ids=CHALLENGE[3:], eval_key="test_challenge_all_b2", leaderboard_prefix=None,
        bundle_dir=ws, completed_ids=set(CHALLENGE[:3]), force_retry=False, root=root, default_experiment_name="x",
    )
    assert plan.experiment_name == "cuga_v1_test_challenge"
    assert plan.task_ids == CHALLENGE[3:]
    with pytest.raises(lb.LeaderboardError, match="not in test_challenge"):
        lb.plan_run(
            task_ids=NORMAL[:1], eval_key="oops", leaderboard_prefix=None, bundle_dir=ws,
            completed_ids=set(), force_retry=False, root=root, default_experiment_name="x",
        )


def test_plan_rejects_prefix_conflict(root, ws):
    lb.store_leaderboard_metadata(ws, prefix="cuga_v1", split="test_challenge", appworld_experiment="cuga_v1_test_challenge")
    with pytest.raises(lb.LeaderboardError, match="prefix"):
        lb.plan_run(
            task_ids=CHALLENGE[:3], eval_key="k", leaderboard_prefix="cuga_v2", bundle_dir=ws,
            completed_ids=set(), force_retry=False, root=root, default_experiment_name="x",
        )


def test_plan_retry_key_reruns_completed(root, ws):
    lb.store_leaderboard_metadata(ws, prefix="cuga_v1", split="test_challenge", appworld_experiment="cuga_v1_test_challenge")
    plan = lb.plan_run(
        task_ids=CHALLENGE[:2], eval_key="test_challenge_all_b1_03_09__10h02m11s_uncompleted_tasks",
        leaderboard_prefix=None, bundle_dir=ws, completed_ids=set(CHALLENGE), force_retry=False,
        root=root, default_experiment_name="x",
    )
    assert plan.mode == "retry" and plan.task_ids == CHALLENGE[:2] and plan.skipped == []


def test_plan_force_retry_on_batch_key(root, ws):
    plan = lb.plan_run(
        task_ids=NORMAL[:2], eval_key="test_normal_all_b1", leaderboard_prefix="cuga_v1", bundle_dir=ws,
        completed_ids=set(NORMAL), force_retry=True, root=root, default_experiment_name="x",
    )
    assert plan.mode == "retry" and plan.task_ids == NORMAL[:2]


def test_plan_no_bundle_dir_is_plain(root):
    plan = lb.plan_run(
        task_ids=NORMAL[:1], eval_key=None, leaderboard_prefix=None, bundle_dir=None,
        completed_ids=set(), force_retry=False, root=root, default_experiment_name="appworld_sdk_evaluation",
    )
    assert plan.mode == "plain" and plan.experiment_name == "appworld_sdk_evaluation"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest benchmarks/appworld/tests/test_leaderboard.py -q -k plan`
Expected: FAIL with `AttributeError ... plan_run`

- [ ] **Step 3: Write the implementation**

```python
# add to benchmarks/appworld/leaderboard.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest benchmarks/appworld/tests/test_leaderboard.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
just format
git add benchmarks/appworld/leaderboard.py benchmarks/appworld/tests/test_leaderboard.py
git commit -m "feat(appworld): plan_run — batch vs retry semantics and stored leaderboard experiment on resume"
```

---

### Task 6: Wire the evaluator (`eval_appworld_sdk.py`)

**Files:**
- Modify: `benchmarks/appworld/eval_appworld_sdk.py` — `AppWorldSdkEvaluator.__init__` (add `leaderboard_prefix`, `force_retry`), `evaluate_all` (use `plan_run`), `main()` (args, `--task-id nargs="+"`).
- Test: `benchmarks/helpers/tests/test_resume_integration.py` (append AST checks), `benchmarks/appworld/tests/test_leaderboard.py` (append).

**Interfaces:**
- Consumes: `plan_run`, `RunPlan`, `store_leaderboard_metadata`, `appworld_root`.
- Produces: evaluator CLI flags `--leaderboard <prefix>`, `--force-retry`, `--task-id ID [ID ...]`; `tracker.experiment_folder` written to `metadata.json["leaderboard"]["tracker_folder"]`; console line `[APPWORLD-SDK] cuga-viz experiment: <folder>`.

- [ ] **Step 1: Write the failing tests**

```python
# append to benchmarks/helpers/tests/test_resume_integration.py
@pytest.mark.regression
def test_appworld_evaluator_exposes_leaderboard_flags():
    source = (PROJECT_ROOT / EVAL_FILES["appworld"]).read_text()
    options = _argparse_option_strings(source)
    assert {"--leaderboard", "--force-retry"} <= options


@pytest.mark.regression
def test_appworld_task_id_accepts_many():
    source = (PROJECT_ROOT / EVAL_FILES["appworld"]).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args
            and getattr(node.args[0], "value", None) == "--task-id"
        ):
            kw = {k.arg: getattr(k.value, "value", None) for k in node.keywords}
            assert kw.get("nargs") == "+", "--task-id must accept several ids (eval.sh --task a b c)"
            return
    pytest.fail("--task-id argument not found")
```

```python
# append to benchmarks/appworld/tests/test_leaderboard.py
def test_evaluator_uses_plan_run_and_stores_metadata():
    """Static guard: the evaluator must route naming through plan_run and persist the block."""
    src = (Path(lb.PROJECT_ROOT) / "benchmarks" / "appworld" / "eval_appworld_sdk.py").read_text()
    assert "plan_run(" in src
    assert "store_leaderboard_metadata(" in src
    assert "tracker.experiment_folder" in src
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest benchmarks/helpers/tests/test_resume_integration.py benchmarks/appworld/tests/test_leaderboard.py -q -k "leaderboard_flags or task_id_accepts or uses_plan_run"`
Expected: 3 FAIL

- [ ] **Step 3: Implement**

In `eval_appworld_sdk.py`:

(a) Import, next to the other `benchmarks.` imports:
```python
from benchmarks.appworld.leaderboard import (
    LeaderboardError,
    appworld_root,
    plan_run,
    store_leaderboard_metadata,
)
```

(b) `AppWorldSdkEvaluator.__init__`: add parameters `leaderboard_prefix: Optional[str] = None, force_retry: bool = False` and store them (`self.leaderboard_prefix`, `self.force_retry`). Change `task_id: Optional[str]` to `task_ids: Optional[List[str]]` (rename attribute `self.task_ids`).

(c) `_task_ids_for_run`: change the first parameter to `task_ids: Optional[List[str]]` and `if task_ids: return list(task_ids), None`.

(d) `evaluate_all`, replace the block from `self.total_tasks = len(task_ids)` down to (but not including) `self.results = []` with:

```python
        plan = plan_run(
            task_ids=task_ids,
            eval_key=eval_group or self.eval_key,
            leaderboard_prefix=self.leaderboard_prefix,
            bundle_dir=self.bundle_dir,
            completed_ids=set(self.resume_completed_ids),
            force_retry=self.force_retry,
            root=appworld_root(),
            default_experiment_name=self.experiment_name,
        )
        self.experiment_name = plan.experiment_name
        logger.info(
            f"[APPWORLD-SDK] mode={plan.mode} experiment={plan.experiment_name} "
            f"run={len(plan.task_ids)} skip={len(plan.skipped)}"
        )
        if plan.mode == "retry":
            self.resume_completed_ids = set()
        # Total intended for this run; compared against len(self.results) so a
        # run that stops early (crash/interrupt) is detected as partial rather
        # than silently reported as complete.
        self.total_tasks = len(task_ids)
```

and, right after the existing `tracker.start_experiment(...)` call (which must now come AFTER the plan so it uses the final `self.experiment_name`), add:

```python
        logger.info(f"[APPWORLD-SDK] cuga-viz experiment: {tracker.experiment_folder}")
        if self.bundle_dir is not None and plan.split and plan.prefix:
            store_leaderboard_metadata(
                self.bundle_dir,
                prefix=plan.prefix,
                split=plan.split,
                appworld_experiment=plan.experiment_name,
                tracker_folder=tracker.experiment_folder,
            )
```

Move `tracker.start_experiment(...)` so the order is: resolve ids → level filter → `plan_run` → `tracker.start_experiment` → metadata → loop.

(e) In the loop, the skip check stays `if tid in self.resume_completed_ids` (already empty in retry mode).

(f) `main()`:
```python
    parser.add_argument("--task-id", nargs="+", default=None, help="Run one or more task IDs")
    parser.add_argument("--leaderboard", default=None, metavar="PREFIX",
                        help="Leaderboard mode: AppWorld experiment becomes <PREFIX>_<split>; "
                             "split inferred from the task ids; persisted in the workspace")
    parser.add_argument("--force-retry", action="store_true",
                        help="Re-run every listed task even if its partial result is clean")
```
Replace uses of `args.task_id` with `args.task_id` (now a list) and pass `task_ids=args.task_id`, `leaderboard_prefix=args.leaderboard`, `force_retry=args.force_retry` into the evaluator. The experiment-name default logic keeps its current shape but use `not args.task_id` (list truthiness). Wrap `evaluator.evaluate_all()` so a `LeaderboardError` logs `logger.error(f"Leaderboard: {e}")` and exits 3 before any task runs (it is raised inside `evaluate_all` before the loop, so nothing has been written).

- [ ] **Step 4: Run the tests**

Run: `uv run --no-sync pytest benchmarks/helpers/tests/test_resume_integration.py benchmarks/appworld/tests -q`
Expected: all PASS (the appworld-dependent tests skip if the package is absent)

- [ ] **Step 5: Smoke the CLI parse**

Run: `uv run --no-sync python -m benchmarks.appworld.eval_appworld_sdk --help | grep -E "leaderboard|force-retry|task-id"`
Expected: three lines listing the new flags.

- [ ] **Step 6: Commit**

```bash
just format
git add benchmarks/appworld/eval_appworld_sdk.py benchmarks/helpers/tests/test_resume_integration.py benchmarks/appworld/tests/test_leaderboard.py
git commit -m "feat(appworld): --leaderboard / --force-retry / multi --task-id in the SDK evaluator via plan_run"
```

---

### Task 7: Retry-key generation and `status` from workspace partials

**Files:**
- Modify: `benchmarks/appworld/leaderboard.py`
- Test: `benchmarks/appworld/tests/test_leaderboard.py`

**Interfaces:**
- Consumes: `read_toml_keys`, `write_toml_key`, `load_leaderboard_metadata`, `load_split_ids`; `benchmarks.helpers.incremental_results.load_all_partial_results`.
- Produces:
  - `retry_candidates(bundle_dir: Path, kind: str, expected_ids: list[str]) -> list[str]` — `kind` in `errored` (`error` not None), `failed` (`error` is None and `success` is not True), `uncompleted` (no partial at all).
  - `write_retry_key(toml_path: Path, bundle_dir: Path, kind: str, expected_ids: list[str], name: str | None = None) -> tuple[str, list[str]]` — key name defaults to `<bundle_dir.name>_<kind>`.
  - `workspace_status(bundle_dir: Path, root: Path) -> dict` — `{"experiment", "split", "expected", "completed", "errored", "score_below_1", "missing"}`; `expected` = split size when a leaderboard block exists, else number of partials.
  - `format_status(status: dict) -> str` — one line: `cuga_v1_chal  split=test_challenge  completed 100/417  errored 2  score<1: 31  missing 315`.

- [ ] **Step 1: Write the failing tests**

```python
# append to benchmarks/appworld/tests/test_leaderboard.py
from benchmarks.helpers import incremental_results as ir


def _seed_partials(ws: Path) -> None:
    ir.write_task_result(ws, NORMAL[0], {"task_name": NORMAL[0], "success": True, "error": None, "match_rate": 1.0})
    ir.write_task_result(ws, NORMAL[1], {"task_name": NORMAL[1], "success": False, "error": None, "match_rate": 0.4})
    ir.write_task_result(ws, NORMAL[2], {"task_name": NORMAL[2], "success": False, "error": "ReadTimeout", "match_rate": 0.0})


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
    lb.store_leaderboard_metadata(ws, prefix="cuga_v1", split="test_normal", appworld_experiment="cuga_v1_test_normal")
    _seed_partials(ws)
    st = lb.workspace_status(ws, root)
    assert st == {
        "experiment": "ws", "split": "test_normal", "expected": 6,
        "completed": 2, "errored": 1, "score_below_1": 1, "missing": 3,
    }
    line = lb.format_status(st)
    assert "completed 2/6" in line and "errored 1" in line and "score<1: 1" in line and "missing 3" in line


def test_workspace_status_plain(root, ws):
    _seed_partials(ws)
    st = lb.workspace_status(ws, root)
    assert st["split"] is None and st["expected"] == 3 and st["missing"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest benchmarks/appworld/tests/test_leaderboard.py -q -k "retry_candidates or write_retry_key or workspace_status"`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Write the implementation**

```python
# add to benchmarks/appworld/leaderboard.py
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
        t for t in expected_ids
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest benchmarks/appworld/tests/test_leaderboard.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
just format
git add benchmarks/appworld/leaderboard.py benchmarks/appworld/tests/test_leaderboard.py
git commit -m "feat(appworld): retry-key generation from workspace partials and leaderboard status"
```

---

### Task 8: Official evaluate (TGC/SGC via `appworld.evaluator`)

**Files:**
- Modify: `benchmarks/appworld/leaderboard.py`
- Test: `benchmarks/appworld/tests/test_leaderboard.py` (unit with a fake runner), `benchmarks/appworld/tests/test_leaderboard_integration.py` (Task 10 exercises the real path)

**Interfaces:**
- Produces:
  - `official_table(evaluation_dict: dict) -> dict` — `{"aggregate": {"task_goal_completion", "scenario_goal_completion"}, "difficulty_1": {...}, "difficulty_2": {...}, "difficulty_3": {...}}` built with `appworld.evaluator.Metric.build_report` (import inside the function).
  - `evaluate_official(experiment_name: str, *, root: Path, split: str | None = None, task_ids: list[str] | None = None, runner: Callable[..., dict] | None = None) -> dict` — with `split`, calls `appworld.evaluator.evaluate_dataset(experiment_name, split, include_details=True, aggregate_only=False, save_reports=True, print_report=False)` (this writes `evaluations/<split>.json|.txt`, required by `appworld make`); with `task_ids`, calls `appworld.evaluator.evaluate_tasks(task_ids, experiment_name, save_reports=False)`. Sets `APPWORLD_ROOT` via `appworld.common.path_store.path_store.update_root(str(root))` first. `runner` overrides the appworld call for tests.
  - `write_official_results(bundle_dir: Path, table: dict, *, split: str | None, task_ids_count: int) -> Path` — writes `<bundle>/results/appworld_official.json` and appends/replaces an `## AppWorld official metrics` section in `<bundle>/report.md` (creates the file if missing).
  - `format_official_table(table: dict) -> str` — the 5-line text table used in the spec.

- [ ] **Step 1: Write the failing tests**

```python
# append to benchmarks/appworld/tests/test_leaderboard.py
FAKE_EVAL = {
    "aggregate": {"task_goal_completion": 50.0, "scenario_goal_completion": 25.0},
    "individual": {
        "a_1": {"difficulty": 1, "success": True}, "a_2": {"difficulty": 1, "success": False},
    },
}


def test_evaluate_official_uses_runner_and_root(tmp_path):
    seen = {}

    def runner(**kw):
        seen.update(kw)
        return FAKE_EVAL

    out = lb.evaluate_official("cuga_v1_test_normal", root=tmp_path, task_ids=["a_1", "a_2"], runner=runner)
    assert out is FAKE_EVAL
    assert seen == {"experiment_name": "cuga_v1_test_normal", "root": tmp_path, "split": None, "task_ids": ["a_1", "a_2"]}
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest benchmarks/appworld/tests/test_leaderboard.py -q -k "official"`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Write the implementation**

```python
# add to benchmarks/appworld/leaderboard.py
from collections.abc import Callable

OFFICIAL_SECTION = "## AppWorld official metrics"
_ROWS = ("aggregate", "difficulty_1", "difficulty_2", "difficulty_3")
_COLS = ("task_goal_completion", "scenario_goal_completion")


def _appworld_runner(*, experiment_name: str, root: Path, split: str | None, task_ids: list[str] | None) -> dict:
    from appworld.common.path_store import path_store
    from appworld.evaluator import evaluate_dataset, evaluate_tasks

    path_store.update_root(str(root))
    if split:
        return evaluate_dataset(
            experiment_name, split, include_details=True, aggregate_only=False,
            save_reports=True, print_report=False,
        )
    return evaluate_tasks(task_ids or [], experiment_name=experiment_name, include_details=True, save_reports=False)


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
    if OFFICIAL_SECTION in text:
        text = text.split(OFFICIAL_SECTION, 1)[0].rstrip() + "\n"
    section = (
        f"\n{OFFICIAL_SECTION}\n\n"
        f"scope: {'split ' + split if split else f'{task_ids_count} task ids'}\n\n"
        f"```\n{format_official_table(table)}\n```\n"
    )
    report.write_text(text.rstrip() + "\n" + section)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest benchmarks/appworld/tests/test_leaderboard.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
just format
git add benchmarks/appworld/leaderboard.py benchmarks/appworld/tests/test_leaderboard.py
git commit -m "feat(appworld): official TGC/SGC via appworld.evaluator, written into the workspace report"
```

---

### Task 9: Pack with verification, and the CLI

**Files:**
- Modify: `benchmarks/appworld/leaderboard.py` (add `pack_and_verify`, `cli`, `__main__`)
- Test: `benchmarks/appworld/tests/test_leaderboard.py`

**Interfaces:**
- Produces:
  - `pack_and_verify(prefix: str, split: str, *, root: Path, method: str, method_tooltip: str, llm: str, llm_tooltip: str, url: str, allow_low_interactions: bool = False, packer: Callable[..., str] | None = None, unpacker: Callable[[Path, Path], list[str]] | None = None) -> Path` — runs `validate_experiment` (raises unless ok), then `packer(...)` which returns the captured stdout of `appworld.leaderboard.pack_experiment`; raises on any `WARNING: Missing file path`; unpacks into a temp dir with `unpacker(bundle_path, tmp_dir)` and asserts exactly `len(split_ids) * 19 + 1` files (`metadata.json`) plus `LICENSE` and `README_BEFORE_SHARING.md` (added by `pack_bundle`), byte-identical (`filecmp.cmp(shallow=False)`) to the source files; returns the bundle path.
  - Default `packer` uses `contextlib.redirect_stdout` around `appworld.leaderboard.pack_experiment(...)` after `path_store.update_root(root)`. Default `unpacker` uses `appworld.common.crypto.unpack_bundle(bundle_file_path, base_directory, PASSWORD, SALT)` with the constants from `appworld.common.constants`.
  - `cli(argv) -> int` with subcommands: `split-key`, `retry-key`, `status`, `validate`, `evaluate`, `pack`.

- [ ] **Step 1: Write the failing tests**

```python
# append to benchmarks/appworld/tests/test_leaderboard.py
import filecmp
import shutil


def _fake_packer_factory(root: Path, warn: bool = False):
    """Simulate appworld pack: copy the 19 files per task + metadata.json into a 'bundle' dir."""

    def packer(*, experiment_name, dataset_name, method_name, method_tooltip, llm_name, llm_tooltip, url, root):
        exp = lb.outputs_dir(root) / experiment_name
        (exp / "metadata.json").write_text(json.dumps({"dataset": dataset_name, "method": {"name": method_name}}))
        staging = root / "_staging" / experiment_name
        if staging.exists():
            shutil.rmtree(staging)
        for t in (exp / "tasks").iterdir():
            for rel in lb.REQUIRED_TASK_FILES:
                src = t / rel
                if src.is_file():
                    dst = staging / "tasks" / t.name / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
        shutil.copy2(exp / "metadata.json", staging / "metadata.json")
        (staging / "LICENSE").write_text("license")
        (staging / "README_BEFORE_SHARING.md").write_text("readme")
        (exp / "leaderboard.bundle").write_text(str(staging))
        return "WARNING: Missing file path (x)\n" if warn else f"Leaderboard bundle ready at '{exp / 'leaderboard.bundle'}'.\n"

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
    bundle = lb.pack_and_verify(
        "cuga_v1", "test_normal", root=root, method="CUGA", method_tooltip="lite", llm="gpt", llm_tooltip="", url="u",
        packer=_fake_packer_factory(root), unpacker=_fake_unpacker,
    )
    assert bundle == exp / "leaderboard.bundle"


def test_pack_refuses_incomplete_experiment(root):
    exp = lb.outputs_dir(root) / "cuga_v1_test_normal"
    for tid in NORMAL[:3]:
        make_task_dir(exp, tid)
    with pytest.raises(lb.LeaderboardError, match="NOT SUBMITTABLE"):
        lb.pack_and_verify(
            "cuga_v1", "test_normal", root=root, method="m", method_tooltip="", llm="l", llm_tooltip="", url="u",
            packer=_fake_packer_factory(root), unpacker=_fake_unpacker,
        )


def test_pack_refuses_low_interactions_unless_allowed(root):
    exp = lb.outputs_dir(root) / "cuga_v1_test_normal"
    for tid in NORMAL:
        make_task_dir(exp, tid, interactions=1)
    kw = dict(root=root, method="m", method_tooltip="", llm="l", llm_tooltip="", url="u",
              packer=_fake_packer_factory(root), unpacker=_fake_unpacker)
    with pytest.raises(lb.LeaderboardError, match="interaction"):
        lb.pack_and_verify("cuga_v1", "test_normal", **kw)
    assert lb.pack_and_verify("cuga_v1", "test_normal", allow_low_interactions=True, **kw).is_file()


def test_pack_fails_on_appworld_warning(root):
    exp = lb.outputs_dir(root) / "cuga_v1_test_normal"
    for tid in NORMAL:
        make_task_dir(exp, tid)
    with pytest.raises(lb.LeaderboardError, match="Missing file path"):
        lb.pack_and_verify(
            "cuga_v1", "test_normal", root=root, method="m", method_tooltip="", llm="l", llm_tooltip="", url="u",
            packer=_fake_packer_factory(root, warn=True), unpacker=_fake_unpacker,
        )


def test_pack_detects_unpack_mismatch(root):
    exp = lb.outputs_dir(root) / "cuga_v1_test_normal"
    for tid in NORMAL:
        make_task_dir(exp, tid)

    def bad_unpacker(bundle_path, dest):
        names = _fake_unpacker(bundle_path, dest)
        (dest / "cuga_v1_test_normal" / "tasks" / NORMAL[0] / "dbs" / "gmail.jsonl").write_text("tampered")
        return names

    with pytest.raises(lb.LeaderboardError, match="differs"):
        lb.pack_and_verify(
            "cuga_v1", "test_normal", root=root, method="m", method_tooltip="", llm="l", llm_tooltip="", url="u",
            packer=_fake_packer_factory(root), unpacker=bad_unpacker,
        )


def test_cli_split_key_and_status(root, toml_path, ws, capsys):
    assert lb.cli(["split-key", "test_normal_all", "--batch-size", "3", "--toml", str(toml_path)]) == 0
    assert "test_normal_all_b2" in capsys.readouterr().out
    lb.store_leaderboard_metadata(ws, prefix="cuga_v1", split="test_normal", appworld_experiment="cuga_v1_test_normal")
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest benchmarks/appworld/tests/test_leaderboard.py -q -k "pack or cli_"`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Write the implementation**

```python
# add to benchmarks/appworld/leaderboard.py
import argparse
import contextlib
import filecmp
import io
import sys
import tempfile

PACKED_EXTRA_FILES = ("metadata.json", "LICENSE", "README_BEFORE_SHARING.md")


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

    return unpack_bundle(bundle_file_path=str(bundle_path), base_directory=str(dest), password=PASSWORD, salt=SALT)


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
        raise LeaderboardError(report.summary() + ("" if report.ok(True) else "\nNOT SUBMITTABLE"))

    out = (packer or _appworld_packer)(
        experiment_name=experiment_name, dataset_name=split, method_name=method,
        method_tooltip=method_tooltip, llm_name=llm, llm_tooltip=llm_tooltip, url=url, root=root,
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
        expected = len(split_ids) * len(REQUIRED_TASK_FILES) + len(PACKED_EXTRA_FILES)
        if len(names) != expected:
            raise LeaderboardError(f"bundle has {len(names)} files, expected {expected}")
        unpacked_root = dest / experiment_name
        for tid in split_ids:
            for rel in REQUIRED_TASK_FILES:
                a, b = exp_dir / "tasks" / tid / rel, unpacked_root / "tasks" / tid / rel
                if not b.is_file() or not filecmp.cmp(a, b, shallow=False):
                    raise LeaderboardError(f"unpacked file differs or is missing: tasks/{tid}/{rel}")
    return bundle_path


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.appworld.leaderboard")
    sub = parser.add_subparsers(dest="cmd", required=True)
    default_toml = PROJECT_ROOT / "benchmarks" / "appworld" / "eval_config.toml"

    p = sub.add_parser("split-key", help="Write <key>_b1..bN batch keys into eval_config.toml")
    p.add_argument("key")
    p.add_argument("--batch-size", type=int, default=100)
    p.add_argument("--toml", type=Path, default=default_toml)

    p = sub.add_parser("retry-key", help="Write a retry key (errored|failed|uncompleted) from workspace partials")
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
    p.add_argument("--bundle-dir", type=Path, default=None, help="also write results/appworld_official.json + report.md")
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
                load_split_ids(args.split, root), args.split,
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
                write_official_results(args.bundle_dir, table, split=args.split, task_ids_count=len(ids or []))
            return 0
        if args.cmd == "pack":
            bundle = pack_and_verify(
                args.prefix, args.split, root=root, method=args.method, method_tooltip=args.method_tooltip,
                llm=args.llm, llm_tooltip=args.llm_tooltip, url=args.url,
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest benchmarks/appworld/tests/test_leaderboard.py -q`
Expected: all PASS

- [ ] **Step 5: Smoke the CLI against the real clone**

Run: `uv run --no-sync python -m benchmarks.appworld.leaderboard validate test_easy_placeholder --split test_normal; echo "exit=$?"`
Expected: prints `test_normal: 0/168 task dirs present`, `missing tasks (168): ...`, `NOT SUBMITTABLE`, `exit=1`.

- [ ] **Step 6: Commit**

```bash
just format
git add benchmarks/appworld/leaderboard.py benchmarks/appworld/tests/test_leaderboard.py
git commit -m "feat(appworld): pack_and_verify (validate → appworld pack → unpack + byte compare) and the leaderboard CLI"
```

---

### Task 10: Integration tests with the real `appworld` package (no LLM)

**Files:**
- Create: `benchmarks/appworld/tests/test_leaderboard_integration.py`

**Interfaces:**
- Consumes: `evaluate_official`, `official_table`, `pack_and_verify`, `validate_experiment`, `REQUIRED_TASK_FILES`, `store_leaderboard_metadata`, `plan_run`; `appworld.AppWorld` (local, in-process), `appworld.task.load_task_ids`.

These tests run tasks locally in-process (no `remote_environment_url`), which needs the downloaded data under `benchmarks/appworld/appworld/data`. They are marked `regression` and skip when the package or data is missing. They use the `train` split ids because `appworld.leaderboard.prepare_metadata` accepts `train` as a dataset name, so the real `pack_experiment` can be exercised without a full test split.

- [ ] **Step 1: Write the tests**

```python
# benchmarks/appworld/tests/test_leaderboard_integration.py
"""Merge → evaluate → pack → unpack with the real appworld package (no LLM).

A stub 'agent' completes each task through world.execute(); the point is the
plumbing: one experiment dir, task dirs recreated in place on retry, official
metrics computed, bundle verified byte-for-byte.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

appworld = pytest.importorskip("appworld", reason="AppWorld not installed; run ./setup_appworld.sh")
from appworld import AppWorld  # noqa: E402
from appworld.common.path_store import path_store  # noqa: E402
from appworld.task import load_task_ids  # noqa: E402

from benchmarks.appworld import leaderboard as lb  # noqa: E402

pytestmark = pytest.mark.regression

ROOT = lb.appworld_root()
if not (ROOT / "data" / "tasks").is_dir():
    pytest.skip("AppWorld data not downloaded", allow_module_level=True)

EXPERIMENT = "citest_train"


@pytest.fixture(scope="module")
def train_ids() -> list[str]:
    path_store.update_root(str(ROOT))
    ids = load_task_ids("train")
    bases: dict[str, list[str]] = {}
    for t in ids:
        bases.setdefault(lb.base_id(t), []).append(t)
    picked = [t for b in list(bases)[:2] for t in sorted(bases[b])]  # 2 bases x 3 scenarios
    assert len(picked) == 6
    return picked


@pytest.fixture(autouse=True, scope="module")
def clean_experiment():
    exp = lb.outputs_dir(ROOT) / EXPERIMENT
    shutil.rmtree(exp, ignore_errors=True)
    yield
    shutil.rmtree(exp, ignore_errors=True)


def run_stub(task_id: str, marker: str, succeed: bool = True) -> None:
    """Complete one task in-process the way the SDK evaluator finishes a task."""
    with AppWorld(task_id=task_id, experiment_name=EXPERIMENT) as world:
        world.execute(f"print({marker!r})")
        status = "success" if succeed else "fail"
        world.execute(f"apis.supervisor.complete_task(status={status!r})")
        world.evaluate()


def test_batches_and_retry_merge_into_one_experiment(train_ids):
    b1, b2 = train_ids[:3], train_ids[3:]
    for t in b1:
        run_stub(t, "first")
    for t in b2:
        run_stub(t, "first")
    run_stub(b1[0], "second")  # retry overwrites in place
    exp = lb.outputs_dir(ROOT) / EXPERIMENT
    rep = lb.validate_experiment(exp, train_ids, "test_normal")
    assert rep.missing_tasks == [] and rep.missing_files == {} and rep.incomplete_bases == []
    io_md = (exp / "tasks" / b1[0] / "logs" / "environment_io.md").read_text()
    assert "second" in io_md and "first" not in io_md
    assert lb.count_interactions(exp / "tasks" / b1[0] / "logs" / "environment_io.md") == 2


def test_official_evaluate_reports_tgc_and_sgc(train_ids):
    for t in train_ids:
        run_stub(t, "m")
    result = lb.evaluate_official(EXPERIMENT, root=ROOT, task_ids=train_ids)
    table = lb.official_table(result)
    agg = table["aggregate"]
    assert set(agg) == {"task_goal_completion", "scenario_goal_completion"}
    assert agg["scenario_goal_completion"] <= agg["task_goal_completion"]
    # break one scenario of base 1 → SGC for that base drops to 0, TGC by one task
    run_stub(train_ids[1], "m", succeed=False)
    table2 = lb.official_table(lb.evaluate_official(EXPERIMENT, root=ROOT, task_ids=train_ids))
    assert table2["aggregate"]["task_goal_completion"] < agg["task_goal_completion"]
    assert table2["aggregate"]["scenario_goal_completion"] < agg["scenario_goal_completion"]


def test_pack_roundtrip_with_real_appworld(train_ids, monkeypatch):
    for t in train_ids:
        run_stub(t, "m")
    # pack_and_verify validates against a split; for the train subset we call the pieces directly
    from appworld.leaderboard import pack_experiment
    import contextlib, io

    path_store.update_root(str(ROOT))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pack_experiment(
            experiment_name=EXPERIMENT, dataset_name="train", method_name="ci", method_tooltip="",
            llm_name="stub", llm_tooltip="", url="https://example.invalid",
        )
    assert "WARNING: Missing file path" not in buf.getvalue()
    bundle = lb.outputs_dir(ROOT) / EXPERIMENT / "leaderboard.bundle"
    assert bundle.is_file()

    import filecmp
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        names = lb._appworld_unpacker(bundle, Path(tmp))
        task_files = [n for n in names if "/tasks/" in n]
        assert len(task_files) == len(train_ids) * len(lb.REQUIRED_TASK_FILES)
        for t in train_ids:
            for rel in lb.REQUIRED_TASK_FILES:
                a = lb.outputs_dir(ROOT) / EXPERIMENT / "tasks" / t / rel
                b = Path(tmp) / EXPERIMENT / "tasks" / t / rel
                assert filecmp.cmp(a, b, shallow=False), rel


def test_rename_after_pack_is_detected(train_ids):
    for t in train_ids[:3]:
        run_stub(t, "m")
    from appworld.leaderboard import pack_experiment, unpack_experiment
    import contextlib, io

    path_store.update_root(str(ROOT))
    with contextlib.redirect_stdout(io.StringIO()):
        pack_experiment(
            experiment_name=EXPERIMENT, dataset_name="train", method_name="ci", method_tooltip="",
            llm_name="stub", llm_tooltip="", url="https://example.invalid",
        )
    exp = lb.outputs_dir(ROOT) / EXPERIMENT
    renamed = exp.with_name("renamed_train")
    shutil.move(exp, renamed)
    try:
        with pytest.raises(Exception, match="renamed the bundled experiment"):
            unpack_experiment("renamed_train")
    finally:
        shutil.rmtree(renamed, ignore_errors=True)
```

- [ ] **Step 2: Run the tests**

Run: `uv run --no-sync pytest benchmarks/appworld/tests/test_leaderboard_integration.py -q -x`
Expected: 4 PASS (or 4 SKIP on a machine without the appworld data). If `AppWorld(...)` in-process needs a local API server, the first test will raise; in that case add `remote_apis_url=None` explicitly and re-run; do not mark the test as skipped to get green.

- [ ] **Step 3: Commit**

```bash
just format
git add benchmarks/appworld/tests/test_leaderboard_integration.py
git commit -m "test(appworld): merge/evaluate/pack/unpack integration tests against the real appworld package"
```

---

### Task 11: `eval.sh` plumbing, `--dry-run`, post-run official evaluate, `--status`

**Files:**
- Modify: `benchmarks/appworld/eval.sh`
- Create: `benchmarks/appworld/tests/test_eval_sh_leaderboard.sh`

**Interfaces:**
- Consumes: CLI `python -m benchmarks.appworld.leaderboard status|evaluate` (Task 9); evaluator flags (Task 6).
- Produces: `eval.sh --leaderboard <prefix>`, `--force-retry`, `--dry-run` (prints `DISPATCH: <command>` and exits 0 before servers start), `--status` prints the leaderboard status line when the workspace has a leaderboard block; after a leaderboard run, `eval.sh` runs `leaderboard evaluate <appworld_experiment> --key <EVAL_KEY> --bundle-dir <ws>`.

- [ ] **Step 1: Write the failing shell tests**

```bash
#!/usr/bin/env bash
# benchmarks/appworld/tests/test_eval_sh_leaderboard.sh
# Dry-run tests for eval.sh flag plumbing. Run: bash benchmarks/appworld/tests/test_eval_sh_leaderboard.sh
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVAL="$SCRIPT_DIR/../eval.sh"
PASS=0; FAIL=0
assert_contains() { if [[ "$3" == *"$2"* ]]; then echo "  PASS: $1"; PASS=$((PASS+1)); else echo "  FAIL: $1"; echo "    want: $2"; echo "    got:  $3"; FAIL=$((FAIL+1)); fi; }
assert_not_contains() { if [[ "$3" != *"$2"* ]]; then echo "  PASS: $1"; PASS=$((PASS+1)); else echo "  FAIL: $1"; echo "    unexpected: $2"; echo "    got: $3"; FAIL=$((FAIL+1)); fi; }

echo "eval.sh --dry-run"
out=$(bash "$EVAL" --sdk --dry-run --leaderboard cuga_v1 --eval-key test_challenge_all_b1 2>&1)
assert_contains "dispatches the SDK evaluator" "benchmarks.appworld.eval_appworld_sdk" "$out"
assert_contains "forwards --leaderboard" "--leaderboard cuga_v1" "$out"
assert_contains "forwards --eval-key" "--eval-key test_challenge_all_b1" "$out"
assert_not_contains "does not start servers" "Starting AppWorld" "$out"

out=$(bash "$EVAL" --sdk --dry-run --task a_1 b_2 c_3 2>&1)
assert_contains "forwards several task ids" "--task-id a_1 b_2 c_3" "$out"

out=$(bash "$EVAL" --sdk --dry-run --force-retry --eval-key k 2>&1)
assert_contains "forwards --force-retry" "--force-retry" "$out"

out=$(bash "$EVAL" --dry-run --leaderboard cuga_v1 --eval-key k 2>&1)
assert_contains "leaderboard implies --sdk" "eval_appworld_sdk" "$out"

echo; echo "passed=$PASS failed=$FAIL"
[[ $FAIL -eq 0 ]]
```

- [ ] **Step 2: Run to verify it fails**

Run: `bash benchmarks/appworld/tests/test_eval_sh_leaderboard.sh`
Expected: FAIL lines (no `--dry-run`, servers would start; the script's `set -e` path may print startup text)

- [ ] **Step 3: Implement in `eval.sh`**

(a) In the arg loop add:
```bash
        --leaderboard) LEADERBOARD="$2"; PASSTHROUGH_ARGS+=(--leaderboard "$2"); USE_SDK=true; shift 2 ;;
        --force-retry) PASSTHROUGH_ARGS+=(--force-retry); shift ;;
        --dry-run)     DRY_RUN=true; shift ;;
```
and extend the `--help` text with the three flags plus `--status` semantics.

(b) Immediately after the loop (before `handle_eval_lifecycle`):
```bash
if [[ "${DRY_RUN:-false}" == "true" ]]; then
    if [ "${AGENT:-cuga}" = "codeact" ]; then mod=benchmarks.appworld.appworld_eval_codeact
    elif [ "${AGENT:-cuga}" = "react" ]; then mod=benchmarks.appworld.appworld_eval_react
    elif [[ "$USE_SDK" == "true" ]]; then mod=benchmarks.appworld.eval_appworld_sdk
    else mod=benchmarks.appworld.appworld_eval; fi
    echo "DISPATCH: uv run --no-sync python -m $mod ${PASSTHROUGH_ARGS[*]}"
    exit 0
fi
```

(c) `--status`: before `handle_eval_lifecycle`, when `STATUS=true`, resolve the bundle dir and, if `metadata.json` has a `leaderboard` block, print the leaderboard line first:
```bash
if [[ "${STATUS:-false}" == "true" ]]; then
    if bd=$(resolve_lifecycle_bundle_dir "appworld" 2>/dev/null) && grep -q '"leaderboard"' "$bd/metadata.json" 2>/dev/null; then
        uv run --no-sync python -m benchmarks.appworld.leaderboard status --bundle-dir "$bd"
    fi
fi
```
(then fall through to the existing `handle_eval_lifecycle`, which prints the generic status).

(d) After the evaluator exits with code 0 and `WORKSPACE_BUNDLE_DIR` is set, before `finalize_experiment_workspace`:
```bash
if [ $EVAL_EXIT -eq 0 ] && [ -n "${WORKSPACE_BUNDLE_DIR:-}" ] && grep -q '"leaderboard"' "$WORKSPACE_BUNDLE_DIR/metadata.json" 2>/dev/null; then
    AW_EXP=$(uv run --no-sync python -c "import json,sys;print(json.load(open(sys.argv[1]))['leaderboard']['appworld_experiment'])" "$WORKSPACE_BUNDLE_DIR/metadata.json")
    if [[ -n "${EVAL_KEY:-}" ]]; then
        echo -e "${YELLOW:-}Official AppWorld evaluate for key ${EVAL_KEY}...${NC:-}"
        uv run --no-sync python -m benchmarks.appworld.leaderboard evaluate "$AW_EXP" --key "$EVAL_KEY" --bundle-dir "$WORKSPACE_BUNDLE_DIR" || echo -e "${YELLOW:-}Warning: official evaluate failed (see above)${NC:-}"
    fi
fi
```
Note `AppWorld.close_all()` is not needed: the evaluator process has exited, so the cached DB handler in this new process is empty.

- [ ] **Step 4: Run the shell tests and the existing helper shell tests**

Run: `bash benchmarks/appworld/tests/test_eval_sh_leaderboard.sh && bash benchmarks/helpers/tests/test_model_config.sh | tail -2`
Expected: `passed=7 failed=0`; helper tests unchanged.

- [ ] **Step 5: Commit**

```bash
git add benchmarks/appworld/eval.sh benchmarks/appworld/tests/test_eval_sh_leaderboard.sh
git commit -m "feat(appworld): eval.sh --leaderboard/--force-retry/--dry-run, leaderboard status, post-run official evaluate"
```

---

### Task 12: `pack_leaderboard.sh`

**Files:**
- Create: `benchmarks/appworld/pack_leaderboard.sh`
- Test: append to `benchmarks/appworld/tests/test_eval_sh_leaderboard.sh`

**Interfaces:**
- Consumes: `python -m benchmarks.appworld.leaderboard validate|evaluate|pack`.
- Produces: `./benchmarks/appworld/pack_leaderboard.sh <prefix> "<method>" "<method tooltip>" "<llm>" "<llm tooltip>" <url> [--allow-low-interactions] [--only test_normal|test_challenge]`; on success prints the two bundle paths and the `/add-to-leaderboard` comment.

- [ ] **Step 1: Write the failing test**

```bash
# append to benchmarks/appworld/tests/test_eval_sh_leaderboard.sh (before the summary lines)
echo "pack_leaderboard.sh"
PACK="$SCRIPT_DIR/../pack_leaderboard.sh"
out=$(bash "$PACK" 2>&1); rc=$?
assert_contains "usage on missing args" "Usage:" "$out"
[[ $rc -ne 0 ]] && { echo "  PASS: non-zero exit"; PASS=$((PASS+1)); } || { echo "  FAIL: exit 0"; FAIL=$((FAIL+1)); }
out=$(bash "$PACK" nope_prefix "m" "" "l" "" https://x --only test_normal 2>&1); rc=$?
assert_contains "validate runs first and reports" "task dirs present" "$out"
[[ $rc -ne 0 ]] && { echo "  PASS: refuses incomplete"; PASS=$((PASS+1)); } || { echo "  FAIL: packed incomplete"; FAIL=$((FAIL+1)); }
```

- [ ] **Step 2: Run to verify it fails**

Run: `bash benchmarks/appworld/tests/test_eval_sh_leaderboard.sh`
Expected: FAIL (script missing)

- [ ] **Step 3: Write the script**

```bash
#!/bin/bash
# Validate, officially evaluate, pack and verify both AppWorld leaderboard splits.
# Usage: ./pack_leaderboard.sh <prefix> "<method>" "<method tooltip>" "<llm>" "<llm tooltip>" <url> [--allow-low-interactions] [--only SPLIT]
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

if [[ $# -lt 6 ]]; then
    echo "Usage: $0 <prefix> \"<method>\" \"<method tooltip>\" \"<llm>\" \"<llm tooltip>\" <url> [--allow-low-interactions] [--only test_normal|test_challenge]" >&2
    exit 2
fi
PREFIX="$1"; METHOD="$2"; METHOD_TIP="$3"; LLM="$4"; LLM_TIP="$5"; URL="$6"; shift 6
EXTRA=(); SPLITS=(test_normal test_challenge)
while [[ $# -gt 0 ]]; do
    case "$1" in
        --allow-low-interactions) EXTRA+=(--allow-low-interactions); shift ;;
        --only) SPLITS=("$2"); shift 2 ;;
        *) echo "unknown flag $1" >&2; exit 2 ;;
    esac
done

LB=(uv run --no-sync python -m benchmarks.appworld.leaderboard)
BUNDLES=()
for split in "${SPLITS[@]}"; do
    echo "== $split: validate"
    "${LB[@]}" validate "$PREFIX" --split "$split" "${EXTRA[@]}" || exit 1
    echo "== $split: official evaluate"
    "${LB[@]}" evaluate "${PREFIX}_${split}" --split "$split" || exit 1
    echo "== $split: pack + verify"
    out=$("${LB[@]}" pack "$PREFIX" --split "$split" --method "$METHOD" --method-tooltip "$METHOD_TIP" \
          --llm "$LLM" --llm-tooltip "$LLM_TIP" --url "$URL" "${EXTRA[@]}") || { echo "$out"; exit 1; }
    echo "$out"
    BUNDLES+=("$(echo "$out" | sed -n 's/^Bundle verified: //p')")
done

APPWORLD_REF=$(git -C benchmarks/appworld/appworld rev-parse --short HEAD 2>/dev/null || echo "<appworld version>")
PY=$(uv run --no-sync python -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo
echo "Bundles:"; printf '  %s\n' "${BUNDLES[@]}"
echo
echo "Next: copy each bundle to appworld-leaderboard/experiments/outputs/<experiment>/leaderboard.bundle,"
echo "open a PR on https://github.com/StonyBrookNLP/appworld-leaderboard and comment:"
echo "  /add-to-leaderboard --python $PY --appworld git+https://github.com/stonybrooknlp/appworld.git@$APPWORLD_REF $PREFIX"
```

`chmod +x benchmarks/appworld/pack_leaderboard.sh`.

- [ ] **Step 4: Run the shell tests**

Run: `bash benchmarks/appworld/tests/test_eval_sh_leaderboard.sh`
Expected: `failed=0`

- [ ] **Step 5: Commit**

```bash
git add benchmarks/appworld/pack_leaderboard.sh benchmarks/appworld/tests/test_eval_sh_leaderboard.sh
git commit -m "feat(appworld): pack_leaderboard.sh — validate, evaluate, pack and verify both splits"
```

---

### Task 13: Skill `.claude/skills/appworld-leaderboard/SKILL.md`

**Files:**
- Create: `.claude/skills/appworld-leaderboard/SKILL.md`

**Interfaces:** documentation only; must match the CLI names from Tasks 9, 11, 12 exactly.

- [ ] **Step 1: Write the skill**

```markdown
---
name: appworld-leaderboard
description: "Run, resume, retry and pack a CUGA AppWorld leaderboard submission (test_normal + test_challenge) batch-by-batch from eval_config.toml. Use when asked to run the full AppWorld test splits, continue an interrupted AppWorld run, retry failed/uncompleted AppWorld tasks, check AppWorld SGC/TGC, or produce leaderboard.bundle files."
trigger: /appworld-leaderboard
---

# AppWorld leaderboard flow

Everything is driven by keys in `benchmarks/appworld/eval_config.toml`. One cuga-eval
workspace (`benchmarks/appworld/evaluation_bundles/<name>`) and one AppWorld experiment
directory (`benchmarks/appworld/appworld/experiments/outputs/<prefix>_<split>`) per split.
Never create a second workspace for the same prefix+split.

## 0. Prepare batch keys (once per split)

    uv run python -m benchmarks.appworld.leaderboard split-key test_challenge_all --batch-size 100
    uv run python -m benchmarks.appworld.leaderboard split-key test_normal_all --batch-size 100

Writes `test_challenge_all_b1..b5` (100/100/100/100/17) and `test_normal_all_b1..b2` (100/68);
scenarios `_1/_2/_3` of a base always stay in the same batch.

## 1. First batch

    ./benchmarks/appworld/eval.sh --sdk --experiment cuga_v1_chal --leaderboard cuga_v1 \
        --eval-key test_challenge_all_b1 --background

Watch: `./benchmarks/appworld/eval.sh --status --resume-experiment cuga_v1_chal`
→ `cuga_v1_chal  split=test_challenge  completed 100/417  errored 0  score<1: 31  missing 317`
The console/background.log also prints `cuga-viz experiment: <card name>`.

## 2. Inspect in cuga-viz (http://localhost:8988/)

Open the card named in the log. **Uncompleted** = never finished (kill, crash).
**Failed** in cuga-viz only lists score == 0.0 and misses AppWorld's fractional scores —
prefer the harness list:

    uv run python -m benchmarks.appworld.leaderboard retry-key errored   --bundle-dir benchmarks/appworld/evaluation_bundles/cuga_v1_chal --of-key test_challenge_all_b1
    uv run python -m benchmarks.appworld.leaderboard retry-key uncompleted --bundle-dir ... --of-key test_challenge_all_b1

Either command appends a key like `cuga_v1_chal_errored = [...]` to eval_config.toml. Pasting
the cuga-viz line (`<card>_uncompleted_tasks = [...]`) into the toml works too.

Decide what to retry: open a failed task's trajectory; timeout / connection reset / 5xx / empty
LLM reply → retry. A genuine agent mistake is NOT retried on a leaderboard run (one attempt per task).

## 3. Retry (same workspace, same AppWorld dir)

    ./benchmarks/appworld/eval.sh --resume-experiment cuga_v1_chal --eval-key cuga_v1_chal_errored

A key ending in `_errored|_failed|_uncompleted|_failed_tasks|_uncompleted_tasks` re-runs every id
even if its partial is clean. For any other key add `--force-retry`.

## 4. Next batches

    ./benchmarks/appworld/eval.sh --resume-experiment cuga_v1_chal --eval-key test_challenge_all_b2 --background
    # inspect / retry, then b3, b4, b5

Batch keys skip ids that already completed. Ids must belong to the workspace's split or the run aborts.

## 5. Validate + official numbers

    uv run python -m benchmarks.appworld.leaderboard validate cuga_v1 --split test_challenge
    uv run python -m benchmarks.appworld.leaderboard evaluate cuga_v1_test_challenge --split test_challenge \
        --bundle-dir benchmarks/appworld/evaluation_bundles/cuga_v1_chal

`validate` exits 1 on missing tasks/files/scenarios. SDK eval copies ToolCallTracker records into
`environment_io.md` / `api_calls.jsonl` after invoke (HTTP still goes to port 9111; the APIs are
not re-executed). Pass `--allow-low-interactions` only for tasks that really made no AppWorld API
calls besides `complete_task`. `evaluate` prints TGC + SGC by difficulty and writes them into the
workspace `report.md` under "AppWorld official metrics".

## 6. Pack both splits

    ./benchmarks/appworld/pack_leaderboard.sh cuga_v1 "CUGA" "CUGA lite via SDK" "gpt-4.1" "gpt-4.1-2025-04-14" \
        https://github.com/cuga-project/cuga-agent

Refuses unless both splits validate; runs `appworld pack`, unpacks the bundle into a temp dir and
byte-compares every file; prints the two `leaderboard.bundle` paths and the
`/add-to-leaderboard --python … --appworld … cuga_v1` comment for the PR.

## Do not

- Rename an AppWorld experiment dir after packing (the bundle then refuses to unpack).
- Run `--task` for leaderboard retries; use a toml key so the attempt is recorded in `resume_history`.
- Trust `appworld pack` output alone: it prints WARNINGs and still writes the bundle, and says
  nothing about absent task dirs. Only `pack_leaderboard.sh` / `leaderboard pack` verify.
```

- [ ] **Step 2: Check every command in the skill exists**

Run: `grep -oE "leaderboard (split-key|retry-key|status|validate|evaluate|pack)" .claude/skills/appworld-leaderboard/SKILL.md | sort -u; uv run --no-sync python -m benchmarks.appworld.leaderboard --help | grep -E "split-key|retry-key|status|validate|evaluate|pack"`
Expected: the same six subcommands in both outputs.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/appworld-leaderboard/SKILL.md
git commit -m "docs(appworld): /appworld-leaderboard skill walking the batch, inspect, retry, pack flow"
```

---

### Task 14: README + `eval.sh --help` + issue link

**Files:**
- Modify: `benchmarks/appworld/README.md` (after "Named experiments and compare resume")
- Modify: `benchmarks/appworld/eval.sh` (`--help` block already touched in Task 11; verify)

- [ ] **Step 1: Add the README section**

Insert a `### Leaderboard submissions (full test_normal / test_challenge)` section that is a condensed copy of steps 0–6 of the skill (same commands), plus the table of what `validate` checks and the sentence about `--allow-low-interactions`. Link the skill: "For an agent-guided walkthrough use `/appworld-leaderboard`."

- [ ] **Step 2: Verify help and docs mention the same flags**

Run: `bash benchmarks/appworld/eval.sh --help | grep -cE "leaderboard|force-retry|dry-run"; grep -c "pack_leaderboard.sh" benchmarks/appworld/README.md`
Expected: `3` and `>=1`.

- [ ] **Step 3: Run the whole suite**

Run: `uv run --no-sync pytest benchmarks/appworld/tests benchmarks/helpers/tests -q && bash benchmarks/appworld/tests/test_eval_sh_leaderboard.sh && just ci`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add benchmarks/appworld/README.md benchmarks/appworld/eval.sh
git commit -m "docs(appworld): leaderboard submission flow in README and eval.sh help"
```

---

### Task 15: Rehearsal on `dev` (manual gate, no code)

- [ ] **Step 1:** `uv run python -m benchmarks.appworld.leaderboard split-key test_normal_all --batch-size 6` is NOT used here (dev is not a leaderboard split). Instead run the plain resume flow on a 6-id `dev` key to exercise kill/resume/retry end to end:
  ```bash
  ./benchmarks/appworld/eval.sh --sdk --experiment rehearsal --eval-key verify_check --background
  sleep 120; ./benchmarks/appworld/eval.sh --stop --resume-experiment rehearsal
  uv run python -m benchmarks.appworld.leaderboard retry-key uncompleted --bundle-dir benchmarks/appworld/evaluation_bundles/rehearsal --of-key verify_check
  ./benchmarks/appworld/eval.sh --resume-experiment rehearsal --eval-key rehearsal_uncompleted
  uv run python -m benchmarks.appworld.leaderboard status --bundle-dir benchmarks/appworld/evaluation_bundles/rehearsal
  ```
  Expected: status shows `completed 5/5`, `results/partial` has 5 files, the AppWorld dir `experiments/outputs/verify_check` (plain mode keeps the eval_key name) has 5 task dirs.
- [ ] **Step 2:** Leaderboard naming rehearsal with 3 real `test_normal` ids (one base) so `--leaderboard` binds the workspace:
  ```bash
  uv run python - <<'EOF'
  from pathlib import Path
  from benchmarks.appworld.leaderboard import write_toml_key
  write_toml_key(Path("benchmarks/appworld/eval_config.toml"), "rehearsal_normal", ["fd1f8fa_1","fd1f8fa_2","fd1f8fa_3"], "3 tasks — leaderboard rehearsal")
  EOF
  ./benchmarks/appworld/eval.sh --sdk --experiment rehearsal_lb --leaderboard rehearsal --eval-key rehearsal_normal
  uv run python -m benchmarks.appworld.leaderboard validate rehearsal --split test_normal   # expect 3/168 present, exit 1
  uv run python -m benchmarks.appworld.leaderboard evaluate rehearsal_test_normal --key rehearsal_normal --bundle-dir benchmarks/appworld/evaluation_bundles/rehearsal_lb
  ```
  Expected: AppWorld dir `experiments/outputs/rehearsal_test_normal/tasks/` has the 3 ids; `report.md` in the workspace has the official table with a real SGC (all three scenarios present).
- [ ] **Step 3:** Remove the two rehearsal keys from `eval_config.toml` and delete `experiments/outputs/rehearsal_test_normal` and the two workspaces. Do not commit any of them.

---

## Self-review

**Spec coverage**
- Item 1 (leaderboard flag, stable name, split-key): Tasks 1, 2, 4, 5, 6, 11. ✔
- Item 2 (interaction logging): SDK backfill from ToolCallTracker (`interaction_logs.py`, hooked in `eval_appworld_sdk.py`). `validate` low-interaction warning + `--allow-low-interactions` remain as a safety valve. ✔
- Item 3 (toml-driven continue/retry, cuga-viz paste, resume_history, `--write-retry-key`): Tasks 2, 4, 5, 7 (`retry-key` CLI), 6. ✔
- Item 4 (multi `--task`): Tasks 6, 11. ✔
- Item 5 (`validate`): Tasks 3, 9. ✔
- Item 6 (pack wrapper): Tasks 9, 12. ✔
- Item 7 (official TGC/SGC): Tasks 8, 11 (post-run), 12. ✔
- Item 8 (docs): Tasks 13, 14. ✔
- Testing A1–A9: Tasks 5 (A1–A5 via plan_run/metadata), 2 (A6, A7), 3 (A8), 8 (A9 partially: TGC consistency check is not implemented as a hard assertion — `evaluate` prints the official table and the workspace report keeps our own metrics; add an assertion in a follow-up if the two ever disagree). B10–B15: Task 10 (B15 is the ToolCallTracker backfill in `interaction_logs.py`). C16–C18: Task 11. D: Task 15.
- cuga-viz Failed fix: out of scope (cuga-viz) — `retry-key failed` covers it. ✔ (deliberate gap)

**Placeholder scan:** none.

**Type consistency:** `plan_run` keyword names match Task 6's call; `store_leaderboard_metadata` signature identical in Tasks 4, 5, 6, 7; `validate_experiment(exp_dir, split_ids, split)` identical in Tasks 3, 9, 10; CLI subcommand names identical in Tasks 9, 11, 12, 13.
