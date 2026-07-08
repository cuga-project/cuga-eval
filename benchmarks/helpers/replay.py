"""Best-effort reconstruction of eval CLI args from bundle metadata (M5)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Keys under metadata["run"] that cli_args_from_metadata knows how to turn
# back into a flag. Anything else recorded there (e.g. "task_files", or a
# field a future benchmark adds) is silently dropped by the reconstruction
# unless _unmapped_fields surfaces it.
_MAPPED_RUN_KEYS = {"agent", "model_profile", "policies_enabled", "task_ids", "eval_key"}


def _unmapped_fields(metadata: Dict[str, Any]) -> List[str]:
    """Return ``key=value`` strings for ``run`` fields this module can't reconstruct.

    Best-effort reconstruction only covers ``_MAPPED_RUN_KEYS``; anything else
    under ``metadata["run"]`` (for example the copied task-file basenames, or
    a field a future benchmark's bundle adds) is dropped on the floor by
    :func:`cli_args_from_metadata` today. Surface it instead of pretending the
    replayed command is a complete reproduction.
    """
    run = metadata.get("run") if isinstance(metadata.get("run"), dict) else {}
    unmapped: List[str] = []
    for key, value in run.items():
        if key in _MAPPED_RUN_KEYS:
            continue
        if value in (None, "", [], {}):
            continue
        unmapped.append(f"{key}={value!r}")
    return unmapped


def cli_args_from_metadata(metadata: Dict[str, Any]) -> List[str]:
    """Reconstruct an ``eval.sh`` argv from ``metadata.json`` fields.

    This is intentionally best-effort: not every runtime detail is persisted,
    and some flags (``--verbose``, task file paths) may need manual adjustment.
    """
    args: List[str] = []
    run = metadata.get("run") if isinstance(metadata.get("run"), dict) else {}
    runtime = metadata.get("runtime_config") if isinstance(metadata.get("runtime_config"), dict) else {}

    model_profile = run.get("model_profile") or runtime.get("model_profile")
    if model_profile:
        args.extend(["--model-profile", str(model_profile)])

    agent = str(run.get("agent") or "cuga_sdk")
    if agent.endswith("_sdk"):
        agent = agent[: -len("_sdk")]
    if agent and agent not in ("cuga", ""):
        if agent == "codeact":
            args.extend(["--agent", "codeact"])
        elif agent == "react":
            args.extend(["--agent", "react"])
        elif agent != "cuga":
            args.extend(["--agent", agent])

    if agent == "cuga" and run.get("agent") == "cuga_sdk":
        benchmark = metadata.get("benchmark")
        if benchmark == "appworld":
            args.append("--sdk")

    if run.get("policies_enabled") is False:
        args.append("--no-policies")

    task_ids = run.get("task_ids")
    if task_ids:
        args.append("--task")
        args.extend(str(t) for t in task_ids)

    eval_key = run.get("eval_key")
    if eval_key:
        args.extend(["--eval-key", str(eval_key)])

    experiment_name = metadata.get("experiment_name")
    if experiment_name:
        args.extend(["--resume-experiment", str(experiment_name)])

    return args


def format_replay_command(
    metadata: Dict[str, Any],
    *,
    benchmark: str | None = None,
    script: str = "./eval.sh",
) -> str:
    bench = benchmark or str(metadata.get("benchmark") or "<benchmark>")
    argv = cli_args_from_metadata(metadata)
    lines = [f"# Replay for {bench}"]

    experiment_name = metadata.get("experiment_name")
    if experiment_name:
        lines.append(
            f"# NOTE: this resumes the existing bundle {experiment_name!r} in place "
            "(--resume-experiment); pass --experiment <new-name> instead of "
            "--resume-experiment to run a fresh reproduction."
        )

    unmapped = _unmapped_fields(metadata)
    if unmapped:
        lines.append(
            "# NOTE: metadata has fields this reconstruction cannot map to a flag "
            "(add manually if relevant): " + ", ".join(unmapped)
        )

    lines.append(" ".join([script] + argv))
    return "\n".join(lines)


def cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Metadata replay helper")
    parser.add_argument(
        "--metadata",
        default=None,
        help="Path to metadata.json (default: read from --bundle-dir)",
    )
    parser.add_argument("--bundle-dir", default=None)
    parser.add_argument("--benchmark", default=None)
    parser.add_argument(
        "--format",
        choices=("argv", "shell", "json"),
        default="shell",
        help="Output format (default: shell comment + command)",
    )
    args = parser.parse_args(argv)

    meta_path: Path | None = None
    if args.metadata:
        meta_path = Path(args.metadata)
    elif args.bundle_dir:
        meta_path = Path(args.bundle_dir) / "metadata.json"
    else:
        parser.error("Provide --metadata or --bundle-dir")

    try:
        metadata = json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"Error reading metadata: {e}", file=sys.stderr)
        return 1

    argv_out = cli_args_from_metadata(metadata)
    unmapped = _unmapped_fields(metadata)
    if args.format == "json":
        print(json.dumps({"argv": argv_out, "unmapped_fields": unmapped}, indent=2))
    elif args.format == "argv":
        if unmapped:
            print(f"# unmapped fields (add manually if relevant): {', '.join(unmapped)}", file=sys.stderr)
        print(" ".join(argv_out), end="")
    else:
        bench = args.benchmark or metadata.get("benchmark")
        print(format_replay_command(metadata, benchmark=str(bench) if bench else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
