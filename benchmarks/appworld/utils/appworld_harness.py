"""Shared AppWorld evaluation harness helpers."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage
from loguru import logger

from benchmarks.appworld.agents.final_answer import maybe_format_appworld_final_answer
from benchmarks.appworld.utils.appworld_utils import evaluation_task_info
from benchmarks.helpers.sdk_eval_helpers import _react_steps_from_invoke_result
from benchmarks.helpers.token_usage import (
    TokenUsageCallback,
    apply_token_metrics,
    invoke_config_with_token_callback,
)

# Backward-compatible re-exports for existing imports.
_apply_token_metrics = apply_token_metrics
_invoke_config_with_token_callback = invoke_config_with_token_callback


def build_user_context(world: Any) -> str:
    sup = json.dumps(world.task.supervisor)
    dt = world.task.datetime.isoformat()
    return f"""Supervisor (JSON): {sup}
Current datetime: {dt}
"""


def complete_task(world: Any, answer: str, is_error: bool) -> None:
    status = "fail" if is_error else "success"
    if answer.strip() != "N/A":
        world.execute(
            "\n" + f"apis.supervisor.complete_task(status={repr(status)}, answer={repr(answer)})" + "\n"
        )
    else:
        world.execute("\n" + f"apis.supervisor.complete_task(status='{status}')" + "\n")


async def invoke_and_score_appworld_agent(
    agent: Any,
    langfuse_handler: Optional[Any],
    world: Any,
    task_id: str,
    task_index: int,
    difficulty: str,
    user_context: Optional[str],
    *,
    agent_label: str = "external",
    track_tool_calls: bool = True,
    tracker: Any = None,
) -> Dict[str, Any]:
    intent = world.task.instruction
    thread_id = f"appworld_{agent_label}_{task_id}_{task_index}_{uuid.uuid4().hex[:8]}"

    logger.info(f"\n{'=' * 80}")
    logger.info(f"Evaluating AppWorld task: {task_id} ({difficulty}) [{agent_label}]")
    logger.info(f"Thread ID: {thread_id}")
    logger.info(f"Intent: {intent[:500]}{'…' if len(intent) > 500 else ''}")
    logger.info(f"{'=' * 80}")

    response = ""
    raw_response = ""
    tool_calls: List[Any] = []
    err: Optional[str] = None
    is_error = False
    invoked = False
    eval_dict: Dict[str, Any] = {}
    trace_id: Optional[str] = None
    _langfuse_metrics = None
    invoke_result_holder: List[Any] = []
    token_callback = TokenUsageCallback()
    token_callback.reset()

    async def run_invoke(invoke_config: Optional[dict] = None) -> None:
        nonlocal response, raw_response, tool_calls, err, is_error, invoked
        try:
            if hasattr(agent, "invoke") and _uses_cuga_invoke(agent):
                invoke_result = await agent.invoke(
                    [HumanMessage(content=intent)],
                    thread_id=thread_id,
                    user_context=user_context,
                    track_tool_calls=track_tool_calls,
                    config=invoke_config or {},
                )
            else:
                invoke_result = await agent.invoke(
                    intent=intent,
                    thread_id=thread_id,
                    user_context=user_context or "",
                    track_tool_calls=track_tool_calls,
                    config=invoke_config or {},
                )
            invoke_result_holder.clear()
            invoke_result_holder.append(invoke_result)
            raw_response = invoke_result.answer
            if _uses_cuga_invoke(agent):
                response = raw_response
            else:
                response = await maybe_format_appworld_final_answer(
                    intent,
                    raw_response,
                    invoke_config=invoke_config,
                )
            tool_calls = list(invoke_result.tool_calls or []) if track_tool_calls else []
            if invoke_result.error:
                err = invoke_result.error
            invoked = True
        except Exception as e:
            err = str(e)
            is_error = True
            logger.error(f"Agent invoke failed: {e}")

    harness_done = False

    def complete_and_eval() -> None:
        nonlocal harness_done, eval_dict
        complete_task(world, response, is_error)
        evaluation = world.evaluate()
        eval_dict = evaluation_task_info(evaluation)
        try:
            world.close_all()
        except Exception:  # noqa: S110
            pass
        harness_done = True

    if langfuse_handler:
        try:
            from langfuse import get_client

            from benchmarks.helpers.sdk_eval_helpers import (
                build_langfuse_invoke_config,
                fetch_langfuse_metrics_for_trace,
                langfuse_score_on_trace,
            )

            langfuse = get_client()
            trace_name = f"appworld_{agent_label}_{task_id}_{task_index}"
            predefined_trace_id = langfuse.create_trace_id(seed=f"{task_id}_{task_index}_{thread_id}")
            trace_id = predefined_trace_id
            logger.info(f"Langfuse trace: {trace_name} (ID: {predefined_trace_id})")

            lf_config = build_langfuse_invoke_config(predefined_trace_id, thread_id)
            await run_invoke(invoke_config_with_token_callback(token_callback, lf_config))
            complete_and_eval()
            langfuse_score_on_trace(
                langfuse,
                predefined_trace_id,
                name="appworld_success",
                value=bool(eval_dict.get("success")),
                data_type="BOOLEAN",
                comment="AppWorld harness evaluation.success",
            )
            langfuse_score_on_trace(
                langfuse,
                predefined_trace_id,
                name="pass_percentage",
                value=float(eval_dict.get("pass_percentage") or 0) / 100.0,
                data_type="NUMERIC",
                comment="Fraction of AppWorld tests passed",
            )

            try:
                _langfuse_metrics = await fetch_langfuse_metrics_for_trace(predefined_trace_id)
            except Exception as langfuse_err:
                logger.warning(f"Failed to fetch Langfuse metrics: {langfuse_err}")
                _langfuse_metrics = None
        except Exception as e:
            logger.warning(f"Langfuse trace failed: {e}")
            _langfuse_metrics = None

    if not harness_done:
        if not invoked:
            await run_invoke(invoke_config_with_token_callback(token_callback))
        if not harness_done:
            complete_and_eval()

    success = bool(eval_dict.get("success")) and not is_error and err is None
    match_rate = (
        (float(eval_dict.get("pass_percentage") or 0) / 100.0)
        if eval_dict.get("num_tests")
        else (1.0 if success else 0.0)
    )

    if tool_calls:
        logger.debug(f"\n{'─' * 40} TOOL CALLS {'─' * 40}")
        for tc in tool_calls:
            logger.debug(tc)
        logger.debug(f"{'─' * 93}\n")

    if success:
        logger.info("AppWorld harness: success")
    else:
        logger.warning(f"AppWorld harness: fail (pass_percentage={eval_dict.get('pass_percentage')})")

    result = {
        "task_name": task_id,
        "difficulty": difficulty,
        "intent": intent,
        "thread_id": thread_id,
        "trace_id": trace_id,
        "success": success,
        "match_rate": match_rate,
        "response": response,
        "raw_response": raw_response or response,
        "expected_keywords": [],
        "found_keywords": [],
        "missing_keywords": [],
        "tool_calls": tool_calls,
        "error": err,
        "appworld_evaluation": eval_dict,
    }

    apply_token_metrics(result, token_callback, _langfuse_metrics)

    agent_steps = None
    if invoke_result_holder:
        agent_steps = _react_steps_from_invoke_result(invoke_result_holder[0])
    if agent_steps is None and tracker is not None:
        agent_steps = len(getattr(tracker, "steps", []) or []) or len(tool_calls)
    if agent_steps is None:
        agent_steps = len(tool_calls)
    if agent_steps is not None:
        result["steps"] = agent_steps

    return result


def _uses_cuga_invoke(agent: Any) -> bool:
    module = type(agent).__module__
    return module.startswith("cuga.") or type(agent).__name__ == "CugaAgent"
