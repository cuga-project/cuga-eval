# CRITICAL: Load environment variables FIRST, before ANY other imports
import sys
from pathlib import Path

# Add project root to path to import config_loader from separate directory
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Add appworld benchmark directory to path for local utils imports
appworld_benchmark_dir = Path(__file__).parent
sys.path.insert(0, str(appworld_benchmark_dir))

# Add appworld source directory to path
appworld_src = appworld_benchmark_dir / "appworld" / "src"
if appworld_src.is_dir():
    sys.path.insert(0, str(appworld_src))

# Import and call config loader before anything else (from separate directory)
from config_loader import load_eval_config

load_eval_config("appworld")

# Verify env vars are set before importing cuga modules
import os

cuga_logging_dir = os.getenv("CUGA_LOGGING_DIR")
if not cuga_logging_dir:
    raise RuntimeError("CUGA_LOGGING_DIR not set after load_eval_config! Check config files.")

# Now safe to import other modules
import argparse
import asyncio
import json
import time
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import requests
from opentelemetry import trace

try:
    from langfuse import get_client as _get_langfuse_client

    _LANGFUSE_AVAILABLE = True
except ImportError:
    _get_langfuse_client = None  # type: ignore[assignment]
    _LANGFUSE_AVAILABLE = False

from appworld import AppWorld, load_task_ids
from cuga.backend.activity_tracker.tracker import ActivityTracker, Step
from cuga.backend.cuga_graph.state.agent_state import VariablesManager
from cuga.backend.cuga_graph.utils.controller import AgentRunner, ExperimentResult
from cuga.config import settings
from cuga.evaluation.langfuse.get_langfuse_data import LangfuseTraceHandler
from loguru import logger
from utils.appworld_data_collection import ExperimentManager
from utils.appworld_utils import (
    appworld_task_info,
    evaluation_task_info,
    get_specific_task_levels,
    get_task_difficulty,
)

tracker = ActivityTracker()
var_manager = VariablesManager()


# Configure logging

cuga_agent = None


# Initialize logging with agent_analytics_sdk
# agent_analytics_sdk.initialize_logging(
#     logs_dir_path="./logs/traces",
#     log_filename="trace",
#     config=OTLPCollectorConfig(
#         endpoint="https://localhost:4318",
#         app_name='cuga',
#     ),
# )
#


@dataclass
class Config:
    """Configuration for the enhanced ReAct agent."""

    # LLM settings
    model_name: str = "gpt-4o"  # Default model
    temperature: float = 0.2  # Slight randomness for creative problem-solving
    max_tokens: int = 2000  # Increased from original to allow for more complex responses
    seed: int = 100  # For reproducibility

    # Provider settings
    provider: str = "openai"  # Options: "openai", "anthropic"

    # Agent behavior settings
    max_retries: int = 3  # Number of times to retry on LLM errors
    retry_delay: int = 2  # Seconds to wait between retries
    max_history_tokens: int = 14000  # Maximum tokens to keep in history

    # Server settings
    environment_url: Optional[str] = None  # URL of the environment server
    apis_url: Optional[str] = None  # URL of the API server
    agent_server_url: Optional[str] = None  # URL of the agent server

    # Prompt customization
    use_examples: bool = True  # Whether to include examples in the prompt
    prompt_template_path: Optional[str] = None  # Path to custom prompt template

    # Misc settings
    verbose: bool = True  # Whether to print verbose logs

    # specific_tasks
    specific_tasks: Optional[List[str]] = None  # List of specific task IDs to run
    specific_task_levels: Optional[List[int]] = None  # List of specific task levels to run

    langfuse_public_key: Optional[str] = os.getenv("LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: Optional[str] = os.getenv("LANGFUSE_SECRET_KEY")
    langfuse_host: Optional[str] = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    agent_type: str = "cuga"


# async def execute_agent_wrapper(task: str):
#     @start_trace(sessionid="test-session", userid="test-user", root_span_name=task_id)
#     def cusotm_funct_2():
#         print("Hi")

#     cusotm_funct_2()


def get_current_trace_id() -> Optional[str]:
    """
    Returns the current trace ID as a hex string if available.

    Returns:
        Optional[str]: The current trace ID as a hexadecimal string, or None if no active trace.
    """
    current_span = trace.get_current_span()
    span_context = current_span.get_span_context()

    if not span_context.is_valid:
        return None

    # Convert the trace ID to a hexadecimal string
    # trace_id is stored as an integer internally
    trace_id_hex = format(span_context.trace_id, "032x")

    return trace_id_hex


def format_time_custom():
    # Get current time
    now = datetime.now()

    # Format as {HH-HH-SS}
    formatted_time = "" + f"{now.hour:02d}-{now.minute:02d}-{now.second:02d}" + ""

    return formatted_time


async def run_agent_on_task(
    task_id: str,
    experiment_name: str = "api_cuga_agent",
    config: Optional[Config] = None,
    save_outputs: bool = True,
    experiment_manager: Optional[ExperimentManager] = None,
):
    """
    Run the agent on a single task.

    Args:
        task_id: The ID of the task to run
        experiment_name: Name of the experiment for saving outputs
        config: Configuration
        max_interactions: Maximum number of interactions with the environment
        save_outputs: Whether to save agent state and outputs to disk

    Returns:
        A tuple of (success: bool, steps: int)
    """
    if config and config.agent_type != "cuga":
        raise NotImplementedError(
            f"Agent '{config.agent_type}' is not implemented yet for AppWorld. "
            "CLI plumbing is in place; next step is wiring the generic ReAct runtime."
        )

    start_time = time.time()
    end_time = None
    langfuse_trace_id = None
    # Initialize task result tracking
    task_metadata = get_task_difficulty(task_id)
    print(task_metadata)
    task_result = None
    agent_runner = AgentRunner(browser_enabled=False)
    result: ExperimentResult = ExperimentResult(answer="", number_of_actions=0, score=0, messages=[])

    # Pre-generate a trace_id so all agent steps land in a single Langfuse trace.
    # Without this, LangfuseCallbackHandler creates a new root trace for every
    # agent_loop_obj.run() call in the controller while-loop.
    _langfuse = None
    if _LANGFUSE_AVAILABLE and _get_langfuse_client is not None:
        try:
            _langfuse = _get_langfuse_client()
            _run_uid = uuid.uuid4().hex[:8]
            langfuse_trace_id = _langfuse.create_trace_id(seed=f"{task_id}_{_run_uid}")
        except Exception as _lf_err:
            logger.warning(f"Langfuse init failed, tracing disabled: {_lf_err}")

    with AppWorld(
        task_id=task_id,
        experiment_name=experiment_name,
        remote_environment_url=config.environment_url if config else None,
        remote_apis_url=config.apis_url if config else None,
    ) as world:
        logger.info(f"Running task: {task_id}")
        task = world.task.instruction
        logger.info(f"Task instruction: {task}")
        is_error = False
        total_steps = 0  # see issue #50; initialised here so the exception path below stays defined.

        try:
            tracker.reset(intent=world.task.instruction, task_id=world.task_id)
            var_manager.reset()
            tracker.current_date = world.task.datetime.isoformat()
            tracker.pi = json.dumps(world.task.supervisor)
            # current datetime added to pi:
            tracker.pi += f"current_datetime: {tracker.current_date}"

            requests.get("http://localhost:8001/api/reset", timeout=10)
            await agent_runner.initialize_appworld_env()

            _lf_ctx = (
                _langfuse.start_as_current_observation(
                    as_type="span",
                    name=f"appworld_{task_id}",
                    trace_context={"trace_id": langfuse_trace_id},
                    input={"task_id": task_id, "intent": world.task.instruction},
                )
                if _langfuse and langfuse_trace_id
                else None
            )
            if _lf_ctx:
                _lf_ctx.__enter__()
            try:
                result = await agent_runner.run_task_generic(
                    eval_mode=False,
                    goal=world.task.instruction,
                    current_datetime=tracker.current_date,
                )
            finally:
                if _lf_ctx:
                    _lf_ctx.__exit__(None, None, None)

            # Capture the full step count before filtering. tracker.actions_count
            # is never incremented in cuga-agent and tracker.steps only sees the
            # one EvaluationResult step we collect below, so without this
            # capture task_result.steps comes out as ~0 — making the bundle's
            # avg_steps useless (issue #50). result.steps at this point contains
            # every graph-node execution (planning, reasoning, code, api_call,
            # final answer), which is the right complexity signal.
            total_steps = len(result.steps)
            filtered_steps = [step for step in result.steps if "api_call" in step.name]
            result.steps = filtered_steps
            end_time = time.time()
            await agent_runner.env.close()

            if _langfuse:
                try:
                    _langfuse.flush()
                except Exception:  # noqa: S110 — flush is best-effort cleanup
                    pass
        except Exception as e:
            await agent_runner.env.close()
            logger.error(traceback.format_exc())
            is_error = True
            logger.error(e)

        # await copy_file_async("./logs/traces/trace.log", f"trace_{task_id}__{format_time_custom()}.log")
        # await copy_file_async("./logs/traces/trace.log", f"trace_backup.log")
        # os.remove('./logs/traces/trace.log')
        if experiment_manager:
            task_result = experiment_manager.create_task_result(task_id, task_metadata)
            task_result.add_appworld_data(appworld_task_info(world, config, task_metadata))
            task_result.api_calls = len(result.steps)

        # Capture events if tracking results
        if task_result:
            task_result.add_event(None)
        # if is_error:
        #     if experiment_manager:
        #         if task_result:
        #             task_result.add_exception(e, "run_agent_on_task")
        #             experiment_manager.update_task_result(task_result)
        #         else:
        #             experiment_manager.handle_exception(task_id, e, "run_agent_on_task")
        if result.answer.strip() != "N/A":
            st = "success" if not is_error else "fail"
            world.execute(
                "\n"
                + f"apis.supervisor.complete_task(status={repr(st)}, answer={repr(result.answer)})"
                + "\n"
            )
        else:
            world.execute(
                "\n" + f"apis.supervisor.complete_task(status='{'success' if not is_error else 'fail'}')"
            )
        evaluation = world.evaluate()
        world.close_all()
        if evaluation.success:
            logger.info("**Task succeeded**")
        else:
            logger.warning("**Task failed**")

            logger.warning(f"Pass percentage: {str(evaluation.pass_percentage)}")
        res = evaluation.report(print_it=False, colorize=False, save_file_path=None)

        langfuse_data = None
        # Extract Langfuse data if trace_id is available
        langfuse_handler = LangfuseTraceHandler(langfuse_trace_id)
        langfuse_data = await langfuse_handler.get_langfuse_data()
        if langfuse_trace_id:
            task_result.trace_id = langfuse_trace_id
        if langfuse_data:
            task_result.total_llm_calls = langfuse_data.total_llm_calls
            task_result.total_tokens = langfuse_data.total_tokens
            task_result.total_cost = langfuse_data.total_cost
            task_result.node_timings = langfuse_data.node_timings
            task_result.llm_call_details = langfuse_data.llm_call_details
            task_result.generation_timings = langfuse_data.generation_timings
            task_result.full_execution_time = langfuse_data.full_execution_time
            task_result.total_cache_input_tokens = langfuse_data.total_cache_input_tokens
        report_md = json.dumps({"report": "---\n" + res})
        score = 1.0 if evaluation.success else 0.0
        tracker.finish_task(
            intent=world.task.instruction,
            site="",
            task_id=world.task_id,
            eval=report_md,
            score=score,
            agent_answer=result.answer,
            exception=is_error,
            num_steps=total_steps,
            total_llm_calls=task_result.total_llm_calls,
            total_tokens=task_result.total_tokens,
            total_cost=task_result.total_cost,
            total_cache_input_tokens=task_result.total_cache_input_tokens,
            duration=task_result.duration,
            agent_v="",
        )
        tracker.collect_step(Step(name="EvaluationResult", data=report_md))
        tracker.collect_score(score)
        if task_result:
            task_result.steps = total_steps  # see issue #50
            task_result.duration = end_time - start_time if start_time and end_time else 0
            if not task_result.total_tokens:
                task_result.total_tokens = tracker.token_usage
        eval_dict = evaluation_task_info(evaluation)
        task_result.add_evaluation(eval_dict) if task_result else None

        # logger.info(f"Evaluation result: {evaluation}")

        if task_result:
            task_result.success = eval_dict["success"]
            # task_result.steps = eval_dict['steps']

        # Update and save task result
        if experiment_manager and task_result:
            experiment_manager.update_task_result(task_result)

        # except Exception as e:
        #     raise e
        # logger.error(traceback.format_exc())

        # # Record the exception

        # return False, 0


async def run_agent_on_dataset(
    dataset_name: str,
    experiment_name: str = "api_cuga_agent",
    config: Optional[Config] = None,
    save_outputs: bool = True,
    continue_experiment: bool = False,
):
    """
    Run the EnhancedReActAgent on all tasks in a dataset.

    Args:
        dataset_name: Name of the dataset (e.g., "train", "dev", "test_normal")
        experiment_name: Name of the experiment for saving outputs
        config: Configuration for the agent
        max_interactions: Maximum number of interactions per task
        save_outputs: Whether to save agent state and outputs to disk

    Returns:
        A dictionary with summary statistics
    """
    # Initialize experiment manager
    experiment_manager = ExperimentManager(
        experiment_name=experiment_name,
        dataset_name=dataset_name,
        continue_experiment=continue_experiment,
    )

    datetime.now()

    try:
        task_ids = config.specific_tasks if config.specific_tasks else load_task_ids(dataset_name)

        # Filter by difficulty level if specified
        if config.specific_task_levels:
            task_ids = get_specific_task_levels(task_ids, config.specific_task_levels)
            logger.info(f"Filtered task IDs based on difficulty levels: {config.specific_task_levels}")

        experiment_manager.summary_report["tasks_total"] = len(task_ids)
        logger.info(f"Running {len(task_ids)} tasks from dataset '{dataset_name}'")
        # tracker.generate_session_id_for_code()
        for index, task_id in enumerate(task_ids):
            logger.info(f"\n\n{'*' * 20} Task {index + 1}/{len(task_ids)} ({task_id}) {'*' * 20}")

            # Run the task
            await run_agent_on_task(
                task_id=task_id,
                experiment_name=experiment_name,
                config=config,
                save_outputs=save_outputs,
                experiment_manager=experiment_manager,
            )

        # Save the final report
        experiment_manager.save_final_report()

        return experiment_manager.summary_report

    except Exception as e:
        logger.error(f"Error running dataset {dataset_name}: {e}")
        logger.error(traceback.format_exc())

        experiment_manager.handle_exception("global", e, "run_agent_on_dataset")
        experiment_manager.save_final_report()

        return experiment_manager.summary_report


def _print_appworld_summary(report: dict):
    """Print AppWorld results in the shared evaluation summary format."""
    total = report.get("tasks_total", 0)
    completed = report.get("tasks_completed", 0)
    success_rate = report.get("success_rate", 0)
    avg_steps = report.get("avg_steps", 0)
    avg_duration = report.get("avg_duration", 0)

    print("\n" + "=" * 80)
    print("EVALUATION COMPLETE")
    print("=" * 80)
    print(f"Total Tasks: {total}")
    print(f"Completed: {completed}/{total} ({success_rate:.1%})")
    print(f"Avg Steps: {avg_steps:.2f}")
    print(f"Avg Duration: {avg_duration:.2f}s")


async def main():
    parser = argparse.ArgumentParser(description="Run EnhancedReActAgent on AppWorld tasks")
    parser.add_argument("--task-id", nargs="*", help="Run specific task ID(s)")
    parser.add_argument(
        "--dataset",
        default="train",
        help="Dataset to run (train, dev, test_normal, test_challenge)",
    )
    parser.add_argument("--experiment-name", default="api_cuga_agent", help="Name for the experiment")
    parser.add_argument(
        "--environment-url",
        default=f"http://localhost:{settings.server_ports.environment_url}",
        help="URL of the environment server",
    )
    parser.add_argument(
        "--apis-url",
        default=f"http://localhost:{settings.server_ports.apis_url}",
        help="URL of the API server",
    )
    parser.add_argument(
        "--agent-server-url",
        default=f"http://localhost:{settings.server_ports.demo}/stream",
        help="URL of the agent server",
    )
    parser.add_argument("--evaluate", action="store_true", help="Run evaluation after completion")
    parser.add_argument(
        "--specific-task-levels",
        type=int,
        nargs="+",
        choices=[1, 2, 3],
        help="Run tasks with specific difficulty levels. Allowed values: 1, 2, 3. Example: --specific-task-levels 1 2",
    )
    parser.add_argument("--eval-key", dest="eval_key", help="Eval config settings.toml", required=False)

    parser.add_argument("specific_tasks", nargs="*", help="Specific task IDs to run, e.g., '82e2fac_1'")
    parser.add_argument(
        "--continue-experiment",
        action="store_true",
        help="Continue a previous experiment",
    )
    parser.add_argument(
        "--agent",
        type=str,
        choices=["cuga", "react"],
        default="cuga",
        help="Agent to run (default: cuga)",
    )

    from benchmarks.helpers.logging_args import add_log_level_args, apply_log_level

    add_log_level_args(parser)

    args = parser.parse_args()
    apply_log_level(args)
    print(args)
    eval_key = (
        args.eval_key
        if args.eval_key
        else (settings.eval_config.eval_key if settings.eval_config.eval_key else None)
    )
    eval_key_tasks = settings.eval_config.get(eval_key) if eval_key else None
    logger.debug(args.eval_key)

    # Determine filtered task list for progress tracking
    if args.task_id:
        filtered_task_ids = args.task_id
    elif args.specific_tasks:
        filtered_task_ids = args.specific_tasks
    else:
        filtered_task_ids = eval_key_tasks

    tracker.start_experiment(task_ids=filtered_task_ids, experiment_name=eval_key, description="")
    # Merge --task-id into specific_tasks for unified handling
    if args.task_id:
        specific_tasks = args.task_id
    elif args.specific_tasks:
        specific_tasks = args.specific_tasks
    else:
        specific_tasks = eval_key_tasks

    config = Config(
        environment_url=args.environment_url,
        apis_url=args.apis_url,
        agent_server_url=args.agent_server_url,
        specific_tasks=specific_tasks,
        specific_task_levels=args.specific_task_levels if args.specific_task_levels else None,
        agent_type=args.agent,
    )

    try:
        if args.task_id and len(args.task_id) == 1:  # Run a single task
            experiment_name = args.experiment_name
            dataset_name = "single_task"
            experiment_manager = ExperimentManager(
                experiment_name=experiment_name,
                dataset_name=dataset_name,
                continue_experiment=args.continue_experiment,
            )

            # Run the task
            await run_agent_on_task(
                task_id=args.task_id[0],
                experiment_name=args.experiment_name,
                config=config,
                experiment_manager=experiment_manager,
            )

            experiment_manager.save_final_report()
            report = experiment_manager.summary_report
            _print_appworld_summary(report)

        else:
            results = await run_agent_on_dataset(
                dataset_name=args.dataset,
                experiment_name=args.experiment_name,
                config=config,
                continue_experiment=args.continue_experiment,
            )
            _print_appworld_summary(results)

    except Exception as e:
        logger.error(f"Error in main: {e}")
        logger.error(traceback.format_exc())


def run_main():
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
