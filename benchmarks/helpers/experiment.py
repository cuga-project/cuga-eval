"""Experiment identity and resume resolution (Slice B).

Named experiments live at ``benchmarks/<bench>/evaluation_bundles/<name>`` (no
timestamp prefix). A ``.last_experiment`` pointer is written whenever a
workspace bundle is opened so bare ``--resume`` can find the most recent run.

The shell layer calls :func:`cli` subcommands; evaluators receive a concrete
``--bundle-dir`` and never re-derive naming logic themselves.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from benchmarks.helpers.incremental_results import atomic_write_json

# Legacy auto-named bundles look like ``20260701_120000_default`` or
# ``20260701_120000_compare_foo`` — reject those shapes as experiment names.
_TIMESTAMP_NAME_RE = re.compile(r"^\d{8}_\d{6}($|_)")

_HELPERS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _HELPERS_DIR.parent.parent


class ExperimentError(Exception):
    """User-facing experiment/resume resolution error."""


def bundle_root(benchmark_name: str, *, compare: bool = False) -> Path:
    """Return ``benchmarks/<bench>/evaluation_bundles`` (compare uses same root today)."""
    del compare  # reserved for M4 compare.sh wiring
    return PROJECT_ROOT / "benchmarks" / benchmark_name / "evaluation_bundles"


def last_experiment_pointer_path(benchmark_name: str, *, compare: bool = False) -> Path:
    return bundle_root(benchmark_name, compare=compare) / ".last_experiment"


def validate_experiment_name(name: str) -> None:
    if not name or not str(name).strip():
        raise ExperimentError("Experiment name must be non-empty")
    name = str(name).strip()
    if _TIMESTAMP_NAME_RE.match(name):
        raise ExperimentError(
            f"Experiment name {name!r} looks like a legacy timestamp bundle name "
            "(use a human-readable name instead)"
        )
    if name.startswith(".") or "/" in name or "\\" in name:
        raise ExperimentError(f"Experiment name {name!r} contains invalid path characters")


def resolve_experiment_bundle_dir(
    benchmark_name: str,
    experiment_name: str,
    *,
    compare: bool = False,
) -> Path:
    validate_experiment_name(experiment_name)
    return bundle_root(benchmark_name, compare=compare) / experiment_name.strip()


def write_last_experiment_pointer(
    benchmark_name: str,
    bundle_dir: Path,
    *,
    compare: bool = False,
) -> Path:
    pointer = last_experiment_pointer_path(benchmark_name, compare=compare)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "bundle_dir": str(Path(bundle_dir).resolve()),
        "benchmark": benchmark_name,
    }
    atomic_write_json(pointer, payload)
    return pointer


def resolve_last_experiment(benchmark_name: str, *, compare: bool = False) -> Path | None:
    pointer = last_experiment_pointer_path(benchmark_name, compare=compare)
    if not pointer.is_file():
        return None
    try:
        import json

        raw = pointer.read_text()
        try:
            data = json.loads(raw)
        except ValueError:
            # Not JSON — fall through to the plain-text pointer handling below
            # instead of bailing out here (a bare `except ValueError: return
            # None` would make that fallback unreachable).
            data = None
        if isinstance(data, dict) and data.get("bundle_dir"):
            return Path(str(data["bundle_dir"]))
        # Backward-compatible plain-text pointer (single line path).
        text = raw.strip()
        if text.startswith("{"):
            return None
        return Path(text) if text else None
    except (OSError, TypeError):
        return None


def new_or_resume_bundle_dir(
    benchmark_name: str,
    *,
    experiment: str | None = None,
    resume: bool = False,
    resume_experiment: str | None = None,
    compare: bool = False,
) -> tuple[Path | None, bool]:
    """Single entry point for experiment/resume flag precedence.

    Returns ``(bundle_dir, is_resume)``. ``bundle_dir`` is ``None`` when no
    experiment/resume flags were supplied (legacy post-hoc ``assemble_bundle``
    path — evaluators do not receive ``--bundle-dir``).
    """
    flags = sum(
        1
        for x in (
            bool(experiment),
            bool(resume),
            bool(resume_experiment),
        )
        if x
    )
    if flags > 1:
        raise ExperimentError("Use only one of --experiment, --resume, or --resume-experiment")

    if resume_experiment:
        path = resolve_experiment_bundle_dir(benchmark_name, resume_experiment, compare=compare)
        if not path.is_dir():
            raise ExperimentError(f"Experiment bundle not found for --resume-experiment: {path}")
        return path, True

    if resume:
        path = resolve_last_experiment(benchmark_name, compare=compare)
        if path is None:
            raise ExperimentError(
                "No .last_experiment pointer found — run an experiment first or "
                "use --resume-experiment <name>"
            )
        if not path.is_dir():
            raise ExperimentError(f".last_experiment points to a missing directory: {path}")
        return path, True

    if experiment:
        path = resolve_experiment_bundle_dir(benchmark_name, experiment, compare=compare)
        if path.exists():
            raise ExperimentError(
                f"Experiment {experiment!r} already exists at {path}. Use --resume-experiment to continue it."
            )
        return path, False

    return None, False


def _experiment_name_for_bundle(
    bundle_dir: Path,
    *,
    experiment: str | None,
    resume_experiment: str | None,
) -> str | None:
    if experiment:
        return experiment
    if resume_experiment:
        return resume_experiment
    meta_path = Path(bundle_dir) / "metadata.json"
    if meta_path.is_file():
        try:
            import json

            meta = json.loads(meta_path.read_text())
            name = meta.get("experiment_name")
            if name:
                return str(name)
        except (OSError, ValueError, TypeError):
            pass
    return Path(bundle_dir).name


def prepare_workspace(
    benchmark_name: str,
    *,
    experiment: str | None = None,
    resume: bool = False,
    resume_experiment: str | None = None,
    model_profile: str | None = None,
    agent: str | None = None,
    no_policies: bool = False,
    eval_key: str | None = None,
    compare: bool = False,
) -> Path:
    """Resolve bundle dir, create/re-open workspace, write ``.last_experiment``."""
    from benchmarks.helpers.bundle import create_workspace_bundle

    bundle_dir, _is_resume = new_or_resume_bundle_dir(
        benchmark_name,
        experiment=experiment,
        resume=resume,
        resume_experiment=resume_experiment,
        compare=compare,
    )
    if bundle_dir is None:
        raise ExperimentError("prepare_workspace called without experiment/resume flags")

    bundle_dir.parent.mkdir(parents=True, exist_ok=True)
    exp_name = _experiment_name_for_bundle(
        bundle_dir,
        experiment=experiment,
        resume_experiment=resume_experiment,
    )
    run_args: dict[str, Any] = {
        "agent": agent or "cuga_sdk",
        "no_policies": no_policies,
        "eval_key": eval_key,
    }
    create_workspace_bundle(
        bundle_dir,
        benchmark_name,
        experiment_name=exp_name,
        args=run_args,
        model_profile=model_profile,
    )
    write_last_experiment_pointer(benchmark_name, bundle_dir, compare=compare)
    return bundle_dir


def finalize_workspace(
    benchmark_name: str,
    bundle_dir: Path,
    *,
    task_files: list[str | Path] | None = None,
    model_profile: str | None = None,
    agent: str | None = None,
    no_policies: bool = False,
    eval_key: str | None = None,
    policies_dir: Path | None = None,
    trajectory_dir: Path | None = None,
    log_files: list[str | Path] | None = None,
    fetch_langfuse: bool = True,
    partial: bool = False,
    cuga_git_info: dict | None = None,
    zip_bundle: bool = False,
    compare: bool = False,
) -> Path:
    """Finalize an experiment workspace and refresh ``.last_experiment``."""
    from benchmarks.helpers.bundle import finalize_workspace_bundle
    from benchmarks.helpers.bundle import zip_bundle as do_zip

    out = finalize_workspace_bundle(
        Path(bundle_dir),
        benchmark_name,
        task_files=task_files,
        args={
            "agent": agent or "cuga_sdk",
            "no_policies": no_policies,
            "eval_key": eval_key,
        },
        model_profile=model_profile,
        policies_dir=policies_dir,
        trajectory_dir=trajectory_dir,
        log_files=log_files,
        fetch_langfuse=fetch_langfuse,
        partial=partial,
        cuga_git_info=cuga_git_info,
    )
    write_last_experiment_pointer(benchmark_name, out, compare=compare)
    if zip_bundle:
        do_zip(out)
    return out


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment workspace CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_experiment_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--benchmark", required=True)
        p.add_argument("--experiment", default=None)
        p.add_argument("--resume", action="store_true")
        p.add_argument("--resume-experiment", default=None)
        p.add_argument("--compare", action="store_true")

    p_prep = sub.add_parser("prepare-workspace", help="Resolve + create experiment workspace")
    add_experiment_flags(p_prep)
    p_prep.add_argument("--model-profile", default=None)
    p_prep.add_argument("--agent", default=None)
    p_prep.add_argument("--no-policies", action="store_true")
    p_prep.add_argument("--eval-key", default=None)

    p_fin = sub.add_parser("finalize-workspace", help="Finalize an experiment workspace")
    p_fin.add_argument("--benchmark", required=True)
    p_fin.add_argument("--bundle-dir", required=True)
    p_fin.add_argument("--task-file", action="append", dest="task_files", default=None)
    p_fin.add_argument("--policies-dir", default=None)
    p_fin.add_argument("--trajectory-dir", default=None)
    p_fin.add_argument("--log-file", action="append", dest="log_files", default=None)
    p_fin.add_argument("--model-profile", default=None)
    p_fin.add_argument("--agent", default=None)
    p_fin.add_argument("--no-policies", action="store_true")
    p_fin.add_argument("--eval-key", default=None)
    p_fin.add_argument("--no-langfuse", action="store_true")
    p_fin.add_argument("--partial", action="store_true")
    p_fin.add_argument("--zip", action="store_true")
    p_fin.add_argument("--cuga-git-info", default=None)
    p_fin.add_argument("--compare", action="store_true")

    p_ptr = sub.add_parser("write-pointer", help="Update .last_experiment for a bundle dir")
    p_ptr.add_argument("--benchmark", required=True)
    p_ptr.add_argument("--bundle-dir", required=True)
    p_ptr.add_argument("--compare", action="store_true")

    p_res = sub.add_parser("resolve", help="Print resolved bundle dir (debug)")
    add_experiment_flags(p_res)

    args = parser.parse_args(argv)

    try:
        if args.command == "resolve":
            bundle_dir, is_resume = new_or_resume_bundle_dir(
                args.benchmark,
                experiment=args.experiment,
                resume=args.resume,
                resume_experiment=args.resume_experiment,
                compare=args.compare,
            )
            if bundle_dir is None:
                print("legacy", end="")
                return 0
            print(f"{bundle_dir}\t{'resume' if is_resume else 'new'}", end="")
            return 0

        if args.command == "prepare-workspace":
            path = prepare_workspace(
                args.benchmark,
                experiment=args.experiment,
                resume=args.resume,
                resume_experiment=args.resume_experiment,
                model_profile=args.model_profile,
                agent=args.agent,
                no_policies=args.no_policies,
                eval_key=args.eval_key,
                compare=args.compare,
            )
            print(path, end="")
            return 0

        if args.command == "write-pointer":
            write_last_experiment_pointer(args.benchmark, Path(args.bundle_dir), compare=args.compare)
            return 0

        if args.command == "finalize-workspace":
            cuga_git = None
            if args.cuga_git_info:
                import json

                cuga_git = json.loads(args.cuga_git_info)
            out = finalize_workspace(
                args.benchmark,
                Path(args.bundle_dir),
                task_files=args.task_files,
                model_profile=args.model_profile,
                agent=args.agent,
                no_policies=args.no_policies,
                eval_key=args.eval_key,
                policies_dir=Path(args.policies_dir) if args.policies_dir else None,
                trajectory_dir=Path(args.trajectory_dir) if args.trajectory_dir else None,
                log_files=args.log_files,
                fetch_langfuse=not args.no_langfuse,
                partial=args.partial,
                cuga_git_info=cuga_git,
                zip_bundle=args.zip,
                compare=args.compare,
            )
            print(out, end="")
            return 0

    except ExperimentError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(cli())
