"""Evaluation loop for BPO Benchmark tasks.

This script:
1. Loads tools from the MCP server (stdio transport)
2. Evaluates each task in bpo_test_suite_v1.json
3. Checks keywords in responses
4. Reports results
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

load_eval_config("bpo")

# Verify env vars are set before importing cuga modules
import os

cuga_logging_dir = os.getenv("CUGA_LOGGING_DIR")
if not cuga_logging_dir:
    raise RuntimeError("CUGA_LOGGING_DIR not set after load_eval_config! Check config files.")

# Now safe to import other modules
import asyncio
import json
from typing import Any, Dict, List, Optional

from loguru import logger

logger.info(f"CUGA_LOGGING_DIR: {cuga_logging_dir}")
logger.info(f"MCP_SERVERS_FILE: {os.environ.get('MCP_SERVERS_FILE', 'not set')}")

# Import cuga modules (these will read env vars, which are now set)
from cuga.backend.activity_tracker.tracker import ActivityTracker
from cuga.backend.cuga_graph.state.agent_state import VariablesManager
from cuga.sdk import CugaAgent

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


class BPOEvaluator:
    """Evaluator for BPO Benchmark tasks."""

    def __init__(self, task_ids: Optional[List[str]] = None, policies_enabled: bool = True):
        """
        Initialize the evaluator.

        Args:
            task_ids: Filter by specific task IDs/names (if provided, only these tasks will be evaluated)
            policies_enabled: Whether to load policies from policies/policies.json (default: True)
        """
        self.task_ids = task_ids
        self.policies_enabled = policies_enabled
        self.agent: Optional[CugaAgent] = None
        self.results: List[Dict[str, Any]] = []

    async def setup(self):
        """Set up the agent with tools and optionally load policies."""
        self.agent, self.langfuse_handler = await setup_agent_with_tools()

        logger.info("Resetting policy database...")
        await clear_all_policies(self.agent)

        if self.policies_enabled:
            policies_file = os.path.join(os.path.dirname(__file__), "policies", "policies.json")
            if os.path.exists(policies_file):
                from cuga.backend.cuga_graph.policy.models import OutputFormatter, Playbook, ToolGuide

                with open(policies_file) as f:
                    policies_data = json.load(f)
                logger.info(f"Loading {len(policies_data)} policies from policies.json...")
                for pdata in policies_data:
                    ptype = pdata.get("type", "")
                    if ptype == "playbook":
                        policy = Playbook.model_validate(pdata)
                    elif ptype == "tool_guide":
                        policy = ToolGuide.model_validate(pdata)
                    elif ptype == "output_formatter":
                        policy = OutputFormatter.model_validate(pdata)
                    else:
                        logger.warning(f"Unknown policy type: {ptype}, skipping")
                        continue
                    await add_policy_via_agent(self.agent, policy)
                logger.info(f"✅ Loaded {len(policies_data)} policies")
            else:
                logger.warning(f"Policies file not found: {policies_file}")
        else:
            logger.info("Policies disabled (--no-policies)")

    async def evaluate_task(self, task: Dict[str, Any], task_index: int) -> Dict[str, Any]:
        """Evaluate a single task.

        Args:
            task: Task dictionary from bpo_test_suite_v1.json
            task_index: Index of the task (for unique thread_id generation)

        Returns:
            Evaluation result dictionary
        """
        task_name = task.get("name", f"task_{task_index}")
        intent = task.get("intent", "")

        tracker.reset(intent=intent, task_id=task_name)
        var_manager.reset()

        # BPO benchmark format instructions
        user_context = """BPO BENCHMARK FORMAT RULES:
- Do NOT invent or assume requisition IDs.
- Return ONLY the final answer (no analysis).
- Preserve punctuation, quotes, and markdown (e.g. **bold**, bullets) when needed.
- Percentages: no space before %, e.g. '67%'.
- If the expected answer is of the form '<Source> with <N>%', respond exactly like that.
- Lists: comma-separated with a single space after commas (e.g. 'A, B, C').
"""

        tracker_callback = create_activity_tracker_callback(tracker, var_manager)

        # BPO uses enhanced metrics: similarity, LLM judge, API tracking, final score
        metrics_config = {
            "enable_similarity": True,
            "enable_llm_judge": True,
            "llm_judge_provider": "groq",
            "enable_api_metrics": True,
            "expected_output_key": "expected_output.response",
            "final_score_threshold_exact": 0.85,
            "final_score_threshold_inexact": 0.9,
            "similarity_method": "rapidfuzz_token_set",
            "require_api_match": True,  # Fail if expected APIs weren't called
        }

        return await evaluate_task_with_langfuse(
            agent=self.agent,
            task=task,
            task_index=task_index,
            langfuse_handler=self.langfuse_handler,
            user_context=user_context,
            tracker_callback=tracker_callback,
            track_tool_calls=True,
            metrics_config=metrics_config,
        )

    async def evaluate_all(self, data_paths=None):
        """
        Evaluate all tasks from one or more test suite JSON files.

        Args:
            data_paths: Path(s) to test suite file(s). Accepts a string or list of strings.
                        Defaults to bpo_test_suite_v1.json.
        """
        if data_paths is None:
            data_paths = [os.path.join(os.path.dirname(__file__), "data", "bpo_test_suite_v1.json")]
        elif isinstance(data_paths, str):
            data_paths = [data_paths]

        # Load and merge test cases from all files
        test_cases = []
        for data_path in data_paths:
            logger.info(f"Loading tasks from: {data_path}")
            with open(data_path, "r") as f:
                data = json.load(f)
            for app_data in data:
                if "test_cases" in app_data:
                    test_cases.extend(app_data["test_cases"])
        logger.info(f"Loaded {len(test_cases)} total tasks from {len(data_paths)} file(s)")

        # Filter by task_ids if specified
        if self.task_ids:
            task_ids_lower = [tid.lower() for tid in self.task_ids]
            test_cases = [
                tc
                for tc in test_cases
                if tc.get("name", "").lower() in task_ids_lower
                or tc.get("name", "").lower() in [f"task_{tid}" for tid in task_ids_lower]
                or str(tc.get("id", "")) in self.task_ids
            ]
            if not test_cases:
                logger.error(f"Tasks {self.task_ids} not found in test data")
                return
            logger.info(f"Filtered to tasks: {self.task_ids}")
        else:
            logger.info(f"Evaluating all {len(test_cases)} tasks")

        # Start experiment tracking
        experiment_name = os.getenv("BPO_EXPERIMENT_NAME", "bpo_evaluation")
        task_ids = [tc.get("name", f"task_{i}") for i, tc in enumerate(test_cases, 1)]
        tracker.start_experiment(
            task_ids=task_ids,
            experiment_name=experiment_name,
            description="BPO benchmark evaluation",
        )

        # Evaluate each task
        self.results = []
        for i, task in enumerate(test_cases, 1):
            logger.info(f"\n[{i}/{len(test_cases)}] Processing task...")
            # Pass task index to generate unique thread_id and ensure fresh state
            result = await self.evaluate_task(task, task_index=i)
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
        if output_dir is None:
            output_dir = Path(__file__).parent / "results"
        return save_evaluation_results(self.results, output_dir, prefix="bpo")


async def main():
    """Main evaluation function."""
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate BPO Benchmark tasks")
    default_data_file = os.path.join(
        os.path.dirname(__file__),
        os.getenv("BPO_DATA_FILE", os.path.join("data", "bpo_test_suite_v1.json")),
    )
    parser.add_argument(
        "--data",
        type=str,
        nargs="+",
        default=[default_data_file],
        help="One or more task JSON files to evaluate (default: bpo_test_suite_v1.json)",
    )
    parser.add_argument(
        "--task",
        type=str,
        nargs="*",
        default=None,
        help="Run specific tasks by ID/name. Accepts task names or numeric IDs.",
    )
    parser.add_argument(
        "--no-policies",
        action="store_true",
        help="Disable CUGA policies (playbooks, tool guides). Useful for baselining.",
    )

    from benchmarks.helpers.logging_args import add_log_level_args, apply_log_level

    add_log_level_args(parser)

    args = parser.parse_args()
    apply_log_level(args)

    # Create evaluator
    evaluator = BPOEvaluator(
        task_ids=args.task,
        policies_enabled=not args.no_policies,
    )

    try:
        # Setup
        await evaluator.setup()

        # Evaluate
        await evaluator.evaluate_all(args.data)

        # Print summary
        evaluator.print_summary()

        # Save results
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
