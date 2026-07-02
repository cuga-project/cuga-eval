"""Best-effort reconstruction of eval CLI args from bundle metadata (M5)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


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
    parts = [script] + cli_args_from_metadata(metadata)
    return f"# Replay for {bench}\n" + " ".join(parts)


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
    if args.format == "json":
        print(json.dumps({"argv": argv_out}, indent=2))
    elif args.format == "argv":
        print(" ".join(argv_out), end="")
    else:
        bench = args.benchmark or metadata.get("benchmark")
        print(format_replay_command(metadata, benchmark=str(bench) if bench else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
