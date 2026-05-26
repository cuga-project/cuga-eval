"""Evaluation loop for M3 multi-turn tasks.

This script:
1. Loads policies (optional)
2. Loads tools from the registry
3. Evaluates each multi-turn task in olympics_mutliturn.json
4. Handles multiple turns in the same conversation thread
5. Checks keywords in final responses
6. Reports results
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

load_eval_config("m3")

# Verify env vars are set before importing cuga modules
import os

cuga_logging_dir = os.getenv("CUGA_LOGGING_DIR")
if not cuga_logging_dir:
    raise RuntimeError("CUGA_LOGGING_DIR not set after load_eval_config! Check config files.")

# Now safe to import other modules
import asyncio
import json
from typing import Any, Dict, List, Optional, Union

from loguru import logger

logger.info(f"CUGA_LOGGING_DIR: {cuga_logging_dir}")
logger.info(f"TRACKER_ENABLED: {os.environ.get('DYNACONF_ADVANCED_FEATURES__TRACKER_ENABLED', 'not set')}")

# Import cuga modules (these will read env vars, which are now set)
from cuga.backend.activity_tracker.tracker import ActivityTracker
from cuga.backend.cuga_graph.state.agent_state import VariablesManager
from cuga.sdk import CugaAgent

# Import helpers after cuga modules (helpers import cuga modules too)
from benchmarks.helpers import (
    add_policy_via_agent,
    clear_all_policies,
    create_activity_tracker_callback,
    evaluate_multiturn_task_with_langfuse,
    flush_langfuse,
    print_evaluation_summary,
    save_evaluation_results,
    setup_agent_with_tools,
)

tracker = ActivityTracker()
var_manager = VariablesManager()


class M3MultiTurnEvaluator:
    """Evaluator for M3 multi-turn tasks."""

    def __init__(self, task_id: Optional[Union[str, List[str]]] = None):
        """
        Initialize the evaluator.

        Args:
            task_id: Filter by specific task/sample ID(s) (if provided, only these will be evaluated)
        """
        self.task_ids = [task_id] if isinstance(task_id, str) else task_id
        self.agent: Optional[CugaAgent] = None
        self.results: List[Dict[str, Any]] = []

    async def setup(self, policies: Optional[List] = None):
        """Set up the agent with tools and policies."""
        special_instructions = ""
        self.agent, self.langfuse_handler = await setup_agent_with_tools(
            special_instructions=special_instructions
        )

        logger.info("Resetting policy database...")
        await clear_all_policies(self.agent)

        if policies:
            logger.info(f"Loading {len(policies)} policies...")
            for policy in policies:
                await add_policy_via_agent(self.agent, policy)
            logger.info(f"✅ Loaded {len(policies)} policies")
        else:
            logger.info("No policies to load")

    async def evaluate_multiturn_task(self, sample: Dict[str, Any], sample_index: int) -> Dict[str, Any]:
        """Evaluate a single multi-turn task.

        Args:
            sample: Sample dictionary from olympics_mutliturn.json
            sample_index: Index of the sample (for unique thread_id generation)

        Returns:
            Evaluation result dictionary
        """
        sample_id = sample.get("sample_id", "unknown")
        domain = sample.get("domain", "unknown")
        dialogue = sample.get("dialogue", {})
        turns = dialogue.get("turns", [])

        initial_intent = turns[0].get("query", "") if turns else ""
        tracker.reset(intent=initial_intent, task_id=sample_id)
        var_manager.reset()

        tracker_callback = create_activity_tracker_callback(tracker, var_manager)

        expected_output = sample.get("expected_output", {})
        expected_keywords = expected_output.get("keywords", []) if expected_output else []

        task_metadata = {
            "sample_id": sample_id,
            "domain": domain,
            "difficulty": sample.get("difficulty", "unknown"),
        }

        result = await evaluate_multiturn_task_with_langfuse(
            agent=self.agent,
            turns=turns,
            task_name=sample_id,
            task_index=sample_index,
            langfuse_handler=self.langfuse_handler,
            user_context=None,
            tracker_callback=tracker_callback,
            track_tool_calls=True,
            expected_keywords=expected_keywords,
            task_metadata=task_metadata,
        )

        result["sample_id"] = sample_id
        return result

    async def evaluate_all(self, data_path: str = None):
        """
        Evaluate all samples from olympics_mutliturn.json.

        Args:
            data_path: Path to olympics_mutliturn.json file (defaults to data/olympics_mutliturn.json)
        """
        if data_path is None:
            data_path = os.path.join(os.path.dirname(__file__), "data", "olympics_mutliturn.json")

        # Load test data
        with open(data_path, "r") as f:
            data = json.load(f)

        # Filter by task_ids if specified
        if self.task_ids:
            task_ids_lower = [tid.lower() for tid in self.task_ids]
            data = [s for s in data if s.get("sample_id", "").lower() in task_ids_lower]
            if not data:
                logger.error(f"Task(s) {self.task_ids} not found in test data")
                return
            logger.info(f"Filtered to {len(data)} task(s): {self.task_ids}")
        else:
            logger.info(f"Evaluating all {len(data)} samples")

        # Start experiment tracking
        experiment_name = os.getenv("M3_MULTITURN_EXPERIMENT_NAME", "m3_multiturn_evaluation")
        sample_ids = [s.get("sample_id", f"sample_{i}") for i, s in enumerate(data, 1)]
        tracker.start_experiment(
            task_ids=sample_ids,
            experiment_name=experiment_name,
            description="M3 multi-turn benchmark evaluation",
        )

        # Evaluate each sample
        self.results = []
        for i, sample in enumerate(data, 1):
            logger.info(f"\n[{i}/{len(data)}] Processing sample...")
            result = await self.evaluate_multiturn_task(sample, sample_index=i)
            self.results.append(result)

            # Small delay to avoid rate limiting between samples
            if i < len(data):
                await asyncio.sleep(0.5)

        flush_langfuse(self.langfuse_handler)

    def print_summary(self):
        """Print evaluation summary."""
        print_evaluation_summary(self.results)

    def save_results(self, output_dir: Optional[str] = None):
        """Save evaluation results to JSON files."""
        if output_dir is None:
            output_dir = Path(__file__).parent / "results"
        return save_evaluation_results(self.results, output_dir, prefix="multiturn")


async def main():
    """Main evaluation function."""
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate M3 multi-turn tasks")
    parser.add_argument(
        "--task",
        "--sample",
        type=str,
        nargs="*",
        default=None,
        dest="task",
        help="Run specific tasks/samples by ID (e.g., '91_sc_ONLY_API_OUT_DOMAIN'). Accepts multiple.",
    )
    default_data_file = os.getenv("M3_MULTITURN_DATA_FILE", "olympics_mutliturn.json")
    parser.add_argument(
        "--data",
        type=str,
        default=os.path.join(os.path.dirname(__file__), "data", default_data_file),
        help=f"Path to data file (default: data/{default_data_file})",
    )
    from benchmarks.helpers.logging_args import add_log_level_args, apply_log_level

    add_log_level_args(parser)

    args = parser.parse_args()
    apply_log_level(args)

    # Create evaluator
    evaluator = M3MultiTurnEvaluator(task_id=args.task)

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
