"""Evaluation loop for Oak Health Insurance tasks.

This script:
1. Loads policies from oak_policies.py
2. Loads tools from the registry
3. Evaluates each task in oak_data.json
4. Checks keywords in responses
5. Reports results with filtering by difficulty
"""

# CRITICAL: Load environment variables FIRST, before ANY other imports
import sys
from pathlib import Path

# Add project root to path to import config_loader from separate directory
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))
# Add oak directory to path for local imports (oak_policies, models, etc.)
sys.path.insert(0, str(Path(__file__).resolve().parent))

# WORKAROUND: CugaAgent auto-loads policies from CWD/.cuga directory.
# This is a design limitation - CugaAgent should accept explicit policy_dir parameter.
# Changing CWD affects global process state and is not thread-safe.
# TODO: Refactor CugaAgent to accept policy_dir parameter to eliminate this workaround.
import os

os.chdir(project_root)

# Import and call config loader before anything else (from separate directory)
from config_loader import load_eval_config

load_eval_config("oak_health_insurance")

# Now safe to import other modules
import asyncio
import json
import os
from typing import Any, Dict, List, Optional, Union

from cuga.backend.activity_tracker.tracker import ActivityTracker
from cuga.backend.cuga_graph.state.agent_state import VariablesManager

# Import cuga modules (these will read env vars, which are now set)
from cuga.sdk import CugaAgent
from loguru import logger
from oak_policies import get_all_oak_policies

# Import helpers after cuga modules (helpers import cuga modules too)
from benchmarks.helpers import (
    add_policy_via_agent,
    clear_all_policies,
    create_activity_tracker_callback,
    evaluate_task_with_langfuse,
    flush_langfuse,
    print_evaluation_summary,
    save_evaluation_results,
    setup_agent_with_tools,
)

tracker = ActivityTracker()
var_manager = VariablesManager()


class OakEvaluator:
    """Evaluator for Oak Health Insurance tasks."""

    def __init__(
        self,
        difficulty_filter: Optional[str] = None,
        task_id: Optional[Union[str, List[str]]] = None,
        policies_enabled: bool = True,
        bundle_dir: Optional[Path] = None,
        resume_completed_ids: Optional[set] = None,
    ):
        """
        Initialize the evaluator.

        Args:
            difficulty_filter: Filter by difficulty ("easy", "medium", "hard", or None for all)
            task_id: Filter by specific task ID(s) (if provided, only these tasks will be evaluated)
            policies_enabled: Whether to load policies (default: True)
            bundle_dir: When set, results persist incrementally under the bundle and the
                        final merge reads from disk, enabling crash-safe resume.
            resume_completed_ids: Task names already completed successfully; these are skipped.
        """
        self.difficulty_filter = difficulty_filter
        self.task_ids = [task_id] if isinstance(task_id, str) else task_id
        self.policies_enabled = policies_enabled
        self.bundle_dir = bundle_dir
        self.resume_completed_ids = resume_completed_ids or set()
        self.agent: Optional[CugaAgent] = None
        self.results: List[Dict[str, Any]] = []
        # Bound from __init__, not inside evaluate_all(): if evaluate_all() raises
        # before task discovery, total_tasks must still be 0 (not None) so the
        # partial-run check in main() can't be silently disabled by a future
        # refactor that catches exceptions inside evaluate_all().
        self.total_tasks: int = 0
        # Hardcoded user info (matching format from agent_state.py:879-882)

    async def setup(self):
        """Set up the agent with tools and policies."""
        self.agent, self.langfuse_handler = await setup_agent_with_tools()

        logger.info("Resetting policy database...")
        await clear_all_policies(self.agent)

        if self.policies_enabled:
            policies = get_all_oak_policies()
            logger.info(f"Loading {len(policies)} policies from oak_policies.py...")

            for policy in policies:
                await add_policy_via_agent(self.agent, policy)

            logger.info(f"✅ Loaded {len(policies)} policies")
        else:
            logger.info("Policies disabled (--no-policies)")

    async def evaluate_task(self, task: Dict[str, Any], task_index: int) -> Dict[str, Any]:
        """Evaluate a single task.

        Args:
            task: Task dictionary from oak_data.json
            task_index: Index of the task (for unique thread_id generation)

        Returns:
            Evaluation result dictionary
        """
        task_name = task.get("name", "unknown")
        intent = task.get("intent", "")

        tracker.reset(intent=intent, task_id=task_name)
        var_manager.reset()

        user_context = """
        Member ID (string): 121231234
        Location: latitude(str):40.7128, longitude(str):-74.0060
        Current Date: 2025-12-31
        """

        tracker_callback = create_activity_tracker_callback(tracker, var_manager)

        return await evaluate_task_with_langfuse(
            agent=self.agent,
            task=task,
            task_index=task_index,
            langfuse_handler=self.langfuse_handler,
            user_context=user_context,
            tracker_callback=tracker_callback,
            track_tool_calls=True,
            bundle_dir=self.bundle_dir,
        )

    async def evaluate_all(self, oak_data_path: str = "oak_data.json"):
        """
        Evaluate all tasks from oak_data.json.

        Args:
            oak_data_path: Path to oak_data.json file
        """
        # Load test data
        with open(oak_data_path, "r") as f:
            data = json.load(f)

        # Extract test cases
        test_cases = []
        for app_data in data:
            if "test_cases" in app_data:
                test_cases.extend(app_data["test_cases"])

        # Filter by task_ids if specified (takes precedence over difficulty filter)
        if self.task_ids:
            task_ids_lower = [tid.lower() for tid in self.task_ids]
            test_cases = [tc for tc in test_cases if tc.get("name", "").lower() in task_ids_lower]
            if not test_cases:
                logger.error(f"Task(s) {self.task_ids} not found in test data")
                return
            logger.info(f"Filtered to {len(test_cases)} task(s): {self.task_ids}")
        # Filter by difficulty if specified
        elif self.difficulty_filter:
            test_cases = [
                tc for tc in test_cases if tc.get("difficulty", "").lower() == self.difficulty_filter.lower()
            ]
            logger.info(f"Filtered to {len(test_cases)} {self.difficulty_filter} tasks")
        else:
            logger.info(f"Evaluating all {len(test_cases)} tasks")

        # Start experiment tracking
        experiment_name = os.getenv("OAK_EXPERIMENT_NAME", "oak_health_evaluation")
        task_ids = [tc.get("name", f"task_{i}") for i, tc in enumerate(test_cases, 1)]
        tracker.start_experiment(
            task_ids=task_ids,
            experiment_name=experiment_name,
            description="Oak Health Insurance benchmark evaluation",
        )

        # Total intended for this run; compared against len(self.results) so a
        # run that stops early (crash/interrupt) is detected as partial rather
        # than silently reported as complete.
        self.total_tasks = len(test_cases)

        # Evaluate each task
        self.results = []
        results_index: Dict[str, int] = {}  # task_name -> index (resume dedupe)
        if self.bundle_dir is not None:
            from benchmarks.helpers.incremental_results import load_all_partial_results

            for r in load_all_partial_results(self.bundle_dir):
                key = r.get("task_name")
                if key is not None:
                    results_index[key] = len(self.results)
                self.results.append(r)

        for i, task in enumerate(test_cases, 1):
            task_name = task.get("name", "unknown")
            if task_name in self.resume_completed_ids:
                logger.info(f"\n[{i}/{len(test_cases)}] Skipping already-completed task: {task_name}")
                continue
            logger.info(f"\n[{i}/{len(test_cases)}] Processing task...")
            # Pass task index to generate unique thread_id and ensure fresh state
            result = await self.evaluate_task(task, task_index=i)
            if task_name in results_index:
                self.results[results_index[task_name]] = result
            else:
                results_index[task_name] = len(self.results)
                self.results.append(result)

            # Small delay to avoid rate limiting between tasks
            if i < len(test_cases):  # Don't sleep after last task
                await asyncio.sleep(0.5)

        flush_langfuse(self.langfuse_handler)

    def print_summary(self):
        """Print evaluation summary."""
        print_evaluation_summary(self.results)

    def save_results(self, output_dir: Optional[str] = None):
        """Save evaluation results to JSON files."""
        if self.bundle_dir is not None:
            from benchmarks.helpers.incremental_results import finalize_merged_results

            return finalize_merged_results(self.bundle_dir, prefix="oak_health")
        if output_dir is None:
            output_dir = Path(__file__).parent / "results"
        return save_evaluation_results(self.results, output_dir, prefix="oak_health")


async def main():
    """Main evaluation function."""
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate Oak Health Insurance tasks")
    parser.add_argument(
        "--difficulty",
        type=str,
        choices=["easy", "medium", "hard"],
        default=None,
        help="Filter by difficulty level (default: all)",
    )
    parser.add_argument(
        "--data",
        type=str,
        default=os.path.join(os.path.dirname(__file__), "oak_health_test_suite_v1.json"),
        help="Path to oak_data.json (default: oak_data.json)",
    )
    parser.add_argument(
        "--task",
        type=str,
        nargs="*",
        default=None,
        help="Run specific tasks by ID/name (e.g., 'care_providers_mri'). Accepts multiple. Overrides --difficulty filter.",
    )
    parser.add_argument(
        "--no-policies",
        action="store_true",
        help="Disable CUGA policies (playbooks, tool guides). Useful for baselining.",
    )
    parser.add_argument(
        "--bundle-dir",
        type=str,
        default=None,
        help="Bundle workspace directory for incremental, resumable results.",
    )
    parser.add_argument(
        "--resume-task-ids",
        type=str,
        nargs="*",
        default=None,
        help="Task names to treat as already completed (skip). Usually computed by the shell layer.",
    )

    from benchmarks.helpers.logging_args import add_log_level_args, apply_log_level

    add_log_level_args(parser)

    args = parser.parse_args()
    apply_log_level(args)

    # Resolve bundle workspace + resume skip-set (success-only + explicit overrides)
    bundle_dir = Path(args.bundle_dir) if args.bundle_dir else None
    resume_completed_ids: set = set()
    if bundle_dir is not None:
        from benchmarks.helpers.incremental_results import load_completed_task_ids

        resume_completed_ids |= load_completed_task_ids(bundle_dir)
    if args.resume_task_ids:
        resume_completed_ids |= set(args.resume_task_ids)

    # Create evaluator
    evaluator = OakEvaluator(
        difficulty_filter=args.difficulty,
        task_id=args.task,
        policies_enabled=not args.no_policies,
        bundle_dir=bundle_dir,
        resume_completed_ids=resume_completed_ids,
    )

    exit_code = 0
    try:
        await evaluator.setup()
        await evaluator.evaluate_all(args.data)
    except KeyboardInterrupt:
        logger.warning("\nEvaluation interrupted by user")
        exit_code = 130
    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        import traceback

        traceback.print_exc()
        exit_code = 1
    finally:
        # Persist whatever completed — even on crash/interrupt — so partial
        # results are recoverable instead of orphaned, and so the harness
        # bundles this run's real (partial) data rather than falling back to a
        # previous run's report.
        results = getattr(evaluator, "results", None)
        if results:
            evaluator.print_summary()
            try:
                evaluator.save_results()
            except Exception as e:
                logger.error(f"Failed to save results: {e}")
                # A clean run that cannot persist its report is not a success —
                # don't let the process exit 0 with no durable result on disk.
                if exit_code == 0:
                    exit_code = 1
        else:
            logger.warning("No results to save")

    # Fewer results than intended means the run stopped early. Report it as a
    # failure so the harness does not present a partial run as a clean pass.
    total = getattr(evaluator, "total_tasks", None)
    completed = len(getattr(evaluator, "results", []) or [])
    if exit_code == 0 and total is not None and completed < total:
        logger.error(f"Partial run: only {completed}/{total} tasks completed — marking as failed")
        exit_code = 2

    if exit_code:
        sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
