"""Evaluation loop for Oak Health Insurance tasks.

This script:
1. Loads tools from the registry
2. Evaluates each task in oak_health_test_suite_v1.json
3. Checks keywords in responses and tracks tool-call metrics
4. Reports results with filtering by difficulty

Supports both cuga and react agents via --agent flag.
"""

# CRITICAL: Load environment variables FIRST, before ANY other imports
import sys
from pathlib import Path

# Add project root to path to import config_loader from separate directory
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

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
from loguru import logger

# Import helpers after cuga modules (helpers import cuga modules too)
from benchmarks.helpers import (
    MetricsConfig,
    add_policy_via_agent,
    clear_all_policies,
    create_activity_tracker_callback,
    evaluate_task_with_langfuse,
    evaluate_task_with_langfuse_react,
    flush_langfuse,
    print_evaluation_summary,
    save_evaluation_results,
    setup_agent_with_tools,
    setup_react_agent_for_evaluation,
)

tracker = ActivityTracker()
var_manager = VariablesManager()

_METRICS_CONFIG: MetricsConfig = {"enable_api_metrics": True}


class OakEvaluator:
    """Evaluator for Oak Health Insurance tasks."""

    def __init__(
        self,
        difficulty_filter: Optional[str] = None,
        task_id: Optional[Union[str, List[str]]] = None,
        agent_type: str = "cuga",
        load_policies: bool = True,
    ):
        """
        Initialize the evaluator.

        Args:
            difficulty_filter: Filter by difficulty ("easy", "medium", "hard", or None for all)
            task_id: Filter by specific task ID(s)
            agent_type: Agent to use ("cuga" or "react")
            load_policies: Whether to load oak policies (default True)
        """
        self.difficulty_filter = difficulty_filter
        self.task_ids = [task_id] if isinstance(task_id, str) else task_id
        self.agent_type = agent_type
        self.load_policies = load_policies
        self.agent = None
        self.langfuse_handler = None
        self.results: List[Dict[str, Any]] = []

    async def setup(self):
        """Set up the agent with tools and optional policies."""
        if self.agent_type == "react":
            self.agent, self.langfuse_handler = await setup_react_agent_for_evaluation()
            logger.info("ReAct agent ready")
        else:
            self.agent, self.langfuse_handler = await setup_agent_with_tools()
            logger.info("Resetting policy database...")
            await clear_all_policies(self.agent)
            logger.info("CugaAgent ready")

        if self.load_policies:
            await self._load_oak_policies()

    async def _load_oak_policies(self):
        """Load oak health insurance policies into the agent."""
        try:
            from benchmarks.oak_health_insurance.oak_policies import get_all_oak_policies

            policies = get_all_oak_policies()
            logger.info(f"Loading {len(policies)} oak policies...")
            loaded = 0
            for policy in policies:
                try:
                    await add_policy_via_agent(self.agent, policy)
                    loaded += 1
                except Exception as e:
                    logger.warning(f"Skipping policy '{policy.id}': {e}")
            logger.info(f"✅ Loaded {loaded}/{len(policies)} policies")
        except Exception as e:
            logger.warning(f"Could not load oak policies: {e}")

    async def evaluate_task(self, task: Dict[str, Any], task_index: int) -> Dict[str, Any]:
        """Evaluate a single task."""
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

        if self.agent_type == "react":
            return await evaluate_task_with_langfuse_react(
                agent=self.agent,
                task=task,
                task_index=task_index,
                langfuse_handler=self.langfuse_handler,
                user_context=user_context,
                tracker_callback=tracker_callback,
                track_tool_calls=True,
                metrics_config=_METRICS_CONFIG,
            )
        else:
            return await evaluate_task_with_langfuse(
                agent=self.agent,
                task=task,
                task_index=task_index,
                langfuse_handler=self.langfuse_handler,
                user_context=user_context,
                tracker_callback=tracker_callback,
                track_tool_calls=True,
                metrics_config=_METRICS_CONFIG,
            )

    async def evaluate_all(self, oak_data_path: str = "oak_health_test_suite_v1.json"):
        """Evaluate all tasks from the test suite JSON."""
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
        elif self.difficulty_filter:
            test_cases = [
                tc for tc in test_cases if tc.get("difficulty", "").lower() == self.difficulty_filter.lower()
            ]
            logger.info(f"Filtered to {len(test_cases)} {self.difficulty_filter} tasks")
        else:
            logger.info(f"Evaluating all {len(test_cases)} tasks")

        experiment_name = os.getenv("OAK_EXPERIMENT_NAME", f"oak_health_{self.agent_type}_evaluation")
        task_ids = [tc.get("name", f"task_{i}") for i, tc in enumerate(test_cases, 1)]
        tracker.start_experiment(
            task_ids=task_ids,
            experiment_name=experiment_name,
            description=f"Oak Health Insurance benchmark evaluation ({self.agent_type})",
        )

        self.results = []
        for i, task in enumerate(test_cases, 1):
            logger.info(f"\n[{i}/{len(test_cases)}] Processing task...")
            result = await self.evaluate_task(task, task_index=i)
            self.results.append(result)

            if i < len(test_cases):
                await asyncio.sleep(0.5)

        flush_langfuse(self.langfuse_handler)

    def print_summary(self):
        """Print evaluation summary."""
        print_evaluation_summary(self.results)

    def save_results(self, output_dir: Optional[str] = None):
        """Save evaluation results to JSON files."""
        if output_dir is None:
            output_dir = Path(__file__).parent / "results"
        prefix = "react_oak_health" if self.agent_type == "react" else "oak_health"
        return save_evaluation_results(self.results, output_dir, prefix=prefix)


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
        help="Path to test suite JSON (default: oak_health_test_suite_v1.json)",
    )
    parser.add_argument(
        "--task",
        type=str,
        nargs="*",
        default=None,
        help="Run specific tasks by ID/name (e.g., 'care_providers_mri'). Accepts multiple. Overrides --difficulty filter.",
    )
    parser.add_argument(
        "--agent",
        type=str,
        choices=["cuga", "react"],
        default="cuga",
        help="Agent to run (default: cuga)",
    )
    parser.add_argument(
        "--no-policy",
        action="store_true",
        default=False,
        help="Skip loading oak policies",
    )
    from benchmarks.helpers.logging_args import add_log_level_args, apply_log_level

    add_log_level_args(parser)

    args = parser.parse_args()
    apply_log_level(args)

    evaluator = OakEvaluator(
        difficulty_filter=args.difficulty,
        task_id=args.task,
        agent_type=args.agent,
        load_policies=not args.no_policy,
    )

    try:
        await evaluator.setup()
        await evaluator.evaluate_all(args.data)
        evaluator.print_summary()
        evaluator.save_results()

    except KeyboardInterrupt:
        logger.warning("\nEvaluation interrupted by user")
        if evaluator.results:
            evaluator.print_summary()
            evaluator.save_results()
    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
