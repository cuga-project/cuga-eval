# CRITICAL: Load environment variables FIRST, before ANY other imports
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Add appworld benchmark directory to path for local utils imports
appworld_benchmark_dir = Path(__file__).parent
sys.path.insert(0, str(appworld_benchmark_dir))

# Add appworld source directory to path
appworld_src = appworld_benchmark_dir / "appworld" / "src"
if appworld_src.is_dir():
    sys.path.insert(0, str(appworld_src))

from config_loader import load_eval_config

load_eval_config("appworld")

import os

cuga_logging_dir = os.getenv("CUGA_LOGGING_DIR")
if not cuga_logging_dir:
    raise RuntimeError("CUGA_LOGGING_DIR not set after load_eval_config! Check config files.")

import argparse
import asyncio
import json
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
from cuga.evaluation.langfuse.get_langfuse_data import LangfuseTraceHandler
from jinja2 import Template
from loguru import logger
from opentelemetry import trace
from utils.appworld_data_collection import ExperimentManager
from utils.appworld_utils import (
    appworld_task_info,
    evaluation_task_info,
    get_specific_task_levels,
    get_task_difficulty,
)

from benchmarks.helpers.sdk_eval_helpers import setup_react_agent_for_evaluation

APPWORLD_REACT_PROMPT = """USER:
I am your supervisor, and you are an AI Assistant whose job is to complete my day-to-day tasks fully autonomously.

To do this, you will need to interact with app(s) using their associated APIs on my behalf. For this you will undertake a multi-step conversation using a python REPL environment. That is, you will write the python code, the environment will execute it and show you the result, based on which, you will write python code for the next step and so on, until you've achieved the goal. This environment will let you interact with app(s) using their associated APIs on my behalf.

Here are three key APIs that you need to know to get more information:

# To get a list of apps that are available to you.
```python
print(apis.api_docs.show_app_descriptions())
```

# To get the list of APIs under any app listed above, e.g. spotify
```python
print(apis.api_docs.show_api_descriptions(app_name='spotify'))
```

# To get the specification of a particular api, e.g. spotify app's login api
```python
print(apis.api_docs.show_api_doc(app_name='spotify', api_name='login'))
```

Each code execution will produce an output that you can use in subsequent calls.

Key instructions:

A. General instructions:
- Act fully on your own. You must make all decisions yourself and never ask for confirmation or clarification.
- Never invent or guess values. Always retrieve real values via APIs.
- Never leave placeholders. Always fill in real values by retrieving them through APIs.
- When details are omitted, choose any valid value.
- Avoid collateral damage. Only perform what is explicitly required.

B. App-specific instructions:
- All personal information, credentials, addresses, and cards are stored in the Supervisor app.
- References to friends, family or other people refer to the phone contacts app.
- Always obtain current date/time from Python or app APIs, never from model memory.
- References to file system mean the file_system app, not the OS.
- Paginated APIs: always process all results by looping through page_index until exhausted.
- If an app API returns unauthorized, missing token, invalid token, or expired token, inspect its API docs and authenticate explicitly using the proper login or signup/verify/login flow before continuing.
- Prefer using api_docs discovery before making assumptions about method names or parameters.

C. Code-operation instructions:
- Return exactly one Python code block per step.
- Make sure code blocks end cleanly.
- You can use variables created in earlier steps in later steps.
- Always inspect API specifications with `apis.api_docs.show_api_doc(...)` before calling an unfamiliar API.
- Write small chunks of code and validate each step before making irreversible changes.
- Use only the provided app APIs, not external Python packages for those services.
- The API docs include both input arguments and response schemas; use them.

D. Task-completion instructions:
- You must call `apis.supervisor.complete_task` after completing the task.
- If the task asks for an answer, your final code block must call exactly `apis.supervisor.complete_task(status="success", answer=<value>)`.
- Do not stop after printing the answer. The final step must include the `complete_task(...)` call.
- If no answer is required, call `apis.supervisor.complete_task(status="success")`.
- Keep answers minimal: return only the direct entity / number / value requested.
- Numbers must be numeric.
- If you cannot find a way, call `apis.supervisor.complete_task(status="fail")`.

Completion examples:
```python
answer = 23
apis.supervisor.complete_task(status="success", answer=answer)
```

```python
apis.supervisor.complete_task(status="success", answer="15")
```

```python
apis.supervisor.complete_task(status="success")
```

My name is: {{ main_user.first_name }} {{ main_user.last_name }}. My personal email is {{ main_user.email }} and phone number is {{ main_user.phone_number }}.
Available apps:
{{ app_descriptions }}
Task: {{ instruction }}

ASSISTANT:
"""


@dataclass
class Config:
    model_name: str = "gpt-4o"
    temperature: float = 0.2
    max_tokens: int = 2000
    seed: int = 100
    provider: str = "openai"
    max_retries: int = 3
    retry_delay: int = 2
    max_history_tokens: int = 14000
    environment_url: Optional[str] = None
    apis_url: Optional[str] = None
    agent_server_url: Optional[str] = None
    use_examples: bool = True
    prompt_template_path: Optional[str] = None
    verbose: bool = True
    specific_tasks: Optional[list[str]] = None
    specific_task_levels: Optional[list[int]] = None
    langfuse_public_key: Optional[str] = os.getenv("LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: Optional[str] = os.getenv("LANGFUSE_SECRET_KEY")
    langfuse_host: Optional[str] = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    agent_type: str = "react"
    max_steps: int = 12


def get_current_trace_id() -> Optional[str]:
    current_span = trace.get_current_span()
    span_context = current_span.get_span_context()
    if not span_context.is_valid:
        return None
    return format(span_context.trace_id, "032x")


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


def _render_initial_prompt(world: AppWorld) -> str:
    template = Template(APPWORLD_REACT_PROMPT)
    app_descriptions = json.dumps(
        [{"name": k, "description": v} for (k, v) in world.task.app_descriptions.items()],
        indent=1,
    )
    return template.render(
        instruction=world.task.instruction,
        main_user=world.task.supervisor,
        app_descriptions=app_descriptions,
    ).strip()


def _extract_python_block(text: str) -> str:
    import re

    match = re.search(r"```python\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    partial_match = re.search(r"```python\s*(.*)$", text, flags=re.DOTALL | re.IGNORECASE)
    if partial_match:
        return partial_match.group(1).strip()

    return text.strip()


def _completion_called(code: str) -> bool:
    return "complete_task(" in code


def _extract_completion_answer(code: str) -> str:
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ""

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "complete_task":
            for keyword in node.keywords:
                if keyword.arg != "answer":
                    continue
                try:
                    value = ast.literal_eval(keyword.value)
                except Exception:
                    return ""
                return str(value)
    return ""


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


async def run_agent_on_task(
    task_id: str,
    experiment_name: str = "api_react_agent",
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
    langfuse_trace_id = None
    task_metadata = get_task_difficulty(task_id)
    task_result = None

    with AppWorld(
        task_id=task_id,
        experiment_name=experiment_name,
        remote_environment_url=config.environment_url if config else None,
        remote_apis_url=config.apis_url if config else None,
    ) as world:
        logger.info(f"Running task: {task_id}")
        logger.info(f"Task instruction: {world.task.instruction}")

        react_agent, _ = await setup_react_agent_for_evaluation(
            special_instructions=(
                "For AppWorld, always emit executable Python code inside ```python fences. "
                "The code runs directly in the AppWorld runtime."
            )
        )
        if config:
            react_agent.max_steps = config.max_steps

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
            logger.info(f"[APPWORLD-REACT] Registry authenticate_apps result: {auth_result}")
        except Exception as auth_exc:
            logger.warning(f"[APPWORLD-REACT] authenticate_apps failed before task run: {auth_exc}")
        initial_prompt = _render_initial_prompt(world)
        conversation = [{"role": "user", "content": initial_prompt}]
        tool_calls: list[dict[str, Any]] = []
        is_error = False
        final_answer = ""
        executed_steps = 0

        try:
            for step_index in range(1, (config.max_steps if config else 12) + 1):
                logger.info(f"[APPWORLD-REACT] Step {step_index}")
                llm_text = await react_agent._call_llm(conversation)
                conversation.append({"role": "assistant", "content": llm_text})
                code = _extract_python_block(llm_text)

                if not code:
                    raise RuntimeError("React agent returned no executable Python code for AppWorld.")

                tool_calls.append({"name": "world.execute", "args": {"code": code}})
                tracker.collect_step(Step(name="api_call_world_execute", data=json.dumps({"code": code})))

                execution_output = world.execute("\n" + code + "\n")
                executed_steps += 1
                completion_answer = _extract_completion_answer(code)
                if completion_answer:
                    final_answer = completion_answer

                output_text = str(execution_output)
                conversation.append(
                    {
                        "role": "user",
                        "content": f"Output:\n```\n{output_text}\n```",
                    }
                )

                if _completion_called(code):
                    break

            evaluation = world.evaluate()
            world.close_all()
            end_time = time.time()

            if evaluation.success:
                logger.info("**Task succeeded**")
            else:
                logger.warning("**Task failed**")
                logger.warning(f"Pass percentage: {str(evaluation.pass_percentage)}")

            res = evaluation.report(print_it=False, colorize=False, save_file_path=None)

            langfuse_data = None
            langfuse_trace_id = get_current_trace_id()
            if langfuse_trace_id:
                langfuse_handler = LangfuseTraceHandler(langfuse_trace_id)
                langfuse_data = await langfuse_handler.get_langfuse_data()

            if task_result and langfuse_data:
                task_result.total_llm_calls = langfuse_data.total_llm_calls
                task_result.total_tokens = langfuse_data.total_tokens
                task_result.total_cost = langfuse_data.total_cost
                task_result.node_timings = langfuse_data.node_timings
                task_result.llm_call_details = langfuse_data.llm_call_details
                task_result.generation_timings = langfuse_data.generation_timings
                task_result.full_execution_time = langfuse_data.full_execution_time
                task_result.total_cache_input_tokens = langfuse_data.total_cache_input_tokens
                task_result.trace_id = langfuse_trace_id

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
                agent_v="react",
            )
            tracker.collect_step(Step(name="EvaluationResult", data=report_md))
            tracker.collect_score(score)

            if task_result:
                task_result.api_calls = len(tool_calls)
                task_result.steps = len(tracker.steps)
                task_result.duration = end_time - start_time if end_time else 0
                if not task_result.total_tokens:
                    task_result.total_tokens = tracker.token_usage
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
                task_result.add_exception(e, "run_agent_on_task_react")
                task_result.api_calls = len(tool_calls)
                task_result.steps = len(tracker.steps)
                task_result.duration = end_time - start_time if end_time else 0
                task_result.success = False
                eval_dict = evaluation_task_info(evaluation)
                task_result.add_evaluation(eval_dict)
                if experiment_manager:
                    experiment_manager.update_task_result(task_result)

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
                agent_v="react",
            )
            tracker.collect_step(Step(name="EvaluationResult", data=report_md))
            tracker.collect_score(0.0)


async def run_agent_on_dataset(
    dataset_name: str,
    experiment_name: str = "api_react_agent",
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

    datetime.now()

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
    parser = argparse.ArgumentParser(description="Run React agent on AppWorld tasks")
    parser.add_argument("--task-id", nargs="*", help="Run specific task ID(s)")
    parser.add_argument(
        "--dataset",
        default="train",
        help="Dataset to run (train, dev, test_normal, test_challenge)",
    )
    parser.add_argument("--experiment-name", default="api_react_agent", help="Name for the experiment")
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
        choices=["cuga", "react"],
        default="react",
        help="Agent to run (default: react)",
    )

    from benchmarks.helpers.logging_args import add_log_level_args, apply_log_level

    add_log_level_args(parser)

    args = parser.parse_args()
    apply_log_level(args)

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
        experiment_name=eval_key or "appworld_react",
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
        agent_server_url=args.agent_server_url,
        specific_tasks=specific_tasks,
        specific_task_levels=args.specific_task_levels if args.specific_task_levels else None,
        agent_type=args.agent,
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
