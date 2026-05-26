"""AppWorld evaluation using the Cuga SDK (CugaAgent + CombinedToolProvider).

No policy loading — tools come from CombinedToolProvider via setup_agent_with_tools.
Task success is determined by AppWorld's harness (world.evaluate()), not keyword checks.
"""

import sys
from datetime import datetime
from pathlib import Path

_eval_run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Add appworld source directory to path
appworld_src = Path(__file__).parent / "appworld" / "src"
if appworld_src.is_dir():
    sys.path.insert(0, str(appworld_src))

from config_loader import load_eval_config

load_eval_config("appworld")

import argparse
import asyncio
import json
import os
import uuid
from typing import Any, Dict, List, Optional

import requests
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from loguru import logger

cuga_logging_dir = os.getenv("CUGA_LOGGING_DIR")
if not cuga_logging_dir:
    raise RuntimeError("CUGA_LOGGING_DIR not set after load_eval_config! Check config files.")

# _aw_src = Path(__file__).resolve().parent / "appworld" / "src"
# if _aw_src.is_dir():
#     sys.path.insert(0, str(_aw_src))

from appworld import AppWorld, load_task_ids
from cuga.backend.activity_tracker.tracker import ActivityTracker, Step
from cuga.backend.cuga_graph.state.agent_state import VariablesManager
from cuga.backend.cuga_graph.utils.controller import AgentRunner
from cuga.config import settings
from cuga.sdk import CugaAgent

from benchmarks.appworld.utils.appworld_utils import (
    evaluation_task_info,
    get_specific_task_levels,
    get_task_difficulty,
)
from benchmarks.helpers import (
    flush_langfuse,
    print_evaluation_summary,
    save_evaluation_results,
    setup_agent_with_tools,
)

tracker = ActivityTracker()
var_manager = VariablesManager()


def _task_ids_for_run(
    task_id: Optional[str],
    dataset_name: str,
    eval_key: Optional[str],
    from_dataset: bool,
) -> tuple[List[str], Optional[str]]:
    """Resolve task IDs: single task, eval_config.toml group, or load_task_ids(dataset).

    Returns (task_ids, eval_group_name) where eval_group_name is set when tasks came from toml.
    """
    if task_id:
        return [task_id], None
    if from_dataset:
        return load_task_ids(dataset_name), None
    key = eval_key or getattr(settings.eval_config, "eval_key", None)
    if key:
        raw = settings.eval_config.get(key)
        if raw:
            ids = [str(t) for t in raw]
            return ids, str(key)
        logger.warning(
            f"eval_config.toml has no task list for key {key!r}; falling back to dataset {dataset_name!r}"
        )
    return load_task_ids(dataset_name), None


def _build_user_context(world: AppWorld) -> str:
    sup = json.dumps(world.task.supervisor)
    dt = world.task.datetime.isoformat()
    return f"""Supervisor (JSON): {sup}
Current datetime: {dt}
"""


def _complete_task(world: AppWorld, answer: str, is_error: bool) -> None:
    status = "fail" if is_error else "success"
    if answer.strip() != "N/A":
        # repr() so quotes/apostrophes/newlines in answer don't break the generated Python
        # (e.g. "I'm ..." used to produce answer='I'm' and leave predicted_answer as <<NOT_GIVEN>>).
        world.execute(
            "\n" + f"apis.supervisor.complete_task(status={repr(status)}, answer={repr(answer)})" + "\n"
        )
    else:
        world.execute("\n" + f"apis.supervisor.complete_task(status='{status}')" + "\n")


async def invoke_and_score_appworld(
    agent: CugaAgent,
    langfuse_handler: Optional[Any],
    world: AppWorld,
    task_id: str,
    task_index: int,
    difficulty: str,
    user_context: Optional[str],
    track_tool_calls: bool = True,
) -> Dict[str, Any]:
    intent = world.task.instruction
    thread_id = f"appworld_sdk_{task_id}_{task_index}_{uuid.uuid4().hex[:8]}"

    logger.info(f"\n{'=' * 80}")
    logger.info(f"Evaluating AppWorld task: {task_id} ({difficulty})")
    logger.info(f"Thread ID: {thread_id}")
    logger.info(f"Intent: {intent[:500]}{'…' if len(intent) > 500 else ''}")
    logger.info(f"{'=' * 80}")

    response = ""
    tool_calls: List[Any] = []
    err: Optional[str] = None
    is_error = False
    invoked = False
    eval_dict: Dict[str, Any] = {}
    trace_id: Optional[str] = None

    async def run_invoke() -> None:
        nonlocal response, tool_calls, err, is_error, invoked
        try:
            invoke_result = await agent.invoke(
                [HumanMessage(content=intent)],
                thread_id=thread_id,
                user_context=user_context,
                track_tool_calls=track_tool_calls,
            )
            response = invoke_result.answer
            tool_calls = list(invoke_result.tool_calls or []) if track_tool_calls else []
            invoked = True
        except Exception as e:
            err = str(e)
            is_error = True
            logger.error(f"Agent invoke failed: {e}")

    harness_done = False

    def complete_and_eval() -> None:
        nonlocal harness_done, eval_dict
        _complete_task(world, response, is_error)
        evaluation = world.evaluate()
        eval_dict = evaluation_task_info(evaluation)
        try:
            world.close_all()
        except Exception:  # noqa: S110 — cleanup is best-effort, swallowing is intentional
            pass
        harness_done = True

    if langfuse_handler:
        try:
            from langfuse import get_client

            langfuse = get_client()
            trace_name = f"appworld_sdk_{task_id}_{task_index}"
            predefined_trace_id = langfuse.create_trace_id(seed=f"{task_id}_{task_index}_{thread_id}")
            trace_id = predefined_trace_id
            logger.info(f"📊 Langfuse trace: {trace_name} (ID: {predefined_trace_id})")

            with langfuse.start_as_current_observation(
                as_type="span",
                name=trace_name,
                trace_context={"trace_id": predefined_trace_id},
                input={"intent": intent, "task_id": task_id, "difficulty": difficulty},
                metadata={"thread_id": thread_id, "task_index": task_index},
            ) as span:
                await run_invoke()
                complete_and_eval()
                span.update(
                    output={
                        "response_preview": (response[:2000] if response else ""),
                        "appworld": eval_dict,
                    },
                    metadata={"thread_id": thread_id, "task_index": task_index},
                )
                span.score_trace(
                    name="appworld_success",
                    value=bool(eval_dict.get("success")),
                    data_type="BOOLEAN",
                    comment="AppWorld harness evaluation.success",
                )
                span.score_trace(
                    name="pass_percentage",
                    value=float(eval_dict.get("pass_percentage") or 0) / 100.0,
                    data_type="NUMERIC",
                    comment="Fraction of AppWorld tests passed",
                )

                # Fetch Langfuse metrics (token usage, LLM calls, cost, timing)
                try:
                    from langfuse import get_client as _get_langfuse_client

                    _get_langfuse_client().flush()

                    from cuga.evaluation.langfuse.get_langfuse_data import LangfuseTraceHandler

                    _langfuse_trace_handler = LangfuseTraceHandler(predefined_trace_id)
                    _langfuse_metrics = await _langfuse_trace_handler.get_langfuse_data()
                except Exception as langfuse_err:
                    logger.warning(f"Failed to fetch Langfuse metrics: {langfuse_err}")
                    _langfuse_metrics = None
        except Exception as e:
            logger.warning(f"Langfuse trace failed: {e}")
            _langfuse_metrics = None

    if not harness_done:
        if not invoked:
            await run_invoke()
        if not harness_done:
            complete_and_eval()

    success = bool(eval_dict.get("success")) and not is_error and err is None
    match_rate = (
        (float(eval_dict.get("pass_percentage") or 0) / 100.0)
        if eval_dict.get("num_tests")
        else (1.0 if success else 0.0)
    )

    # Save trajectory to Evolve, tagged with the AppWorld benchmark task_id.
    # cuga-agent's sdk_callback_node (used by CugaAgent.invoke, the entry
    # point for `--sdk` evals) intentionally does not invoke save_trajectory:
    # the SDK code path is leaner than the full-graph CugaLiteNode.callback,
    # which has the save hook. Driving the write from the eval side is the
    # canonical approach for SDK-based AppWorld memory experiments — using
    # the benchmark task_id (e.g. "fd1f8fa_1") rather than the natural-language
    # task description gives us a stable join key for downstream analysis.
    # Retrieval (get_guidelines) is similarity-based on task description, so
    # this id-as-task_id does not affect lookup.
    #
    # NOTE: requires cuga-agent >= 0.2.19, when EvolveIntegration.save_trajectory
    # and is_enabled were added. Older versions hit ImportError on the inline
    # import below, which is caught by the surrounding try/except — the eval
    # continues normally and the save just no-ops with a warning.
    try:
        from cuga.backend.evolve.integration import EvolveIntegration

        if EvolveIntegration.is_enabled():
            evolve_msgs: List[BaseMessage] = [HumanMessage(content=intent)]
            for tc in tool_calls or []:
                try:
                    name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                    args_ = tc.get("arguments") if isinstance(tc, dict) else getattr(tc, "arguments", None)
                    res = tc.get("result") if isinstance(tc, dict) else getattr(tc, "result", None)
                    call_str = json.dumps({"name": name, "arguments": args_}, default=str)
                    res_str = json.dumps(res, default=str)
                    evolve_msgs.append(AIMessage(content=f"Tool call: {call_str}"))
                    evolve_msgs.append(HumanMessage(content=f"Tool result: {res_str[:4000]}"))
                except Exception as e:
                    logger.debug(f"Evolve: skipping malformed tool call {tc!r}: {e}")
                    continue
            evolve_msgs.append(AIMessage(content=response or ""))
            await EvolveIntegration.save_trajectory(
                chat_messages=evolve_msgs,
                task_id=task_id,
                success=success,
            )
    except Exception as e:
        logger.warning(f"Evolve save (eval-side) failed (non-fatal): {e}")

    if tool_calls:
        logger.debug(f"\n{'─' * 40} TOOL CALLS {'─' * 40}")
        for tc in tool_calls:
            logger.debug(tc)
        logger.debug(f"{'─' * 93}\n")

    if success:
        logger.info("✅ AppWorld harness: success")
    else:
        logger.warning(f"❌ AppWorld harness: fail (pass_percentage={eval_dict.get('pass_percentage')})")

    result = {
        "task_name": task_id,
        "difficulty": difficulty,
        "intent": intent,
        "thread_id": thread_id,
        "trace_id": trace_id,
        "success": success,
        "match_rate": match_rate,
        "response": response,
        "expected_keywords": [],
        "found_keywords": [],
        "missing_keywords": [],
        "tool_calls": tool_calls,
        "error": err,
        "appworld_evaluation": eval_dict,
    }

    # Add Langfuse metrics if available
    if langfuse_handler and '_langfuse_metrics' in dir() and _langfuse_metrics:
        result["total_tokens"] = _langfuse_metrics.total_tokens
        result["total_llm_calls"] = _langfuse_metrics.total_llm_calls
        result["total_cost"] = _langfuse_metrics.total_cost
        result["full_execution_time"] = _langfuse_metrics.full_execution_time
        result["total_cache_input_tokens"] = _langfuse_metrics.total_cache_input_tokens
        result["generation_timings"] = _langfuse_metrics.generation_timings
        result["llm_call_details"] = _langfuse_metrics.llm_call_details
        result["node_timings"] = _langfuse_metrics.node_timings

    return result


class AppWorldSdkEvaluator:
    def __init__(
        self,
        dataset_name: str = "train",
        task_id: Optional[str] = None,
        specific_task_levels: Optional[List[int]] = None,
        experiment_name: Optional[str] = None,
        environment_url: Optional[str] = None,
        apis_url: Optional[str] = None,
        eval_key: Optional[str] = None,
        from_dataset: bool = False,
    ):
        self.dataset_name = dataset_name
        self.task_id = task_id
        self.specific_task_levels = specific_task_levels
        self.eval_key = eval_key
        self.from_dataset = from_dataset
        self.experiment_name = experiment_name or os.getenv(
            "APPWORLD_SDK_EXPERIMENT_NAME", "appworld_sdk_evaluation"
        )
        self.environment_url = environment_url or f"http://localhost:{settings.server_ports.environment_url}"
        self.apis_url = apis_url or f"http://localhost:{settings.server_ports.apis_url}"
        self.agent: Optional[CugaAgent] = None
        self.langfuse_handler: Optional[Any] = None
        self.results: List[Dict[str, Any]] = []
        self.special_instructions: Optional[str] = """
# INSTRUCTIONS

A. General instructions:

- Never invent or guess values. For example, if I ask you to play a song, do not assume the ID is 123. Instead, look it up properly through the right API.
- Never leave placeholders; don't output things like "your_username". Always fill in the real value by retrieving it via APIs (e.g., Supervisor app for credentials).
- Always map specific nouns in the user's prompt (e.g., 'friends', 'unread emails', 'recent transactions') to the available parameters or schema fields for each tool (from **Current Available Tools** or from **`find_tools`** output). Never fetch a generalized list if the tool provides a parameter to filter the exact subset the user asked for.

B. App-specific instructions:

- Any reference to my friends, family or any other person or relation refers to the people in my phone's contacts list.
- Always obtain the current date or time, from Python function calls like `datetime.now()`, or from the phone app's get_current_date_and_time API, never from your internal clock.
- For temporal requests, use proper time boundaries, e.g., when asked about periods like "yesterday", use complete ranges: 00:00:00 to 23:59:59.
        """

    async def setup(self):
        self.agent, self.langfuse_handler = await setup_agent_with_tools(
            special_instructions=self.special_instructions
        )
        # Register a prompt-capture callback so the trajectory JSON files have
        # their `prompts` field populated.  The SDK path (CugaAgent.invoke) uses
        # self._callbacks instead of the agent_loop get_stream() callbacks where
        # TokenUsageTracker is normally registered.
        #
        # We use a safe subclass rather than TokenUsageTracker directly because
        # on_llm_end's token-counting line raises AttributeError for Anthropic
        # responses (llm_output has no "token_usage" key), and that exception
        # propagates through agent.invoke() leaving invoke_result.answer empty.
        from langchain_core.callbacks import BaseCallbackHandler
        from langchain_core.outputs import LLMResult

        _tracker = tracker

        class _PromptCaptureCallback(BaseCallbackHandler):
            async def on_llm_start(self, serialized, prompts, **kwargs):
                for p in prompts:
                    _tracker.collect_prompt(role="system", value=p)

            async def on_llm_end(self, response: LLMResult, **kwargs):
                # Both blocks swallow exceptions on purpose: this callback runs
                # inside agent.invoke(), and any uncaught error here propagates
                # out of invoke() and silently empties invoke_result.answer.
                # See _PromptCaptureCallback docstring above.
                try:
                    text = response.generations[0][0].text
                    if text:
                        _tracker.collect_prompt(role="assistant", value=text)
                except Exception as e:  # noqa: BLE001 — see comment above
                    logger.debug(f"prompt capture: text extraction skipped: {e}")
                try:
                    usage = (response.llm_output or {}).get("token_usage") or {}
                    total = usage.get("total_tokens")
                    if total is not None:
                        _tracker.collect_tokens_usage(total)
                except Exception as e:  # noqa: BLE001 — see comment above
                    logger.debug(f"prompt capture: token count skipped: {e}")

        self.agent._callbacks = list(self.agent._callbacks or [])
        self.agent._callbacks.append(_PromptCaptureCallback())

    async def evaluate_task(self, task_id: str, task_index: int) -> Dict[str, Any]:
        meta = get_task_difficulty(task_id)
        difficulty = str(meta.get("difficulty", "unknown"))

        agent_runner = AgentRunner(browser_enabled=False)

        try:
            requests.get("http://localhost:8001/api/reset", timeout=10)
            await agent_runner.initialize_appworld_env()

            with AppWorld(
                task_id=task_id,
                experiment_name=self.experiment_name,
                remote_environment_url=self.environment_url,
                remote_apis_url=self.apis_url,
            ) as world:
                tracker.reset(intent=world.task.instruction, task_id=world.task_id)
                var_manager.reset()
                tracker.current_date = world.task.datetime.isoformat()
                tracker.pi = json.dumps(world.task.supervisor)
                tracker.pi += f"current_datetime: {tracker.current_date}"

                user_context = _build_user_context(world)

                def tracker_callback(result: Dict[str, Any], keyword_check: Dict[str, Any], intent: str):
                    eval_info = result.get("appworld_evaluation") or {}
                    report_md = json.dumps(
                        {
                            "task_id": task_id,
                            "success": result.get("success"),
                            "pass_percentage": eval_info.get("pass_percentage"),
                            "evaluation": eval_info,
                        }
                    )
                    score = float(result.get("match_rate", 0.0))
                    if result.get("error"):
                        tracker.finish_task(
                            intent=intent,
                            site="",
                            task_id=task_id,
                            eval=report_md,
                            score=0.0,
                            agent_answer="",
                            exception=True,
                            num_steps=0,
                            total_llm_calls=result.get("total_llm_calls", 0),
                            total_tokens=result.get("total_tokens", 0),
                            total_cost=result.get("total_cost", 0.0),
                            total_cache_input_tokens=result.get("total_cache_input_tokens", 0),
                            duration=result.get("full_execution_time", 0),
                            agent_v="",
                        )
                        tracker.collect_score(0.0)
                    else:
                        tracker.finish_task(
                            intent=intent,
                            site="",
                            task_id=task_id,
                            eval=report_md,
                            score=score,
                            agent_answer=result.get("response", ""),
                            exception=False,
                            num_steps=0,
                            total_llm_calls=result.get("total_llm_calls", 0),
                            total_tokens=result.get("total_tokens", 0),
                            total_cost=result.get("total_cost", 0.0),
                            total_cache_input_tokens=result.get("total_cache_input_tokens", 0),
                            duration=result.get("full_execution_time", 0),
                            agent_v="",
                        )
                        tracker.collect_step(Step(name="EvaluationResult", data=report_md))
                        tracker.collect_score(score)

                merged = await invoke_and_score_appworld(
                    agent=self.agent,
                    langfuse_handler=self.langfuse_handler,
                    world=world,
                    task_id=task_id,
                    task_index=task_index,
                    difficulty=difficulty,
                    user_context=user_context,
                )
                tracker_callback(merged, {}, world.task.instruction)
                return merged
        finally:
            try:
                await agent_runner.env.close()
            except Exception as e:
                logger.debug(f"agent_runner.env.close: {e}")

    async def evaluate_all(self):
        task_ids, eval_group = _task_ids_for_run(
            self.task_id,
            self.dataset_name,
            self.eval_key,
            self.from_dataset,
        )
        if self.task_id:
            logger.info(f"Single task mode: {self.task_id}")
        elif eval_group:
            logger.info(f"Tasks from eval_config.toml (group {eval_group!r}): {len(task_ids)} tasks")
        else:
            logger.info(f"Dataset '{self.dataset_name}': {len(task_ids)} tasks")

        if self.specific_task_levels and not self.task_id:
            task_ids = get_specific_task_levels(task_ids, self.specific_task_levels)
            logger.info(f"Filtered to levels {self.specific_task_levels}: {len(task_ids)} tasks")

        tracker.start_experiment(
            task_ids=task_ids,
            experiment_name=self.experiment_name,
            description="AppWorld SDK (CombinedToolProvider) evaluation",
        )

        self.results = []
        for i, tid in enumerate(task_ids, 1):
            logger.info(f"\n[{i}/{len(task_ids)}] Task {tid}")
            result = await self.evaluate_task(tid, task_index=i)
            self.results.append(result)
            if i < len(task_ids):
                await asyncio.sleep(0.5)

        flush_langfuse(self.langfuse_handler)

    def print_summary(self):
        print_evaluation_summary(self.results)

    def save_results(self, output_dir: Optional[str] = None):
        if output_dir is None:
            # Use experiments/outputs to match appworld_eval.py structure
            output_dir = Path(__file__).parent / "experiments" / "outputs"
        saved_file = save_evaluation_results(
            self.results,
            Path(output_dir),
            prefix="appworld_sdk",
            run_timestamp=_eval_run_timestamp,
        )

        # Also create a _final_report.json symlink for bundle compatibility
        final_report_path = saved_file.parent / f"appworld_sdk_{_eval_run_timestamp}_final_report.json"
        if not final_report_path.exists():
            try:
                import shutil

                shutil.copy(saved_file, final_report_path)
                logger.info(f"📁 Final report: {final_report_path}")
            except Exception as e:
                logger.warning(f"Failed to create final report copy: {e}")

        return saved_file


async def main():
    parser = argparse.ArgumentParser(
        description="Evaluate AppWorld tasks via Cuga SDK (CombinedToolProvider)"
    )
    parser.add_argument(
        "--dataset", default="train", help="Dataset name when using --from-dataset or as fallback"
    )
    parser.add_argument("--task-id", default=None, help="Run a single task ID")
    parser.add_argument(
        "--eval-key",
        default=None,
        help="Task group key in eval_config.toml (default: eval_key from that file, e.g. test_normal_easy)",
    )
    parser.add_argument(
        "--from-dataset",
        action="store_true",
        help="Use load_task_ids(--dataset) instead of eval_config.toml task lists",
    )
    parser.add_argument(
        "--specific-task-levels",
        type=int,
        nargs="+",
        choices=[1, 2, 3],
        help="Filter tasks by difficulty level",
    )
    parser.add_argument(
        "--environment-url",
        default=f"http://localhost:{settings.server_ports.environment_url}",
        help="AppWorld environment server URL",
    )
    parser.add_argument(
        "--apis-url",
        default=f"http://localhost:{settings.server_ports.apis_url}",
        help="AppWorld APIs URL",
    )
    parser.add_argument(
        "--experiment-name",
        default=None,
        help="Experiment name (default: eval group key, env, or appworld_sdk_evaluation)",
    )

    from benchmarks.helpers.logging_args import add_log_level_args, apply_log_level

    add_log_level_args(parser)

    args = parser.parse_args()
    apply_log_level(args)

    eval_key_toml = getattr(settings.eval_config, "eval_key", None)
    eval_key_resolved = args.eval_key or eval_key_toml
    experiment_name = args.experiment_name
    if experiment_name is None:
        experiment_name = os.getenv("APPWORLD_SDK_EXPERIMENT_NAME")
    if experiment_name is None and not args.from_dataset and eval_key_resolved and not args.task_id:
        experiment_name = eval_key_resolved
    if experiment_name is None:
        experiment_name = "appworld_sdk_evaluation"

    evaluator = AppWorldSdkEvaluator(
        dataset_name=args.dataset,
        task_id=args.task_id,
        specific_task_levels=args.specific_task_levels,
        experiment_name=experiment_name,
        environment_url=args.environment_url,
        apis_url=args.apis_url,
        eval_key=args.eval_key,
        from_dataset=args.from_dataset,
    )

    try:
        await evaluator.setup()
        await evaluator.evaluate_all()
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
