"""M3 Benchmark Evaluation Script - Registry Mode Only

Architecture:
1. Config-only mode: Load tasks from YAML config file
2. Agent talks to registry to get tools
3. Registry loads tools from containers using stdio

Usage:
    uv run python benchmarks/m3/eval_m3.py --from-config benchmarks/m3/config/m3_registry.yaml

Features:
- Registry-based tool loading (no direct container access)
- Supports both single-turn and multi-turn evaluation
- Evaluates tasks from domain-specific data files
- Checks keywords in responses
- Reports results with filtering by difficulty
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
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Union

import yaml
from loguru import logger

logger.add(sys.stderr, level="INFO")

# Force line-buffering so our summary prints (which use print()) land in the
# console before process exit. Without this, Python block-buffers stdout when
# eval.sh pipes it through `tee`, and the final summary is delayed/lost behind
# loguru's stderr stream.
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:  # noqa: S110 — best-effort line buffering on stdout
    pass

logger.info(f"CUGA_LOGGING_DIR: {cuga_logging_dir}")
logger.info(f"TRACKER_ENABLED: {os.environ.get('DYNACONF_ADVANCED_FEATURES__TRACKER_ENABLED', 'not set')}")
logger.info("✅ eval_m3.py environment loaded; importing CUGA modules next")

# Import cuga modules (these will read env vars, which are now set)
from cuga.backend.activity_tracker.tracker import ActivityTracker
from cuga.backend.cuga_graph.nodes.cuga_lite.providers.combined import CombinedToolProvider
from cuga.backend.cuga_graph.state.agent_state import VariablesManager
from cuga.sdk import CugaAgent

logger.info("✅ CUGA modules imported successfully")

# Import Task 1 specific evaluator (handles uuid-based tool universe switching)
# from benchmarks.m3.eval_m3_task_1_support import evaluate_single_task_1

# Import helpers after cuga modules (helpers import cuga modules too)
from benchmarks.helpers import (
    create_activity_tracker_callback,
    evaluate_multiturn_task_with_langfuse,
    evaluate_task_with_langfuse,
    flush_langfuse,
    save_evaluation_results,
    setup_langfuse,
)
from benchmarks.helpers.sdk_eval_helpers import add_policy_via_agent, clear_all_policies
from benchmarks.m3.m3_data_loader import M3DataLoader, diff_tool_calls


async def _load_m3_policies(agent: CugaAgent, policies_enabled: bool = True) -> None:
    """Load CUGA policies into the per-domain agent.

    Mirrors the bpo eval_bench_sdk.py pattern: clear any pre-existing policies
    from the agent's policy DB, then (if enabled) load each entry in
    benchmarks/m3/policies/policies.json and register it. The .json is
    compiled from .md by scripts/policies_md_to_json.py — driven by eval.sh
    before this code runs.
    """
    await clear_all_policies(agent)
    if not policies_enabled:
        logger.info("Policies disabled (--no-policies)")
        return
    policies_file = os.path.join(os.path.dirname(__file__), "policies", "policies.json")
    if not os.path.exists(policies_file):
        logger.warning(f"Policies file not found: {policies_file} — running without policies")
        return
    from cuga.backend.cuga_graph.policy.models import OutputFormatter, Playbook, ToolGuide

    with open(policies_file) as f:
        policies_data = json.load(f)
    logger.info(f"Loading {len(policies_data)} policy/policies from policies.json...")
    loaded = 0
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
        await add_policy_via_agent(agent, policy)
        loaded += 1
    logger.info(f"✅ Loaded {loaded} policy/policies")


# m3_vakra_score is imported lazily — its top-level evaluator import instantiates
# Groq/OpenAI LLM judges at class-body time, which raises if API_KEY is unset.
# --no-ground-truth runs never need scoring, so let them succeed without judge env.
def _vakra():
    """Lazy import of m3_vakra_score; raises only if you actually call scoring."""
    from benchmarks.m3 import m3_vakra_score as _mod

    return _mod


def vakra_score_results_async(*args, **kwargs):
    return _vakra().score_results_async(*args, **kwargs)


def patch_tracker_scores(*args, **kwargs):
    return _vakra().patch_tracker_scores(*args, **kwargs)


def print_vakra_summary(*args, **kwargs):
    return _vakra().print_vakra_summary(*args, **kwargs)


def _vakra_capability_for_task_id(*args, **kwargs):
    return _vakra().capability_name_for_task_id(*args, **kwargs)


def _stringify_gt_answer(answer: Any) -> str:
    """Stringify a GT answer payload for Vakra's CorrectnessJudge."""
    if answer is None:
        return ""
    if isinstance(answer, str):
        return answer
    try:
        return json.dumps(answer, default=str)
    except (TypeError, ValueError):
        return str(answer)


tracker = ActivityTracker()


class FilteredToolProvider:
    """Wrapper that filters tools from another provider by app name.

    This provides domain isolation without modifying CugaAgent.
    When an agent is created with this provider, it only sees tools
    from the specified app/domain.

    Example:
        # Base provider has tools from all domains (hockey, olympics, address)
        base_provider = CombinedToolProvider()
        await base_provider.initialize()

        # Create filtered provider for olympics domain only
        olympics_provider = FilteredToolProvider(base_provider, "olympics")
        await olympics_provider.initialize()

        # Agent only sees olympics tools
        agent = CugaAgent(
            tool_provider=olympics_provider,
            auto_load_policies=False,
            filesystem_sync=False,
        )
    """

    def __init__(self, base_provider, app_name: str):
        """Initialize filtered provider.

        Args:
            base_provider: Base ToolProviderInterface with all apps/tools
            app_name: Name of app to filter to (e.g., "olympics", "hockey")
        """
        self.base_provider = base_provider
        self.app_name = app_name
        self._filtered_apps = None

    async def initialize(self):
        """Initialize base provider (if not already initialized)."""
        if hasattr(self.base_provider, 'initialized') and not self.base_provider.initialized:
            await self.base_provider.initialize()

    async def get_apps(self):
        """Return only the filtered app."""
        if self._filtered_apps is None:
            all_apps = await self.base_provider.get_apps()
            self._filtered_apps = [app for app in all_apps if app.name == self.app_name]
            logger.debug(
                f"FilteredToolProvider: Filtered to app '{self.app_name}' ({len(self._filtered_apps)} apps)"
            )
        return self._filtered_apps

    async def get_tools(self, app_name: str):
        """Only return tools if app_name matches our filter."""
        if app_name != self.app_name:
            logger.debug(
                f"FilteredToolProvider: Rejecting tools for '{app_name}' (filter is '{self.app_name}')"
            )
            return []
        tools = await self.base_provider.get_tools(app_name)
        logger.debug(f"FilteredToolProvider: Returning {len(tools)} tools for '{app_name}'")
        return tools

    async def get_all_tools(self):
        """Return only tools from the filtered app."""
        tools = await self.base_provider.get_tools(self.app_name)
        logger.info(
            f"FilteredToolProvider: get_all_tools() returning {len(tools)} tools for '{self.app_name}'"
        )
        return tools


var_manager = VariablesManager()


def _emit_cleanly(func, *args, **kwargs) -> None:
    """Run `func(*args, **kwargs)` with stdout pointed at `sys.__stdout__`.

    `sys.__stdout__` is Python's preserved reference to the *original* stdout
    at interpreter start, which is not affected when some code later reassigns
    `sys.stdout` (and fails to restore it). Under 20-way asyncio.gather the
    agent stack occasionally does exactly that, which is why `print()` inside
    our summary code silently vanished. Writing through `sys.__stdout__` and
    flushing explicitly gives the same clean bpo-style output and bypasses
    the hijack.
    """
    import contextlib

    target = sys.__stdout__ or sys.stdout
    try:
        with contextlib.redirect_stdout(target):
            func(*args, **kwargs)
    except Exception as e:
        import traceback

        logger.error(f"{func.__name__} crashed: {e}")
        logger.error(traceback.format_exc())
    finally:
        try:
            target.flush()
        except Exception:  # noqa: S110 — flush is best-effort cleanup
            pass


M3_SUMMARY_FILE = "/tmp/m3_summary.txt"  # noqa: S108  # nosec B108 — fixed dev-tool output path; not security-sensitive


def print_m3_data_summary(results: List[Dict[str, Any]]) -> None:
    """Unified bpo-style summary for --m3-data mode.

    Pass/fail is tool-call-count match against gold_sequence. Keyword matching
    is ignored entirely. Reports expected vs actual tool calls per sample with
    the full list of expected and observed calls, plus per-position diffs.
    """
    relevant = [r for r in results if "tool_call_diffs" in r]
    total = len(relevant)
    if total == 0:
        print("\n(no --m3-data results to summarize)")
        return

    passed = sum(1 for r in relevant if r.get("tool_call_count_match"))
    failed = total - passed
    errored = sum(1 for r in relevant if r.get("error"))
    total_expected = sum(r.get("expected_tool_call_count", 0) for r in relevant)
    total_actual = sum(r.get("actual_tool_call_count", 0) for r in relevant)

    print()
    print("=" * 80)
    print("EVALUATION COMPLETE (--m3-data, tool-call count scoring)")
    print("=" * 80)
    print(f"Total samples:            {total}")
    print(f"Tool-call count match:    {passed}/{total} ({passed / total * 100:.1f}%)")
    print(f"Failed (count mismatch):  {failed}")
    print(f"Errored (agent crash):    {errored}")
    print(f"Total expected calls:     {total_expected}")
    print(f"Total actual calls:       {total_actual}")

    # Roll-up by capability (task_id) and domain
    from collections import defaultdict

    by_cap: dict = defaultdict(lambda: {"pass": 0, "total": 0})
    by_domain: dict = defaultdict(lambda: {"pass": 0, "total": 0})
    for r in relevant:
        cap = f"task_{r.get('m3_task_id', '?')}"
        dom = r.get("domain", "?")
        by_cap[cap]["total"] += 1
        by_domain[dom]["total"] += 1
        if r.get("tool_call_count_match"):
            by_cap[cap]["pass"] += 1
            by_domain[dom]["pass"] += 1

    print()
    print("-" * 80)
    print("Results by Capability:")
    print("-" * 80)
    for cap in sorted(by_cap):
        s = by_cap[cap]
        print(f"  {cap:12s}  {s['pass']}/{s['total']} passed ({s['pass'] / s['total'] * 100:.1f}%)")

    print()
    print("-" * 80)
    print("Results by Domain:")
    print("-" * 80)
    for dom in sorted(by_domain):
        s = by_domain[dom]
        print(f"  {dom:35s}  {s['pass']}/{s['total']} passed ({s['pass'] / s['total'] * 100:.1f}%)")

    def _sample_id(r):
        return r.get("sample_id") or r.get("task_name") or r.get("uuid", "?")

    def _fmt_call(c):
        if c is None:
            return "(none)"
        return f"{c.get('name', '?')} args={c.get('arguments', {})}"

    # Failed details — every sample that didn't count-match
    failed_results = [r for r in relevant if not r.get("tool_call_count_match")]
    if failed_results:
        print()
        print("-" * 80)
        print("Failed Samples:")
        print("-" * 80)
        for r in failed_results:
            sid = _sample_id(r)
            dom = r.get("domain", "?")
            exp = r.get("expected_tool_call_count", 0)
            act = r.get("actual_tool_call_count", 0)
            print(f"\n❌ {dom}/{sid} — expected={exp}  actual={act}")
            print(f"   Intent: {r.get('intent', '')}")
            if r.get("error"):
                print(f"   Error: {r['error']}")
            for diff in r.get("tool_call_diffs", []):
                tid = diff.get("turn_id", 0)
                exp_calls = diff.get("expected") or []
                act_calls = diff.get("actual") or []
                print(f"   turn {tid}:  expected {len(exp_calls)} call(s), actual {len(act_calls)} call(s)")
                MAX_CALLS = 10
                if exp_calls:
                    print("     expected tool calls:")
                    for c in exp_calls[:MAX_CALLS]:
                        print(f"       - {_fmt_call(c)}")
                    if len(exp_calls) > MAX_CALLS:
                        print(f"       ... and {len(exp_calls) - MAX_CALLS} more expected")
                if act_calls:
                    print("     actual tool calls:")
                    for c in act_calls[:MAX_CALLS]:
                        print(f"       - {_fmt_call(c)}")
                    if len(act_calls) > MAX_CALLS:
                        print(f"       ... and {len(act_calls) - MAX_CALLS} more actual")
                # Per-position diff status — cap to a sensible number of
                # mismatches so a runaway agent (e.g. 300 extra calls) doesn't
                # drown the rest of the summary.
                MAX_POS = 10
                mismatches = [e for e in diff.get("per_position", []) if e.get("status") != "match"]
                for entry in mismatches[:MAX_POS]:
                    pos = entry.get("position")
                    print(f"     pos {pos} [{entry.get('status')}]")
                if len(mismatches) > MAX_POS:
                    print(f"     ... and {len(mismatches) - MAX_POS} more mismatches")

    # Short roll-up of every sample
    print()
    print("-" * 80)
    print("All Samples:")
    print("-" * 80)
    for r in relevant:
        sid = _sample_id(r)
        dom = r.get("domain", "?")
        exp = r.get("expected_tool_call_count", 0)
        act = r.get("actual_tool_call_count", 0)
        mark = "✅" if r.get("tool_call_count_match") else "❌"
        print(f"{mark} {dom}/{sid} — expected={exp}  actual={act}")

    print()
    print("=" * 80)


def _render_m3_data_summary(results: List[Dict[str, Any]]) -> str:
    """Render the summary into a string (same as print_m3_data_summary prints)."""
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_m3_data_summary(results)
    return buf.getvalue()


# Back-compat alias — older code paths call print_tool_call_report(...)
print_tool_call_report = print_m3_data_summary


def _count_actual_tool_calls(result: Dict[str, Any]) -> int:
    """Count tool calls observed across all turns of a multi-turn result."""
    n = 0
    for turn in result.get("all_responses") or []:
        n += len(turn.get("tool_calls") or [])
    if not result.get("all_responses") and result.get("tool_calls"):
        n += len(result.get("tool_calls") or [])
    return n


def print_no_gt_summary(results: List[Dict[str, Any]]) -> None:
    """Summary for --no-ground-truth runs: tool-call count per sample only.

    No expected/actual comparison, no pass/fail — just how many tool calls the
    agent emitted for each sample, with totals rolled up by capability/domain.
    """
    if not results:
        print("\n(no --no-ground-truth results to summarize)")
        return

    total = len(results)
    errored = sum(1 for r in results if r.get("error"))
    total_calls = sum(_count_actual_tool_calls(r) for r in results)

    print()
    print("=" * 80)
    print("EVALUATION COMPLETE (--no-ground-truth, tool-call counts only)")
    print("=" * 80)
    print(f"Total samples:           {total}")
    print(f"Errored (agent crash):   {errored}")
    print(f"Total tool calls:        {total_calls}")

    from collections import defaultdict

    by_cap: dict = defaultdict(lambda: {"samples": 0, "calls": 0})
    by_domain: dict = defaultdict(lambda: {"samples": 0, "calls": 0})
    for r in results:
        cap = f"task_{r.get('m3_task_id', '?')}"
        dom = r.get("domain", "?")
        n = _count_actual_tool_calls(r)
        by_cap[cap]["samples"] += 1
        by_cap[cap]["calls"] += n
        by_domain[dom]["samples"] += 1
        by_domain[dom]["calls"] += n

    print()
    print("-" * 80)
    print("Tool calls by Capability:")
    print("-" * 80)
    for cap in sorted(by_cap):
        s = by_cap[cap]
        avg = s["calls"] / s["samples"] if s["samples"] else 0.0
        print(f"  {cap:12s}  samples={s['samples']:>4}  calls={s['calls']:>5}  avg={avg:.2f}")

    print()
    print("-" * 80)
    print("Tool calls by Domain:")
    print("-" * 80)
    for dom in sorted(by_domain):
        s = by_domain[dom]
        avg = s["calls"] / s["samples"] if s["samples"] else 0.0
        print(f"  {dom:35s}  samples={s['samples']:>4}  calls={s['calls']:>5}  avg={avg:.2f}")

    def _sample_id(r):
        return r.get("sample_id") or r.get("task_name") or r.get("uuid", "?")

    print()
    print("-" * 80)
    print("All Samples:")
    print("-" * 80)
    for r in results:
        sid = _sample_id(r)
        dom = r.get("domain", "?")
        n = _count_actual_tool_calls(r)
        mark = "❌" if r.get("error") else "•"
        print(f"{mark} {dom}/{sid} — tool_calls={n}")

    print()
    print("=" * 80)


def _render_no_gt_summary(results: List[Dict[str, Any]]) -> str:
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_no_gt_summary(results)
    return buf.getvalue()


def write_predictions_no_gt(
    results: List[Dict[str, Any]],
    output_dir: Path,
    domain: str,
) -> Optional[Path]:
    """Write a vakra-shaped prediction file for one domain when there's no GT.

    Output path: ``<output_dir>/_vakra/prediction/<domain>.json``. Same shape
    as the prediction half of `m3_vakra_score._prepare_inputs` so downstream
    tools that consume vakra prediction files work unchanged. Skips the
    groundtruth/ side and skips scoring.
    """
    pred_dir = Path(output_dir) / "_vakra" / "prediction"
    pred_dir.mkdir(parents=True, exist_ok=True)

    def _norm_tc(tc: Any) -> Dict[str, Any]:
        if not isinstance(tc, dict):
            return {"name": getattr(tc, "name", ""), "arguments": {}}
        return {
            "name": tc.get("name", ""),
            "arguments": tc.get("arguments", tc.get("args", {})),
        }

    def _norm_resp(tc: Any) -> str:
        if not isinstance(tc, dict):
            return ""
        payload = tc.get("result") if "result" in tc else tc.get("error", "")
        if payload is None:
            return ""
        if isinstance(payload, str):
            return payload
        try:
            return json.dumps(payload, default=str)
        except (TypeError, ValueError):
            return str(payload)

    pred_list: List[Dict[str, Any]] = []
    for r in results:
        uuid = (
            r.get("uuid")
            or (r.get("task_metadata") or {}).get("uuid")
            or r.get("sample_id")
            or r.get("task_name")
        )
        if not uuid:
            continue

        # Multi-turn: turns are in all_responses; fall back to single-turn fields.
        all_responses = r.get("all_responses") or []
        output_turns: List[Dict[str, Any]] = []
        if all_responses:
            for t in all_responses:
                tcs = t.get("tool_calls") or []
                output_turns.append(
                    {
                        "turn_id": (t.get("turn") or 1) - 1,
                        "query": t.get("query", ""),
                        "answer": t.get("response", ""),
                        "sequence": {
                            "tool_call": [_norm_tc(tc) for tc in tcs],
                            "tool_response": [_norm_resp(tc) for tc in tcs],
                        },
                    }
                )
        else:
            tcs = r.get("tool_calls") or []
            output_turns.append(
                {
                    "turn_id": 0,
                    "query": r.get("intent") or r.get("query") or "",
                    "answer": r.get("answer") or r.get("response") or "",
                    "sequence": {
                        "tool_call": [_norm_tc(tc) for tc in tcs],
                        "tool_response": [_norm_resp(tc) for tc in tcs],
                    },
                }
            )

        pred_list.append(
            {
                "uuid": uuid,
                "domain": r.get("domain") or domain,
                "output": output_turns,
            }
        )

    if not pred_list:
        logger.warning(f"[{domain}] no predictions to write (empty result set)")
        return None

    pred_path = pred_dir / f"{domain}.json"
    pred_path.write_text(json.dumps(pred_list, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"[{domain}] wrote {len(pred_list)} prediction(s) → {pred_path}")
    return pred_path


def load_registry_config(config_path: str) -> Dict[str, Any]:
    """Load and parse the registry YAML config."""
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    return config


# Removed load_mcp_tools_directly function - now using registry mode only
# Tools are loaded via CombinedToolProvider from the registry


class M3Evaluator:
    """Evaluator for M3 tasks (single-turn and multi-turn)."""

    def __init__(
        self,
        difficulty_filter: Optional[str] = None,
        task_id: Optional[Union[str, List[str]]] = None,
        multiturn: bool = False,
        max_samples: Optional[int] = None,
        m3_data_mode: bool = False,
        m3_task_id: Optional[int] = None,
        domain: Optional[str] = None,
    ):
        """
        Initialize the evaluator.

        Args:
            difficulty_filter: Filter by difficulty ("easy", "medium", "hard", or None for all)
            task_id: Filter by specific task ID(s) (if provided, only these tasks will be evaluated)
            multiturn: If True, evaluate multi-turn tasks; if False, evaluate single-turn tasks
            max_samples: Maximum number of samples to evaluate (None = all)
            m3_data_mode: If True, score by tool-call count vs gold_sequence and
                ignore keyword matching
            m3_task_id: Registry task_id (e.g. 2 or 3), used to strip registry prefixes
                from actual tool-call names when computing diffs
            domain: Domain name (e.g. "hockey"), used alongside m3_task_id for prefix stripping
        """
        self.difficulty_filter = difficulty_filter
        self.task_ids = [task_id] if isinstance(task_id, str) else task_id
        self.task_id = self.task_ids[0] if self.task_ids and len(self.task_ids) == 1 else None
        self.multiturn = multiturn
        self.max_samples = max_samples
        self.m3_data_mode = m3_data_mode
        self.m3_task_id = m3_task_id
        self.domain = domain
        self.agent: Optional[CugaAgent] = None
        self.langfuse_handler = None
        self.results: List[Dict[str, Any]] = []

    # Removed setup() method - now using registry mode only
    # Agent is created in evaluate_single_task() using CombinedToolProvider

    async def evaluate_task(self, task: Dict[str, Any], task_index: int) -> Dict[str, Any]:
        """Evaluate a single task.

        Args:
            task: Task dictionary from domain data file
            task_index: Index of the task (for unique thread_id generation)

        Returns:
            Evaluation result dictionary
        """
        task_name = task.get("name", "unknown")
        intent = task.get("intent", "")

        tracker.reset(intent=intent, task_id=task_name)
        var_manager.reset()

        tracker_callback = create_activity_tracker_callback(tracker, var_manager)

        return await evaluate_task_with_langfuse(
            agent=self.agent,
            task=task,
            task_index=task_index,
            langfuse_handler=self.langfuse_handler,
            user_context=None,
            tracker_callback=tracker_callback,
            track_tool_calls=True,
        )

    async def evaluate_multiturn_task(self, sample: Dict[str, Any], sample_index: int) -> Dict[str, Any]:
        """Evaluate a single multi-turn task.

        Args:
            sample: Sample dictionary from multiturn data file
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

        # Preserve UUID from input sample if present (M3 benchmark format)
        if "uuid" in sample:
            task_metadata["uuid"] = sample["uuid"]

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
        if "uuid" in sample:
            result["uuid"] = sample["uuid"]
        result["domain"] = domain

        # Surface the GT bits Vakra needs so _to_vakra_pair can build a real
        # ground-truth dialogue (single-turn samples; multi-turn would need
        # per-turn arrays threaded through). Names here mirror the test_case
        # shape used by the react path so _to_vakra_pair handles both uniformly.
        gold_seq = (expected_output or {}).get("gold_sequence") or []
        answers = (expected_output or {}).get("answer_per_turn") or []
        tool_resps = (expected_output or {}).get("tool_response_per_turn") or []
        result["expected_output"] = {
            "response": _stringify_gt_answer(answers[0]) if answers else "",
            "tool_calls": gold_seq[0] if gold_seq else [],
            "tool_responses": tool_resps[0] if tool_resps else [],
        }

        gold_per_turn = (expected_output or {}).get("gold_sequence")
        if self.m3_data_mode and gold_per_turn is not None:
            self._annotate_tool_call_diffs(result, gold_per_turn)

        return result

    def _annotate_tool_call_diffs(
        self,
        result: Dict[str, Any],
        gold_per_turn: List[List[Dict[str, Any]]],
    ) -> None:
        """Attach tool-call count/diff metrics and reset pass/fail based on counts.

        Modifies `result` in place. For each turn we capture expected vs actual
        count, the normalized call lists, and per-position diffs. Pass/fail for
        --m3-data mode is defined as: totals match AND every turn's count matches.
        """
        task_id = self.m3_task_id if self.m3_task_id is not None else 0
        domain = self.domain or result.get("domain", "")

        all_responses: List[Dict[str, Any]] = result.get("all_responses") or []
        actual_per_turn: List[List[Dict[str, Any]]] = []
        for turn_entry in all_responses:
            calls = turn_entry.get("tool_calls") or []
            normalized: List[Dict[str, Any]] = []
            for c in calls:
                if isinstance(c, dict):
                    normalized.append(c)
                elif hasattr(c, "model_dump"):
                    normalized.append(c.model_dump())
                elif hasattr(c, "name"):
                    normalized.append(
                        {
                            "name": c.name,
                            "arguments": getattr(c, "arguments", getattr(c, "args", {})),
                        }
                    )
            actual_per_turn.append(normalized)

        # Pad so expected/actual align turn-by-turn
        num_turns = max(len(gold_per_turn), len(actual_per_turn))
        while len(actual_per_turn) < num_turns:
            actual_per_turn.append([])
        while len(gold_per_turn) < num_turns:
            gold_per_turn.append([])

        per_turn_diffs: List[Dict[str, Any]] = []
        expected_total = 0
        actual_total = 0
        all_counts_match = True
        for i in range(num_turns):
            diff = diff_tool_calls(gold_per_turn[i], actual_per_turn[i], task_id=task_id, domain=domain)
            diff["turn_id"] = i
            per_turn_diffs.append(diff)
            expected_total += diff["expected_count"]
            actual_total += diff["actual_count"]
            if not diff["count_match"]:
                all_counts_match = False

        result["expected_tool_call_count"] = expected_total
        result["actual_tool_call_count"] = actual_total
        result["tool_call_count_match"] = all_counts_match
        result["tool_call_diffs"] = per_turn_diffs
        # success/match_rate are set later by vakra_score_results (LLM-judge based).

    async def evaluate_all(
        self,
        data_path: str = None,
        preloaded_data: Optional[List[Dict[str, Any]]] = None,
    ):
        """
        Evaluate all tasks from domain data file (single-turn or multi-turn).

        Args:
            data_path: Path to domain data file (defaults to data/<domain>.json or data/<domain>_multiturn.json)
            preloaded_data: If provided, use this list of samples instead of loading from disk.
                Used by --m3-data mode which merges input+output from a zip or directory.
        """
        if preloaded_data is not None:
            data = preloaded_data
            # Samples from --m3-data are in multi-turn shape
            self.multiturn = True
        else:
            if data_path is None:
                # Default to domain-based data file
                domain = os.getenv("M3_DOMAIN", "hockey")
                suffix = "_multiturn" if self.multiturn else ""
                data_path = os.path.join(os.path.dirname(__file__), "data", f"{domain}{suffix}.json")

                # If multiturn file doesn't exist, try without suffix (auto-detect format)
                if self.multiturn and not os.path.exists(data_path):
                    fallback_path = os.path.join(os.path.dirname(__file__), "data", f"{domain}.json")
                    if os.path.exists(fallback_path):
                        logger.info(
                            f"Multiturn file not found, using {fallback_path} (will auto-detect format)"
                        )
                        data_path = fallback_path

            # Load test data
            with open(data_path, "r") as f:
                data = json.load(f)

        # Auto-detect format if not explicitly set
        if self.multiturn is None and isinstance(data, list) and len(data) > 0:
            # Check if first item has multiturn structure (uuid/sample_id, dialogue, turns)
            first_item = data[0]
            has_uuid = "uuid" in first_item or "sample_id" in first_item
            has_dialogue = "dialogue" in first_item
            has_test_cases = "test_cases" in first_item

            if has_uuid or has_dialogue:
                self.multiturn = True
                logger.info("Auto-detected multiturn format (found uuid/sample_id or dialogue)")
            elif has_test_cases:
                self.multiturn = False
                logger.info("Auto-detected single-turn format (found test_cases)")
            else:
                # Default to single-turn if unclear
                self.multiturn = False
                logger.warning("Could not auto-detect format, defaulting to single-turn")

        # Handle multi-turn evaluation
        if self.multiturn:
            # Multi-turn format: list of samples with sample_id/uuid, dialogue, etc.
            samples = data

            # Filter by task_ids (sample_id or uuid) if specified. The plural
            # form `self.task_ids` is what gets populated for both 1 and N
            # UUIDs; `self.task_id` is only set when exactly one UUID was
            # passed, so use the plural to handle both cases.
            if self.task_ids:
                wanted = {tid.lower() for tid in self.task_ids}
                samples = [s for s in samples if s.get("sample_id", s.get("uuid", "")).lower() in wanted]
                if not samples:
                    logger.error(f"Sample(s) {self.task_ids} not found in test data")
                    return
                logger.info(f"Filtered to {len(samples)} sample(s): {self.task_ids}")
            else:
                logger.info(f"Evaluating all {len(samples)} samples")

            # Apply max_samples limit if specified
            if self.max_samples and len(samples) > self.max_samples:
                samples = samples[: self.max_samples]
                logger.info(f"Limited to {self.max_samples} samples")

            # Start experiment tracking
            experiment_name = os.getenv("M3_MULTITURN_EXPERIMENT_NAME", "m3_multiturn_evaluation")
            sample_ids = [s.get("sample_id", s.get("uuid", f"sample_{i}")) for i, s in enumerate(samples, 1)]
            tracker.start_experiment(
                task_ids=sample_ids,
                experiment_name=experiment_name,
                description="M3 multi-turn benchmark evaluation",
            )

            # Evaluate each sample
            self.results = []
            for i, sample in enumerate(samples, 1):
                logger.info(f"\n[{i}/{len(samples)}] Processing sample...")
                result = await self.evaluate_multiturn_task(sample, sample_index=i)
                self.results.append(result)

                # Small delay to avoid rate limiting between samples
                if i < len(samples):
                    await asyncio.sleep(0.5)

        # Handle single-turn evaluation
        else:
            # Single-turn format: list of apps with test_cases
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
                    tc
                    for tc in test_cases
                    if tc.get("difficulty", "").lower() == self.difficulty_filter.lower()
                ]
                logger.info(f"Filtered to {len(test_cases)} {self.difficulty_filter} tasks")
            else:
                logger.info(f"Evaluating all {len(test_cases)} tasks")

            # Apply max_samples limit if specified
            if self.max_samples and len(test_cases) > self.max_samples:
                test_cases = test_cases[: self.max_samples]
                logger.info(f"Limited to {self.max_samples} tasks")

            # Start experiment tracking
            experiment_name = os.getenv("M3_EXPERIMENT_NAME", "m3_evaluation")
            task_ids = [tc.get("name", f"task_{i}") for i, tc in enumerate(test_cases, 1)]
            tracker.start_experiment(
                task_ids=task_ids,
                experiment_name=experiment_name,
                description="M3 single-turn benchmark evaluation",
            )

            # Evaluate each task
            self.results = []
            for i, task in enumerate(test_cases, 1):
                logger.info(f"\n[{i}/{len(test_cases)}] Processing task...")
                result = await self.evaluate_task(task, task_index=i)
                self.results.append(result)

                # Small delay to avoid rate limiting between tasks
                if i < len(test_cases):
                    await asyncio.sleep(0.5)

        # Vakra scoring for the cuga --m3-data path is invoked from
        # `evaluate_single_task` (above), once each result has been tagged with
        # m3_task_id/domain so capability resolution works. Scoring inside this
        # method is a no-op for that path.
        flush_langfuse(self.langfuse_handler)

    def print_summary(self):
        """Print evaluation summary (Vakra-only; legacy keyword/count reports removed)."""
        if any("vakra" in r for r in self.results):
            print_vakra_summary(self.results)
        else:
            logger.warning("No Vakra scores produced — check API_KEY and the Vakra warnings above.")

    def save_results(self, output_dir: Optional[str] = None):
        """Save evaluation results to JSON files."""
        if output_dir is None:
            output_dir = Path(__file__).parent / "results"

        # Save standard results
        results_path = save_evaluation_results(self.results, output_dir, prefix="m3")

        # Save ground truth format file
        ground_truth_path = self._save_ground_truth_format(output_dir)

        return results_path, ground_truth_path

    def _save_ground_truth_format(self, output_dir: Path) -> Path:
        """Save results in ground truth format for M3 benchmark.

        Output structure:
            <output_dir>/<experiment_timestamp>/task_<task_id>/<domain>.json

        Each domain file contains a list of ground truth entries for that domain.

        Args:
            output_dir: Base output directory path

        Returns:
            Path to the experiment directory that was created
        """
        import hashlib
        from datetime import datetime

        output_dir = Path(output_dir)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Root experiment folder: results/<timestamp>/
        experiment_dir = output_dir / timestamp
        experiment_dir.mkdir(parents=True, exist_ok=True)

        # Group results by (task_id, domain)
        # results have: result["m3_task_id"], result["domain"]
        from collections import defaultdict

        grouped: dict = defaultdict(list)
        for result in self.results:
            task_id = result.get("m3_task_id", "unknown")
            domain = result.get("domain", "unknown")
            grouped[(task_id, domain)].append(result)

        saved_files = []

        for (task_id, domain), results in grouped.items():
            # Create task subfolder: task_<task_id>/
            task_dir = experiment_dir / f"task_{task_id}"
            task_dir.mkdir(parents=True, exist_ok=True)

            domain_entries = []

            for result in results:
                task_name = result.get("task_name") or result.get("sample_id", "unknown")

                # Use UUID from result if present (from input data), otherwise generate deterministic one
                if "uuid" in result:
                    formatted_uuid = result["uuid"]
                else:
                    # Fallback: Deterministic UUID based on task_name + domain
                    uuid_seed = f"{task_name}_{domain}"
                    uuid_hash = hashlib.md5(uuid_seed.encode(), usedforsecurity=False).hexdigest()
                    formatted_uuid = f"{uuid_hash[:12]}-{uuid_hash[12:24]}"

                all_responses = result.get("all_responses", [])

                # Shared helpers ------------------------------------------------
                # Build the registry prefix to strip from tool names:
                # Registry prefixes tools as "{app_name}_{tool_name}" where
                # app_name = "{domain}" (no task_<n>_ prefix).
                registry_prefix = f"{domain}_"

                def _strip_prefix(name: str) -> str:
                    """Strip the registry app prefix from a tool name."""
                    if name.startswith(registry_prefix):
                        return name[len(registry_prefix) :]
                    return name

                def _extract_tool_call(tc):
                    """Return (call_dict, response_value) from a raw tool call."""
                    if isinstance(tc, dict):
                        call = {
                            "name": _strip_prefix(tc.get("name", "unknown")),
                            "arguments": tc.get("arguments", {}),
                        }
                        response = tc.get("result", [])
                    else:
                        call = {
                            "name": _strip_prefix(getattr(tc, "name", "unknown")),
                            "arguments": getattr(tc, "arguments", {}),
                        }
                        response = getattr(tc, "result", [])
                    return call, response

                def _build_sequence(raw_tool_calls):
                    """Build sequence dict from a flat list of raw tool calls.

                    Returns {"tool_call": [call, ...]} or None when there are no calls.
                    """
                    if not raw_tool_calls:
                        return None
                    calls = []
                    for tc in raw_tool_calls:
                        c, _ = _extract_tool_call(tc)
                        calls.append(c)
                    return {"tool_call": calls}

                # Common entry-level fields
                # Use "success" when the agent produced tool calls (non-empty gold_sequence),
                # regardless of keyword matching (which is not used in M3 ground truth collection).
                entry_error = result.get("error") or ""
                entry_duration = result.get("duration_s", 0.0)

                # Determine success: agent ran tool calls = success; explicit error = error
                _has_tool_calls = bool(
                    result.get("all_responses")
                    and any(r.get("tool_calls") for r in result.get("all_responses", []))
                    or result.get("tool_calls")
                )

                # Check if tool calls contain errors (HTTP 500, etc.)
                def has_tool_call_errors(tool_calls):
                    """Check if any tool call results contain errors."""
                    if not tool_calls:
                        return False
                    for tc in tool_calls:
                        # Check if tool call arguments contain error
                        args = tc.get("arguments", {})
                        if isinstance(args, dict):
                            # Check for error in data field
                            data = args.get("data", {})
                            if isinstance(data, dict) and "error" in data:
                                error_msg = data["error"]
                                # Check for HTTP errors or Internal Server Error
                                if (
                                    "HTTP Error" in error_msg
                                    or "500" in error_msg
                                    or "Internal Server Error" in error_msg
                                ):
                                    return True
                    return False

                # Check all tool calls for errors
                tool_call_has_errors = False
                if result.get("all_responses"):
                    # Multi-turn: check all turns
                    for turn_data in result.get("all_responses", []):
                        if has_tool_call_errors(turn_data.get("tool_calls", [])):
                            tool_call_has_errors = True
                            break
                elif result.get("tool_calls"):
                    # Single turn
                    tool_call_has_errors = has_tool_call_errors(result.get("tool_calls", []))

                # Success only if: has tool calls AND no explicit error AND no tool call errors
                is_success = _has_tool_calls and not entry_error and not tool_call_has_errors
                entry_status = "success" if is_success else "error"

                # Update error message if tool calls had errors
                if tool_call_has_errors and not entry_error:
                    entry_error = "Tool call returned error (HTTP 500 or Internal Server Error)"

                if all_responses:
                    # Multi-turn format
                    output_turns = []
                    for turn_data in all_responses:
                        turn_num = turn_data.get("turn", 0)
                        query = turn_data.get("query", "")
                        answer = turn_data.get("response", "")
                        turn_tool_calls = turn_data.get("tool_calls", [])

                        turn_entry = {
                            "turn_id": turn_num - 1,
                            "query": query,
                            "answer": answer,
                        }
                        seq = _build_sequence(turn_tool_calls)
                        if seq is not None:
                            turn_entry["sequence"] = seq
                        output_turns.append(turn_entry)

                    entry = {
                        "uuid": formatted_uuid,
                        "domain": domain,
                        "status": entry_status,
                        "error": entry_error,
                        "duration_s": entry_duration,
                        "output": output_turns,
                    }
                else:
                    # Single-turn format
                    intent = result.get("intent", "")
                    response = result.get("response", "")
                    tool_calls_data = result.get("tool_calls", [])

                    # Normalise tuple format [(_, tc), ...] → [tc, ...]
                    if (
                        isinstance(tool_calls_data, list)
                        and tool_calls_data
                        and isinstance(tool_calls_data[0], (tuple, list))
                        and len(tool_calls_data[0]) == 2
                    ):
                        tool_calls_data = [tc for _, tc in tool_calls_data]

                    turn_entry = {
                        "turn_id": 0,
                        "query": intent,
                        "answer": response,
                    }
                    seq = _build_sequence(tool_calls_data)
                    if seq is not None:
                        turn_entry["sequence"] = seq

                    entry = {
                        "uuid": formatted_uuid,
                        "domain": domain,
                        "status": entry_status,
                        "error": entry_error,
                        "duration_s": entry_duration,
                        "output": [turn_entry],
                    }

                domain_entries.append(entry)

            # Write one file per domain: task_<task_id>/<domain>.json
            domain_file = task_dir / f"{domain}.json"
            with open(domain_file, "w") as f:
                json.dump(domain_entries, f, indent=4)
            saved_files.append(domain_file)
            logger.info(f"  📄 {domain_file} ({len(domain_entries)} entries)")

        logger.info(f"📁 Ground truth saved to: {experiment_dir}  ({len(saved_files)} domain files)")
        return experiment_dir


async def evaluate_single_task(
    service_name: str,
    task_id: int,
    container: str,
    domains: List,
    task_multiturn: bool,
    args,
    container_runtime: str,
    m3_data_loader: Optional[M3DataLoader] = None,
) -> List[Dict[str, Any]]:
    """Evaluate a single task (all its domains sequentially).

    This function can run in parallel with other tasks since each
    task uses a separate container (no resource conflicts).

    Args:
        service_name: Name of the service/task
        task_id: M3 task ID (1, 2, or 5)
        container: Container name
        domains: List of domains to evaluate
        task_multiturn: Task-level multiturn setting
        args: Command-line arguments
        container_runtime: Container runtime (docker/podman)

    Returns:
        List of evaluation results for all domains in this task
    """
    # In --no-ground-truth mode, the YAML config's hard-coded domain list is
    # almost certainly stale (e.g. small_train names) for an unlabeled test
    # set. Replace it with whatever the loader actually has for this task_id
    # so we run against the test domains the user supplied via --m3-data.
    no_gt_mode = bool(m3_data_loader and getattr(m3_data_loader, "allow_missing_output", False))
    if no_gt_mode and m3_data_loader is not None:
        loader_domains = m3_data_loader.available_domains(task_id)
        if loader_domains:
            logger.info(
                f"[{service_name}] --no-ground-truth: overriding YAML domains "
                f"with {len(loader_domains)} domain(s) from data source: {loader_domains}"
            )
            domains = loader_domains

    logger.info(f"\n{'=' * 80}")
    logger.info(f"🚀 Processing {service_name} (Task ID: {task_id})")
    logger.info(f"Container: {container}")
    logger.info(
        f"Domains: {', '.join(str(d) if isinstance(d, str) else d.get('name', 'unknown') for d in domains)}"
    )
    logger.info(f"Multiturn: {task_multiturn}")
    logger.info(f"{'=' * 80}\n")

    task_results = []

    # OPTIMIZATION: Create tool provider ONCE for this task and reuse across all domains
    # This avoids repeated API calls to registry and enables tool caching
    logger.info(f"🔧 Initializing shared tool provider for task {service_name}")
    tool_provider = CombinedToolProvider()
    await tool_provider.initialize()
    logger.info(f"✅ Tool provider initialized with {len(tool_provider.apps)} apps")

    # DEBUG: Check what tools are available per app
    logger.info("📋 [DATA LEAKAGE CHECK] Apps visible to base tool provider:")
    if tool_provider.apps:
        app_names = [app.name for app in tool_provider.apps]
        logger.info(f"  📦 Total apps in provider: {len(app_names)}")
        logger.info(f"  📦 App names: {app_names}")
        logger.warning(f"  ⚠️  If you see apps other than '{service_name}', there's data leakage!")

        for app in tool_provider.apps:
            try:
                tools = await tool_provider.get_tools(app.name)
                logger.info(f"  📦 App '{app.name}': {len(tools)} tools available")
                if tools:
                    tool_names = [t.name for t in tools]  # Show first 5
                    logger.info(f"     All tools: {tool_names}")
                else:
                    logger.warning(f"     ⚠️  No tools found for app '{app.name}'!")
            except Exception as e:
                logger.error(f"     ❌ Error getting tools for '{app.name}': {e}")
    else:
        logger.error("❌ No apps found in tool provider! Registry might not be working.")

    # Apply optional --domain filter before iterating
    domain_filter = getattr(args, "domain", None)
    if domain_filter:
        wanted = {d.lower() for d in domain_filter}

        def _dom_name(dc):
            return dc.lower() if isinstance(dc, str) else str(dc.get("name", "")).lower()

        filtered = [dc for dc in domains if _dom_name(dc) in wanted]
        if not filtered:
            logger.warning(
                f"[{service_name}] --domain filter {domain_filter} matched no domains in this task; skipping."
            )
            return []
        logger.info(
            f"[{service_name}] --domain filter: {len(filtered)}/{len(domains)} domain(s) "
            f"after filtering to {sorted(wanted)}"
        )
        domains = filtered

    # Process each domain for this task SEQUENTIALLY
    # (Only one connection to this task's container at a time)
    for domain_config in domains:
        # Handle both string and dict domain formats
        if isinstance(domain_config, str):
            domain = domain_config
            domain_multiturn = task_multiturn  # Use task-level setting
        else:
            domain = domain_config.get("name", "unknown")
            # Domain-level multiturn overrides task-level if specified
            domain_multiturn = domain_config.get("multiturn", task_multiturn)

        logger.info(f"\n--- [{service_name}] Evaluating domain: {domain} (multiturn={domain_multiturn}) ---")

        preloaded_data: Optional[List[Dict[str, Any]]] = None
        data_path: Optional[str] = None

        if m3_data_loader is not None:
            # --m3-data mode: load samples from the provided zip/directory.
            try:
                preloaded_data = m3_data_loader.load_domain(task_id, domain)
            except FileNotFoundError as e:
                logger.warning(f"Skipping domain '{domain}' (--m3-data): {e}")
                continue
            domain_multiturn = True
            logger.info(f"📦 --m3-data: loaded {len(preloaded_data)} samples for task_{task_id}/{domain}")
        else:
            # Determine data file path
            # Use M3_DATA_DIR environment variable if set, otherwise default to benchmarks/m3/data
            data_dir = os.getenv("M3_DATA_DIR")
            if data_dir is None:
                data_dir = os.path.join(os.path.dirname(__file__), "data")
                logger.info(f"Using default data directory: {data_dir}")
            else:
                logger.info(f"Using M3_DATA_DIR from environment: {data_dir}")

            suffix = "_multiturn" if domain_multiturn else ""
            data_path = os.path.join(data_dir, f"{domain}{suffix}.json")

            # If multiturn file doesn't exist, try without suffix (will auto-detect format)
            if not os.path.exists(data_path):
                fallback_path = os.path.join(data_dir, f"{domain}.json")
                logger.info(f"Checking for data file: {data_path} -> exists: {os.path.exists(data_path)}")
                logger.info(f"Checking fallback: {fallback_path} -> exists: {os.path.exists(fallback_path)}")
                if os.path.exists(fallback_path):
                    logger.info(
                        f"Data file not found at {data_path}, using {fallback_path} (will auto-detect format)"
                    )
                    data_path = fallback_path
                    domain_multiturn = None  # Reset to None for auto-detection
                else:
                    logger.error(f"❌ Data file not found: {data_path}")
                    logger.error(f"❌ Fallback also not found: {fallback_path}")
                    logger.error(f"   M3_DATA_DIR env var: {os.getenv('M3_DATA_DIR')}")
                    logger.error(f"   Current directory: {os.getcwd()}")
                    logger.error(f"   Script directory: {os.path.dirname(__file__)}")
                    logger.warning(f"Skipping domain '{domain}'")
                    continue

        # Create evaluator for this domain
        # Use max_samples_per_domain if specified, otherwise fall back to max_samples
        max_samples_for_domain = (
            args.max_samples_per_domain
            if hasattr(args, 'max_samples_per_domain') and args.max_samples_per_domain
            else (args.max_samples if hasattr(args, 'max_samples') else None)
        )

        # Check if --task filter contains test case names (for filtering within domain)
        # Test case names typically contain underscores and numbers (e.g., hockey_395_0)
        # Service names are like m3_task_2 or task_2_hockey
        test_case_filters = None
        if hasattr(args, 'test_case_filter') and args.test_case_filter:
            test_case_filters = args.test_case_filter
            logger.info(f"Filtering to specific test cases: {test_case_filters}")

        evaluator = M3Evaluator(
            task_id=test_case_filters,  # Pass test case filters to evaluator
            multiturn=domain_multiturn,
            max_samples=max_samples_for_domain,
            m3_data_mode=m3_data_loader is not None,
            m3_task_id=task_id,
            domain=domain,
        )

        try:
            # Registry mode: Use FilteredToolProvider for domain isolation.
            # The registry app name is just the domain — no `task_<n>_` prefix —
            # so the tool names CUGA records start with the domain itself, not
            # the task ID. Cross-task collisions are prevented by the collision
            # guard in expand_registry_config (and in practice each eval run is
            # narrowed to a single task via --capability).
            registry_app_name = domain
            logger.info(
                f"🔧 Creating filtered tool provider for domain: {domain} (registry app: {registry_app_name})"
            )

            # Create filtered provider that only exposes tools from this domain
            # This provides defense-in-depth: registry filters at MCP level, we filter at agent level
            filtered_provider = FilteredToolProvider(
                base_provider=tool_provider,  # Shared provider with all domains
                app_name=registry_app_name,  # Filter to only this domain's tools
            )
            await filtered_provider.initialize()

            # DEBUG: Check what the filtered provider exposes
            logger.info(f"📋 [DATA LEAKAGE CHECK] Filtered provider for domain '{domain}':")
            logger.info(f"  🎯 Target app: {registry_app_name}")
            logger.info(f"  📦 Base provider has {len(tool_provider.apps)} apps")
            if hasattr(filtered_provider, 'app_name'):
                logger.info(f"  🔒 Filtered to app: {filtered_provider.app_name}")

            # Create agent with filtered provider
            langfuse_handler = setup_langfuse()
            callbacks = [langfuse_handler] if langfuse_handler else []

            evaluator.agent = CugaAgent(
                tool_provider=filtered_provider,  # Only sees this domain's tools
                callbacks=callbacks,
                # Policies are loaded explicitly by _load_m3_policies below per
                # eval run. Disable .cuga auto-load and filesystem sync to keep
                # the per-domain agent's policy set deterministic — otherwise
                # the .cuga folder drifts across domain iterations and policies
                # disappear mid-run (see investigation 2026-05-17).
                auto_load_policies=False,
                filesystem_sync=False,
            )
            evaluator.langfuse_handler = langfuse_handler
            logger.info(f"Agent created with filtered tool provider (domain: {domain})")

            # Load CUGA policies for this per-domain agent (mirrors benchmarks/bpo
            # eval_bench_sdk.py). The source of truth is benchmarks/m3/policies/*.md;
            # eval.sh compiles them to policies.json before invoking us.
            await _load_m3_policies(evaluator.agent, policies_enabled=not getattr(args, "no_policies", False))

            # DEBUG: Verify agent can see tools (check filtered provider)
            try:
                filtered_tools = await filtered_provider.get_all_tools()
                logger.info("🔍 [DATA LEAKAGE CHECK] Agent tool access verification:")
                logger.info(f"  📊 Total tools accessible: {len(filtered_tools)}")

                if not filtered_tools:
                    logger.error(f"  ❌ CRITICAL: Agent has NO TOOLS for domain '{domain}'!")
                    logger.error("     Check registry logs and MCP server connections.")
                else:
                    # Show sample tool names and check for leakage
                    sample_names = [t.name for t in filtered_tools[:10]]
                    logger.info(f"  ✅ Sample tool names: {sample_names}")

                    # Check if any tools belong to other domains
                    other_domain_tools = [t.name for t in filtered_tools if domain not in t.name.lower()]
                    if other_domain_tools:
                        logger.warning(
                            f"  ⚠️  POTENTIAL LEAKAGE: Found {len(other_domain_tools)} tools not matching domain '{domain}'"
                        )
                        logger.warning(f"     Examples: {other_domain_tools[:5]}")
                    else:
                        logger.info(f"  ✅ All tools appear to be from domain '{domain}'")
            except Exception as e:
                logger.error(f"❌ Error checking agent tools: {e}")

            # Evaluate
            await evaluator.evaluate_all(data_path=data_path, preloaded_data=preloaded_data)

            # Add domain info to results before scoring (so the wrapper can
            # derive capability/domain from result["m3_task_id"] / result["domain"]).
            for result in evaluator.results:
                result["domain"] = domain
                result["m3_task_id"] = task_id
                result["service_name"] = service_name

            # Vakra scoring runs here, after results are tagged with task_id/domain.
            # capability_name is resolved from the numeric task_id so the wrapper
            # connects to the matching capability container instead of always
            # defaulting to capability_bi_apis.
            if evaluator.results:
                if no_gt_mode:
                    # No ground truth → skip scoring entirely, just dump
                    # per-sample predictions to results/_vakra/prediction/<domain>.json
                    try:
                        write_predictions_no_gt(
                            evaluator.results,
                            output_dir=Path(__file__).parent / "results",
                            domain=domain,
                        )
                    except Exception as e:
                        logger.warning(f"[{service_name}/{domain}] Writing prediction file failed: {e}")
                else:
                    cap_name = (
                        os.getenv("M3_VAKRA_CAPABILITY")
                        or _vakra_capability_for_task_id(task_id)
                        or "capability_bi_apis"
                    )
                    domain_name = os.getenv("M3_DOMAIN") or domain
                    try:
                        await vakra_score_results_async(
                            evaluator.results,
                            output_dir=Path(__file__).parent / "results",
                            capability_name=cap_name,
                            domain=domain_name,
                        )
                        # Push Vakra-corrected scores back into the tracker so
                        # trajectories/results.json matches report.md (issue #71).
                        patch_tracker_scores(evaluator.results, tracker)
                    except Exception as e:
                        logger.warning(f"[{service_name}/{domain}] Vakra scoring failed (continuing): {e}")

            task_results.extend(evaluator.results)
            logger.info(f"✅ [{service_name}] Completed domain: {domain} ({len(evaluator.results)} results)")

            # Per-domain summary. Vakra is the source of truth for pass/fail
            # and per-step detail; legacy keyword/count summaries are gone.
            if evaluator.results:
                logger.info(f">>> [{service_name}] Domain summary: {domain}")
                if no_gt_mode:
                    _emit_cleanly(print_no_gt_summary, evaluator.results)
                elif any("vakra" in r for r in evaluator.results):
                    _emit_cleanly(print_vakra_summary, evaluator.results)
                else:
                    logger.warning(
                        f"[{service_name}/{domain}] No Vakra scores produced "
                        "(check API_KEY and Vakra failure warnings above)."
                    )

        except Exception as e:
            logger.error(f"❌ [{service_name}] Failed to evaluate domain '{domain}': {e}")
            import traceback

            traceback.print_exc()

    logger.info(f"\n✅ Task {service_name} completed: {len(task_results)} total results")
    return task_results


def get_registry_port() -> int:
    """Registry port shared by the MCP server and cuga-agent HTTP client.

    Reads ``settings.server_ports.registry`` (override via
    ``DYNACONF_SERVER_PORTS__REGISTRY``), the same source
    ``get_registry_base_url()`` uses when the agent calls the registry.
    """
    from cuga.config import settings

    return int(settings.server_ports.registry)


async def start_registry_server(config_path: str) -> subprocess.Popen:
    """Start the registry server with the specified config.

    Args:
        config_path: Path to the registry config file

    Returns:
        Process object for the registry server
    """
    import os
    import subprocess

    registry_port = get_registry_port()

    # Check if the registry port is already in use
    logger.info(f"🔍 Checking if port {registry_port} is available...")
    try:
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', registry_port))
        sock.close()

        if result == 0:
            # Port is in use
            logger.error(f"❌ Port {registry_port} is already in use!")
            logger.error("Another registry server or process is using this port.")
            logger.error("")
            logger.error("To fix this, run one of these commands:")
            logger.error(f"  1. Kill processes on port {registry_port}:")
            logger.error(f"     lsof -ti :{registry_port} | xargs kill")
            logger.error("")
            logger.error("  2. Or find and kill specific process:")
            logger.error(f"     lsof -i :{registry_port}")
            logger.error("     kill <PID>")
            logger.error("")
            raise RuntimeError(
                f"Port {registry_port} is already in use. Please kill the existing process first."
            )
    except RuntimeError:
        raise  # Re-raise the port-in-use error
    except Exception as e:
        logger.debug(f"Port check failed (continuing anyway): {e}")

    # Kill any existing registry servers to avoid conflicts
    logger.info("🧹 Cleaning up any existing registry servers...")
    try:
        # More specific pattern to avoid killing this script
        subprocess.run(["pkill", "-9", "-f", "uv run registry"], capture_output=True)  # noqa: S607 — relies on PATH for shell tools
        subprocess.run(["pkill", "-9", "-f", "fastapi.*registry"], capture_output=True)  # noqa: S607 — same
        subprocess.run(["pkill", "-9", "-f", "uvicorn.*api_registry_server"], capture_output=True)  # noqa: S607 — same
        await asyncio.sleep(1)  # Give time for processes to die
    except Exception as e:
        logger.debug(f"Error during cleanup (this is OK): {e}")

    # Convert to absolute path to ensure subprocess can find it
    abs_config_path = str(Path(config_path).resolve())
    logger.info(f"🚀 Starting registry server with config: {abs_config_path}")

    # Set environment variables for registry config
    env = os.environ.copy()
    env["MCP_SERVERS_FILE"] = abs_config_path
    env["DYNACONF_SERVER_PORTS__REGISTRY"] = str(registry_port)
    env["REGISTRY_PORT"] = str(registry_port)

    # Ensure CONTAINER_RUNTIME is set for the registry subprocess as a full path.
    # The registry server calls os.path.expandvars() on the YAML, so ${CONTAINER_RUNTIME}
    # must resolve to an executable path (not just a bare name like "podman").
    current_runtime = env.get("CONTAINER_RUNTIME", "")
    if current_runtime:
        # Resolve bare name to full path if needed
        resolved = shutil.which(current_runtime) or current_runtime
        env["CONTAINER_RUNTIME"] = resolved
        logger.info(f"Using CONTAINER_RUNTIME: {resolved}")
    else:
        # Auto-detect: prefer podman, fall back to docker
        for candidate in ("podman", "docker"):
            full_path = shutil.which(candidate)
            if full_path:
                env["CONTAINER_RUNTIME"] = full_path
                logger.info(f"Auto-detected container runtime: {full_path}")
                break
        else:
            env["CONTAINER_RUNTIME"] = "docker"
            logger.warning("No container runtime detected, defaulting to 'docker'")

    # Start registry in background with output logging
    registry_log_file = Path(__file__).parent / "registry_server.log"
    log_file = open(registry_log_file, "w")
    logger.info(f"📝 Registry server output will be logged to: {registry_log_file}")
    logger.info("📝 Registry log preview will be echoed here during warmup")

    # Avoid `uv run registry` here because that entrypoint goes through fastapi-cli/rich
    # terminal detection, which crashes in non-interactive background execution.
    # Launch uvicorn directly against the registry app instead.
    # Start in a new process group/session so we can kill the whole
    # tree (uv wrapper → python → uvicorn → any docker exec children) in
    # one shot via killpg. process.terminate() on its own only SIGTERMs
    # the `uv` wrapper, and that doesn't always propagate to uvicorn.
    process = subprocess.Popen(  # noqa: S603 — args are constant literals, no untrusted input
        [  # noqa: S607 — uv resolved from PATH by design
            "uv",
            "run",
            "python",
            "-m",
            "uvicorn",
            "cuga.backend.tools_env.registry.registry.api_registry_server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(registry_port),
        ],
        stdout=log_file,
        stderr=subprocess.STDOUT,  # Combine stderr with stdout
        env=env,
        cwd=Path(__file__).parent.parent.parent,  # Project root
        start_new_session=True,
    )

    # Wait for registry to start with retry logic
    logger.info("⏳ Waiting for registry to start...")
    import httpx

    max_retries = 30  # 30 retries * 2 seconds = 60 seconds max wait
    retry_delay = 5  # seconds (increased from 1 to give more time between attempts)

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://localhost:{registry_port}/applications", timeout=5.0)
                if response.status_code == 200:
                    apps = response.json()
                    logger.info(
                        f"✅ Registry started successfully with {len(apps)} applications (attempt {attempt + 1}/{max_retries})"
                    )
                    logger.info(f"📋 Registered applications: {[app.get('name', 'unknown') for app in apps]}")

                    # Poll registry health to ensure all MCP servers are ready
                    # MCP servers with large tool sets (e.g. 206 hockey tools) need time to
                    # fetch the OpenAPI spec and complete the initialize handshake before
                    # the first tools/list request is sent.
                    logger.info(
                        "⏳ Starting registry warmup: polling health status until all MCP servers are ready. "
                        "Goal: allow MCP servers to finish startup, load tool definitions, "
                        "and complete initialize/tools discovery before evaluation begins."
                    )

                    max_warmup_time = 300  # Maximum 5 minutes
                    poll_interval = 10  # Check every 10 seconds
                    warmup_start = asyncio.get_event_loop().time()
                    all_ready = False

                    while (
                        not all_ready and (asyncio.get_event_loop().time() - warmup_start) < max_warmup_time
                    ):
                        try:
                            async with httpx.AsyncClient() as client:
                                # Check if all apps are ready (have tools loaded)
                                # Note: Registry doesn't have /health endpoint, so we check /applications directly
                                apps_response = await client.get(
                                    f"http://localhost:{registry_port}/applications", timeout=5.0
                                )
                                if apps_response.status_code == 200:
                                    apps = apps_response.json()

                                    # If we have applications registered, they're ready
                                    # The registry log shows "✓ Connected to MCP server 'X' with N tools"
                                    # which means if an app is in the /applications list, it has tools
                                    elapsed = int(asyncio.get_event_loop().time() - warmup_start)

                                    if len(apps) > 0:
                                        logger.info(
                                            f"✅ Registry ready with {len(apps)} MCP server(s) registered! "
                                            f"(warmup took {elapsed}s)"
                                        )
                                        for app in apps:
                                            app_name = app.get('name', 'unknown')
                                            logger.info(f"   ✅ {app_name}: registered and ready")
                                        all_ready = True
                                        break
                                    else:
                                        logger.info(
                                            f"⏳ Registry warmup: waiting for applications to register "
                                            f"(elapsed: {elapsed}s, max: {max_warmup_time}s)"
                                        )
                        except Exception as e:
                            elapsed = int(asyncio.get_event_loop().time() - warmup_start)
                            logger.debug(f"Health check failed at {elapsed}s: {e}")

                        # Show log preview
                        try:
                            log_file.flush()
                            if registry_log_file.exists():
                                preview_lines = registry_log_file.read_text(errors='replace').splitlines()[
                                    -5:
                                ]
                                if preview_lines:
                                    logger.debug("📋 Registry log preview:\n" + "\n".join(preview_lines))
                        except Exception as preview_error:
                            logger.debug(f"Could not read registry log preview: {preview_error}")

                        await asyncio.sleep(poll_interval)

                    if not all_ready:
                        logger.warning(
                            f"⚠️  Registry warmup timeout after {max_warmup_time}s. "
                            "Some MCP servers may not be fully ready. Proceeding anyway..."
                        )

                    break
                else:
                    logger.debug(f"Registry responded with status {response.status_code}, retrying...")
        except Exception as e:
            if attempt < max_retries - 1:
                logger.debug(
                    f"Attempt {attempt + 1}/{max_retries}: Registry not ready yet, waiting {retry_delay}s..."
                )
                await asyncio.sleep(retry_delay)
            else:
                logger.warning(f"⚠️  Could not connect to registry after {max_retries} attempts: {e}")

    return process


async def stop_registry_server(process: subprocess.Popen):
    """Stop the registry server and every descendant.

    We started the server with start_new_session=True, so `process.pid` is
    the session leader / process-group id. Signalling the group with
    os.killpg takes out the `uv` wrapper, the `python` it forked, the
    `uvicorn` worker, and any docker-exec MCP subprocesses in one shot.
    Without this, terminate() only hits `uv` and leaves uvicorn alive,
    which keeps the `tee` pipe open and makes eval.sh look hung.

    Args:
        process: Process object for the registry server
    """
    import errno
    import signal

    if process is None:
        return

    logger.info("🛑 Stopping registry server (process group)...")

    def _kill_group(sig: int) -> None:
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except OSError as e:
            if e.errno != errno.ESRCH:
                raise

    try:
        _kill_group(signal.SIGTERM)
        try:
            process.wait(timeout=5)
            logger.info("✅ Registry server stopped gracefully")
        except subprocess.TimeoutExpired:
            logger.warning("⚠️  Registry did not stop gracefully, sending SIGKILL...")
            _kill_group(signal.SIGKILL)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.error("❌ Registry server still alive after SIGKILL")
            logger.info("✅ Registry server force-stopped")
    except Exception as e:
        logger.error(f"❌ Error stopping registry: {e}")


def rewrite_config_with_loader_domains(config_path: str, m3_data_loader: M3DataLoader) -> str:
    """Write a copy of `config_path` with each service's `metadata.domains`
    replaced by the loader's view of that task_id's domains.

    Used in --no-ground-truth mode so the registry expands services for the
    test domains the user supplied, instead of the small_train domains the
    YAML hard-codes. Services whose task_id has no loader domains are kept
    as-is — they'll just produce no expanded services later.
    """
    import tempfile

    with open(config_path, "r") as f:
        config = yaml.safe_load(f) or {}

    services = config.get("services", []) or []
    rewritten = 0
    for svc_dict in services:
        svc_name = list(svc_dict.keys())[0]
        meta = svc_dict[svc_name].setdefault("metadata", {})
        task_id = meta.get("task_id")
        if task_id is None:
            continue
        loader_domains = m3_data_loader.available_domains(int(task_id))
        if loader_domains:
            meta["domains"] = list(loader_domains)
            rewritten += 1

    fd, path = tempfile.mkstemp(suffix=".yaml", prefix="m3_registry_no_gt_")
    with os.fdopen(fd, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    logger.info(
        f"📝 [--no-ground-truth] Rewrote {rewritten}/{len(services)} service(s) "
        f"with loader-derived domains → {path}"
    )
    return path


def _service_name_filters_from_task(task_list: Optional[List[str]]) -> Optional[List[str]]:
    """Return source-yaml service names from args.task (e.g. m3_task_2).

    UUIDs and hockey_395_0-style test-case IDs are not service-name filters.
    """
    if not task_list:
        return None
    import re

    uuid_re = re.compile(r"^[a-f0-9]{12}-[a-f0-9]{12}$")
    testcase_re = re.compile(r"^[a-z_]+_\d+_\d+$")
    names = [f for f in task_list if not uuid_re.match(f) and not testcase_re.match(f)]
    return names or None


def _non_service_task_filters(task_list: List[str]) -> List[str]:
    """Keep UUID / test-case filters when auto-sequencing capability passes."""
    import re

    uuid_re = re.compile(r"^[a-f0-9]{12}-[a-f0-9]{12}$")
    testcase_re = re.compile(r"^[a-z_]+_\d+_\d+$")
    return [f for f in task_list if uuid_re.match(f) or testcase_re.match(f)]


def expand_registry_config(
    config_path: str,
    capability_filter: Optional[List[str]] = None,
) -> str:
    """Expand registry config by replacing {domain} placeholders with actual domains
    and expanding environment variables.

    Reads a config with {domain} placeholders and generates a temporary config
    with one service per task+domain combination. Also expands environment variables
    like ${CONTAINER_RUNTIME:-docker} before writing the expanded config.

    Args:
        config_path: Path to the generic config file with {domain} placeholders
        capability_filter: Optional list of source-yaml service names (e.g.
            ``["m3_task_2"]``). When provided, services whose key is not in
            this list are skipped before expansion. This prevents the
            post-expansion collision guard from firing when two tasks share a
            domain name (e.g. both ``m3_task_2`` and ``m3_task_3`` define
            ``books``). Items that don't look like service-name filters
            (UUIDs, ``hockey_395_0``-style test-case IDs) are ignored — pass
            them through as-is.

    Returns:
        Path to the temporary expanded config file
    """
    import tempfile

    import yaml

    logger.info(f"Expanding registry config: {config_path}")

    # Read the raw YAML content first to expand environment variables
    with open(config_path, 'r') as f:
        raw_content = f.read()

    # Expand environment variables (including ${VAR:-default} syntax)
    expanded_content = os.path.expandvars(raw_content)

    # Now parse the expanded YAML
    config = yaml.safe_load(expanded_content)

    services = config.get("services", [])
    expanded_services = []

    # Build the set of source-service-name filters from capability_filter. Items
    # that look like UUIDs or test-case IDs (hockey_395_0) are not service-name
    # filters and don't constrain the expansion at all.
    _service_filter: Optional[set] = None
    if capability_filter:
        import re as _re_cap

        _uuid_re = _re_cap.compile(r"^[a-f0-9]{12}-[a-f0-9]{12}$")
        _testcase_re = _re_cap.compile(r"^[a-z_]+_\d+_\d+$")
        cap_items = [f for f in capability_filter if not _uuid_re.match(f) and not _testcase_re.match(f)]
        if cap_items:
            _service_filter = set(cap_items)
            logger.info(
                f"Pre-expansion filter: only services matching {sorted(_service_filter)} will be expanded"
            )

    for service_dict in services:
        service_name = list(service_dict.keys())[0]
        if _service_filter is not None and service_name not in _service_filter:
            logger.info(f"  Skipping (filtered out): {service_name}")
            continue
        service_config = service_dict[service_name]

        metadata = service_config.get("metadata", {})
        domains = metadata.get("domains", [])

        # Check if this service uses {domain} placeholder
        args_list = service_config.get("args", [])
        has_placeholder = any("{domain}" in str(arg) for arg in args_list)

        if has_placeholder and domains:
            # Expand this service into one per domain
            for domain_config in domains:
                # Handle both string and dict domain formats
                if isinstance(domain_config, str):
                    domain_name = domain_config
                    domain_multiturn = None  # Will use task-level default
                else:
                    domain_name = domain_config.get("name")
                    domain_multiturn = domain_config.get("multiturn")

                # The expanded service name is just the domain. The registry uses
                # this as the unique app identifier and CombinedToolProvider prefixes
                # each MCP tool with `<app_name>_`, so CUGA's recorded tool names
                # start with the bare domain (e.g. `codebase_comments_get_…`).
                # Cross-task collisions (two tasks sharing a domain) are caught
                # by the post-expansion check below.
                expanded_service_name = domain_name

                # Deep copy service config
                import copy

                expanded_config = copy.deepcopy(service_config)

                # Replace {domain} placeholder in args
                expanded_args = []
                for arg in expanded_config.get("args", []):
                    if isinstance(arg, str):
                        expanded_args.append(arg.replace("{domain}", domain_name))
                    else:
                        expanded_args.append(arg)
                expanded_config["args"] = expanded_args

                # Update metadata to have single domain (preserve dict format if needed)
                if domain_multiturn is not None:
                    expanded_config["metadata"]["domains"] = [
                        {"name": domain_name, "multiturn": domain_multiturn}
                    ]
                else:
                    expanded_config["metadata"]["domains"] = [domain_name]

                # Add to expanded services
                expanded_services.append({expanded_service_name: expanded_config})

                logger.info(f"  Expanded: {service_name} -> {expanded_service_name} (domain={domain_name})")
        else:
            # No placeholder or no domains, keep as-is
            expanded_services.append(service_dict)
            logger.info(f"  Kept as-is: {service_name}")

    # Collision guard: detect duplicate expanded service names. Since we now use
    # the bare domain as the service name, two tasks sharing a domain (e.g.
    # both task_2 and task_3 have "books") would silently overwrite each other
    # when the dict-list is dumped to yaml. Fail loudly instead — the caller
    # should narrow to a single task with --capability before getting here.
    from collections import Counter as _Counter

    _service_names = [list(s.keys())[0] for s in expanded_services]
    _dups = sorted(n for n, c in _Counter(_service_names).items() if c > 1)
    if _dups:
        raise RuntimeError(
            "Service-name collision in expanded registry config: "
            f"{_dups}. This usually means multiple tasks share a domain name. "
            "Narrow to a single task via --capability before expansion, "
            "or differentiate the domain names in the source yaml."
        )

    # Create temporary config file
    expanded_config = {"services": expanded_services}

    # Save to temp file
    temp_fd, temp_path = tempfile.mkstemp(suffix=".yaml", prefix="m3_registry_expanded_")
    with open(temp_path, 'w') as f:
        yaml.dump(expanded_config, f, default_flow_style=False, sort_keys=False)

    logger.info(f"✅ Expanded config saved to: {temp_path}")
    logger.info(f"   Original services: {len(services)}")
    logger.info(f"   Expanded services: {len(expanded_services)}")

    return temp_path


def _write_single_service_yaml(service_dict: Dict[str, Any]) -> str:
    """Write a minimal registry yaml containing only the given service.

    Used in sequential mode so each expanded (task, domain) pair gets its own
    registry with just that domain's MCP server loaded, instead of all ~20
    MCP servers running at once.
    """
    import tempfile

    service_name = list(service_dict.keys())[0]
    mini = {"services": [service_dict]}
    fd, path = tempfile.mkstemp(suffix=".yaml", prefix=f"m3_registry_{service_name}_")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(mini, f, default_flow_style=False, sort_keys=False)
    except Exception:
        # Best effort: clean up if write failed
        try:
            os.unlink(path)
        except Exception:  # noqa: S110 — unlink during error cleanup is best-effort
            pass
        raise
    return path


def _write_single_service_yaml(service_dict: Dict[str, Any]) -> str:
    """Write a minimal registry yaml containing only the given service.

    Used in sequential mode so each expanded (task, domain) pair gets its own
    registry with just that domain's MCP server loaded, instead of all ~20
    MCP servers running at once.
    """
    import tempfile

    service_name = list(service_dict.keys())[0]
    mini = {"services": [service_dict]}
    fd, path = tempfile.mkstemp(suffix=".yaml", prefix=f"m3_registry_{service_name}_")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(mini, f, default_flow_style=False, sort_keys=False)
    except Exception:
        # Best effort: clean up if write failed
        try:
            os.unlink(path)
        except Exception:  # noqa: S110 — unlink during error cleanup is best-effort
            pass
        raise
    return path


async def evaluate_tasks_in_batches(task_evaluations: List[tuple], batch_size: int, args) -> List[Any]:
    """Evaluate tasks in batches to manage resources for large-scale evaluation.

    Args:
        task_evaluations: List of (service_name, coroutine) tuples
        batch_size: Number of tasks to evaluate per batch
        args: Command-line arguments

    Returns:
        List of all results from all batches
    """
    all_results = []
    total_tasks = len(task_evaluations)
    num_batches = (total_tasks + batch_size - 1) // batch_size  # Ceiling division

    logger.info(f"\n{'=' * 80}")
    logger.info(f"📦 BATCHED EVALUATION: {total_tasks} tasks split into {num_batches} batches")
    logger.info(f"   Batch size: {batch_size} tasks per batch")
    logger.info("   This helps manage resources for large-scale evaluation")
    logger.info(f"{'=' * 80}\n")

    for batch_num in range(num_batches):
        batch_start = batch_num * batch_size
        batch_end = min(batch_start + batch_size, total_tasks)
        batch = task_evaluations[batch_start:batch_end]

        logger.info(f"\n{'=' * 80}")
        logger.info(f"🔄 BATCH {batch_num + 1}/{num_batches}: Evaluating tasks {batch_start + 1}-{batch_end}")
        logger.info(f"{'=' * 80}\n")

        # Run tasks in this batch in parallel
        batch_results = await asyncio.gather(*[coro for _, coro in batch], return_exceptions=True)

        # Process results
        for (service_name, _), task_results in zip(batch, batch_results):
            if isinstance(task_results, Exception):
                logger.error(f"❌ Task {service_name} failed: {task_results}")
                import traceback

                traceback.print_exception(type(task_results), task_results, task_results.__traceback__)
            elif isinstance(task_results, list):
                all_results.extend(task_results)
                logger.info(f"✅ Task {service_name}: {len(task_results)} results")

        # Cleanup between batches (except for last batch)
        if batch_num < num_batches - 1:
            logger.info(f"\n⏸️  Batch {batch_num + 1} complete. Cleaning up before next batch...")

            # Force garbage collection
            import gc

            gc.collect()

            # Brief pause to allow resources to be released
            await asyncio.sleep(2)

            logger.info(f"✅ Ready for batch {batch_num + 2}\n")

    logger.info(f"\n{'=' * 80}")
    logger.info(f"✅ ALL BATCHES COMPLETE: Processed {total_tasks} tasks in {num_batches} batches")
    logger.info(f"{'=' * 80}\n")

    return all_results


async def run_config_mode(args, container_runtime: str):
    """Run evaluation in config mode with task-level parallelism and optional batching.

    Tasks run in parallel (each uses separate container).
    Domains within each task run sequentially (one connection per container).

    For large-scale evaluation (many domains), use --batch-size to process in batches.
    """
    logger.info(f"Loading config from: {args.from_config}")
    logger.info("✅ Entered run_config_mode()")

    # Initialize M3 data loader early so any errors fail before registry startup
    m3_data_loader: Optional[M3DataLoader] = None
    no_ground_truth = bool(getattr(args, "no_ground_truth", False))
    if no_ground_truth and not getattr(args, "m3_data", None):
        logger.error("--no-ground-truth requires --m3-data <path>")
        return
    if getattr(args, "m3_data", None):
        m3_data_loader = M3DataLoader(args.m3_data, allow_missing_output=no_ground_truth)
        logger.info(
            f"📦 --m3-data mode enabled. Source: {args.m3_data} | "
            f"capabilities: {m3_data_loader.available_capabilities()} | "
            f"no_ground_truth={no_ground_truth}"
        )

    # When --m3-data is set but no --capability/--task service name was given,
    # expand one capability at a time. Bare-domain registry names (books,
    # mondial_geo, soccer_2016, …) collide across m3_task_2 and m3_task_3 if
    # both are expanded into the same yaml (regression from the vakra tool-name
    # fix in c0ce9f1). Sequential passes restore the old "run everything"
    # behaviour without requiring --capability on the CLI.
    _task_filters = list(args.task) if getattr(args, "task", None) else []
    if m3_data_loader and _service_name_filters_from_task(_task_filters) is None:
        cap_ids = m3_data_loader.available_capabilities()
        preserved = _non_service_task_filters(_task_filters)
        if len(cap_ids) > 1:
            logger.info(
                f"No --capability filter: running {len(cap_ids)} capability passes "
                f"sequentially ({', '.join(f'm3_task_{i}' for i in cap_ids)}) "
                f"to avoid cross-task domain-name collisions"
            )
            import copy

            for task_id in cap_ids:
                cap_name = f"m3_task_{task_id}"
                logger.info(f"\n{'=' * 80}\n🔁 Auto capability pass: {cap_name}\n{'=' * 80}")
                pass_args = copy.copy(args)
                pass_args.task = [cap_name] + preserved
                await run_config_mode(pass_args, container_runtime)
            return
        if len(cap_ids) == 1:
            cap_name = f"m3_task_{cap_ids[0]}"
            logger.info(f"No --capability filter: auto-narrowing to data capability {cap_name}")
            args.task = [cap_name] + preserved

    # In --no-ground-truth mode, rewrite the YAML so each service's
    # metadata.domains reflects the loader's view (test domains), not the
    # YAML's hard-coded small_train list. Without this, `--domain X` filters
    # at the service level reject test domains, and even if they didn't,
    # expand_registry_config wouldn't generate services for them.
    rewritten_config_path: Optional[str] = None
    source_config_path = args.from_config
    if no_ground_truth and m3_data_loader is not None:
        rewritten_config_path = rewrite_config_with_loader_domains(args.from_config, m3_data_loader)
        source_config_path = rewritten_config_path

    # Expand config if it contains {domain} placeholders. Pre-filter source
    # services by --capability so the bare-domain expanded names (e.g.
    # `books` from m3_task_2 vs `books` from m3_task_3) can't collide in
    # the same expanded yaml. UUID / hockey_395_0-style items in args.task
    # don't constrain the source service set; they're filtered later.
    _capability_filter = list(args.task) if getattr(args, "task", None) else None
    expanded_config_path = expand_registry_config(source_config_path, capability_filter=_capability_filter)
    temp_config_created = expanded_config_path != args.from_config

    # Check if registry mode is enabled
    registry_enabled = os.getenv("DYNACONF_ADVANCED_FEATURES__REGISTRY", "false").lower() == "true"
    registry_process = None
    # Determine concurrency up front so we know whether to start one shared
    # registry (parallel/batched) or one-per-service (sequential).
    batch_size = args.batch_size or 1
    sequential_mode = batch_size < 2

    try:
        # Start registry if enabled. In sequential mode we *don't* start a
        # shared registry here — each service spawns its own mini registry
        # below so only that domain's MCP server is running at a time.
        if registry_enabled and not sequential_mode:
            logger.info("🔧 Registry mode enabled - starting shared registry server for parallel run...")
            registry_process = await start_registry_server(expanded_config_path)

            # IMPORTANT: Update MCP_SERVERS_FILE in current process to point to expanded config
            # This ensures CombinedToolProvider reads the same config as the registry server
            # Use absolute path to ensure consistency
            abs_expanded_path = str(Path(expanded_config_path).resolve())
            os.environ["MCP_SERVERS_FILE"] = abs_expanded_path
            logger.info(f"Updated MCP_SERVERS_FILE to: {abs_expanded_path}")
        elif registry_enabled and sequential_mode:
            logger.info(
                "🔧 Registry mode enabled - will start a fresh registry per service (sequential mode)"
            )
        else:
            logger.info("📋 Direct mode - connecting to containers directly (no registry)")

        # Load expanded registry config
        config = load_registry_config(expanded_config_path)
        services = config.get("services", [])

        if not services:
            logger.error("No services found in config file")
            return

        # Filter to specific task if requested
        if args.task:
            # args.task is a list due to nargs="*", convert to single string if only one item
            task_filter = args.task[0] if len(args.task) == 1 else args.task

            # Detect if this is a test case name (e.g., hockey_395_0) vs service name (e.g., m3_task_2)
            # Test case names typically have format: domain_number_number
            # Service names are like: m3_task_2, task_2_hockey
            import re as _re

            # Check if any filter looks like a test case name (contains domain_number_number pattern)
            test_case_pattern = r'^[a-z_]+_\d+_\d+$'
            # Also accept the --m3-data UUID format (12hex-12hex), e.g. "1960f609e439-e5d337d143b6".
            # When UUIDs are used, the user must also pass --domain to constrain which
            # service these UUIDs come from (a UUID alone doesn't encode its domain).
            uuid_filter_pattern = r'^[a-f0-9]{12}-[a-f0-9]{12}$'
            task_filters = [task_filter] if isinstance(task_filter, str) else task_filter

            is_test_case_filter = any(_re.match(test_case_pattern, tf) for tf in task_filters)
            is_uuid_filter = any(_re.match(uuid_filter_pattern, tf) for tf in task_filters)

            if is_uuid_filter:
                # UUID filter: skip domain extraction (caller must use --domain),
                # set test_case_filter so the evaluator filters per-sample at the
                # right point. Strip out items that aren't sample UUIDs (e.g. a
                # capability name like "m3_task_2" passed alongside via
                # --capability) — those don't match any sample_id and would just
                # be dead weight inside the per-sample filter. Capability-name
                # items are already handled by expand_registry_config's
                # capability_filter and the service-name filter below.
                uuid_only_filters = [tf for tf in task_filters if _re.match(uuid_filter_pattern, tf)]
                logger.info(f"Detected UUID-style test case filter: {uuid_only_filters}")
                args.test_case_filter = uuid_only_filters
            elif is_test_case_filter:
                # This is a test case filter - extract domain and pass to evaluator
                logger.info(f"Detected test case filter: {task_filters}")

                # Extract domain from test case name (e.g., hockey_395_0 -> hockey)
                # Find which domain this test case belongs to
                test_case_domains = set()
                for tf in task_filters:
                    # Extract domain by removing _number_number suffix
                    domain_match = _re.match(r'^([a-z_]+)_\d+_\d+$', tf)
                    if domain_match:
                        test_case_domains.add(domain_match.group(1))

                if not test_case_domains:
                    logger.error(f"Could not extract domain from test case name(s): {task_filters}")
                    return

                logger.info(f"Extracted domains from test cases: {test_case_domains}")

                # Filter services to only those matching the extracted domains
                def _domain_matches(service_dict):
                    svc_name = list(service_dict.keys())[0]
                    svc_config = service_dict[svc_name]
                    meta = svc_config.get("metadata", {})
                    domains = meta.get("domains", [])

                    # Check if any domain in this service matches our test case domains
                    for domain_config in domains:
                        domain_name = (
                            domain_config if isinstance(domain_config, str) else domain_config.get("name")
                        )
                        if domain_name in test_case_domains:
                            return True
                    return False

                services = [s for s in services if _domain_matches(s)]
                if not services:
                    logger.error(f"No services found for test case domain(s): {test_case_domains}")
                    return

                # Store test case filter for later use in evaluator
                args.test_case_filter = task_filters
                logger.info(
                    f"Will filter to specific test cases: {task_filters} ({len(services)} service(s) to check)"
                )
            else:
                # This is a service/task name filter - use original logic
                # Handle both single task and multiple tasks
                if isinstance(task_filter, str):
                    # Single task - extract task_id if present
                    _task_id_match = _re.search(r'(\d+)$', task_filter)
                    _task_id_filter = int(_task_id_match.group(1)) if _task_id_match else None
                    task_filters = [task_filter]
                else:
                    # Multiple tasks
                    _task_id_filter = None
                    task_filters = task_filter

                def _task_matches(service_dict):
                    svc_name = list(service_dict.keys())[0]
                    # Check against all task filters
                    for task_name in task_filters:
                        # Direct substring match (original service names before expansion)
                        if task_name in svc_name:
                            return True
                        # Match by numeric task_id in metadata (only for single task filter)
                        if _task_id_filter is not None:
                            meta = service_dict[svc_name].get("metadata", {})
                            if meta.get("task_id") == _task_id_filter:
                                return True
                    return False

                services = [s for s in services if _task_matches(s)]
                if not services:
                    logger.error(f"Task(s) '{task_filter}' not found in config")
                    return

                # No test case filter for service-level filtering
                args.test_case_filter = None
                logger.info(f"Filtered to task(s): {task_filter} ({len(services)} service(s))")

        # Apply --domain filter at the service level so we don't spin up a
        # registry for services that evaluate_single_task will just skip.
        if getattr(args, "domain", None):
            wanted = {d.lower() for d in args.domain}

            def _service_has_wanted_domain(svc_dict):
                svc_name = list(svc_dict.keys())[0]
                doms = svc_dict[svc_name].get("metadata", {}).get("domains", [])
                for dc in doms:
                    name = dc if isinstance(dc, str) else dc.get("name", "")
                    if name.lower() in wanted:
                        return True
                return False

            filtered = [s for s in services if _service_has_wanted_domain(s)]
            if not filtered:
                logger.error(f"--domain {args.domain} matched no services")
                return
            logger.info(
                f"Applied --domain filter: {len(filtered)}/{len(services)} service(s) after filtering to {sorted(wanted)}"
            )
            services = filtered

        # Initialize Langfuse (optional)
        try:
            from langfuse.callback import CallbackHandler

            CallbackHandler()
            logger.info("Langfuse handler initialized")
        except Exception as e:
            logger.warning(f"Could not initialize Langfuse: {e}")

        # Collect task evaluation coroutines only for parallel/batched mode.
        # In sequential mode we await evaluate_single_task per service below
        # (after starting a one-service registry). Building coroutines here
        # and never awaiting them triggers "coroutine was never awaited".
        task_evaluations: List[tuple[str, Any]] = []

        if not sequential_mode:
            for service_dict in services:
                service_name = list(service_dict.keys())[0]
                service_config = service_dict[service_name]

                metadata = service_config.get("metadata", {})
                task_id = metadata.get("task_id")
                container = metadata.get("container")
                domains = metadata.get("domains", [])
                task_multiturn = metadata.get("multiturn", None)  # None = auto-detect

                task_coro = evaluate_single_task(
                    service_name=service_name,
                    task_id=task_id,
                    container=container,
                    domains=domains,
                    task_multiturn=task_multiturn,
                    args=args,
                    container_runtime=container_runtime,
                    m3_data_loader=m3_data_loader,
                )
                task_evaluations.append((service_name, task_coro))

        # Concurrency: sequential by default, batched when --batch-size >= 2.
        # "Fully parallel" is just a large batch size (>= total tasks).
        all_results: List[Dict[str, Any]] = []
        if not sequential_mode:
            # Batched evaluation returns an already-flattened list.
            all_results = await evaluate_tasks_in_batches(
                task_evaluations=task_evaluations,
                batch_size=batch_size,
                args=args,
            )
        else:
            logger.info(f"\n{'=' * 80}")
            logger.info(
                f"🐢 Running {len(task_evaluations)} tasks SEQUENTIALLY "
                f"(pass --batch-size N > 1 for parallelism)"
            )
            logger.info(f"{'=' * 80}\n")

            # In sequential mode we ignore the pre-built coroutines and
            # iterate `services` directly, because each service needs its
            # own one-service registry started *before* evaluate_single_task
            # connects. The coroutines in task_evaluations would read
            # MCP_SERVERS_FILE at await-time, so we need to set env +
            # registry up per iteration.
            for service_dict in services:
                service_name = list(service_dict.keys())[0]
                service_config = service_dict[service_name]
                metadata = service_config.get("metadata", {})
                task_id = metadata.get("task_id")
                container = metadata.get("container")
                domains = metadata.get("domains", [])
                task_multiturn = metadata.get("multiturn", None)

                mini_yaml = None
                svc_registry = None
                try:
                    if registry_enabled:
                        mini_yaml = _write_single_service_yaml(service_dict)
                        logger.info(f"🔧 [{service_name}] Starting one-service registry from {mini_yaml}")
                        svc_registry = await start_registry_server(mini_yaml)
                        os.environ["MCP_SERVERS_FILE"] = str(Path(mini_yaml).resolve())

                    task_results = await evaluate_single_task(
                        service_name=service_name,
                        task_id=task_id,
                        container=container,
                        domains=domains,
                        task_multiturn=task_multiturn,
                        args=args,
                        container_runtime=container_runtime,
                        m3_data_loader=m3_data_loader,
                    )
                    if isinstance(task_results, list):
                        all_results.extend(task_results)
                        logger.info(f"✅ Task {service_name}: {len(task_results)} results")
                except Exception as e:
                    import traceback

                    logger.error(f"❌ Task {service_name} failed: {e}")
                    traceback.print_exception(type(e), e, e.__traceback__)
                finally:
                    if svc_registry is not None:
                        await stop_registry_server(svc_registry)
                    if mini_yaml:
                        try:
                            os.unlink(mini_yaml)
                        except Exception:  # noqa: S110 — temp registry yaml cleanup is best-effort
                            pass

        # Print overall summary. Every step is defended with explicit
        # exception handling so that if any one reporting call raises, we
        # still see (a) what failed and (b) the remaining output — instead
        # of silently dropping the whole summary.
        logger.info("=" * 80)
        logger.info(f"OVERALL SUMMARY (All Tasks & Domains) — {len(all_results)} results")
        logger.info("=" * 80)
        sys.stderr.flush()

        if all_results:
            # In no-ground-truth mode there's no scoring — render the
            # tool-call-count summary instead and capture to the summary file.
            if no_ground_truth:
                _emit_cleanly(print_no_gt_summary, all_results)
                try:
                    with open(M3_SUMMARY_FILE, "w") as _sf:
                        _sf.write(_render_no_gt_summary(all_results))
                    logger.info(f"Summary written to {M3_SUMMARY_FILE}")
                except Exception as e:
                    logger.warning(f"Failed to write summary to {M3_SUMMARY_FILE}: {e}")

                # Save raw results JSON and skip vakra-format ground-truth dump.
                output_dir = Path(__file__).parent / "results"
                saved_path = save_evaluation_results(all_results, output_dir, prefix="m3_config_no_gt")
                logger.info(f"\nResults saved to: {saved_path}")
                return

            # Vakra is the source of truth for the overall summary. We capture
            # it to M3_SUMMARY_FILE so eval.sh can re-echo it as the last thing
            # on screen.
            if any("vakra" in r for r in all_results):
                _emit_cleanly(print_vakra_summary, all_results)
                try:
                    import io as _io

                    buf = _io.StringIO()
                    _orig = sys.__stdout__

                    # Re-render to capture text for the summary file
                    class _Cap:
                        def write(self, s):
                            buf.write(s)
                            return len(s)

                        def flush(self):
                            pass

                    sys.__stdout__ = _Cap()  # type: ignore[assignment]
                    try:
                        print_vakra_summary(all_results)
                    finally:
                        sys.__stdout__ = _orig  # type: ignore[assignment]
                    with open(M3_SUMMARY_FILE, "w") as _sf:
                        _sf.write(buf.getvalue())
                    logger.info(f"Summary written to {M3_SUMMARY_FILE}")
                except Exception as e:
                    logger.warning(f"Failed to write summary to {M3_SUMMARY_FILE}: {e}")
            else:
                logger.warning(
                    "No Vakra scores produced for any task — check API_KEY and "
                    "the per-domain Vakra warnings above."
                )

            # Save results
            output_dir = Path(__file__).parent / "results"
            saved_path = save_evaluation_results(all_results, output_dir, prefix="m3_config")
            logger.info(f"\nResults saved to: {saved_path}")

            # Save ground truth format
            evaluator_temp = M3Evaluator()
            evaluator_temp.results = all_results
            ground_truth_path = evaluator_temp._save_ground_truth_format(output_dir)
            logger.info(f"Ground truth format saved to: {ground_truth_path}")
        else:
            logger.warning("⚠️  No results produced. Check the registry logs and task filters.")

    finally:
        # Stop registry if it was started
        if registry_process is not None:
            await stop_registry_server(registry_process)

        # Cleanup temporary config file if created
        if temp_config_created:
            try:
                os.unlink(expanded_config_path)
                logger.info(f"🧹 Cleaned up temporary config: {expanded_config_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temporary config: {e}")
        if rewritten_config_path:
            try:
                os.unlink(rewritten_config_path)
                logger.info(f"🧹 Cleaned up rewritten config: {rewritten_config_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup rewritten config: {e}")


async def main():
    """Main evaluation function."""
    import argparse
    import shutil

    # Auto-detect container runtime (docker or podman) — always resolve to full path
    def detect_container_runtime():
        """Detect which container runtime is available, returning the full path."""
        # Check env var first (may be a bare name like 'podman' or a full path)
        env_runtime = os.environ.get("CONTAINER_RUNTIME", "")
        if env_runtime:
            # Resolve bare name to full path if needed
            full_path = shutil.which(env_runtime) or env_runtime
            return full_path

        # Auto-detect: prefer podman, fall back to docker
        for candidate in ("podman", "docker"):
            full_path = shutil.which(candidate)
            if full_path:
                return full_path

        logger.warning("Neither docker nor podman found in PATH, defaulting to 'docker'")
        return "docker"

    # Always resolve CONTAINER_RUNTIME to a full path so subprocess exec works
    # regardless of whether PATH is inherited by the registry subprocess
    runtime = detect_container_runtime()
    os.environ["CONTAINER_RUNTIME"] = runtime
    logger.info(f"Container runtime resolved to: {runtime}")

    parser = argparse.ArgumentParser(
        description="Evaluate M3 tasks with Cuga agent (Registry mode only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all tasks/domains from config
  python eval_m3.py --from-config benchmarks/m3/config/m3_registry.yaml

  # Run specific capability from config
  python eval_m3.py --from-config m3_registry.yaml --capability m3_task_2

  # Limit samples per domain for testing
  python eval_m3.py --from-config m3_registry.yaml --max-samples-per-domain 5
        """,
    )

    # Config mode option (required)
    parser.add_argument(
        "--from-config",
        type=str,
        required=True,
        metavar="CONFIG_FILE",
        help="YAML config file specifying tasks and domains (e.g., m3_registry.yaml)",
    )

    # Task filtering. `--capability` is the preferred name when selecting a
    # service like `m3_task_2` / `m3_task_3`; `--task` is kept as an alias
    # for backward compatibility (it's referenced in README, other scripts,
    # and older tooling). Both feed the same dest via action='extend', so
    # `--capability m3_task_2 --task <uuid>` appends both into args.task
    # (the previous default `store` action made the second flag overwrite
    # the first, which silently dropped one of the filters).
    parser.add_argument(
        "--capability",
        "--task",
        dest="task",
        type=str,
        nargs="*",
        action="extend",
        default=[],
        help="Filter by capability/service name (e.g., 'm3_task_2') or by a "
        "test-case ID (e.g., 'hockey_395_0' or M3-data UUID). Accepts "
        "multiple values and multiple invocations (they're appended). "
        "Overrides --difficulty.",
    )
    parser.add_argument(
        "--max-samples-per-domain",
        "--max-samples",
        dest="max_samples_per_domain",
        type=int,
        default=None,
        help="Maximum number of samples to evaluate per domain (default: all). "
        "Useful for testing. `--max-samples` is accepted as an alias for parity "
        "with eval_m3_react.py.",
    )
    parser.add_argument(
        "--domain",
        type=str,
        nargs="*",
        default=None,
        help="Only evaluate the named domain(s) within each selected task (e.g., 'hockey'). "
        "Combine with --task to run a single task/domain pair.",
    )

    # Concurrency. Default is sequential (one task at a time). Pass
    # --batch-size N > 1 to run N tasks in parallel per batch.
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Run this many tasks in parallel per batch (default: 1 = sequential). "
        "For full parallelism pass a value >= total number of tasks.",
    )
    parser.add_argument(
        "--domains-per-container",
        type=int,
        default=10,
        help="Number of domains to assign to each container in parallel (default: 10). "
        "Lower values reduce container load, higher values increase parallelism.",
    )
    parser.add_argument(
        "--parallel-containers",
        type=int,
        default=4,
        help="Number of containers to run in parallel per batch (default: 4). "
        "Adjust based on available RAM (~2GB per container).",
    )
    parser.add_argument(
        "--m3-data",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to an M3 data source: either a .zip archive or a directory "
        "containing capability_<id>_* subdirs with input/ and output/ JSONs "
        "per domain. When set, samples are loaded by merging input/output "
        "pairs. Pass/fail is scored by tool-call count match against "
        "gold_sequence; keyword matching is bypassed.",
    )
    parser.add_argument(
        "--no-ground-truth",
        action="store_true",
        help="Run --m3-data on input-only data (no output/ folder). Skips "
        "evaluation/scoring entirely; only collects per-sample tool calls "
        "and writes them to results/_vakra/prediction/<domain>.json. The "
        "domain list is taken from the data source rather than the YAML "
        "config, so unlabeled test domains run without editing the config.",
    )
    parser.add_argument(
        "--no-policies",
        action="store_true",
        help="Disable CUGA policies (mirrors benchmarks/bpo). When enabled "
        "(default), policies are loaded per-domain from "
        "benchmarks/m3/policies/policies.json after the per-domain agent is "
        "constructed.",
    )

    from benchmarks.helpers.logging_args import add_log_level_args, apply_log_level

    add_log_level_args(parser)

    args = parser.parse_args()
    apply_log_level(args)

    container_runtime = os.environ.get("CONTAINER_RUNTIME", "podman")

    logger.info(f"Running in CONFIG MODE (registry-based) with config file: {args.from_config}")
    await run_config_mode(args, container_runtime)


# Removed run_direct_mode() function - now using registry mode only


if __name__ == "__main__":
    asyncio.run(main())
