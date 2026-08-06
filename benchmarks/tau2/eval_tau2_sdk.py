"""tau2-bench (τ²) evaluation entrypoint for cuga-eval.

Runs CUGA on τ² tasks and records results the same way as the other benchmarks:
per-task reward via ActivityTracker + a results/tau2_*.json in the schema compare_report
expects. The heavy lifting (the bridge round-trip) is in cuga_runner._run_one_task.

CRITICAL ordering rule: load_eval_config("tau2") MUST run before any `cuga` (or `tau2`)
import — it sets CUGA_LOGGING_DIR and other env vars cuga reads at import time.
"""

# CRITICAL: load env FIRST, before ANY other imports.
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from config_loader import load_eval_config

load_eval_config("tau2")

import os

cuga_logging_dir = os.getenv("CUGA_LOGGING_DIR")
if not cuga_logging_dir:
    raise RuntimeError("CUGA_LOGGING_DIR not set after load_eval_config! Check config files.")

# cuga / tau2 imports live BELOW, inside run() — keep them lazy so importing this module
# stays cheap and the config-first contract holds.
import argparse
import shutil
import time
from datetime import datetime
from typing import Any, Optional

SUBSETS = ["mock", "airline", "retail", "telecom"]


def _result_dict(
    domain: str,
    task: Any,
    reward: Optional[float],
    duration_s: float,
    error=None,
    trace_id: Optional[str] = None,
    agent_model: Optional[str] = None,
    user_sim_model: Optional[str] = None,
    reward_info: Optional[dict] = None,
    messages: Optional[list] = None,
) -> dict:
    """Per-task result in the shape compare_report / bundles expect (§11.5).

    `trace_id` is the Langfuse trace id — the bundle's --fetch-langfuse reads it from here
    to download each task's trace. `agent_model` + `user_sim_model` record BOTH LLMs: τ²
    scores are not comparable across user-sim choices, so both must live in the results.
    `reward_info` is τ²'s per-check breakdown (db/action/nl/communicate checks) — the "why"
    behind a non-1.0 reward, so failures are explainable straight from the results file.
    """
    success = reward is not None and reward >= 0.999
    return {
        "task_name": task.id,
        "task_id": task.id,
        "domain": domain,
        "success": success,
        "score": reward,
        "reward": reward,
        "full_execution_time": round(duration_s, 3),
        "trace_id": trace_id,
        "agent_model": agent_model,
        "user_sim_model": user_sim_model,
        "reward_info": reward_info,
        "messages": messages,
        "error": str(error) if error else None,
    }


def _user_sim_llm_args() -> dict:
    """Pass the user-simulator LLM's creds through to litellm. WatsonX reads its creds from
    env; the OpenAI-compatible gateway needs api_base/api_key passed explicitly."""
    args: dict = {}
    if os.getenv("WATSONX_PROJECT_ID"):
        args["project_id"] = os.getenv("WATSONX_PROJECT_ID")
    if os.getenv("OPENAI_BASE_URL"):
        args["api_base"] = os.getenv("OPENAI_BASE_URL")
        args["api_key"] = os.getenv("OPENAI_API_KEY")
    return args


def _parse_args(argv=None) -> argparse.Namespace:
    from benchmarks.helpers.logging_args import add_log_level_args, apply_log_level

    ap = argparse.ArgumentParser(description="Evaluate CUGA on tau2-bench.")
    ap.add_argument("--subset", default="mock", choices=SUBSETS)
    ap.add_argument("--task", nargs="*", dest="task_ids", default=None, help="specific task id(s)")
    ap.add_argument("--num-tasks", type=int, default=1)
    ap.add_argument(
        "--user-simulator-model",
        dest="user_sim_model",
        default=os.getenv("TAU2_USER_SIM_MODEL"),
        help="LiteLLM model string for τ²'s customer LLM (or set TAU2_USER_SIM_MODEL)",
    )
    # τ² counts every message (agent↔user, agent↔env) as a step. CUGA's exploratory
    # tool-call bursts consume steps fast, so the τ² default of 30 truncates real tasks
    # mid-action (retail measured 0→3/10 going 30→50). 50 clears the observed ceiling.
    ap.add_argument("--max-steps", type=int, default=50)
    ap.add_argument("--max-workers", type=int, default=1)
    ap.add_argument("--run-id", default=None)
    add_log_level_args(ap)  # --verbose / --quiet, same as the other entrypoints
    args = ap.parse_args(argv)
    apply_log_level(args)
    return args


def run(args: argparse.Namespace) -> list[dict]:
    if args.max_workers != 1:
        raise SystemExit("tau2 supports only --max-workers 1 (one bridge per process).")
    if not args.user_sim_model:
        raise SystemExit("--user-simulator-model (or env TAU2_USER_SIM_MODEL) is required.")

    from cuga.backend.activity_tracker.tracker import ActivityTracker
    from tau2.runner.helpers import get_tasks

    from benchmarks.helpers.incremental_results import (
        finalize_merged_results,
        partial_dir,
        write_task_result,
    )
    from benchmarks.tau2.cuga_runner import _run_one_task

    run_ts = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    llm_args_user = _user_sim_llm_args()
    # CUGA's own LLM (recorded alongside the user-sim model — see _result_dict/§11.5).
    agent_model = os.getenv("MODEL_NAME") or "unknown"

    # When explicit --task ids are given, run all of them: the --num-tasks default (1) must
    # NOT silently truncate an explicit id list (get_tasks applies num_tasks as a cap even
    # when task_ids are passed). Only apply num_tasks when no ids were requested.
    num_tasks = None if args.task_ids else args.num_tasks
    tasks = get_tasks(args.subset, task_ids=args.task_ids, num_tasks=num_tasks)
    if not tasks:
        raise SystemExit(f"No tasks found for subset={args.subset} task_ids={args.task_ids}.")

    tracker = ActivityTracker()
    tracker.start_experiment(
        task_ids=[t.id for t in tasks],
        experiment_name=f"tau2_{args.subset}",
        description=f"tau2 {args.subset} evaluation",
    )

    # Incremental, crash-safe persistence via the shared helper (same mechanism the other
    # benchmarks use): each task is written atomically under results/partial/, then all
    # partials are merged into the canonical results/tau2_*.json — at the end OR on a
    # crash/interrupt via `finally`. Start from a clean partial dir so a previous run's
    # partials aren't merged into this run's results.
    bundle_dir = Path(cuga_logging_dir)
    pdir = partial_dir(bundle_dir)
    if pdir.exists():
        shutil.rmtree(pdir, ignore_errors=True)

    results: list[dict] = []
    try:
        for i, task in enumerate(tasks, 1):
            # task.description is a τ² Description object, not a str — stringify for the tracker.
            intent = str(task.description) if task.description else task.id
            print(f"[{i}/{len(tasks)}] {task.id} — running...")
            tracker.reset(intent=intent, task_id=task.id)
            t0 = time.monotonic()
            reward: Optional[float] = None
            error = None
            extra: dict = {}
            try:
                reward = _run_one_task(
                    args.subset,
                    task,
                    args.user_sim_model,
                    llm_args_user=llm_args_user,
                    max_steps=args.max_steps,
                    out=extra,
                )
            except Exception as e:  # noqa: BLE001 — record the failure, keep going
                error = e
                print(f"    FAILED: {e!r}")
            dur = time.monotonic() - t0
            rd = _result_dict(
                args.subset,
                task,
                reward,
                dur,
                error,
                trace_id=extra.get("trace_id"),
                agent_model=agent_model,
                user_sim_model=args.user_sim_model,
                reward_info=extra.get("reward_info"),
                messages=extra.get("messages"),
            )
            results.append(rd)
            write_task_result(bundle_dir, task.id, rd, domain=args.subset)  # atomic per-task
            tracker.finish_task(
                task_id=task.id,
                site=f"tau2/{args.subset}",
                intent=intent,
                score=reward if reward is not None else 0.0,
                exception=bool(error),
                duration=int(dur),
            )
            if reward is not None:
                tracker.collect_score(reward)
            print(f"    reward={reward}  ({dur:.1f}s)")
    finally:
        # Merge whatever partials exist into the canonical results file — on normal
        # completion AND on crash/interrupt (strictly stronger than an in-memory save).
        saved = finalize_merged_results(bundle_dir, prefix="tau2", run_timestamp=run_ts)
    # tau2-shaped summary. (The shared print_evaluation_summary is bpo-specific — it hard-reads
    # `match_rate`, which tau2 results don't have; compare_report prints the full report at bundle.)
    passed = sum(1 for r in results if r["success"])
    print(f"\nPass@1: {passed}/{len(results)}  (agent: {agent_model}, user-sim: {args.user_sim_model})")
    print(f"Saved results -> {saved}")
    return results


def main() -> None:
    run(_parse_args())


if __name__ == "__main__":
    main()
