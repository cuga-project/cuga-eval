# CRITICAL: Load environment variables FIRST, before ANY other imports
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Add appworld benchmark directory to path for local utils/opencode imports
appworld_benchmark_dir = Path(__file__).parent.parent
sys.path.insert(0, str(appworld_benchmark_dir))

# Add appworld source directory to path
appworld_src = appworld_benchmark_dir / "appworld" / "src"
if appworld_src.is_dir():
    sys.path.insert(0, str(appworld_src))

from config_loader import load_eval_config

load_eval_config("appworld")

import os

# Load the root .env (LLM + Langfuse secrets) so the opencode harness reads the SAME variables as the
# rest of the framework — even when run directly (not via eval.sh's load_env.sh). `override=False` so
# values already set by the shell / model profiles / config files take precedence.
try:
    from dotenv import load_dotenv

    _root_env = project_root / ".env"
    if _root_env.exists():
        load_dotenv(_root_env, override=False)
except Exception:
    pass

cuga_logging_dir = os.getenv("CUGA_LOGGING_DIR")
if not cuga_logging_dir:
    raise RuntimeError("CUGA_LOGGING_DIR not set after load_eval_config! Check config files.")

import argparse
import asyncio
import json
import shutil
import tempfile
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import httpx
from appworld import AppWorld, load_task_ids  # pyright: ignore[reportAttributeAccessIssue]
from cuga.backend.activity_tracker.tracker import ActivityTracker, Step
from cuga.backend.cuga_graph.state.agent_state import VariablesManager
from cuga.config import settings
from loguru import logger
from utils.appworld_data_collection import ExperimentManager
from utils.appworld_utils import (
    appworld_task_info,
    evaluation_task_info,
    get_specific_task_levels,
    get_task_difficulty,
)
from opencode.bridge import AppWorldMcpBridge
from opencode.runner import OpencodeResult, compute_cost, opencode_available, run_opencode
from opencode.trace import summarize_tool_calls_for_trace

from benchmarks.helpers.sdk_eval_helpers import (
    is_langfuse_tracing_enabled,
    record_harness_trace_output,
)


@dataclass
class Config:
    # OpenCode is evaluated with MODEL_NAME (resolved by the runner when left None), matching how
    # react/codeact pick the configured model. OpenCode points directly at the LLM endpoint below.
    model_name: Optional[str] = None
    environment_url: Optional[str] = None
    apis_url: Optional[str] = None
    agent_server_url: Optional[str] = None
    verbose: bool = True
    specific_tasks: Optional[list[str]] = None
    specific_task_levels: Optional[list[int]] = None
    agent_type: str = "opencode"
    # OpenCode-specific knobs
    opencode_tools: str = "repl"  # "repl" | "apis"
    opencode_bin: str = "opencode"
    opencode_base_url: Optional[str] = None  # default: env LITE_LLM_URL/OPENAI_BASE_URL
    opencode_extra_args: Optional[list[str]] = None
    opencode_timeout: float = 900.0


def _print_appworld_summary(report: dict):
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


def _get_registry_base_url() -> str:
    registry_port = os.getenv("DYNACONF_SERVER_PORTS__REGISTRY")
    if registry_port:
        return f"http://localhost:{registry_port}"

    server_ports = getattr(settings, "server_ports", None)
    for attr_name in ("registry", "registry_url", "registry_port"):
        port = getattr(server_ports, attr_name, None) if server_ports else None
        if port:
            return f"http://localhost:{port}"

    return "http://localhost:8001"


async def _authenticate_apps(app_names: list[str]) -> dict[str, Any]:
    payload = {"apps": app_names}
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{_get_registry_base_url()}/api/authenticate_apps",
            json=payload,
            timeout=15.0,
        )
        response.raise_for_status()
        try:
            return response.json()
        except Exception:
            return {"status_code": response.status_code, "text": response.text[:500]}


def _resolve_llm_endpoint(config: Optional[Config]) -> tuple[str, str]:
    """Return (base_url, api_key) for OpenCode → LLM endpoint (same upstream the other agents use)."""
    base_url = (
        (config.opencode_base_url if config and config.opencode_base_url else None)
        or os.getenv("LITE_LLM_URL")
        or os.getenv("OPENAI_BASE_URL")
        or ""
    )
    api_key = os.getenv("LITE_LLM_KEY") or os.getenv("OPENAI_API_KEY") or "sk-none"
    return base_url, api_key


def _apply_usage(task_result: Any, usage: dict[str, Any], model: str) -> None:
    """Populate token/cost/call metrics from OpenCode's own JSON usage."""
    if task_result is None or not usage:
        return
    task_result.total_tokens = int(usage.get("total_tokens") or 0)
    task_result.total_llm_calls = int(usage.get("llm_calls") or 0)
    cost = usage.get("cost")
    if cost is None:
        cost = compute_cost(
            model, int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
        )
    task_result.total_cost = float(cost) if cost is not None else 0.0


async def run_agent_on_task(
    task_id: str,
    experiment_name: str = "api_opencode_agent",
    config: Optional[Config] = None,
    save_outputs: bool = True,
    experiment_manager: Optional[ExperimentManager] = None,
    tracker: Optional[ActivityTracker] = None,
):
    del save_outputs
    tracker = tracker or ActivityTracker()
    var_manager = VariablesManager()
    start_time = time.time()
    end_time = None
    task_metadata = get_task_difficulty(task_id)
    task_result = None

    mode = config.opencode_tools if config and config.opencode_tools else "repl"
    model = (config.model_name if config and config.model_name else None) or os.getenv("MODEL_NAME") or "gpt-4o"

    with AppWorld(
        task_id=task_id,
        experiment_name=experiment_name,
        remote_environment_url=config.environment_url if config else None,
        remote_apis_url=config.apis_url if config else None,
    ) as world:
        logger.info(f"Running task: {task_id}")
        logger.info(f"Task instruction: {world.task.instruction}")

        tracker.reset(intent=world.task.instruction, task_id=world.task_id)
        var_manager.reset()
        tracker.current_date = world.task.datetime.isoformat()
        tracker.pi = json.dumps(world.task.supervisor) + f"current_datetime: {tracker.current_date}"

        if experiment_manager:
            task_result = experiment_manager.create_task_result(task_id, task_metadata)
            task_result.add_appworld_data(appworld_task_info(world, config, task_metadata))

        app_names = sorted(world.task.app_descriptions.keys())
        try:
            auth_result = await _authenticate_apps(app_names)
            logger.info(f"[APPWORLD-OPENCODE] Registry authenticate_apps result: {auth_result}")
        except Exception as auth_exc:
            logger.warning(f"[APPWORLD-OPENCODE] authenticate_apps failed before task run: {auth_exc}")

        # Optional Langfuse: record a harness-level trace for this opencode run (no proxy — OpenCode's
        # per-LLM-call generations aren't traced; we push the run's I/O + token/cost/score). Reads
        # LANGFUSE_* from the same .env as the other agents.
        _langfuse = None
        predefined_trace_id: Optional[str] = None
        if is_langfuse_tracing_enabled():
            try:
                from langfuse import get_client

                _langfuse = get_client()
                predefined_trace_id = _langfuse.create_trace_id(seed=f"appworld_opencode_{task_id}")
                logger.info(f"[APPWORLD-OPENCODE] Langfuse trace ID: {predefined_trace_id}")
            except Exception as lf_err:
                logger.warning(f"[APPWORLD-OPENCODE] Langfuse init failed, tracing disabled: {lf_err}")

        tool_calls: list[dict[str, Any]] = []
        final_answer = ""
        executed_steps = 0
        opencode_result: Optional[OpencodeResult] = None
        is_error = False

        try:
            bridge = AppWorldMcpBridge(world, mode=mode)
            bridge.start()
            scratch_dir = tempfile.mkdtemp(prefix=f"opencode_{task_id}_")
            try:
                base_url, api_key = _resolve_llm_endpoint(config)
                # Always-on LLM capture for opencode: tee every request/response to a per-task
                # JSONL next to the other task outputs (falls back to the scratch dir if there's
                # no experiment manager — that run isn't persisted anyway).
                capture_dir = (
                    os.path.join(experiment_manager.experiment_dir, "tasks")
                    if experiment_manager is not None
                    else scratch_dir
                )
                os.makedirs(capture_dir, exist_ok=True)
                llm_capture_path = os.path.join(capture_dir, f"{task_id}_llm_calls.jsonl")
                logger.info(
                    f"[APPWORLD-OPENCODE] tools={mode} model={model} bridge={bridge.url} "
                    f"base={base_url or '<default openai>'} llm_capture={llm_capture_path}"
                )
                opencode_result = await run_opencode(
                    instruction=world.task.instruction,
                    app_descriptions=world.task.app_descriptions,
                    bridge_url=bridge.url,
                    base_url=base_url,
                    api_key=api_key,
                    mode=mode,
                    model=model,
                    opencode_bin=(config.opencode_bin if config else "opencode"),
                    scratch_dir=scratch_dir,
                    extra_args=(config.opencode_extra_args if config else None),
                    timeout=(config.opencode_timeout if config else 900.0),
                    llm_capture_path=llm_capture_path,
                )
            finally:
                bridge.stop()
                shutil.rmtree(scratch_dir, ignore_errors=True)

            tool_calls = bridge.state.tool_calls
            final_answer = bridge.state.final_answer or (
                opencode_result.final_answer if opencode_result else ""
            )
            executed_steps = len(tool_calls)
            if not bridge.state.completed:
                logger.warning(
                    "[APPWORLD-OPENCODE] Agent finished without calling complete_task; evaluating as-is."
                )

            # Replay the bridge's tool calls into the tracker (main thread).
            for call in tool_calls:
                tracker.collect_step(
                    Step(
                        name=f"opencode_{call['name']}",
                        data=json.dumps(
                            {"args": call.get("args"), "output": (call.get("output") or "")[:2000]}
                        ),
                    )
                )

            evaluation = world.evaluate()
            world.close_all()
            end_time = time.time()

            if evaluation.success:
                logger.info("**Task succeeded**")
            else:
                logger.warning("**Task failed**")
                logger.warning(f"Pass percentage: {str(evaluation.pass_percentage)}")

            res = evaluation.report(print_it=False, colorize=False, save_file_path=None)

            if task_result and opencode_result:
                _apply_usage(task_result, opencode_result.usage, model)

            if _langfuse and predefined_trace_id:
                if task_result:
                    task_result.trace_id = predefined_trace_id
                try:
                    record_harness_trace_output(
                        _langfuse,
                        predefined_trace_id,
                        input={"task_id": task_id, "intent": world.task.instruction},
                        output={
                            "final_answer": final_answer,
                            # Surface the generated code per call (not just the tool name) so the
                            # run is inspectable in Langfuse.
                            "tool_calls": summarize_tool_calls_for_trace(tool_calls),
                        },
                        metadata={
                            "opencode_tools": mode,
                            "model": model,
                            "success": bool(evaluation.success),
                            "total_tokens": task_result.total_tokens if task_result else 0,
                            "total_cost": task_result.total_cost if task_result else 0.0,
                            "total_llm_calls": task_result.total_llm_calls if task_result else 0,
                        },
                    )
                    _langfuse.flush()
                except Exception as lf_err:
                    logger.debug(f"[APPWORLD-OPENCODE] Langfuse record failed: {lf_err}")

            report_md = json.dumps({"report": "---\n" + res})
            score = 1.0 if evaluation.success else 0.0
            tracker.finish_task(
                intent=world.task.instruction,
                site="",
                task_id=world.task_id,
                eval=report_md,
                score=score,
                agent_answer=final_answer,
                exception=False,
                num_steps=executed_steps,
                total_llm_calls=task_result.total_llm_calls if task_result else 0,
                total_tokens=task_result.total_tokens if task_result else 0,
                total_cost=task_result.total_cost if task_result else 0.0,
                total_cache_input_tokens=task_result.total_cache_input_tokens if task_result else 0,
                duration=int((end_time - start_time) if end_time else 0),
                agent_v="opencode",
            )
            tracker.collect_step(Step(name="EvaluationResult", data=report_md))
            tracker.collect_score(score)

            if task_result:
                task_result.api_calls = len(tool_calls)
                task_result.steps = len(tracker.steps)
                task_result.duration = end_time - start_time if end_time else 0
                eval_dict = evaluation_task_info(evaluation)
                task_result.add_evaluation(eval_dict)
                task_result.success = eval_dict["success"]
                experiment_manager.update_task_result(task_result) if experiment_manager else None

        except Exception as e:
            logger.error(traceback.format_exc())
            is_error = True
            try:
                world.execute("\n" + "apis.supervisor.complete_task(status='fail')" + "\n")
            except Exception:
                logger.warning("Failed to mark AppWorld task as failed after exception")
            evaluation = world.evaluate()
            try:
                world.close_all()
            except Exception:
                logger.warning("Failed to close AppWorld cleanly after exception")
            end_time = time.time()

            if task_result:
                task_result.add_exception(e, "run_agent_on_task_opencode")
                task_result.api_calls = len(tool_calls)
                task_result.steps = len(tracker.steps)
                task_result.duration = end_time - start_time if end_time else 0
                task_result.success = False
                eval_dict = evaluation_task_info(evaluation)
                task_result.add_evaluation(eval_dict)
                if experiment_manager:
                    experiment_manager.update_task_result(task_result)

            if _langfuse and predefined_trace_id:
                if task_result:
                    task_result.trace_id = predefined_trace_id
                try:
                    record_harness_trace_output(
                        _langfuse,
                        predefined_trace_id,
                        input={"task_id": task_id, "intent": world.task.instruction},
                        output={"final_answer": "", "error": str(e)},
                        metadata={"opencode_tools": mode, "model": model, "success": False},
                    )
                    _langfuse.flush()
                except Exception:
                    pass

            report_md = json.dumps(
                {"report": "---\n" + evaluation.report(print_it=False, colorize=False, save_file_path=None)}
            )
            tracker.finish_task(
                intent=world.task.instruction,
                site="",
                task_id=world.task_id,
                eval=report_md,
                score=0.0,
                agent_answer="",
                exception=is_error,
                num_steps=executed_steps,
                total_llm_calls=task_result.total_llm_calls if task_result else 0,
                total_tokens=task_result.total_tokens if task_result else 0,
                total_cost=task_result.total_cost if task_result else 0.0,
                total_cache_input_tokens=task_result.total_cache_input_tokens if task_result else 0,
                duration=int((end_time - start_time) if end_time else 0),
                agent_v="opencode",
            )
            tracker.collect_step(Step(name="EvaluationResult", data=report_md))
            tracker.collect_score(0.0)


async def run_agent_on_dataset(
    dataset_name: str,
    experiment_name: str = "api_opencode_agent",
    config: Optional[Config] = None,
    save_outputs: bool = True,
    continue_experiment: bool = False,
    tracker: Optional[ActivityTracker] = None,
):
    experiment_manager = ExperimentManager(
        experiment_name=experiment_name,
        dataset_name=dataset_name,
        continue_experiment=continue_experiment,
    )

    try:
        task_ids = config.specific_tasks if config and config.specific_tasks else load_task_ids(dataset_name)

        if config and config.specific_task_levels:
            task_ids = get_specific_task_levels(task_ids, config.specific_task_levels)
            logger.info(f"Filtered task IDs based on difficulty levels: {config.specific_task_levels}")

        experiment_manager.summary_report["tasks_total"] = len(task_ids)
        logger.info(f"Running {len(task_ids)} tasks from dataset '{dataset_name}'")

        for index, task_id in enumerate(task_ids):
            logger.info(f"\n\n{'*' * 20} Task {index + 1}/{len(task_ids)} ({task_id}) {'*' * 20}")
            await run_agent_on_task(
                task_id=task_id,
                experiment_name=experiment_name,
                config=config,
                save_outputs=save_outputs,
                experiment_manager=experiment_manager,
                tracker=tracker,
            )

        experiment_manager.save_final_report()
        return experiment_manager.summary_report

    except Exception as e:
        logger.error(f"Error running dataset {dataset_name}: {e}")
        logger.error(traceback.format_exc())
        experiment_manager.handle_exception("global", e, "run_agent_on_dataset")
        experiment_manager.save_final_report()
        return experiment_manager.summary_report


async def main():
    parser = argparse.ArgumentParser(description="Run the OpenCode agent on AppWorld tasks")
    parser.add_argument("--task-id", nargs="*", help="Run specific task ID(s)")
    parser.add_argument(
        "--dataset",
        default="train",
        help="Dataset to run (train, dev, test_normal, test_challenge)",
    )
    parser.add_argument("--experiment-name", default="api_opencode_agent", help="Name for the experiment")
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
        "--opencode-tools",
        choices=["repl", "apis"],
        default="repl",
        help="OpenCode action surface: 'repl' (execute_python) or 'apis' (per-API tools)",
    )
    parser.add_argument("--opencode-bin", default="opencode", help="Path/name of the opencode CLI binary")
    parser.add_argument(
        "--opencode-base-url",
        default=None,
        help="LLM endpoint OpenCode posts to (default env LITE_LLM_URL/OPENAI_BASE_URL, else OpenAI)",
    )
    parser.add_argument(
        "--specific-task-levels",
        type=int,
        nargs="+",
        choices=[1, 2, 3],
        help="Run tasks with specific difficulty levels.",
    )
    parser.add_argument("--eval-key", dest="eval_key", help="Eval config settings.toml", required=False)
    parser.add_argument("specific_tasks", nargs="*", help="Specific task IDs to run")
    parser.add_argument(
        "--continue-experiment",
        action="store_true",
        help="Continue a previous experiment",
    )
    parser.add_argument(
        "--agent",
        type=str,
        choices=["opencode"],
        default="opencode",
        help="Agent to run (only 'opencode' for this harness)",
    )

    from benchmarks.helpers.logging_args import add_log_level_args, apply_log_level

    add_log_level_args(parser)

    args = parser.parse_args()
    apply_log_level(args)

    if not opencode_available(args.opencode_bin):
        logger.warning(
            f"[APPWORLD-OPENCODE] opencode CLI ({args.opencode_bin!r}) not found on PATH. "
            "Install it (e.g. `npm i -g opencode-ai` or `brew install opencode`) before running real tasks."
        )

    eval_key = (
        args.eval_key
        if args.eval_key
        else (settings.eval_config.eval_key if settings.eval_config.eval_key else None)
    )
    eval_key_tasks = settings.eval_config.get(eval_key) if eval_key else None

    if args.task_id:
        filtered_task_ids = args.task_id
    elif args.specific_tasks:
        filtered_task_ids = args.specific_tasks
    else:
        filtered_task_ids = eval_key_tasks

    tracker = ActivityTracker()
    tracker.start_experiment(
        task_ids=filtered_task_ids or [],
        experiment_name=eval_key or "appworld_opencode",
        description="",
    )

    if args.task_id:
        specific_tasks = args.task_id
    elif args.specific_tasks:
        specific_tasks = args.specific_tasks
    else:
        specific_tasks = eval_key_tasks

    config = Config(
        environment_url=args.environment_url,
        apis_url=args.apis_url,
        specific_tasks=specific_tasks,
        specific_task_levels=args.specific_task_levels if args.specific_task_levels else None,
        agent_type=args.agent,
        opencode_tools=args.opencode_tools,
        opencode_bin=args.opencode_bin,
        opencode_base_url=args.opencode_base_url,
    )

    try:
        if args.task_id and len(args.task_id) == 1:
            experiment_name = args.experiment_name
            dataset_name = "single_task"
            experiment_manager = ExperimentManager(
                experiment_name=experiment_name,
                dataset_name=dataset_name,
                continue_experiment=args.continue_experiment,
            )

            await run_agent_on_task(
                task_id=args.task_id[0],
                experiment_name=args.experiment_name,
                config=config,
                experiment_manager=experiment_manager,
                tracker=tracker,
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
                tracker=tracker,
            )
            _print_appworld_summary(results)

    except Exception as e:
        logger.error(f"Error in main: {e}")
        logger.error(traceback.format_exc())


def run_main():
    asyncio.run(main())


if __name__ == "__main__":
    run_main()

# Made with Bob
