# ruff: noqa: S311  -- random is used for non-cryptographic pair sampling only
"""
Trace Comparison Analytics Pipeline

Orchestrates step-by-step comparison and root cause analysis
on Langfuse trace data from evaluation bundles.

Usage:
    python pipeline.py \\
      --benchmark appworld \\
      --agent-config appworld_mcp \\
      --rules latest \\
      [--bundles all] \\
      [--since 2026-04-01] \\
      [--pairing-mode one_pair_per_task] \\
      [--n 5] \\
      [--model aws/claude-opus-4-6] \\
      [--prompt-file root_cause_analysis.jinja]

Mandatory: --benchmark, --agent-config, --rules
Optional:  --bundles (default: all), --since, --task-ids,
           --pairing-mode (default: one_pair_per_task), --n (default: 5),
           --model (default: aws/claude-opus-4-6),
           --prompt-file (default: root_cause_analysis.jinja)
"""

import argparse
import asyncio
import json
import random
import sys
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

# Ensure src/ is importable regardless of working directory.
_pipeline_dir = Path(__file__).resolve().parent
_src_dir = _pipeline_dir / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

# Project root: analytics/trace_comparison_rules/../../  →  repo root
_project_root = _pipeline_dir.parent.parent

DEFAULT_MODEL = "aws/claude-opus-4-6"
DEFAULT_PROMPT_FILE = "root_cause_analysis.jinja"


# ---------------------------------------------------------------------------
# Bundle discovery
# ---------------------------------------------------------------------------


def discover_bundles(benchmark: str, bundles_arg: list[str], since: str | None) -> list[Path]:
    """Return bundle directories that match the filter criteria."""
    bundles_root = _project_root / "benchmarks" / benchmark / "evaluation_bundles"
    if not bundles_root.is_dir():
        print(f"Bundles root not found: {bundles_root}")
        return []

    all_bundles = sorted(d for d in bundles_root.iterdir() if d.is_dir())

    if bundles_arg == ["all"]:
        candidates = all_bundles
    else:
        candidates = [bundles_root / b for b in bundles_arg if (bundles_root / b).is_dir()]
        missing = [b for b in bundles_arg if not (bundles_root / b).is_dir()]
        if missing:
            print(f"Warning: bundles not found and skipped: {missing}")

    if since:
        since_dt = datetime.fromisoformat(since).replace(tzinfo=timezone.utc)
        filtered = []
        for b in candidates:
            meta = b / "metadata.json"
            if not meta.exists():
                filtered.append(b)
                continue
            try:
                meta_data = json.loads(meta.read_text())
            except Exception as e:
                print(f"Warning: skipping {b.name} — could not parse metadata.json: {e}")
                continue
            created_raw = meta_data.get("created_at", "")
            if not created_raw:
                print(f"Warning: {b.name} has no created_at in metadata.json — including it.")
                filtered.append(b)
                continue
            try:
                created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            except ValueError as e:
                print(f"Warning: {b.name} has unparseable created_at {created_raw!r} — including it: {e}")
                filtered.append(b)
                continue
            if created >= since_dt:
                filtered.append(b)
        return filtered

    return candidates


# ---------------------------------------------------------------------------
# Trace inventory
# ---------------------------------------------------------------------------


def collect_traces(bundle_dirs: list[Path]) -> dict[str, list[dict]]:
    """
    Walk each bundle's run directories and collect Langfuse trace info per task_id.

    Returns:
        {task_id: [{"score": float, "trace_path": Path}, ...]}
    """
    by_task: dict[str, list[dict]] = {}

    for bundle in bundle_dirs:
        runs_dir = bundle / "runs"
        if not runs_dir.is_dir():
            continue
        for run_dir in sorted(runs_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            results_file = run_dir / "trajectories" / "results.json"
            traces_dir = run_dir / "langfuse_traces"
            if not results_file.exists() or not traces_dir.is_dir():
                continue
            try:
                results = json.loads(results_file.read_text())
            except Exception as e:
                print(f"Warning: could not read {results_file}: {e}")
                continue
            for task_id, task_data in results.items():
                score = task_data.get("score")
                if score is None:
                    continue
                # Trace file pattern: {task_id}_{trace_id}.json
                trace_files = list(traces_dir.glob(f"{task_id}_*.json"))
                if not trace_files:
                    continue
                by_task.setdefault(task_id, []).append(
                    {
                        "score": float(score),
                        "trace_path": trace_files[0],
                    }
                )

    return by_task


# ---------------------------------------------------------------------------
# Pair construction
# ---------------------------------------------------------------------------


MAX_PAIRS_DEFAULT = 50


def build_pairs(
    by_task: dict[str, list[dict]],
    pairing_mode: str,
    n: int = 1,
    max_pairs: int | None = MAX_PAIRS_DEFAULT,
) -> tuple[list[str], list[str]]:
    """
    Build parallel (successful_path, failed_path) lists.

    Modes:
        all_permutations   — every (success, fail) combo per task
        one_pair_per_task  — one random pair per task that has both outcomes
        n_pairs            — N pairs total, preferring different tasks when possible
        all_trajectories   — every trace participates in at least one comparison
                             (per task: shuffle both lists, zip with recycling of
                             the shorter list until the longer list is exhausted)

    max_pairs caps the total for all_permutations and all_trajectories.
    Pass None to disable the cap.
    """
    pairs: list[tuple[Path, Path]] = []

    for task_id, traces in sorted(by_task.items()):
        successes = [t["trace_path"] for t in traces if t["score"] == 1.0]
        failures = [t["trace_path"] for t in traces if t["score"] < 1.0]
        if not successes or not failures:
            continue

        if pairing_mode == "all_permutations":
            for s, f in product(successes, failures):
                pairs.append((s, f))
        elif pairing_mode == "one_pair_per_task":
            pairs.append((random.choice(successes), random.choice(failures)))
        elif pairing_mode == "all_trajectories":
            random.shuffle(successes)
            random.shuffle(failures)
            length = max(len(successes), len(failures))
            for i in range(length):
                pairs.append(
                    (
                        successes[i % len(successes)],
                        failures[i % len(failures)],
                    )
                )
        elif pairing_mode == "n_pairs":
            pairs.append((random.choice(successes), random.choice(failures)))

    if pairing_mode == "n_pairs":
        random.shuffle(pairs)
        pairs = pairs[:n]

    if pairing_mode in ("all_permutations", "all_trajectories") and max_pairs is not None:
        if len(pairs) > max_pairs:
            print(f"Capping {len(pairs)} pairs to --max-pairs {max_pairs}.")
            random.shuffle(pairs)
            pairs = pairs[:max_pairs]

    return [str(p[0]) for p in pairs], [str(p[1]) for p in pairs]


# ---------------------------------------------------------------------------
# Agent prompt loader
# ---------------------------------------------------------------------------


def load_agent_prompts(agent_config: str) -> dict[str, str]:
    """Load agent prompts using cuga_agent_manifest.json to map agent names to .jinja2 files."""
    prompts_dir = _pipeline_dir / "agent_prompts" / agent_config
    if not prompts_dir.is_dir():
        print(f"Warning: agent prompts directory not found: {prompts_dir}")
        return {}

    names_file = prompts_dir / "cuga_agent_manifest.json"
    if not names_file.exists():
        print(f"Warning: cuga_agent_manifest.json not found in {prompts_dir}")
        return {}

    entries = json.loads(names_file.read_text())

    agent_prompts = {}
    for entry in entries:
        agent_name = entry["agent_name"]
        prompt_file = prompts_dir / entry["system_prompt"]
        if prompt_file.exists():
            agent_prompts[agent_name] = prompt_file.read_text()
        else:
            print(f"Warning: prompt file not found: {prompt_file}")
    return agent_prompts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Run trace comparison analytics on evaluation bundles.")
    parser.add_argument("--benchmark", required=True, help="Benchmark name, e.g. appworld")
    parser.add_argument(
        "--bundles",
        nargs="+",
        default=["all"],
        help="Bundle folder names, 'all', or use --since for date filtering",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Include only bundles created on/after this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--agent-config",
        required=True,
        help="Subfolder under agent_prompts/ (e.g. appworld_mcp)",
    )
    parser.add_argument(
        "--rules",
        required=True,
        help="Rules filename inside comparison_rules/, or 'latest'",
    )
    parser.add_argument(
        "--pairing-mode",
        default="one_pair_per_task",
        choices=["all_permutations", "one_pair_per_task", "n_pairs", "all_trajectories"],
    )
    parser.add_argument("--n", type=int, default=5, help="Number of pairs for n_pairs mode (default: 5)")
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=MAX_PAIRS_DEFAULT,
        help=f"Max pairs for all_permutations and all_trajectories modes (default: {MAX_PAIRS_DEFAULT}). "
        "Set to 0 to disable.",
    )
    parser.add_argument(
        "--task-ids",
        nargs="+",
        default=None,
        help="Restrict analysis to these task IDs (e.g. e775c78_1 fd1f8fa_2). "
        "Default: all tasks found in the bundles.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"LLM model (default: {DEFAULT_MODEL})")
    parser.add_argument(
        "--prompt-file",
        default=DEFAULT_PROMPT_FILE,
        help=f"Root cause analysis prompt template (default: {DEFAULT_PROMPT_FILE})",
    )
    args = parser.parse_args()

    # --- Bundle discovery ---
    bundle_dirs = discover_bundles(args.benchmark, args.bundles, args.since)
    if not bundle_dirs:
        print("No bundles found matching the criteria.")
        sys.exit(1)
    print(f"Found {len(bundle_dirs)} bundle(s).")

    # --- Trace inventory ---
    by_task = collect_traces(bundle_dirs)
    if not by_task:
        print("No Langfuse traces found in the selected bundles.")
        sys.exit(0)

    # --- Task ID filter ---
    if args.task_ids:
        unknown = [t for t in args.task_ids if t not in by_task]
        if unknown:
            print(f"Warning: task IDs not found in any bundle: {unknown}")
        by_task = {t: by_task[t] for t in args.task_ids if t in by_task}
        if not by_task:
            print("None of the specified task IDs were found. Analytics cannot run.")
            sys.exit(0)
        print(f"Filtering to {len(by_task)} task(s): {list(by_task)}")

    # --- Guard clause ---
    has_pairs = any(
        any(t["score"] == 1.0 for t in traces) and any(t["score"] < 1.0 for t in traces)
        for traces in by_task.values()
    )
    if not has_pairs:
        print(
            "No tasks have both a successful and a failed trace in the selected bundles. "
            "Analytics cannot run."
        )
        sys.exit(0)

    # --- Pair construction ---
    max_pairs = None if args.max_pairs == 0 else args.max_pairs
    successful_logs, failed_logs = build_pairs(by_task, args.pairing_mode, args.n, max_pairs)
    if not successful_logs:
        print("No pairs could be constructed. Analytics cannot run.")
        sys.exit(0)
    print(f"Constructed {len(successful_logs)} pair(s) using mode '{args.pairing_mode}'.")

    # --- Run output folder (one per pipeline run) ---
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_folder = (
        _project_root
        / "benchmarks"
        / args.benchmark
        / "analytics_output"
        / "trace_comparison_rules"
        / f"{run_timestamp}_{args.benchmark}_{args.agent_config}"
    )
    run_folder.mkdir(parents=True, exist_ok=True)

    # --- Experiment config (written at end with token usage) ---
    pairs_index = [
        {
            "comparison": i + 1,
            "successful_trace": Path(s).stem,
            "failed_trace": Path(f).stem,
        }
        for i, (s, f) in enumerate(zip(successful_logs, failed_logs))
    ]
    config_data = {
        "created_at": datetime.now(timezone.utc).isoformat() + "Z",
        "benchmark": args.benchmark,
        "agent_config": args.agent_config,
        "rules_file": args.rules,
        "bundles": args.bundles,
        "since": args.since,
        "task_ids": args.task_ids,
        "pairing_mode": args.pairing_mode,
        "n": args.n,
        "model": args.model,
        "prompt_file": args.prompt_file,
        "num_pairs": len(successful_logs),
        "pairs": pairs_index,
    }

    # --- Rules file ---
    rules_dir = _pipeline_dir / "comparison_rules"
    if args.rules == "latest":
        rules_files = sorted(rules_dir.glob("*.txt"))
        if not rules_files:
            print(f"No rules files found in {rules_dir}.")
            sys.exit(1)
        rules_file = rules_files[-1].name
    else:
        rules_file = args.rules
    print(f"Using rules file: {rules_file}")

    # --- Agent prompts ---
    agent_prompts = load_agent_prompts(args.agent_config)

    # --- Step-by-step comparison ---
    import root_cause_analysis as _rca
    from trace_step_comparison import run_comparison

    _rca.MODEL = args.model

    print("\n--- Step-by-step comparison ---")
    step_output_path = asyncio.run(
        run_comparison(
            successful_logs=successful_logs,
            failed_logs=failed_logs,
            agent_data_file=rules_file,
            agent_prompts=agent_prompts,
            trace_format="langfuse",
            output_dir=str(run_folder),
        )
    )

    if not step_output_path:
        print("Step-by-step comparison produced no output. Skipping root cause analysis.")
        sys.exit(0)
    print(f"Step-by-step comparison output: {step_output_path}")

    # --- Root cause analysis ---
    from root_cause_analysis import run_root_cause_analysis

    print("\n--- Root cause analysis ---")
    summary_path, llm_usage = run_root_cause_analysis(
        prompt_file=args.prompt_file,
        input_data=Path(step_output_path).name,
        input_dir=str(run_folder),
        output_dir=str(run_folder),
    )
    print(f"Root cause analysis output: {summary_path}")

    # --- Write config.json with token usage ---
    if llm_usage:
        config_data["llm_usage"] = llm_usage
    (run_folder / "config.json").write_text(json.dumps(config_data, indent=2) + "\n")

    print(f"\nPipeline complete. Outputs in:\n  {run_folder}")


if __name__ == "__main__":
    main()
