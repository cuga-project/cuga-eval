"""Compare-level progress tracking (Slice C / M4).

``compare_state.json`` lives at the compare experiment workspace root and
records which ``(config, run)`` pairs have finished. Each pair gets its own
sub-experiment bundle (``<compare>__<config>__r<N>``) so individual eval runs
remain resumable via the M2 workspace machinery.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from benchmarks.helpers.incremental_results import atomic_write_json

COMPARE_STATE_FILENAME = "compare_state.json"
_COMBO_SEP = "::"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compare_state_path(compare_dir: Path) -> Path:
    return Path(compare_dir) / COMPARE_STATE_FILENAME


def _sanitize_config(config: str) -> str:
    """Sanitize a config label for use as a sub-experiment path component.

    Aligned with ``experiment.py::validate_experiment_name``'s allowed
    character class (letters, digits, ``.``, ``_``, ``+``, ``-``). Unlike a
    plain "replace disallowed runs with a single underscore" pass, this also
    collapses any resulting run of underscores (including ones already
    present in ``config``) down to one, so the sanitized output can never
    contain ``__`` — the delimiter :func:`sub_experiment_name` uses to join
    ``<compare>__<config>__r<run>``. Without that guarantee, a config like
    ``"gpt4__opus"`` would sanitize unchanged and make the resulting
    sub-experiment name ambiguous to parse back into its three parts.
    """
    safe = re.sub(r"[^A-Za-z0-9.+-]+", "_", str(config))
    return re.sub(r"_+", "_", safe)


def combo_key(config: str, run: int) -> str:
    return f"{config}{_COMBO_SEP}{run}"


def sub_experiment_name(compare_experiment: str, config: str, run: int) -> str:
    safe = _sanitize_config(config)
    return f"{compare_experiment}__{safe}__r{run}"


def read_compare_state(compare_dir: Path) -> Dict[str, Any]:
    path = compare_state_path(compare_dir)
    if not path.is_file():
        return {}
    import json

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def write_compare_state(compare_dir: Path, state: Dict[str, Any]) -> Path:
    state = dict(state)
    state["updated_at"] = _utc_now()
    return atomic_write_json(compare_state_path(compare_dir), state)


def init_compare_state(
    compare_dir: Path,
    *,
    total_planned: int,
    configs: Iterable[str],
    runs_per_config: int,
    compare_experiment: str,
) -> Path:
    compare_dir = Path(compare_dir)
    existing = read_compare_state(compare_dir)
    combos = existing.get("combos") if isinstance(existing.get("combos"), dict) else {}
    state = {
        "compare_experiment": compare_experiment,
        "total_planned": total_planned,
        "configs": list(configs),
        "runs_per_config": runs_per_config,
        "combos": combos,
        "started_at": existing.get("started_at") or _utc_now(),
    }
    return write_compare_state(compare_dir, state)


def mark_combo_run_started(
    compare_dir: Path,
    config: str,
    run: int,
    *,
    sub_experiment: str,
) -> Path:
    """Record a combo run's start in ``compare_state.json``.

    Invariant (not currently enforced): like ``run_state.py::write_run_state``,
    this is a read-modify-write over the whole state dict with no locking —
    only the final ``atomic_write_json`` write is atomic. Safe today because
    combo runs execute sequentially (one ``mark-started``/``mark-completed``
    pair in flight at a time); if combos are ever parallelized, concurrent
    calls here can race and drop each other's updates to ``combos``.
    """
    state = read_compare_state(compare_dir)
    combos = state.setdefault("combos", {})
    combos[combo_key(config, run)] = {
        "config": config,
        "run": run,
        "status": "running",
        "sub_experiment": sub_experiment,
        "started_at": _utc_now(),
    }
    return write_compare_state(compare_dir, state)


def mark_combo_run_completed(
    compare_dir: Path,
    config: str,
    run: int,
    *,
    exit_code: int,
) -> Path:
    """Record a combo run's completion in ``compare_state.json``.

    Same read-modify-write-with-no-locking invariant as
    :func:`mark_combo_run_started` — see that docstring.
    """
    state = read_compare_state(compare_dir)
    combos = state.setdefault("combos", {})
    key = combo_key(config, run)
    entry = dict(combos.get(key) or {"config": config, "run": run})
    entry["status"] = "completed" if exit_code == 0 else "failed"
    entry["exit_code"] = exit_code
    entry["completed_at"] = _utc_now()
    combos[key] = entry
    return write_compare_state(compare_dir, state)


def already_completed_combo_runs(compare_dir: Path) -> Set[Tuple[str, int]]:
    done: Set[Tuple[str, int]] = set()
    combos = read_compare_state(compare_dir).get("combos") or {}
    if not isinstance(combos, dict):
        return done
    for entry in combos.values():
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "completed":
            continue
        config = entry.get("config")
        run = entry.get("run")
        if config is not None and run is not None:
            done.add((str(config), int(run)))
    return done


def is_combo_done(compare_dir: Path, config: str, run: int) -> bool:
    return (config, run) in already_completed_combo_runs(compare_dir)


def eval_flags_for_combo(
    compare_experiment: str,
    config: str,
    run: int,
    *,
    compare_dir: Path | None = None,
) -> List[str]:
    """Return ``eval.sh`` flags for this combo (new or resume sub-experiment)."""
    sub = sub_experiment_name(compare_experiment, config, run)
    if compare_dir is not None:
        combos = read_compare_state(compare_dir).get("combos") or {}
        entry = combos.get(combo_key(config, run)) if isinstance(combos, dict) else None
        if isinstance(entry, dict) and entry.get("status") in ("running", "failed"):
            return ["--resume-experiment", sub]
        sub_path = Path(compare_dir).parent / sub
        if sub_path.is_dir():
            return ["--resume-experiment", sub]
    return ["--experiment", sub]


def load_compare_progress(compare_dir: Path) -> Dict[str, Any]:
    state = read_compare_state(compare_dir)
    combos = state.get("combos") or {}
    completed = failed = running = 0
    if isinstance(combos, dict):
        for entry in combos.values():
            if not isinstance(entry, dict):
                continue
            status = entry.get("status")
            if status == "completed":
                completed += 1
            elif status == "failed":
                failed += 1
            elif status == "running":
                running += 1
    total = state.get("total_planned")
    remaining = None
    if isinstance(total, int):
        remaining = max(total - completed - failed, 0)
    return {
        "compare_dir": str(Path(compare_dir).resolve()),
        "compare_experiment": state.get("compare_experiment"),
        "total_planned": total,
        "completed": completed,
        "failed": failed,
        "running": running,
        "remaining": remaining,
        "updated_at": state.get("updated_at"),
    }


def format_compare_progress(compare_dir: Path) -> str:
    progress = load_compare_progress(compare_dir)
    lines = [
        f"compare bundle: {progress['compare_dir']}",
        f"experiment: {progress.get('compare_experiment') or '—'}",
    ]
    total = progress.get("total_planned")
    if total is not None:
        lines.append(
            "combos: "
            f"{progress['completed']}/{total} completed, "
            f"{progress['failed']} failed, "
            f"{progress['running']} running, "
            f"{progress.get('remaining', '—')} remaining"
        )
    else:
        lines.append(
            f"combos: {progress['completed']} completed, "
            f"{progress['failed']} failed, {progress['running']} running"
        )
    if progress.get("updated_at"):
        lines.append(f"updated: {progress['updated_at']}")
    return "\n".join(lines)


def resolve_compare_experiment_name(
    *,
    experiment: str | None,
    resume_experiment: str | None,
    compare_dir: Path | None,
) -> str:
    if experiment:
        return experiment
    if resume_experiment:
        return resume_experiment
    if compare_dir is not None:
        return Path(compare_dir).name
    raise ValueError("compare experiment name could not be resolved")


def workspace_bundle_inputs(compare_dir: Path) -> Dict[str, Any]:
    """Aggregate combo sub-bundles into ``assemble_compare_bundle`` inputs.

    In workspace/experiment mode, each ``(config, run)`` combo writes its
    results/trajectories/logs into its own sub-experiment bundle directory (a
    sibling of ``compare_dir``, named via :func:`sub_experiment_name`) —
    ``compare.sh``'s legacy before/after diff of the benchmark's flat
    ``results/`` scratch directory never sees these, since workspace-mode
    combos don't write there at all. This reads every recorded combo's
    sub-bundle directly instead, so the final comparison bundle/report is
    correct whether a combo ran in this invocation or was skipped because a
    prior invocation already completed it (``--resume``/``--resume-experiment``
    at the compare level).

    Returns the same shapes :func:`assemble_compare_bundle` (in ``bundle.py``)
    expects for ``config_results``/``trajectory_dirs``/``log_files``, with
    paths as strings so the caller can serialize directly to JSON.
    """
    compare_dir = Path(compare_dir)
    state = read_compare_state(compare_dir)
    combos = state.get("combos") or {}

    by_config: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
    for entry in combos.values():
        if not isinstance(entry, dict):
            continue
        config = entry.get("config")
        run = entry.get("run")
        sub_exp = entry.get("sub_experiment")
        if config is None or run is None or not sub_exp:
            continue
        by_config.setdefault(str(config), []).append((int(run), entry))

    config_results: Dict[str, List[str]] = {}
    trajectory_dirs: Dict[str, List[List[str]]] = {}
    log_files: Dict[str, List[List[str]]] = {}

    for config, entries in by_config.items():
        entries.sort(key=lambda x: x[0])
        result_files: List[str] = []
        traj_groups: List[List[str]] = []
        log_groups: List[List[str]] = []
        for _run, entry in entries:
            sub_dir = compare_dir.parent / str(entry["sub_experiment"])
            if not sub_dir.is_dir():
                continue
            results_subdir = sub_dir / "results"
            rfiles = sorted(str(p) for p in results_subdir.glob("*.json")) if results_subdir.is_dir() else []
            if not rfiles:
                # Nothing to contribute yet (still running, or failed before
                # producing a merged results file) — skip this combo/run
                # rather than padding the report with an empty entry.
                continue
            result_files.extend(rfiles)
            traj_dir = sub_dir / "trajectories"
            traj_groups.append([str(traj_dir)] if traj_dir.is_dir() else [])
            logs_dir = sub_dir / "logs"
            log_groups.append(sorted(str(p) for p in logs_dir.glob("*")) if logs_dir.is_dir() else [])
        if result_files:
            config_results[config] = result_files
        if any(traj_groups):
            trajectory_dirs[config] = traj_groups
        if any(log_groups):
            log_files[config] = log_groups

    return {
        "config_results": config_results,
        "trajectory_dirs": trajectory_dirs,
        "log_files": log_files,
    }


def cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compare progress CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize compare_state.json")
    p_init.add_argument("--compare-dir", required=True)
    p_init.add_argument("--compare-experiment", required=True)
    p_init.add_argument("--total-planned", type=int, required=True)
    p_init.add_argument("--runs-per-config", type=int, required=True)
    p_init.add_argument("--config", action="append", dest="configs", required=True)

    p_done = sub.add_parser("is-done", help="Exit 0 when combo already completed")
    p_done.add_argument("--compare-dir", required=True)
    p_done.add_argument("--config", required=True)
    p_done.add_argument("--run", type=int, required=True)

    p_flags = sub.add_parser("eval-flags", help="Print eval.sh flags for a combo")
    p_flags.add_argument("--compare-dir", default=None)
    p_flags.add_argument("--compare-experiment", required=True)
    p_flags.add_argument("--config", required=True)
    p_flags.add_argument("--run", type=int, required=True)

    p_start = sub.add_parser("mark-started", help="Record combo start")
    p_start.add_argument("--compare-dir", required=True)
    p_start.add_argument("--config", required=True)
    p_start.add_argument("--run", type=int, required=True)
    p_start.add_argument("--sub-experiment", required=True)

    p_fin = sub.add_parser("mark-completed", help="Record combo completion")
    p_fin.add_argument("--compare-dir", required=True)
    p_fin.add_argument("--config", required=True)
    p_fin.add_argument("--run", type=int, required=True)
    p_fin.add_argument("--exit-code", type=int, required=True)

    p_status = sub.add_parser("status", help="Print compare progress")
    p_status.add_argument("--compare-dir", required=True)

    p_name = sub.add_parser("sub-name", help="Print sub-experiment name")
    p_name.add_argument("--compare-experiment", required=True)
    p_name.add_argument("--config", required=True)
    p_name.add_argument("--run", type=int, required=True)

    p_inputs = sub.add_parser(
        "bundle-inputs", help="Print one assemble_compare_bundle input field, sourced from combo sub-bundles"
    )
    p_inputs.add_argument("--compare-dir", required=True)
    p_inputs.add_argument(
        "--field", required=True, choices=["config-results", "trajectory-dirs", "log-files"]
    )

    args = parser.parse_args(argv)

    if args.command == "init":
        init_compare_state(
            Path(args.compare_dir),
            total_planned=args.total_planned,
            configs=args.configs,
            runs_per_config=args.runs_per_config,
            compare_experiment=args.compare_experiment,
        )
        return 0

    if args.command == "is-done":
        return 0 if is_combo_done(Path(args.compare_dir), args.config, args.run) else 1

    if args.command == "eval-flags":
        flags = eval_flags_for_combo(
            args.compare_experiment,
            args.config,
            args.run,
            compare_dir=Path(args.compare_dir) if args.compare_dir else None,
        )
        print(" ".join(flags), end="")
        return 0

    if args.command == "mark-started":
        mark_combo_run_started(
            Path(args.compare_dir),
            args.config,
            args.run,
            sub_experiment=args.sub_experiment,
        )
        return 0

    if args.command == "mark-completed":
        mark_combo_run_completed(
            Path(args.compare_dir),
            args.config,
            args.run,
            exit_code=args.exit_code,
        )
        return 0

    if args.command == "status":
        print(format_compare_progress(Path(args.compare_dir)))
        return 0

    if args.command == "sub-name":
        print(
            sub_experiment_name(args.compare_experiment, args.config, args.run),
            end="",
        )
        return 0

    if args.command == "bundle-inputs":
        import json

        field_map = {
            "config-results": "config_results",
            "trajectory-dirs": "trajectory_dirs",
            "log-files": "log_files",
        }
        inputs = workspace_bundle_inputs(Path(args.compare_dir))
        print(json.dumps(inputs[field_map[args.field]]), end="")
        return 0

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(cli())
