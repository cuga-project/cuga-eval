"""Helper functions for SDK evaluation benchmarks.

This module provides reusable functions for:
- Agent setup with tools and Langfuse
- Policy management
- Keyword checking
- Task evaluation with Langfuse tracing
- Multi-turn task evaluation
- Summary printing
- Tracker callbacks

Enhanced metrics (opt-in via metrics_config):
- String similarity scoring
- LLM judge semantic evaluation
- Final score calculation
"""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypedDict

from loguru import logger


class MetricsConfig(TypedDict, total=False):
    """Configuration for enhanced evaluation metrics.

    All fields are optional. When metrics_config is not provided or empty,
    only keyword matching is performed (default behavior for backwards compatibility).

    Fields:
        enable_similarity: Compute string similarity score (0.0-1.0)
        enable_llm_judge: Run LLM judge for semantic evaluation
        llm_judge_provider: LLM judge provider ("groq", "mock", etc.)
        expected_output_key: Key path to expected output in task dict (default: "expected_output.answer")
        final_score_threshold_exact: Threshold when exact match (default: 0.85)
        final_score_threshold_inexact: Threshold when no exact match (default: 0.9)
        similarity_method: Method for string similarity (default: "rapidfuzz_token_set")
    """

    enable_similarity: bool
    enable_llm_judge: bool
    llm_judge_provider: str
    expected_output_key: str
    final_score_threshold_exact: float
    final_score_threshold_inexact: float
    similarity_method: str


# Lazy-loaded modules for enhanced metrics
_metrics_module = None
_llm_judge_module = None


def _get_metrics_class():
    """Lazy import of EvaluationMetrics."""
    global _metrics_module
    if _metrics_module is None:
        try:
            from benchmarks.helpers.metrics import EvaluationMetrics

            _metrics_module = EvaluationMetrics
        except ImportError:
            logger.warning("benchmarks.helpers.metrics not available - similarity metrics disabled")
            _metrics_module = False
    return _metrics_module if _metrics_module else None


def _get_llm_judge(provider: str, **kwargs):
    """Lazy import and creation of LLM judge."""
    global _llm_judge_module
    if _llm_judge_module is None:
        try:
            from benchmarks.bpo import llm_judge as ljm

            _llm_judge_module = ljm
        except ImportError:
            logger.warning("benchmarks.bpo.llm_judge not available - LLM judge disabled")
            _llm_judge_module = False

    if _llm_judge_module:
        try:
            return _llm_judge_module.get_llm_judge(provider, **kwargs)
        except Exception as e:
            logger.warning(f"Failed to create LLM judge: {e}")
    return None


def _get_nested_value(d: Dict, key_path: str, default=None):
    """Get a nested value from a dict using dot notation."""
    keys = key_path.split(".")
    value = d
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    return value


def _extract_tool_calls_from_tracker() -> List[Dict[str, Any]]:
    """Extract tool calls from ActivityTracker.steps.

    This is the standard approach used by oak_health_insurance and cuga evaluate.
    Tool calls are recorded as steps with "api_call" in the name.

    For M3 benchmark, tool calls are in "Assistant_code" steps as Python code.

    Returns:
        List of tool call dicts with 'name' and 'args' keys
    """
    import re

    from cuga.backend.activity_tracker.tracker import ActivityTracker

    tracker = ActivityTracker()  # Singleton - returns existing instance
    tool_calls = []

    # Debug: log step names to understand what's being tracked
    logger.info(f"[TOOL_TRACKING] ActivityTracker has {len(tracker.steps)} steps")
    if tracker.steps:
        step_names = [s.name for s in tracker.steps[:10]]
        logger.info(f"[TOOL_TRACKING] First step names: {step_names}")

    for step in tracker.steps:
        # Standard approach: steps with "api_call" in the name
        if step.name and "api_call" in step.name:
            try:
                call_data = json.loads(step.data) if step.data else {}
                tool_calls.append(
                    {
                        "name": call_data.get("function_name", ""),
                        "arguments": call_data.get("args", {}),  # Use "arguments" for M3 ground truth format
                    }
                )
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Failed to parse tool call step data: {e}")
                continue

        # M3 approach: extract tool calls from "User_output" steps (actual executed calls)
        # User_output steps contain the results of executed tool calls
        elif step.name and step.name == "User_output" and step.data:
            try:
                # User_output contains the result of a tool call
                # We need to find the corresponding Assistant_code step to get the function name
                # For now, we'll look for patterns in the data that indicate a tool was called

                # Check if this is a tool result (contains structured data)
                if step.data and len(step.data) > 0:
                    # Look back to find the most recent Assistant_code step
                    step_index = tracker.steps.index(step)
                    for i in range(step_index - 1, -1, -1):
                        prev_step = tracker.steps[i]
                        if prev_step.name == "Assistant_code" and prev_step.data:
                            # Extract the last await call before this User_output
                            pattern = r'await\s+(\w+)\s*\((.*?)\)'
                            matches = re.findall(pattern, prev_step.data, re.DOTALL)
                            if matches:
                                # Take only the last match (most recent call)
                                func_name, args_str = matches[-1]
                                args_dict = {}
                                if args_str.strip():
                                    arg_pairs = re.findall(r'(\w+)\s*=\s*([^,]+)', args_str)
                                    for key, value in arg_pairs:
                                        value = value.strip().strip('"\'')
                                        args_dict[key] = value

                                # Extract result/error from User_output
                                result_data = step.data
                                error_data = None

                                # Check if this is an error
                                if "Error" in result_data or "error" in result_data.lower():
                                    error_data = result_data[:500]  # Truncate long errors
                                    result_data = None
                                else:
                                    result_data = result_data[:500] if len(result_data) > 500 else result_data

                                # Calculate duration by finding time between steps
                                # We'll estimate based on step indices (rough approximation)
                                # In a real scenario, steps would have timestamps
                                duration_ms = None
                                try:
                                    # Simple heuristic: assume ~1000ms per step on average
                                    # This is a rough estimate since ActivityTracker steps don't have timestamps
                                    steps_between = step_index - i
                                    if steps_between > 0:
                                        # Estimate: tool calls typically take 500-2000ms
                                        # Use a base of 1000ms plus 200ms per intermediate step
                                        duration_ms = 1000 + (steps_between - 1) * 200
                                except Exception:  # noqa: S110 — duration heuristic is best-effort
                                    pass

                                tool_call_record = {
                                    "name": func_name,
                                    "arguments": args_dict,  # Use "arguments" for M3 ground truth format
                                }

                                # Add result/error if present
                                if result_data:
                                    tool_call_record["result"] = result_data
                                if error_data:
                                    tool_call_record["error"] = error_data

                                # Add duration if calculated
                                if duration_ms is not None:
                                    tool_call_record["duration_ms"] = duration_ms

                                tool_calls.append(tool_call_record)
                                logger.info(
                                    f"[TOOL_TRACKING] Extracted tool call '{func_name}' from User_output step (duration: {duration_ms}ms)"
                                )
                            break
            except Exception as e:
                logger.warning(f"Failed to parse M3 tool calls from User_output: {e}")
                continue

    return tool_calls


from cuga.backend.cuga_graph.nodes.cuga_lite.combined_tool_provider import CombinedToolProvider
from cuga.backend.cuga_graph.policy.models import PolicyType
from cuga.sdk import CugaAgent
from langchain_core.messages import HumanMessage

from .react_agent import GenericReactAgent, setup_react_agent_with_tools


async def setup_agent_with_tools(
    special_instructions: Optional[str] = None,
    extra_callbacks: Optional[List[Any]] = None,
    enable_token_usage_tracker: bool = True,
) -> tuple[CugaAgent, Optional[Any]]:
    """Set up CugaAgent with tools and Langfuse tracing.

    Args:
        special_instructions: Optional special instructions to pass to the agent
        extra_callbacks: Optional additional LangChain callbacks (e.g. TokenUsageCallback)
        enable_token_usage_tracker: Whether to enable TokenUsageTracker-like callback for rich trajectories (default: True)

    Returns:
        Tuple of (agent, langfuse_handler)
    """
    logger.info("Setting up evaluator...")

    tool_provider = CombinedToolProvider()
    await tool_provider.initialize()
    all_tools = await tool_provider.get_all_tools()
    logger.info(f"Loaded {len(all_tools)} tools")

    langfuse_handler = setup_langfuse()
    callbacks = [langfuse_handler] if langfuse_handler else []
    if langfuse_handler:
        logger.info("✅ Langfuse tracing enabled")
        logger.info(f"   Callback handler type: {type(langfuse_handler).__name__}")
    else:
        logger.info("ℹ️  Langfuse not available (optional)")

    if extra_callbacks:
        callbacks = callbacks + extra_callbacks

    # Add TokenUsageTracker-like callback for rich trajectory capture
    if enable_token_usage_tracker:
        try:
            from cuga.backend.activity_tracker.tracker import ActivityTracker

            from benchmarks.helpers.token_usage_tracker_callback import create_token_usage_tracker_callback

            tracker = ActivityTracker()  # Singleton - returns existing instance
            token_tracker_callback = create_token_usage_tracker_callback(tracker)
            callbacks.append(token_tracker_callback)
            logger.info("✅ TokenUsageTracker callback enabled for rich trajectory capture")
        except Exception as e:
            logger.warning(f"Failed to enable TokenUsageTracker callback: {e}")

    agent_kwargs = {"tool_provider": tool_provider, "callbacks": callbacks}
    if special_instructions:
        agent_kwargs["special_instructions"] = special_instructions
        logger.info("   Special instructions provided")

    agent = CugaAgent(**agent_kwargs)
    logger.info(f"   Agent created with {len(callbacks)} callback(s)")

    return agent, langfuse_handler


def setup_langfuse():
    """Setup Langfuse tracing callback handler.

    Returns:
        Langfuse callback handler if available, None otherwise
    """
    # Check if Langfuse is enabled in settings
    try:
        from cuga.config import settings

        langfuse_enabled = getattr(getattr(settings, 'advanced_features', None), 'langfuse_tracing', False)
        if not langfuse_enabled:
            logger.info("Langfuse disabled in settings")
            return None
    except ImportError:
        pass  # If cuga.config unavailable, fall through to package check

    try:
        from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
    except ImportError:
        try:
            from langfuse.callback.langchain import LangchainCallbackHandler as LangfuseCallbackHandler
        except ImportError:
            logger.warning("Langfuse package not installed. Install with: pip install langfuse")
            return None

    try:
        handler = LangfuseCallbackHandler()
        return handler
    except Exception as e:
        logger.error(f"Failed to create Langfuse handler: {e}")
        import traceback

        logger.debug(traceback.format_exc())
        return None


async def clear_all_policies(agent: CugaAgent):
    """Clear all existing policies from the database."""
    try:
        existing_policies = await agent.policies.list()
        if existing_policies:
            logger.info(f"Found {len(existing_policies)} existing policies, deleting...")
            for policy in existing_policies:
                await agent.policies.delete(policy["id"])
            logger.info(f"✅ Cleared {len(existing_policies)} existing policies")
        else:
            logger.info("No existing policies to clear")
    except Exception as e:
        logger.warning(f"Failed to clear existing policies: {e}")


async def add_policy_via_agent(agent: CugaAgent, policy):
    """Add a policy using the agent's public API methods.

    Args:
        agent: CugaAgent instance
        policy: Policy object (Playbook, ToolGuide, etc.)
    """
    policy_type = policy.policy_type if hasattr(policy, 'policy_type') else policy.type

    if policy_type == PolicyType.PLAYBOOK:
        keywords = []
        natural_language_trigger = []
        threshold = 0.7

        for trigger in policy.triggers:
            trigger_type = getattr(trigger, 'type', None)
            if trigger_type == "keyword":
                trigger_value = getattr(trigger, 'value', [])
                if isinstance(trigger_value, list):
                    keywords.extend(trigger_value)
                else:
                    keywords.append(trigger_value)
            elif trigger_type == "natural_language":
                trigger_value = getattr(trigger, 'value', [])
                if isinstance(trigger_value, list):
                    natural_language_trigger.extend(trigger_value)
                else:
                    natural_language_trigger.append(trigger_value)
                threshold = getattr(trigger, 'threshold', 0.7)

        await agent.policies.add_playbook(
            name=policy.name,
            content=policy.markdown_content,
            description=policy.description,
            keywords=keywords if keywords else None,
            natural_language_trigger=natural_language_trigger if natural_language_trigger else None,
            threshold=threshold,
            priority=policy.priority,
            enabled=policy.enabled,
            policy_id=policy.id,
        )

    elif policy_type == PolicyType.TOOL_GUIDE:
        keywords = []

        for trigger in policy.triggers:
            trigger_type = getattr(trigger, 'type', None)
            if trigger_type == "keyword":
                trigger_value = getattr(trigger, 'value', [])
                if isinstance(trigger_value, list):
                    keywords.extend(trigger_value)
                else:
                    keywords.append(trigger_value)

        await agent.policies.add_tool_guide(
            name=policy.name,
            content=policy.guide_content,
            target_tools=policy.target_tools,
            description=policy.description,
            keywords=keywords if keywords else None,
            target_apps=getattr(policy, 'target_apps', None),
            prepend=getattr(policy, 'prepend', False),
            priority=policy.priority,
            enabled=policy.enabled,
            policy_id=policy.id,
        )

    else:
        policy_system = await agent.policies._ensure_policy_system()
        await policy_system.storage.add_policy(policy)
        await policy_system.initialize()


def create_activity_tracker_callback(
    tracker, var_manager=None
) -> Callable[[Dict[str, Any], Dict[str, Any], str], None]:
    """Create a tracker callback function for ActivityTracker.

    Args:
        tracker: ActivityTracker instance
        var_manager: Optional VariablesManager instance to reset

    Returns:
        Callback function that can be passed to evaluate_task_with_langfuse
    """

    def tracker_callback(result: Dict[str, Any], keyword_check: Dict[str, Any], intent: str):
        """Callback for tracking evaluation results with ActivityTracker."""
        from cuga.backend.activity_tracker.tracker import Step

        # Capture agent steps before callback adds its own
        agent_steps = len(tracker.steps)

        task_name = result["task_name"]
        response = result.get("response", "")

        # Collect prompt data so it appears in trajectory task files.
        # Prompts are accumulated and then flushed into the next collect_step call.
        user_context = result.get("user_context", "")
        if user_context:
            tracker.collect_prompt(role="system", value=user_context)
        tracker.collect_prompt(role="user", value=intent)
        tracker.collect_step(Step(name="UserPrompt", data=intent))

        if result.get("error"):
            error_report = json.dumps(
                {
                    "task_name": task_name,
                    "difficulty": result.get("difficulty", "unknown"),
                    "success": False,
                    "error": result["error"],
                }
            )
            tracker.finish_task(
                intent=intent,
                site="",
                task_id=task_name,
                eval=error_report,
                score=0.0,
                agent_answer="",
                exception=True,
                num_steps=agent_steps,
                total_llm_calls=result.get("total_llm_calls", 0),
                total_tokens=result.get("total_tokens", 0),
                total_cost=result.get("total_cost", 0.0),
                total_cache_input_tokens=result.get("total_cache_input_tokens", 0),
                duration=result.get("full_execution_time", 0),
                agent_v="",
            )
            tracker.collect_score(0.0)
        else:
            report_md = json.dumps(
                {
                    "task_name": task_name,
                    "difficulty": result.get("difficulty", "unknown"),
                    "success": result["success"],
                    "match_rate": keyword_check["match_rate"],
                    "found_keywords": keyword_check["found_keywords"],
                    "missing_keywords": keyword_check["missing_keywords"],
                }
            )
            score = keyword_check["match_rate"]
            tracker.finish_task(
                intent=intent,
                site="",
                task_id=task_name,
                eval=report_md,
                score=score,
                agent_answer=response,
                exception=False,
                num_steps=agent_steps,
                total_llm_calls=result.get("total_llm_calls", 0),
                total_tokens=result.get("total_tokens", 0),
                total_cost=result.get("total_cost", 0.0),
                total_cache_input_tokens=result.get("total_cache_input_tokens", 0),
                duration=result.get("full_execution_time", 0),
                agent_v="",
            )
            tracker.collect_step(Step(name="EvaluationResult", data=report_md))
            tracker.collect_score(score)

    return tracker_callback


def check_keywords(response: str, expected_keywords: List[str]) -> Dict[str, Any]:
    """Check if expected keywords are present in the response.

    Supports OR mechanism: keywords can use "|" to specify alternatives.
    Example: "1000|1,000" will match if either "1000" or "1,000" is found.

    Args:
        response: Agent's response text
        expected_keywords: List of keywords that should be present (can use "|" for OR)

    Returns:
        Dictionary with keyword check results
    """
    answer_str = response.replace("\u202f", " ")
    response_lower = answer_str.lower()
    found_keywords = []
    missing_keywords = []

    for keyword in expected_keywords:
        if "|" in keyword:
            alternatives = [alt.strip() for alt in keyword.split("|")]
            matched = False
            for alt in alternatives:
                alt_lower = alt.lower()
                if alt_lower in response_lower:
                    matched = True
                    break

            if matched:
                found_keywords.append(keyword)
            else:
                missing_keywords.append(keyword)
        else:
            keyword_lower = keyword.lower()
            if keyword_lower in response_lower:
                found_keywords.append(keyword)
            else:
                missing_keywords.append(keyword)

    all_found = len(missing_keywords) == 0
    match_rate = len(found_keywords) / len(expected_keywords) if expected_keywords else 0.0

    return {
        "all_found": all_found,
        "match_rate": match_rate,
        "found_keywords": found_keywords,
        "missing_keywords": missing_keywords,
        "total_keywords": len(expected_keywords),
        "found_count": len(found_keywords),
    }


async def evaluate_task_with_langfuse(
    agent: CugaAgent,
    task: Dict[str, Any],
    task_index: int,
    langfuse_handler: Optional[Any] = None,
    user_context: Optional[str] = None,
    tracker_callback: Optional[Callable[[Dict[str, Any], Dict[str, Any], str], None]] = None,
    track_tool_calls: bool = True,
    metrics_config: Optional[MetricsConfig] = None,
) -> Dict[str, Any]:
    """Evaluate a single task with optional Langfuse tracing and enhanced metrics.

    Args:
        agent: CugaAgent instance
        task: Task dictionary with 'name', 'intent', 'difficulty', 'expected_output'
        task_index: Index of the task (for unique thread_id generation)
        langfuse_handler: Optional Langfuse handler for tracing
        user_context: Optional user context string
        tracker_callback: Optional callback function for tracking (receives result dict, keyword_check dict, intent string)
        track_tool_calls: Whether to track tool calls (default: True)
        metrics_config: Optional configuration for enhanced metrics (similarity, LLM judge, final score).
                       When None, only keyword matching is performed (backwards compatible).

    Returns:
        Evaluation result dictionary with:
        - Basic fields: task_name, difficulty, intent, thread_id, success, match_rate, response, etc.
        - Enhanced fields (when metrics_config provided): output_similarity, output_exact_match,
          llm_judge_score, llm_judge_binary, llm_judge_rationale, task_final_score
    """
    task_name = task.get("name", "unknown")
    intent = task.get("intent", "")
    difficulty = task.get("difficulty", "unknown")
    expected_output = task.get("expected_output", {})
    expected_keywords = expected_output.get("keywords", [])

    thread_id = f"eval_{task_name}_{task_index}_{uuid.uuid4().hex[:8]}"

    logger.info(f"\n{'=' * 80}")
    logger.info(f"Evaluating: {task_name} ({difficulty})")
    logger.info(f"Thread ID: {thread_id}")
    logger.info(f"Intent: {intent}")
    logger.info(f"Expected keywords: {expected_keywords}")
    logger.info(f"{'=' * 80}")

    try:
        keyword_check_result = None
        tool_calls = []

        if langfuse_handler:
            try:
                from langfuse import get_client

                langfuse = get_client()

                trace_name = f"eval_{task_name}_{task_index}"
                predefined_trace_id = langfuse.create_trace_id(seed=f"{task_name}_{task_index}_{thread_id}")

                logger.info(f"📊 Starting Langfuse trace: {trace_name} (ID: {predefined_trace_id})")

                with langfuse.start_as_current_observation(
                    as_type="span",
                    name=trace_name,
                    trace_context={"trace_id": predefined_trace_id},
                    input={
                        "intent": intent,
                        "task_name": task_name,
                        "difficulty": difficulty,
                        "expected_keywords": expected_keywords,
                    },
                    metadata={"thread_id": thread_id, "task_index": task_index},
                ) as span:
                    invoke_result = await agent.invoke(
                        [HumanMessage(content=intent)],
                        thread_id=thread_id,
                        user_context=user_context or "",
                        track_tool_calls=track_tool_calls,
                    )
                    # Handle both string and object return types
                    result_state = invoke_result.answer if hasattr(invoke_result, 'answer') else invoke_result

                    keyword_check = check_keywords(result_state, expected_keywords)

                    response_preview = result_state
                    span.update(
                        output={
                            "response_preview": response_preview,
                            "keyword_results": {
                                "found_keywords": keyword_check["found_keywords"],
                                "missing_keywords": keyword_check["missing_keywords"],
                                "total_keywords": keyword_check["total_keywords"],
                                "found_count": keyword_check["found_count"],
                            },
                        },
                        metadata={
                            "thread_id": thread_id,
                            "task_index": task_index,
                        },
                    )

                    missing_keywords_str = (
                        ", ".join(keyword_check['missing_keywords'])
                        if keyword_check['missing_keywords']
                        else "none"
                    )
                    span.score_trace(
                        name="keyword_match",
                        value=keyword_check["match_rate"],
                        data_type="NUMERIC",
                        comment=f"Keyword match rate: {keyword_check['found_count']}/{keyword_check['total_keywords']} keywords found. Missing keywords: {missing_keywords_str}",
                    )

                    overall_score = True if keyword_check["all_found"] else False
                    span.score_trace(
                        name="success",
                        value=overall_score,
                        data_type="BOOLEAN",
                        comment="Overall task success: True if all keywords found, otherwise False",
                    )

                response = result_state
                keyword_check_result = keyword_check

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
                logger.warning(f"Failed to start Langfuse trace: {e}")
                invoke_result = await agent.invoke(
                    [HumanMessage(content=intent)],
                    thread_id=thread_id,
                    user_context=user_context or "",
                    track_tool_calls=track_tool_calls,
                )
                # Handle both string and object return types
                response = invoke_result.answer if hasattr(invoke_result, 'answer') else invoke_result
                keyword_check_result = check_keywords(response, expected_keywords)
        else:
            invoke_result = await agent.invoke(
                [HumanMessage(content=intent)],
                thread_id=thread_id,
                user_context=user_context or "",
                track_tool_calls=track_tool_calls,
            )
            # Handle both string and object return types
            response = invoke_result.answer if hasattr(invoke_result, 'answer') else invoke_result
            keyword_check_result = check_keywords(response, expected_keywords)

        if keyword_check_result is None:
            keyword_check = check_keywords(response, expected_keywords)
        else:
            keyword_check = keyword_check_result

        # Extract tool calls - prioritize invoke_result.tool_calls (when track_tool_calls=True)
        # This is the correct source for CugaLite/M3 benchmarks
        # Fall back to ActivityTracker for older CUGA versions
        if track_tool_calls:
            tool_calls = []

            # Debug: Check what's in invoke_result
            logger.info(f"[TOOL_TRACKING] invoke_result type: {type(invoke_result)}")
            logger.info(
                f"[TOOL_TRACKING] invoke_result has tool_calls attr: {hasattr(invoke_result, 'tool_calls')}"
            )
            if hasattr(invoke_result, 'tool_calls'):
                logger.info(f"[TOOL_TRACKING] invoke_result.tool_calls value: {invoke_result.tool_calls}")
                logger.info(
                    f"[TOOL_TRACKING] invoke_result.tool_calls type: {type(invoke_result.tool_calls)}"
                )
                if invoke_result.tool_calls:
                    logger.info(
                        f"[TOOL_TRACKING] invoke_result.tool_calls length: {len(invoke_result.tool_calls)}"
                    )

            # Primary: Use invoke_result.tool_calls (available when track_tool_calls=True)
            if hasattr(invoke_result, 'tool_calls') and invoke_result.tool_calls:
                logger.info("[TOOL_TRACKING] Using invoke_result.tool_calls (primary source)")
                for tc in invoke_result.tool_calls:
                    if isinstance(tc, dict):
                        # Preserve all metadata from the tool call record
                        # Use "arguments" as the standard key (M3 ground truth format)
                        tool_call_record = {
                            "name": tc.get("name", ""),
                            "arguments": tc.get("arguments", tc.get("args", {})),
                        }
                        # Add optional metadata if present
                        if "result" in tc:
                            tool_call_record["result"] = tc["result"]
                        if "error" in tc:
                            tool_call_record["error"] = tc["error"]
                        if "duration_ms" in tc:
                            tool_call_record["duration_ms"] = tc["duration_ms"]
                        if "operation_id" in tc:
                            tool_call_record["operation_id"] = tc["operation_id"]
                        if "app_name" in tc:
                            tool_call_record["app_name"] = tc["app_name"]
                        tool_calls.append(tool_call_record)
                    elif hasattr(tc, 'name'):
                        tool_call_record = {
                            "name": tc.name,
                            "arguments": getattr(tc, 'arguments', getattr(tc, 'args', {})),
                        }
                        # Add optional metadata if present
                        for attr in ['result', 'error', 'duration_ms', 'operation_id', 'app_name']:
                            if hasattr(tc, attr):
                                tool_call_record[attr] = getattr(tc, attr)
                        tool_calls.append(tool_call_record)
                    elif hasattr(tc, 'model_dump'):
                        tc_dict = tc.model_dump()
                        tool_call_record = {
                            "name": tc_dict.get("name", ""),
                            "arguments": tc_dict.get("arguments", tc_dict.get("args", {})),
                        }
                        # Add optional metadata if present
                        for key in ['result', 'error', 'duration_ms', 'operation_id', 'app_name']:
                            if key in tc_dict:
                                tool_call_record[key] = tc_dict[key]
                        tool_calls.append(tool_call_record)
                logger.info(f"[TOOL_TRACKING] Extracted {len(tool_calls)} tool calls from invoke_result")
            # Fallback: Extract from ActivityTracker if invoke_result didn't have tool calls
            if not tool_calls:
                logger.info("[TOOL_TRACKING] Falling back to ActivityTracker extraction")
                tool_calls = _extract_tool_calls_from_tracker()
                if tool_calls:
                    logger.info(
                        f"[TOOL_TRACKING] Extracted {len(tool_calls)} tool calls from ActivityTracker (fallback)"
                    )
        else:
            tool_calls = []

        # Build base result (backwards compatible)
        result = {
            "task_name": task_name,
            "difficulty": difficulty,
            "intent": intent,
            "user_context": user_context or "",
            "thread_id": thread_id,
            "success": keyword_check["all_found"],
            "match_rate": keyword_check["match_rate"],
            "response": response,
            "expected_keywords": expected_keywords,
            "found_keywords": keyword_check["found_keywords"],
            "missing_keywords": keyword_check["missing_keywords"],
            "tool_calls": [tc for tc in tool_calls] if tool_calls else [],
            "error": None,
        }

        # Preserve UUID from input task if present (M3 benchmark format)
        if "uuid" in task:
            result["uuid"] = task["uuid"]
        elif "sample_id" in task:
            result["uuid"] = task["sample_id"]

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
            result["trace_id"] = predefined_trace_id

        # Compute enhanced metrics if metrics_config is provided
        if metrics_config:
            # Get expected output for comparison
            expected_output_key = metrics_config.get("expected_output_key", "expected_output.answer")
            expected_answer = _get_nested_value(task, expected_output_key)
            if expected_answer is None:
                # Fallback: try common patterns
                expected_answer = (
                    task.get("expected_output", {}).get("answer")
                    or task.get("expected_output", {}).get("text")
                    or task.get("expected_answer")
                    or str(task.get("expected_output", ""))
                )

            result["expected_answer"] = expected_answer

            # Similarity metrics
            if metrics_config.get("enable_similarity", False):
                MetricsClass = _get_metrics_class()
                if MetricsClass:
                    method = metrics_config.get("similarity_method", "rapidfuzz_token_set")
                    try:
                        similarity = MetricsClass.string_similarity(response, expected_answer, method=method)
                        exact_match = MetricsClass.exact_match(response, expected_answer)
                        result["output_similarity"] = similarity
                        result["output_exact_match"] = 1 if exact_match else 0
                    except Exception as e:
                        logger.warning(f"Failed to compute similarity: {e}")
                        result["output_similarity"] = None
                        result["output_exact_match"] = None

            # LLM Judge metrics
            if metrics_config.get("enable_llm_judge", False):
                provider = metrics_config.get("llm_judge_provider", "groq")
                judge = _get_llm_judge(provider)
                if judge:
                    try:
                        judge_result = await judge.judge(
                            predicted=response,
                            expected=expected_answer,
                            task_context={"utterance": intent, "task_id": task_name},
                        )
                        llm_score = judge_result.get("score")
                        result["llm_judge_score"] = llm_score
                        result["llm_judge_binary"] = 1 if llm_score and llm_score >= 0.5 else 0
                        result["llm_judge_rationale"] = judge_result.get("rationale", "")[:200]
                        result["llm_judge_name"] = judge.name
                    except Exception as e:
                        logger.warning(f"LLM judge failed: {e}")
                        result["llm_judge_score"] = None
                        result["llm_judge_binary"] = None
                        result["llm_judge_rationale"] = f"Error: {e}"
                        result["llm_judge_name"] = None

            # API call metrics
            if metrics_config.get("enable_api_metrics", False):
                # Get expected tool calls from task
                expected_tool_calls = task.get("expected_output", {}).get("tool_calls", [])
                expected_api_names = set()
                for tc in expected_tool_calls:
                    if isinstance(tc, dict) and "name" in tc:
                        expected_api_names.add(tc["name"])
                    elif isinstance(tc, str):
                        expected_api_names.add(tc)

                # Get actual tool calls from agent response
                actual_api_names = set()
                for tc in tool_calls:
                    if hasattr(tc, "name"):
                        actual_api_names.add(tc.name)
                    elif isinstance(tc, dict) and "name" in tc:
                        actual_api_names.add(tc["name"])
                    elif isinstance(tc, str):
                        actual_api_names.add(tc)

                # Normalize API names for comparison
                # Registry tool names are verbose: bpo_candidate_source_sla_per_source_candidate_source_sla_per_source_requisition_id_get
                # Expected names are short: candidate_source_sla_per_source
                def normalize_api_name(name: str) -> str:
                    name = name.lower().strip()
                    # Remove app prefix
                    if name.startswith("bpo_"):
                        name = name[4:]
                    # Remove common suffixes (HTTP methods and parameter patterns)
                    for suffix in ["_get", "_post", "_put", "_delete"]:
                        if name.endswith(suffix):
                            name = name[: -len(suffix)]
                    for suffix in ["_requisition_id", "_skill_name"]:
                        if name.endswith(suffix):
                            name = name[: -len(suffix)]
                    return name.replace("-", "_").replace(" ", "_")

                def api_matches(expected: str, actual: str) -> bool:
                    """Check if expected API name matches actual (allowing for verbose registry names)."""
                    exp_norm = normalize_api_name(expected)
                    act_norm = normalize_api_name(actual)
                    # Direct match
                    if exp_norm == act_norm:
                        return True
                    # Check if expected is contained in actual (for verbose registry names)
                    # e.g., "candidate_source_sla_per_source" in "candidate_source_sla_per_source_candidate_source_sla_per_source"
                    if exp_norm in act_norm:
                        return True
                    return False

                logger.info(f"[API_TRACKING] Expected APIs: {list(expected_api_names)}")
                logger.info(f"[API_TRACKING] Actual APIs: {list(actual_api_names)}")

                # Compute API metrics using flexible matching
                apis_missing = []
                for exp_api in expected_api_names:
                    if not any(api_matches(exp_api, act_api) for act_api in actual_api_names):
                        apis_missing.append(exp_api)

                apis_extra = []
                for act_api in actual_api_names:
                    if not any(api_matches(exp_api, act_api) for exp_api in expected_api_names):
                        apis_extra.append(act_api)

                apis_correct = len(apis_missing) == 0

                result["expected_apis"] = list(expected_api_names)
                result["apis_called"] = list(actual_api_names)
                result["apis_missing"] = apis_missing
                result["apis_extra"] = apis_extra
                result["apis_correct"] = 1 if apis_correct else 0
                result["api_call_count"] = len(tool_calls)
                result["expected_api_count"] = len(expected_tool_calls)
                result["api_count_correct"] = 1 if len(apis_missing) == 0 else 0

            # Final score (composite metric)
            if metrics_config.get("enable_similarity", False) or metrics_config.get(
                "enable_llm_judge", False
            ):
                MetricsClass = _get_metrics_class()
                if MetricsClass and result.get("output_similarity") is not None:
                    try:
                        threshold_exact = metrics_config.get("final_score_threshold_exact", 0.85)
                        threshold_inexact = metrics_config.get("final_score_threshold_inexact", 0.9)
                        # Include API metrics in final score if enabled
                        apis_missing = (
                            result.get("apis_missing", [])
                            if metrics_config.get("enable_api_metrics", False)
                            else []
                        )
                        require_api_match = metrics_config.get("require_api_match", False)
                        final_score = MetricsClass.final_task_score(
                            output_exact_match=result.get("output_exact_match", 0),
                            output_similarity=result.get("output_similarity", 0.0),
                            llm_judge_score=result.get("llm_judge_score"),
                            llm_judge_requested=metrics_config.get("enable_llm_judge", False),
                            agent_output=response,
                            threshold_exact=threshold_exact,
                            threshold_inexact=threshold_inexact,
                            apis_missing=apis_missing,
                            require_api_match=require_api_match,
                        )
                        result["task_final_score"] = final_score
                        # Override success based on final score if we have enhanced metrics
                        result["success"] = final_score == 1
                    except Exception as e:
                        logger.warning(f"Failed to compute final score: {e}")
                        result["task_final_score"] = None

        # Log results
        if result["success"]:
            logger.info("✅ PASS: All keywords found")
        else:
            logger.warning(f"❌ FAIL: Missing keywords: {keyword_check['missing_keywords']}")
            logger.info(f"   Match rate: {keyword_check['match_rate']:.1%}")

        # Log enhanced metrics if present
        if metrics_config:
            if "output_similarity" in result and result["output_similarity"] is not None:
                logger.info(f"   Similarity: {result['output_similarity']:.2f}")
            if "llm_judge_score" in result and result["llm_judge_score"] is not None:
                binary_str = "✓" if result.get("llm_judge_binary") == 1 else "✗"
                logger.info(f"   LLM Judge: {result['llm_judge_score']:.2f} ({binary_str})")
            if "apis_called" in result:
                api_status = "✓" if result.get("apis_correct") == 1 else "✗"
                logger.info(f"   APIs: {len(result.get('apis_called', []))} called, {api_status}")
                if result.get("apis_missing"):
                    logger.info(f"   Missing APIs: {', '.join(result['apis_missing'])}")
            if "task_final_score" in result and result["task_final_score"] is not None:
                final_str = "✓ PASS" if result["task_final_score"] == 1 else "✗ FAIL"
                logger.info(f"   Final Score: {final_str}")

        if tool_calls:
            logger.debug(f"\n{'─' * 40} TOOL CALLS {'─' * 40}")
            for tc in tool_calls:
                logger.debug(tc)
            logger.debug(f"{'─' * 93}\n")

        if tracker_callback:
            tracker_callback(result, keyword_check, intent)

        return result

    except Exception as e:
        import traceback

        logger.error(traceback.format_exc())
        logger.error(f"❌ ERROR in task {task_name}: {e}")

        error_result = {
            "task_name": task_name,
            "difficulty": difficulty,
            "intent": intent,
            "thread_id": thread_id,
            "success": False,
            "match_rate": 0.0,
            "response": "",
            "expected_keywords": expected_keywords,
            "found_keywords": [],
            "missing_keywords": expected_keywords,
            "tool_calls": [],
            "error": str(e),
        }

        if tracker_callback:
            tracker_callback(error_result, {"match_rate": 0.0, "all_found": False}, intent)

        return error_result


async def evaluate_multiturn_task_with_langfuse(
    agent: CugaAgent,
    turns: List[Dict[str, Any]],
    task_name: str,
    task_index: int,
    langfuse_handler: Optional[Any] = None,
    user_context: Optional[str] = None,
    tracker_callback: Optional[Callable[[Dict[str, Any], Dict[str, Any], str], None]] = None,
    track_tool_calls: bool = True,
    expected_keywords: Optional[List[str]] = None,
    task_metadata: Optional[Dict[str, Any]] = None,
    turn_delay: float = 0.2,
) -> Dict[str, Any]:
    """Evaluate a multi-turn task with optional Langfuse tracing.

    Args:
        agent: CugaAgent instance
        turns: List of turn dictionaries, each with 'query' key
        task_name: Name/ID of the task
        task_index: Index of the task (for unique thread_id generation)
        langfuse_handler: Optional Langfuse handler for tracing
        user_context: Optional user context string
        tracker_callback: Optional callback function for tracking
        track_tool_calls: Whether to track tool calls (default: True)
        expected_keywords: Optional list of keywords to check in final response
        task_metadata: Optional metadata dict (domain, difficulty, etc.) to include in results
        turn_delay: Delay in seconds between turns (default: 0.2)

    Returns:
        Evaluation result dictionary
    """
    num_turns = len(turns)
    thread_id = f"multiturn_{task_name}_{task_index}_{uuid.uuid4().hex[:8]}"

    logger.info(f"\n{'=' * 80}")
    logger.info(f"Evaluating multi-turn task: {task_name}")
    logger.info(f"Thread ID: {thread_id} (used for all {num_turns} turns)")
    logger.info(f"Number of turns: {num_turns}")
    logger.info(f"{'=' * 80}")

    initial_intent = turns[0].get("query", "") if turns else ""

    try:
        keyword_check_result = None
        all_responses = []
        all_tool_calls = []
        final_response = None

        if langfuse_handler:
            try:
                from langfuse import get_client

                langfuse = get_client()

                trace_name = f"multiturn_{task_name}_{task_index}"
                predefined_trace_id = langfuse.create_trace_id(seed=f"{task_name}_{task_index}_{thread_id}")

                logger.info(f"📊 Starting Langfuse trace: {trace_name} (ID: {predefined_trace_id})")

                metadata = {"thread_id": thread_id, "task_index": task_index}
                if task_metadata:
                    metadata.update(task_metadata)

                with langfuse.start_as_current_observation(
                    as_type="span",
                    name=trace_name,
                    trace_context={"trace_id": predefined_trace_id},
                    input={
                        "task_name": task_name,
                        "num_turns": num_turns,
                        "turns": [turn.get("query", "") for turn in turns],
                        **(task_metadata or {}),
                    },
                    metadata=metadata,
                ) as span:
                    for turn_idx, turn in enumerate(turns, 1):
                        query = turn.get("query", "")
                        logger.info(f"\n[Turn {turn_idx}/{num_turns}] Query: {query}")
                        logger.info(f"[Turn {turn_idx}] Using thread_id: {thread_id}")

                        invoke_result = await agent.invoke(
                            [HumanMessage(content=query)],
                            thread_id=thread_id,
                            user_context=user_context,
                            track_tool_calls=track_tool_calls,
                        )
                        result_state = invoke_result.answer
                        turn_tool_calls = invoke_result.tool_calls or []
                        all_tool_calls.extend([(turn_idx, tc) for tc in turn_tool_calls])

                        all_responses.append(
                            {
                                "turn": turn_idx,
                                "query": query,
                                "response": result_state,
                                "tool_calls": [tc for tc in turn_tool_calls],
                            }
                        )

                        # Enhanced logging for tool call tracking
                        answer_preview = result_state[:100] if result_state else "(empty)"
                        logger.info(
                            f"[Turn {turn_idx}] Response received: {answer_preview}{'...' if len(result_state) > 100 else ''}"
                        )
                        logger.info(f"[Turn {turn_idx}] Tool calls captured: {len(turn_tool_calls)}")

                        if not turn_tool_calls and result_state:
                            logger.warning(
                                f"[Turn {turn_idx}] ⚠️  Answer provided but NO tool calls recorded!"
                            )
                            logger.warning(f"[Turn {turn_idx}] This suggests either:")
                            logger.warning("  1. Agent hallucinated without using tools (agent failure)")
                            logger.warning(
                                "  2. Tool tracking system failed to capture calls (tracking failure)"
                            )
                            logger.warning(f"  3. track_tool_calls={track_tool_calls} - verify this is True")
                        elif turn_tool_calls:
                            tool_names = [
                                tc.get('name', 'unknown')
                                if isinstance(tc, dict)
                                else getattr(tc, 'name', 'unknown')
                                for tc in turn_tool_calls
                            ]
                            logger.info(f"[Turn {turn_idx}] Tools used: {tool_names}")

                        if turn_idx < num_turns:
                            await asyncio.sleep(turn_delay)

                    final_response = all_responses[-1]["response"] if all_responses else None

                    if expected_keywords and final_response:
                        keyword_check = check_keywords(final_response, expected_keywords)
                        keyword_check_result = keyword_check

                        span.update(
                            output={
                                "final_response": final_response,
                                "all_responses": all_responses,
                                "keyword_results": {
                                    "found_keywords": keyword_check["found_keywords"],
                                    "missing_keywords": keyword_check["missing_keywords"],
                                    "total_keywords": keyword_check["total_keywords"],
                                    "found_count": keyword_check["found_count"],
                                },
                            },
                            metadata={
                                "thread_id": thread_id,
                                "task_index": task_index,
                                "num_turns": num_turns,
                                **(task_metadata or {}),
                            },
                        )

                        missing_keywords_str = (
                            ", ".join(keyword_check["missing_keywords"])
                            if keyword_check["missing_keywords"]
                            else "none"
                        )
                        span.score_trace(
                            name="keyword_match",
                            value=keyword_check["match_rate"],
                            data_type="NUMERIC",
                            comment=f"Keyword match rate: {keyword_check['found_count']}/{keyword_check['total_keywords']} keywords found. Missing keywords: {missing_keywords_str}",
                        )

                        overall_score = True if keyword_check["all_found"] else False
                        span.score_trace(
                            name="success",
                            value=overall_score,
                            data_type="BOOLEAN",
                            comment="Overall task success: True if all keywords found, otherwise False",
                        )
                    else:
                        span.update(
                            output={
                                "final_response": final_response,
                                "all_responses": all_responses,
                            },
                            metadata={
                                "thread_id": thread_id,
                                "task_index": task_index,
                                "num_turns": num_turns,
                                **(task_metadata or {}),
                            },
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
                logger.warning(f"Langfuse tracing failed: {e}")
                for turn_idx, turn in enumerate(turns, 1):
                    query = turn.get("query", "")
                    logger.info(f"\n[Turn {turn_idx}/{num_turns}] Query: {query}")
                    logger.info(f"[Turn {turn_idx}] Using thread_id: {thread_id}")

                    invoke_result = await agent.invoke(
                        [HumanMessage(content=query)],
                        thread_id=thread_id,
                        user_context=user_context,
                        track_tool_calls=track_tool_calls,
                    )
                    result_state = invoke_result.answer
                    turn_tool_calls = invoke_result.tool_calls or []
                    all_tool_calls.extend([(turn_idx, tc) for tc in turn_tool_calls])

                    all_responses.append(
                        {
                            "turn": turn_idx,
                            "query": query,
                            "response": result_state,
                            "tool_calls": [tc for tc in turn_tool_calls],
                        }
                    )

                    # Enhanced logging for tool call tracking (Langfuse error fallback path)
                    answer_preview = result_state[:100] if result_state else "(empty)"
                    logger.info(
                        f"[Turn {turn_idx}] Response received: {answer_preview}{'...' if len(result_state) > 100 else ''}"
                    )
                    logger.info(f"[Turn {turn_idx}] Tool calls captured: {len(turn_tool_calls)}")

                    if not turn_tool_calls and result_state:
                        logger.warning(f"[Turn {turn_idx}] ⚠️  Answer provided but NO tool calls recorded!")
                        logger.warning(f"[Turn {turn_idx}] This suggests either:")
                        logger.warning("  1. Agent hallucinated without using tools (agent failure)")
                        logger.warning("  2. Tool tracking system failed to capture calls (tracking failure)")
                        logger.warning(f"  3. track_tool_calls={track_tool_calls} - verify this is True")
                    elif turn_tool_calls:
                        tool_names = [
                            tc.get('name', 'unknown')
                            if isinstance(tc, dict)
                            else getattr(tc, 'name', 'unknown')
                            for tc in turn_tool_calls
                        ]
                        logger.info(f"[Turn {turn_idx}] Tools used: {tool_names}")

                    if turn_idx < num_turns:
                        await asyncio.sleep(turn_delay)

                final_response = all_responses[-1]["response"] if all_responses else None

                if expected_keywords and final_response:
                    keyword_check_result = check_keywords(final_response, expected_keywords)
        else:
            for turn_idx, turn in enumerate(turns, 1):
                query = turn.get("query", "")
                logger.info(f"\n[Turn {turn_idx}/{num_turns}] Query: {query}")
                logger.info(f"[Turn {turn_idx}] Using thread_id: {thread_id}")

                invoke_result = await agent.invoke(
                    [HumanMessage(content=query)],
                    thread_id=thread_id,
                    user_context=user_context,
                    track_tool_calls=track_tool_calls,
                )
                result_state = invoke_result.answer
                turn_tool_calls = invoke_result.tool_calls or []
                all_tool_calls.extend([(turn_idx, tc) for tc in turn_tool_calls])

                all_responses.append(
                    {
                        "turn": turn_idx,
                        "query": query,
                        "response": result_state,
                        "tool_calls": [tc for tc in turn_tool_calls],
                    }
                )

                # Enhanced logging for tool call tracking (no Langfuse path)
                answer_preview = result_state[:100] if result_state else "(empty)"
                logger.info(
                    f"[Turn {turn_idx}] Response received: {answer_preview}{'...' if len(result_state) > 100 else ''}"
                )
                logger.info(f"[Turn {turn_idx}] Tool calls captured: {len(turn_tool_calls)}")

                if not turn_tool_calls and result_state:
                    logger.warning(f"[Turn {turn_idx}] ⚠️  Answer provided but NO tool calls recorded!")
                    logger.warning(f"[Turn {turn_idx}] This suggests either:")
                    logger.warning("  1. Agent hallucinated without using tools (agent failure)")
                    logger.warning("  2. Tool tracking system failed to capture calls (tracking failure)")
                    logger.warning(f"  3. track_tool_calls={track_tool_calls} - verify this is True")
                elif turn_tool_calls:
                    tool_names = [
                        tc.get('name', 'unknown') if isinstance(tc, dict) else getattr(tc, 'name', 'unknown')
                        for tc in turn_tool_calls
                    ]
                    logger.info(f"[Turn {turn_idx}] Tools used: {tool_names}")

                if turn_idx < num_turns:
                    await asyncio.sleep(turn_delay)

            final_response = all_responses[-1]["response"] if all_responses else None

            if expected_keywords and final_response:
                keyword_check_result = check_keywords(final_response, expected_keywords)

        if not keyword_check_result:
            keyword_check_result = {
                "all_found": False,
                "match_rate": 0.0,
                "found_keywords": [],
                "missing_keywords": expected_keywords or [],
                "total_keywords": len(expected_keywords) if expected_keywords else 0,
                "found_count": 0,
            }

        intent = turns[0].get("query", "") if turns else initial_intent

        result = {
            "task_name": task_name,
            "name": task_name,
            "intent": intent,
            "num_turns": num_turns,
            "thread_id": thread_id,
            "response": final_response or "",
            "success": keyword_check_result["all_found"],
            "match_rate": keyword_check_result["match_rate"],
            "expected_keywords": expected_keywords or [],
            "found_keywords": keyword_check_result["found_keywords"],
            "missing_keywords": keyword_check_result["missing_keywords"],
            "final_response": final_response,
            "all_responses": all_responses,
            "tool_calls": [
                tc for turn_idx, tc in all_tool_calls
            ],  # Fixed: Remove turn_idx from tuple, keep flat list of dicts
            "error": None,
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
            result["trace_id"] = predefined_trace_id

        if task_metadata:
            result.update(task_metadata)
            # Preserve UUID from task_metadata if present (M3 benchmark format)
            # task_metadata may contain "uuid" passed from the caller

        logger.info(f"✅ Completed: {task_name}")
        if keyword_check_result:
            logger.info(
                f"   Keywords: {keyword_check_result['found_count']}/{keyword_check_result['total_keywords']} found"
            )
            logger.info(f"   Match rate: {keyword_check_result['match_rate']:.2%}")

        if all_tool_calls:
            logger.debug(f"\n{'─' * 40} TOOL CALLS ({len(all_tool_calls)} total) {'─' * 30}")
            for turn_idx, tc in all_tool_calls:
                logger.debug(f"[Turn {turn_idx}] {tc}")
            logger.debug(f"{'─' * 93}\n")

        if tracker_callback:
            tracker_callback(result, keyword_check_result, initial_intent)

        return result

    except Exception as e:
        import traceback

        logger.error(traceback.format_exc())
        logger.error(f"❌ ERROR in multi-turn task {task_name}: {e}")

        intent = turns[0].get("query", "") if turns else ""

        error_result = {
            "task_name": task_name,
            "name": task_name,
            "intent": intent,
            "num_turns": num_turns,
            "thread_id": thread_id,
            "response": "",
            "success": False,
            "match_rate": 0.0,
            "expected_keywords": expected_keywords or [],
            "found_keywords": [],
            "missing_keywords": expected_keywords or [],
            "error": str(e),
            "final_response": None,
            "all_responses": all_responses if "all_responses" in locals() else [],
            "tool_calls": (
                [(turn_idx, tc) for turn_idx, tc in all_tool_calls] if "all_tool_calls" in locals() else []
            ),
        }

        if task_metadata:
            error_result.update(task_metadata)

        if tracker_callback:
            tracker_callback(
                error_result,
                {
                    "match_rate": 0.0,
                    "all_found": False,
                    "found_keywords": [],
                    "missing_keywords": expected_keywords or [],
                    "total_keywords": len(expected_keywords) if expected_keywords else 0,
                    "found_count": 0,
                },
                intent,
            )

        return error_result


def print_evaluation_summary(results: List[Dict[str, Any]]):
    """Print evaluation summary.

    Args:
        results: List of evaluation result dictionaries
    """
    if not results:
        logger.warning("No results to summarize")
        return

    total = len(results)
    avg_match_rate = sum(r["match_rate"] for r in results) / total if total > 0 else 0.0

    # Check if enhanced metrics are present
    has_similarity = any("output_similarity" in r and r["output_similarity"] is not None for r in results)
    has_exact_match = any("output_exact_match" in r and r["output_exact_match"] is not None for r in results)
    has_llm_judge = any("llm_judge_score" in r and r["llm_judge_score"] is not None for r in results)
    has_final_score = any("task_final_score" in r and r["task_final_score"] is not None for r in results)
    has_api_metrics = any("apis_called" in r for r in results)
    has_api_count = any("api_call_count" in r and "expected_api_count" in r for r in results)

    by_difficulty: Dict[str, List[Dict[str, Any]]] = {}
    for result in results:
        diff = result.get("difficulty", "unknown")
        if diff not in by_difficulty:
            by_difficulty[diff] = []
        by_difficulty[diff].append(result)

    print("\n" + "=" * 80)
    print("EVALUATION COMPLETE")
    print("=" * 80)
    print(f"Total Tasks: {total}")

    # Final Score first (most important metric)
    if has_final_score:
        final_passes = sum(1 for r in results if r.get("task_final_score") == 1)
        print(f"Final Score: {final_passes}/{total} ({final_passes / total * 100:.1f}%)")

    # Exact matches
    if has_exact_match:
        exact_matches = sum(1 for r in results if r.get("output_exact_match") == 1)
        print(f"Exact Matches: {exact_matches} ({exact_matches / total * 100:.1f}%)")

    # Similarity
    if has_similarity:
        similarities = [r["output_similarity"] for r in results if r.get("output_similarity") is not None]
        if similarities:
            avg_sim = sum(similarities) / len(similarities)
            print(f"Avg Similarity: {avg_sim:.2f}")

    # Keyword match
    tasks_with_keywords = sum(1 for r in results if r.get("match_rate") is not None)
    keyword_full_matches = sum(1 for r in results if r.get("match_rate", 0) == 1.0)
    print(
        f"Keyword Match: {avg_match_rate:.1%} avg ({keyword_full_matches}/{tasks_with_keywords} full matches)"
    )

    # LLM Judge
    if has_llm_judge:
        judge_scores = [r["llm_judge_score"] for r in results if r.get("llm_judge_score") is not None]
        judge_binary = [r["llm_judge_binary"] for r in results if r.get("llm_judge_binary") is not None]
        if judge_scores:
            avg_judge = sum(judge_scores) / len(judge_scores)
            binary_pass = sum(1 for b in judge_binary if b == 1)
            binary_accuracy = binary_pass / len(judge_binary) * 100 if judge_binary else 0
            print(f"LLM Judge: {len(judge_scores)} tasks, avg score={avg_judge:.2f}")
            print(f"  Binary accuracy: {binary_accuracy:.1f}%")

    # API metrics
    if has_api_metrics:
        api_correct = sum(1 for r in results if r.get("apis_correct") == 1)
        print(f"API Accuracy: {api_correct}/{total} ({api_correct / total * 100:.1f}%)")

    if has_api_count:
        api_count_correct = sum(1 for r in results if r.get("api_count_correct") == 1)
        print(f"API Count Accuracy: {api_count_correct}/{total} ({api_count_correct / total * 100:.1f}%)")

    print("\n" + "-" * 80)
    print("Results by Difficulty:")
    print("-" * 80)
    for difficulty in sorted(by_difficulty.keys()):
        results = by_difficulty[difficulty]
        passed_count = sum(1 for r in results if r["success"])
        print(f"\n{difficulty.upper()}:")
        print(f"  Total: {len(results)}")
        print(f"  Passed: {passed_count} ({passed_count / len(results) * 100:.1f}%)")
        print(f"  Failed: {len(results) - passed_count}")

    print("\n" + "-" * 80)
    print("Failed Tasks:")
    print("-" * 80)
    failed_results = [r for r in results if not r["success"]]
    if failed_results:
        for result in failed_results:
            print(f"\n❌ {result['task_name']} ({result.get('difficulty', 'unknown')})")
            print(f"   Intent: {result['intent']}")
            print(f"   Keyword Match: {result['match_rate']:.1%}")
            if result.get('missing_keywords'):
                print(f"   Missing Keywords: {', '.join(result['missing_keywords'])}")
            if result.get('output_similarity') is not None:
                print(f"   Similarity: {result['output_similarity']:.2f}")
            if result.get('llm_judge_score') is not None:
                binary_str = "✓" if result.get('llm_judge_binary') == 1 else "✗"
                print(f"   LLM Judge: {result['llm_judge_score']:.2f} ({binary_str})")
            if result.get('apis_missing'):
                print(f"   Missing APIs: {', '.join(result['apis_missing'])}")
            if result.get('error'):
                print(f"   Error: {result['error']}")
    else:
        print("  None! 🎉")

    print("\n" + "-" * 80)
    print("All Results:")
    print("-" * 80)
    for result in results:
        status = "✅" if result["success"] else "❌"
        task_name = result.get('task_name', 'unknown')
        difficulty = result.get('difficulty', 'unknown')
        match_rate = result.get('match_rate', 0)

        # Build metrics string
        metrics_parts = [f"kw={match_rate:.0%}"]
        if result.get('output_similarity') is not None:
            metrics_parts.append(f"sim={result['output_similarity']:.2f}")
        if result.get('llm_judge_score') is not None:
            metrics_parts.append(f"llm={result['llm_judge_score']:.2f}")
        if result.get('task_final_score') is not None:
            final_str = "✓" if result['task_final_score'] == 1 else "✗"
            metrics_parts.append(f"final={final_str}")

        metrics_str = ", ".join(metrics_parts)
        print(f"{status} {task_name:25s} ({difficulty:6s}) - {metrics_str}")


def flush_langfuse(langfuse_handler: Optional[Any]):
    """Flush Langfuse events in short-lived applications.

    Args:
        langfuse_handler: Optional Langfuse handler
    """
    if langfuse_handler:
        try:
            from langfuse import get_client

            langfuse = get_client()
            langfuse.flush()
            logger.info("✅ Flushed Langfuse events")
        except Exception as e:
            logger.warning(f"Failed to flush Langfuse events: {e}")


def save_evaluation_results(
    results: List[Dict[str, Any]],
    output_dir: Path,
    prefix: str = "evaluation",
    run_timestamp: Optional[str] = None,
) -> Path:
    """Save evaluation results to a JSON file.

    Args:
        results: List of evaluation result dictionaries
        output_dir: Output directory path
        prefix: Filename prefix (e.g., "multiturn", "evaluation")
        run_timestamp: If set, used for filename and metrics (e.g. process start time); otherwise now.

    Returns:
        Path to the saved results file
    """
    from datetime import datetime

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = run_timestamp if run_timestamp else datetime.now().strftime("%Y%m%d_%H%M%S")

    def serialize_tool_calls(obj):
        if hasattr(obj, 'model_dump'):
            return obj.model_dump()
        elif isinstance(obj, tuple) and len(obj) == 2:
            turn_idx, tc = obj
            if hasattr(tc, 'model_dump'):
                return {"turn": turn_idx, "tool_call": tc.model_dump()}
            return {"turn": turn_idx, "tool_call": tc}
        return obj

    serializable_results = []
    for result in results:
        serializable_result = {}
        for key, value in result.items():
            if key == "tool_calls" and isinstance(value, list):
                serializable_result[key] = [serialize_tool_calls(tc) for tc in value]
            elif key == "all_responses" and isinstance(value, list):
                serialized_responses = []
                for resp in value:
                    if isinstance(resp, dict) and "tool_calls" in resp:
                        resp_copy = resp.copy()
                        resp_copy["tool_calls"] = [
                            tc if hasattr(tc, 'model_dump') else tc for tc in resp["tool_calls"]
                        ]
                        serialized_responses.append(resp_copy)
                    else:
                        serialized_responses.append(resp)
                serializable_result[key] = serialized_responses
            else:
                serializable_result[key] = value
        serializable_results.append(serializable_result)

    total = len(results)
    passed = sum(1 for r in results if r.get("success"))
    avg_match_rate = sum(r.get("match_rate", 0) for r in results) / total if total > 0 else 0

    output = {
        "metrics": {
            "timestamp": timestamp,
            "total_tasks": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": passed / total if total > 0 else 0,
            "avg_match_rate": avg_match_rate,
        },
        "results": serializable_results,
    }

    output_file = output_dir / f"{prefix}_{timestamp}.json"
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2, default=str)
    logger.info(f"📁 Results saved to: {output_file}")

    return output_file


# ============================================================================
# ReAct Agent Support
# ============================================================================


async def setup_react_agent_for_evaluation(
    special_instructions: Optional[str] = None,
) -> tuple[GenericReactAgent, Optional[Any]]:
    """Set up the generic ReAct agent with tools and optional Langfuse."""
    return await setup_react_agent_with_tools(special_instructions=special_instructions)


async def evaluate_task_with_langfuse_react(
    agent: "GenericReactAgent",
    task: Dict[str, Any],
    task_index: int,
    langfuse_handler: Optional[Any] = None,
    user_context: Optional[str] = None,
    tracker_callback: Optional[Callable[[Dict[str, Any], Dict[str, Any], str], None]] = None,
    track_tool_calls: bool = True,
    metrics_config: Optional[MetricsConfig] = None,
) -> Dict[str, Any]:
    """ReAct wrapper that reuses the standard single-turn evaluation/result flow."""
    return await evaluate_task_with_langfuse(
        agent=agent,  # type: ignore[arg-type]
        task=task,
        task_index=task_index,
        langfuse_handler=langfuse_handler,
        user_context=user_context,
        tracker_callback=tracker_callback,
        track_tool_calls=track_tool_calls,
        metrics_config=metrics_config,
    )


async def evaluate_multiturn_task_with_langfuse_react(
    agent: "GenericReactAgent",
    turns: List[Dict[str, Any]],
    task_name: str,
    task_index: int,
    langfuse_handler: Optional[Any] = None,
    user_context: Optional[str] = None,
    tracker_callback: Optional[Callable[[Dict[str, Any], Dict[str, Any], str], None]] = None,
    track_tool_calls: bool = True,
    expected_keywords: Optional[List[str]] = None,
    task_metadata: Optional[Dict[str, Any]] = None,
    turn_delay: float = 0.2,
) -> Dict[str, Any]:
    """Evaluate a multi-turn task using the generic ReAct agent."""
    return await evaluate_multiturn_task_with_langfuse(
        agent=agent,  # type: ignore[arg-type]
        turns=turns,
        task_name=task_name,
        task_index=task_index,
        langfuse_handler=langfuse_handler,
        user_context=user_context,
        tracker_callback=tracker_callback,
        track_tool_calls=track_tool_calls,
        expected_keywords=expected_keywords,
        task_metadata=task_metadata,
        turn_delay=turn_delay,
    )
