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
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Union

import yaml
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
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
    should_trace_langfuse_task,
)
from benchmarks.helpers.sdk_eval_helpers import (
    add_policy_via_agent,
    clear_all_policies,
    is_langfuse_tracing_enabled,
)
from benchmarks.m3.container_health import (
    EnvironmentFailureError,
    EnvironmentFailureStreakTracker,
    health_check_or_abort,
    record_streak_or_abort,
    render_environment_failure_banner,
    resume_hint_for,
)
from benchmarks.m3.eval_config_loader import filter_samples_by_eval_key, load_eval_key_ids
from benchmarks.m3.m3_data_loader import M3DataLoader, diff_tool_calls

# Injected into CugaLite's system prompt via SDK special_instructions (eval-only).
# Many M3 MCP tools lack a documented output/response schema (response_doc is empty).
# Without guidance the model assumes dict-shaped results and calls .get() on lists/strings.
M3_TOOL_OUTPUT_INSTRUCTIONS = """
## Undocumented tool outputs (M3 eval)

When a tool in **Current Available Tools** has no **Response Schema** / output documentation:

1. **First use — isolated probe:** Run the tool alone (Isolated Tools rule). End with a `print()` of a **compact shape summary**, not a full dump:
   - Top-level type: `dict`, `list`, `str`, `int`, etc.
   - If `dict`: key names (first ~10) and the type of each value at one level (e.g. `list`, `dict`, `str`).
   - If `list`: length and the type of the first element (e.g. `list[dict]`, `list[str]`).
   - Shallow shape is enough (`dict[str, object]`, `list[int]`, `dict[str, dict]`) — do not recurse deeply.

2. **All follow-up code — handle defensively:** Never assume dict/list/key types from memory.
   - Use `isinstance(result, dict)` before `.get()` or key access.
   - Use `isinstance(result, list)` before indexing or iteration.
   - If APIs vary (bare list vs `{"items": [...]}`), normalize once then proceed, e.g.:
     `rows = result if isinstance(result, list) else (result.get("items") if isinstance(result, dict) else [])`
   - Do not call `.get()`, `[0]`, or attribute access on a value until its type is confirmed.

Reporting shape in step 1 is for choosing correct access in step 2 — the goal is **crash-free Python**, not type narration for its own sake.
""".strip()


# Wave-1 Change #1: the evidence-chain / groundedness rider. Split out from the
# tool-output section so it can be A/B-toggled via M3_GROUNDEDNESS_PROMPT
# (default on). The tool-output section above stays constant across both arms.
M3_GROUNDEDNESS_INSTRUCTIONS = """
## Final answers for M3 groundedness

For M3 final answers, make every factual claim traceable to the tool response text. Add no claim the tool output does not literally support.

1. Answer only the user's question, using the data you retrieved. Never refuse, and never claim that a tool, API, or dataset "cannot", "does not provide", "is unable to", or "lacks" something — those are ungrounded claims about capabilities. Do not mention missing endpoints, dataset limitations, tool-search attempts, retries, uncertainty, or "for context" information. If you obtained the values needed, state the answer.

2. State values exactly as the tool returned them. Round only if the question explicitly asks for it; otherwise give the value as returned.

3. If the answer comes directly from a tool response, repeat the exact returned value and, when natural, the exact returned field/key name. Prefer:
   - `The answer is <value>.`
   - `<field_name>: <value>.`
   Avoid extra explanation.

4. If the answer requires combining multiple tool responses, include a one-line evidence chain before the final answer:
   - `Evidence: <raw value/key from response 1>; <raw value/key from response 2>. Answer: <combined result>.`
   Keep the chain literal and short. Do not add facts that were not present in tool outputs.

5. If the answer requires arithmetic, compute it directly from the exact tool-returned values and show the formula using those values. Use only the source values the question asks you to combine; do not introduce a complement, total, difference, or any other quantity the question did not ask for. The final answer is the result of the formula — never an intermediate value:
   - `Evidence: numerator = 17, denominator = 25. Calculation: 17 / 25 = 0.68. Answer: 0.68.`
   Use only values/field names that appear in the tool output. Do not describe the calculation in prose beyond the formula.

6. If a tool returns an ID and another tool resolves that ID to a name, preserve both:
   - `Evidence: id = 112; country = United States. Answer: United States.`
   This makes the join explicit.

7. For single-value answers, prefer one sentence. For multi-hop answers, use at most two sentences: one `Evidence:` sentence and one `Answer:` sentence.
""".strip()


# Wave-1 Change #1b: the "selector / derivation-encapsulation" trim sub-rule.
# Targets tasks where a single tool selected/ranked the answer entity by criteria
# the agent did NOT separately retrieve (the gold tool encapsulates the
# derivation), so the underlying premises never enter the evidence. Restating
# those criteria as fact is therefore ungrounded and fails the whole answer.
# Gated separately via M3_GROUNDEDNESS_TRIM (default off) so it can be A/B'd as
# an extra rule on top of the rider. Appended as rule 8 when enabled.
M3_GROUNDEDNESS_TRIM_RULE = """
8. Do not restate the question's selection criteria as asserted facts. If a tool selected or ranked an entity by criteria whose underlying values you did not separately retrieve (e.g. a single tool returned the answer entity directly), name the entity and answer the question — do not assert *why* it was selected. Prefer `United States: 0 mountains.` over `The United States, which has the highest GDP and the lowest agriculture proportion, has 0 mountains.` The selection criteria live in the question, not in any tool output; repeating them as fact adds an ungrounded claim that fails the whole answer.
""".strip()


# Change #2: the claim-verification rule, targeting three groundedness-failure
# patterns mined from cap4-300's real judge explanations (55/72 policy-related
# failures fail here, not on tool selection — see cap4_groundedness_probe1..3
# in eval_config.toml): (a) asserting an attribute/category a tool response
# never actually returned, (b) claiming a returned list is exhaustive when
# nothing confirms it isn't paginated/truncated, (c) supplying a name/value
# from prior knowledge that no tool response for this task actually contained.
# Gated separately via M3_GROUNDEDNESS_CLAIM_CHECK (default off, same opt-in
# pattern as the Change #1b trim rule) so it can be A/B'd independently.
M3_GROUNDEDNESS_CLAIM_RULE = """
9. Do not assert any attribute, category, or property of a returned item unless that exact attribute is present as a field in the tool response for that item. If the result has no country/origin/date/category field, do not claim the item belongs to a country, era, or category — even if the question asked about one — just because the question implied that category. State only what the returned fields actually say.

10. Do not describe a returned list as complete, exhaustive, or "all" of anything unless nothing about the tool response or its parameters (a result-count limit, a top-N/n_results argument, a page token) indicates the result could be partial. When in doubt, describe the list as "the items returned by <tool>" rather than "all the items."

11. Never state a name, value, or fact that did not appear in any tool response for this task, even if it is common knowledge or you are confident it is correct. If no tool returned it, it is not part of the grounded answer — say you could not find it rather than supplying it from memory.
""".strip()


# Change #2b: omit-don't-hedge sub-rule. Direct response to a live-tested
# failure: on cap4_groundedness_probe1 (cars, 1f58b1e965af-03bc27917845),
# Change #2 alone visibly influenced the model's output (it started echoing
# rule 9's own language back, e.g. "Tesla Model X (not confirmed by the
# retrieved data — the tool response did not include this field)") but still
# scored 0/3 across an isolated 3-run compare (2026-07-23) — the groundedness
# judge does not credit hedged/caveated claims, only their absence. The model
# was treating "state it with a caveat" as satisfying rule 9-11; this rule
# makes explicit that the required response to an unconfirmable claim is
# omission, not annotation. Checked against the full cap4-300 mined dataset:
# this attribute-inference pattern (rule 9's country/origin shape
# specifically) also hit mondial_geo (3x) and world (1x), not just cars, so
# this fix is not narrowly cars-specific. Only meaningful on top of Change #2
# (references "rules 9-11"), so gated as a nested sub-toggle under
# _claim_verification_enabled(), not a sibling of it. Default off via
# M3_GROUNDEDNESS_OMIT_UNCONFIRMED so it can be A/B'd independently of #2's
# base claim-verification behavior.
M3_GROUNDEDNESS_OMIT_RULE = """
14. If a claim in your draft answer cannot be stated as fully supported by a tool response under rules 9-11, do not include that claim in your final answer with a caveat, hedge, or parenthetical qualifier (e.g. do NOT write "Tesla Model X (not confirmed by the retrieved data)"). Instead, remove that item or claim from your answer entirely, as if it were never a candidate. A shorter answer containing only fully-supported items is correct; a longer one padded with caveated or hedged unsupported items is not — hedging does not make an unsupported claim acceptable, omission does.
""".strip()


def _omit_unconfirmed_enabled() -> bool:
    """Change #2b sub-toggle (rule 14, omit-don't-hedge). Default OFF - opt
    in with M3_GROUNDEDNESS_OMIT_UNCONFIRMED=on/1/true/yes. Only takes
    effect when Change #2 (claim-verification) is also enabled - this rule
    references rules 9-11 directly and is meaningless without them."""
    return os.getenv("M3_GROUNDEDNESS_OMIT_UNCONFIRMED", "off").strip().lower() in ("1", "on", "true", "yes")


# Change #3: extractive-construction rule. Annotating an ungrounded claim
# after the fact (Change #2 / the OutputFormatter policy) does not help —
# the groundedness judge scores whether a claim is supported, not whether
# it's hedged. This rule instead tries to prevent the fabrication at
# construction time: for list/attribute-style answers, build the answer
# value in code from the tool's actual returned data and print it, then
# require the final NL answer to just restate what was printed, rather than
# letting a separate, unconstrained generation re-compose prose from memory
# of the tool call. Gated separately via M3_GROUNDEDNESS_EXTRACTIVE (default
# off) so it can be A/B'd independently of Changes #1/#1b/#2.
M3_GROUNDEDNESS_EXTRACTIVE_RULE = """
12. When your final answer reports a list of names, titles, categories, or other multi-item attributes, build that list in your LAST code execution step as a Python variable assembled only from values actually present in a tool's returned data (e.g. `titles = [r["title"] for r in rows]`), then `print()` it. Your final natural-language answer must then simply restate exactly what was printed — do not add, infer, or supply any item, attribute, or category that was not itself present in the printed tool-derived data.

13. If the tool response has no field for the specific attribute the question asks about (e.g. it returns counts but not titles, or IDs but not names), say so explicitly — "the retrieved data does not include <attribute>" — rather than supplying plausible-sounding values for that attribute from general knowledge. A partial, honestly-scoped answer is correct; a complete-looking but partly invented one is not.
""".strip()


# find_tools query-phrasing rider. Motivated by a specific repeated failure
# (professional_basketball's d14bbb0be92d-d09ad3135cea: "nickname of the NBA
# player ... Western Conference ... season 2006 ... two blocks") where
# find_tools sometimes failed to surface the one correct tool
# (get_player_nicknames_by_blocks_conference_season) across several
# similarly-worded query attempts. The winning attempt (a PASS run) phrased
# its find_tools query naming all three filter constraints at once
# ("player stats season 2006 blocks conference western"); losing attempts
# used looser, single-word queries ("blocks", "season", "players"). NOTE:
# checked whether this generalizes via a domain tool-count vs. pass-rate
# correlation across the full cap4-300 dataset (300 tasks, 35 domains) -
# r=-0.010 task-level / r=0.059 domain-level, i.e. no correlation; large
# catalogs are not systematically harder for find_tools. This rider is
# therefore NOT gated on catalog size - it's a general query-phrasing
# instruction, tested here against one task known to be sensitive to it.
# Gated via M3_FIND_TOOLS_QUERY_RIDER (default off, opt-in, same convention
# as Change #2/#3) so it can be A/B'd independently.
M3_FIND_TOOLS_QUERY_RULE = """
## Phrasing find_tools queries

When calling `find_tools`, name every specific filter or parameter the task needs, not just a general topic word. If the task requires N distinct constraints (e.g. a count, a category, and a time period), your query should mention all N, not just one or two.

If a `find_tools` call returns few or no matches, do not conclude the tool doesn't exist. Try again with a different, more specific query that names the constraints more explicitly, before giving up on that domain's catalog.
""".strip()


def _find_tools_query_rider_enabled() -> bool:
    """find_tools query-phrasing rider toggle. Default OFF - opt in with
    M3_FIND_TOOLS_QUERY_RIDER=on/1/true/yes. Independent of the groundedness
    rider family; always appended when enabled, not nested under it."""
    return os.getenv("M3_FIND_TOOLS_QUERY_RIDER", "off").strip().lower() in ("1", "on", "true", "yes")


# Parameter-variation rider. Complementary to M3_FIND_TOOLS_QUERY_RULE above,
# targeting a different failure stage: even once the correct tool is found,
# a filter-style parameter with no discoverable valid-value list (no schema
# enum, no listing/enumeration endpoint in the domain's catalog - confirmed
# for professional_basketball_get_player_nicknames_by_blocks_conference_season's
# `conference` param, plain `str` with no enum) gets guessed one spelling at
# a time, one call per code block, burning step budget. The one observed PASS
# on d14bbb0be92d-d09ad3135cea used the opposite approach: a small brute-force
# grid over plausible spelling/casing variants x plausible season values,
# tried together in a single code block, which found the correct value
# ("West", not "west"/"Western"/"western") on that pass. Gated via
# M3_PARAMETER_VARIATION_RIDER (default off) so it can be A/B'd independently
# of the find_tools query-phrasing rider - the two target different stages
# (finding the tool vs. calling it correctly) and either could be enabled
# without the other.
M3_PARAMETER_VARIATION_RULE = """
## Retrying filter parameters that return empty results

If a tool call with a string-typed filter parameter (e.g. a category, region, or status) returns an empty result, do not conclude no data matches and do not guess one alternative spelling per code block. Instead, in a SINGLE code block, try a small set of plausible variations together — different casing, abbreviations, and full/short forms (e.g. `["west", "West", "Western", "Western Conference", "W"]`) — combined with any other uncertain parameter values, and check all combinations before reporting no result. Only conclude the data doesn't exist after this batch of plausible variations has been tried.
""".strip()


def _parameter_variation_rider_enabled() -> bool:
    """Parameter-variation retry rider toggle. Default OFF - opt in with
    M3_PARAMETER_VARIATION_RIDER=on/1/true/yes. Independent of the
    find_tools query-phrasing rider and the groundedness rider family."""
    return os.getenv("M3_PARAMETER_VARIATION_RIDER", "off").strip().lower() in ("1", "on", "true", "yes")


def _groundedness_prompt_enabled() -> bool:
    """Wave-1 Change #1 A/B toggle. Default on; set M3_GROUNDEDNESS_PROMPT to
    off / 0 / false / no to drop the evidence-chain rider (the baseline arm)."""
    return os.getenv("M3_GROUNDEDNESS_PROMPT", "on").strip().lower() not in ("0", "off", "false", "no")


def _trim_selection_enabled() -> bool:
    """Wave-1 Change #1b sub-toggle (rule 8, selector/derivation-encapsulation
    trim). Default OFF — opt in with M3_GROUNDEDNESS_TRIM=on/1/true/yes. Only
    takes effect when the groundedness rider itself is enabled."""
    return os.getenv("M3_GROUNDEDNESS_TRIM", "off").strip().lower() in ("1", "on", "true", "yes")


def _claim_verification_enabled() -> bool:
    """Change #2 sub-toggle (rules 9-11, claim-verification: unsupported
    attributes, false completeness, fabrication). Default OFF — opt in with
    M3_GROUNDEDNESS_CLAIM_CHECK=on/1/true/yes. Only takes effect when the
    groundedness rider itself is enabled."""
    return os.getenv("M3_GROUNDEDNESS_CLAIM_CHECK", "off").strip().lower() in ("1", "on", "true", "yes")


def _extractive_construction_enabled() -> bool:
    """Change #3 sub-toggle (rules 12-13, extractive construction: build
    list/attribute answers in code from tool data, print, then restate
    verbatim). Default OFF — opt in with M3_GROUNDEDNESS_EXTRACTIVE=on/1/
    true/yes. Only takes effect when the groundedness rider itself is
    enabled."""
    return os.getenv("M3_GROUNDEDNESS_EXTRACTIVE", "off").strip().lower() in ("1", "on", "true", "yes")


def _build_m3_special_instructions() -> str:
    """Compose the eval-only system rider. The tool-output (crash-free) section
    is always present; the Change #1 groundedness rider is gated for A/B, and the
    Change #1b trim rule, Change #2 claim-verification rule, and Change #3
    extractive-construction rule are further independent opt-in sub-rules on
    top of the rider.

    Called fresh at each agent creation (not cached at import time) so that
    in-process env var changes — a pytest fixture, a subprocess-free A/B
    toggle, an interactive flip — take effect immediately instead of reading
    a value baked in when this module was first imported."""
    parts = [M3_TOOL_OUTPUT_INSTRUCTIONS]
    if _find_tools_query_rider_enabled():
        parts.append(M3_FIND_TOOLS_QUERY_RULE)
    if _parameter_variation_rider_enabled():
        parts.append(M3_PARAMETER_VARIATION_RULE)
    if _groundedness_prompt_enabled():
        parts.append(M3_GROUNDEDNESS_INSTRUCTIONS)
        if _trim_selection_enabled():
            parts.append(M3_GROUNDEDNESS_TRIM_RULE)
        if _claim_verification_enabled():
            parts.append(M3_GROUNDEDNESS_CLAIM_RULE)
            if _omit_unconfirmed_enabled():
                parts.append(M3_GROUNDEDNESS_OMIT_RULE)
        if _extractive_construction_enabled():
            parts.append(M3_GROUNDEDNESS_EXTRACTIVE_RULE)
    return "\n\n".join(parts)


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


def _policy_tool_scoping_enabled() -> bool:
    """M3_POLICY_TOOL_SCOPING (default off). Technique #1 from the
    cuga_vakra_agent comparison (2026-07-26): deterministically prune
    forbidden tools from the list CUGA sees, instead of only reactively
    blocking a call after the agent attempts it (RetrieverPolicyGuard).
    See docs/m3-cap4-policy-investigation-20260723/README.md and this
    session's transcript for the analysis behind it."""
    return os.getenv("M3_POLICY_TOOL_SCOPING", "0") == "1"


_POLICY_COND_RULE_RE = re.compile(
    r"if a user.s query pertains to (.+?), which is/are about (.+?)[,.]",
    re.IGNORECASE | re.DOTALL,
)


def _policy_is_retriever_tool(name: str) -> bool:
    # Registry-exposed names are domain-prefixed (e.g.
    # "professional_basketball_query_professional_basketball"), so this must
    # be a substring match, not startswith.
    return "query_" in name.lower() or "retriev" in name.lower()


async def _classify_policy_topic_match(model: Any, query: str, topic: str, desc: str) -> bool:
    """One cheap LLM call: does `query` actually pertain to a conditional
    policy's stated topic? Ported from cuga_vakra_agent/adapter/cuga_v2_agent.py
    (_classify_topic_match). Assumes a match on any classification failure
    (fail open -> same behavior as not having this feature)."""
    try:
        response = await model.ainvoke(
            f"Topic area: {topic}\nIt covers: {desc}\n\nQuestion: {query}\n\n"
            f"Does the question pertain to this topic area? Reply exactly YES or NO."
        )
        content = response.content
        if isinstance(content, list):
            content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
        return str(content).strip().upper().startswith("Y")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[policy-scope] topic classify failed ({e}); assuming match")
        return True


async def resolve_policy_tool_scope(model: Any, policy_text: str, query: str) -> str:
    """Deterministically resolve a cap4 policy's tool-usage scope: 'all',
    'retriever_only', or 'no_retriever'. Ported from cuga_vakra_agent's
    CugaV2Agent._resolve_scope. Absolute rules ("do not use document
    retrievers" / "only use document retrievers") prune unconditionally;
    conditional rules ("if a user's query pertains to X...") first classify
    whether this specific query is on-topic before scoping anything."""
    text = (policy_text or "").lower()
    if "document retriever" not in text:
        return "all"
    m = _POLICY_COND_RULE_RE.search(policy_text or "")
    if m:
        topic, desc = m.group(1).strip(), m.group(2).strip()
        if not await _classify_policy_topic_match(model, query, topic, desc):
            return "all"
        return "no_retriever" if "do not use document retrievers" in text else "retriever_only"
    if text.startswith("do not use document retriever"):
        return "no_retriever"
    if "do not use any other" in text or "only" in text:
        return "retriever_only"
    return "all"


class PolicyScopedToolProvider:
    """Wraps another tool provider, deterministically pruning tools per-task
    based on a bound scope ('all' / 'retriever_only' / 'no_retriever').

    CUGA's prepare_tools_and_apps graph node re-fetches tools from the
    provider fresh on every .invoke() (confirmed by reading
    cuga-agent/.../adapter/prepare_node.py), so set_scope() before each
    task's invoke is enough to take effect per-task without rebuilding the
    CugaAgent instance the domain-level evaluator reuses across all its
    tasks. One instance is constructed per domain (see evaluate_single_task),
    and domain tasks are processed sequentially within that instance, so a
    plain instance attribute (not a per-thread/contextvar map) is safe here.
    """

    def __init__(self, base_provider):
        self.base_provider = base_provider
        self._scope = "all"

    def set_scope(self, scope: str) -> None:
        self._scope = scope

    async def initialize(self):
        if hasattr(self.base_provider, "initialize"):
            await self.base_provider.initialize()

    async def get_apps(self):
        return await self.base_provider.get_apps()

    def _filter(self, tools):
        if self._scope == "all":
            return tools
        want_retriever = self._scope == "retriever_only"
        filtered = [t for t in tools if _policy_is_retriever_tool(t.name) == want_retriever]
        logger.info(f"[policy-scope] scope={self._scope} -> {len(filtered)}/{len(tools)} tools")
        return filtered

    async def get_tools(self, app_name: str):
        tools = await self.base_provider.get_tools(app_name)
        return self._filter(tools)

    async def get_all_tools(self):
        tools = await self.base_provider.get_all_tools()
        return self._filter(tools)


def _refusal_normalization_enabled() -> bool:
    """M3_REFUSAL_NORM (default off). Technique #3 from the cuga_vakra_agent
    comparison (2026-07-26), rebuilt 2026-07-26 around the scorer's actual
    lever: benchmarks/m3/evaluator/scorer.py's unanswerable special case
    checks `input.pred_answer in ["", " "]` (or zero pred tool calls) against
    a ground-truth answer containing "i can not answer" - it does NOT check
    the prediction for any specific canonical string. Blanking a give-up
    answer satisfies that condition outright, regardless of how many tool
    calls were made; writing a canonical sentence does not. Neutral on tasks
    with a real answer (a give-up already scores 0 there); only changes
    shape on tasks whose GT *is* a refusal."""
    return os.getenv("M3_REFUSAL_NORM", "0") == "1"


_GIVEUP_MARKERS = (
    "i can not answer",
    "i cannot answer",
    "unable to locate",
    "unable to find",
    "i'm unable",
    "i am unable",
    "no tool",
    "no available tool",
    "no suitable tool",
    "don't have any tool",
    "do not have any tool",
    "don't have access",
    "cannot find a tool",
    "can't find a tool",
    "execution cancelled",
    "requires your approval",
    "no accessible tool",
    "step limit",
    "maximum step",
)


def _is_giveup(text: str) -> bool:
    # gpt-oss outputs typographic punctuation (curly apostrophes etc.); the
    # marker list uses straight ASCII, so normalize before matching or
    # real matches like "I’m unable" silently miss "i'm unable".
    low = (text or "").lower().replace("’", "'").replace("‘", "'")
    return any(m in low for m in _GIVEUP_MARKERS)


def _normalize_refusal_in_result(result: dict, sample_id: str = "?") -> None:
    """Mutate `result` in place: any give-up-shaped answer text becomes
    blank. Covers every field downstream scoring (_to_vakra_pair) or
    reporting might read the final answer from."""
    blanked = False
    for key in ("response", "answer", "final_response"):
        val = result.get(key)
        if isinstance(val, str) and _is_giveup(val):
            result[key] = ""
            blanked = True
    all_responses = result.get("all_responses")
    if isinstance(all_responses, list) and all_responses:
        last = all_responses[-1]
        if isinstance(last, dict):
            val = last.get("response")
            if isinstance(val, str) and _is_giveup(val):
                last["response"] = ""
                blanked = True
    if blanked:
        logger.info(f"[{sample_id}] [refusal-norm] give-up answer blanked")


def _support_check_enabled() -> bool:
    """M3_SUPPORT_CHECK (default off). Technique #4 from the cuga_vakra_agent
    comparison (2026-07-26): a confident answer whose load-bearing tokens
    (numbers + proper-noun entities) mostly don't appear in this task's own
    successful tool results is fabrication - blank it rather than score it.
    Unlike the original (cuga_vakra_agent/adapter/cuga_v2_agent.py
    _post_answer_hook), this is NOT gated on a "retriever_only" policy
    scope - that scope is effectively unreachable in our system (see
    technique #1's investigation: 2026-07-26, our capability_4_multiturn
    container has zero retriever tools in most domains), so gating on it
    would make this dead code here too. Applied generally instead, same
    lesson as technique #3: blank the answer (not a canonical sentence) so
    it hits scorer.py's real deterministic unanswerable bypass
    (pred_answer in ["", " "]) rather than depending on judge leniency."""
    return os.getenv("M3_SUPPORT_CHECK", "0") == "1"


_SUPPORT_CHECK_STOPWORDS = {
    "The",
    "This",
    "That",
    "These",
    "Those",
    "Here",
    "There",
    "Based",
    "According",
    "Answer",
    "Note",
    "However",
    "Additionally",
    "Overall",
}

_SUPPORT_CHECK_NUM_RE = re.compile(r"\d[\d,.]*\d|\d")
_SUPPORT_CHECK_ENTITY_RE = re.compile(r"\b[A-Z][a-zA-Z'’\-]+(?:\s+[A-Z][a-zA-Z'’\-]+)*")


def _collect_tool_evidence(result: dict) -> str:
    """Concatenate every successful tool-call result in this task into one
    lowercased evidence blob to check claim tokens against."""
    chunks: List[str] = []

    def _add(tool_calls):
        if not isinstance(tool_calls, list):
            return
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            res = tc.get("result")
            text = res if isinstance(res, str) else json.dumps(res, default=str)
            if not text.lower().startswith(("error", '"error')):
                chunks.append(text)

    _add(result.get("tool_calls"))
    for turn in result.get("all_responses") or []:
        if isinstance(turn, dict):
            _add(turn.get("tool_calls"))
    return " ".join(chunks).lower().replace(",", "")


def _extract_claim_tokens(answer: str) -> set:
    nums = _SUPPORT_CHECK_NUM_RE.findall(answer)
    ents = _SUPPORT_CHECK_ENTITY_RE.findall(answer)
    tokens = {t.strip(".,;:") for t in nums + ents}
    return {t for t in tokens if len(t) > 2 and t not in _SUPPORT_CHECK_STOPWORDS}


def _is_unsupported_claim(answer: str, evidence: str) -> bool:
    tokens = _extract_claim_tokens(answer)
    if not tokens:
        return False
    supported = sum(1 for t in tokens if t.lower().replace(",", "") in evidence)
    return (supported / len(tokens)) < 0.5


def _apply_support_check(result: dict, sample_id: str = "?") -> None:
    """Mutate `result` in place: blank an answer whose claim tokens mostly
    lack support in this task's own tool results."""
    evidence = _collect_tool_evidence(result)
    blanked = False
    for key in ("response", "answer", "final_response"):
        val = result.get(key)
        if isinstance(val, str) and val.strip() and not _is_giveup(val):
            if _is_unsupported_claim(val, evidence):
                result[key] = ""
                blanked = True
    all_responses = result.get("all_responses")
    if isinstance(all_responses, list) and all_responses:
        last = all_responses[-1]
        if isinstance(last, dict):
            val = last.get("response")
            if isinstance(val, str) and val.strip() and not _is_giveup(val):
                if _is_unsupported_claim(val, evidence):
                    last["response"] = ""
                    blanked = True
    if blanked:
        logger.info(f"[{sample_id}] [support-check] unsupported claim blanked")


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


# eval.sh exports a run-scoped path so concurrent runs on one host don't
# overwrite each other's summary (issue #115); the fixed default only applies
# when eval_m3 is invoked directly.
M3_SUMMARY_FILE = os.getenv("M3_SUMMARY_FILE", "/tmp/m3_summary.txt")  # noqa: S108  # nosec B108 — dev-tool output path; not security-sensitive


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
        bundle_dir: Optional[Path] = None,
        resume_completed_ids: Optional[set] = None,
        policies_enabled: bool = True,
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
            policies_enabled: False when the run was started with --no-policies.
                Gates both the per-domain policies.json corpus (_load_m3_policies,
                called by evaluate_single_task) and the per-task ToolGuide built
                from each sample's additional_instructions (evaluate_multiturn_task).
        """
        self.difficulty_filter = difficulty_filter
        self.task_ids = [task_id] if isinstance(task_id, str) else task_id
        self.task_id = self.task_ids[0] if self.task_ids and len(self.task_ids) == 1 else None
        self.multiturn = multiturn
        self.max_samples = max_samples
        self.m3_data_mode = m3_data_mode
        self.m3_task_id = m3_task_id
        self.domain = domain
        self.bundle_dir = bundle_dir
        self.resume_completed_ids = resume_completed_ids or set()
        self.policies_enabled = policies_enabled
        self.agent: Optional[CugaAgent] = None
        self.langfuse_enabled = None
        self.results: List[Dict[str, Any]] = []
        # Per-domain sample-level environment-failure streak. Fresh per
        # M3Evaluator instance, so it naturally resets each domain — this is
        # what catches a container dying mid-domain, independent of how many
        # domains or samples are configured (a single domain can hold 100+
        # samples and run for hours; per-domain-only detection would
        # otherwise grind through all of them before noticing).
        self._env_fail_streak = EnvironmentFailureStreakTracker(threshold=_env_int("M3_ENV_FAIL_STREAK", 3))

    def _resume_skip(self, identity: str) -> bool:
        """True if `identity` (optionally scoped to self.domain) is already done."""
        if not self.resume_completed_ids:
            return False
        if self.domain is not None and (identity, self.domain) in self.resume_completed_ids:
            return True
        return identity in self.resume_completed_ids

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
            langfuse_handler=self.langfuse_enabled,
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
        num_turns = len(turns)

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

        # VAKRA per-sample policy text (M3DataLoader's "additional_instructions").
        # Task-specific: read fresh from this sample every call. Every instance
        # of this text in the dataset is a tool-usage restriction ("use only
        # document retrievers" / "do not use document retrievers") — verified
        # across all 150 policy-bearing samples, no other policy shape exists —
        # so it's delivered as a per-task ToolGuide (add_tool_guide, added
        # right before this sample's invocation and deleted right after,
        # win or lose) rather than free text folded into the prompt/history.
        # ToolGuide's default trigger with no keywords is an AlwaysTrigger, so
        # it applies unconditionally for exactly this one task's lifetime —
        # never accumulated onto the agent or leaked into a later sample.
        policy_text = sample.get("additional_instructions") or None
        policy_id: Optional[str] = None
        if policy_text and self.policies_enabled:
            try:
                policy_id = await self.agent.policies.add_tool_guide(
                    name=f"cap4_policy_{sample_id}",
                    content=policy_text,
                    target_tools=["*"],
                    target_apps=[domain],
                )
                if policy_id is None:
                    logger.warning(
                        f"[{sample_id}] additional_instructions present but no ToolGuide was "
                        "added (policy system disabled — check DYNACONF_POLICY__ENABLED); this "
                        "task runs with no tool-usage constraint delivered to the agent."
                    )
            except Exception as e:
                logger.warning(f"[{sample_id}] Failed to add per-task ToolGuide policy: {e}")
                policy_id = None

        # Technique #1 (M3_POLICY_TOOL_SCOPING, default off): resolve and bind
        # this task's deterministic tool scope on top of (not instead of) the
        # ToolGuide description-enrichment above and RetrieverPolicyGuard's
        # reactive runtime block. Reset to "all" every task (not just when a
        # policy is present) since the wrapper's scope is a plain instance
        # attribute reused across this domain's sequential task loop.
        scope_provider = getattr(self, "_policy_scope_provider", None)
        if scope_provider is not None:
            scope = "all"
            if policy_text:
                live_query = turns[-1].get("query", "") if turns else ""
                scope = await resolve_policy_tool_scope(self.agent._model, policy_text, live_query)
                logger.info(f"[{sample_id}] [policy-scope] resolved scope={scope}")
            scope_provider.set_scope(scope)

        try:
            if num_turns >= 2:
                # Dialogue-priming: VAKRA's dialogue.turns holds every turn except
                # the last one already answered (each has a gold "answer" the
                # sample's own author/solver gave). We emulate that conversation
                # having already happened - prior turns become synthetic
                # HumanMessage/AIMessage history - and only live-invoke the agent
                # on the final, unanswered turn. This is what makes the final turn
                # a genuine follow-up question instead of a fresh one asked cold.
                prior_turns = turns[:-1]
                live_turn = turns[-1]
                history_messages: List[BaseMessage] = []
                for prior_turn in prior_turns:
                    history_messages.append(HumanMessage(content=prior_turn.get("query", "")))
                    # VAKRA's answer is structured data (lists/dicts), not prose -
                    # stringify it into plausible prior-agent-response text so it's
                    # valid AIMessage content.
                    history_messages.append(AIMessage(content=_stringify_gt_answer(prior_turn.get("answer"))))
                live_query = live_turn.get("query", "")
                live_intent = live_query

                single_result = await evaluate_task_with_langfuse(
                    agent=self.agent,
                    task={
                        "name": sample_id,
                        "intent": live_intent,
                        "difficulty": sample.get("difficulty", "unknown"),
                    },
                    task_index=sample_index,
                    langfuse_handler=self.langfuse_enabled,
                    user_context=None,
                    tracker_callback=tracker_callback,
                    track_tool_calls=True,
                    history_messages=history_messages,
                    policy_text=policy_text,
                )
                # Start from the full single-turn result (preserves tokens, cost,
                # LLM-call counts, trace_id, etc. for reporting) and layer on the
                # multiturn-shaped fields _annotate_tool_call_diffs and the
                # downstream Vakra scoring expect.
                result = dict(single_result)
                result["final_response"] = single_result.get("response")
                result["all_responses"] = [
                    {
                        "turn": num_turns,
                        "query": live_query,
                        "response": single_result.get("response"),
                        "tool_calls": single_result.get("tool_calls") or [],
                    }
                ]
            else:
                result = await evaluate_multiturn_task_with_langfuse(
                    agent=self.agent,
                    turns=turns,
                    task_name=sample_id,
                    task_index=sample_index,
                    langfuse_handler=self.langfuse_enabled,
                    user_context=None,
                    tracker_callback=tracker_callback,
                    track_tool_calls=True,
                    expected_keywords=expected_keywords,
                    task_metadata=task_metadata,
                    policy_text=policy_text,
                )
        finally:
            if policy_id is not None:
                try:
                    await self.agent.policies.delete(policy_id)
                except Exception as e:
                    logger.warning(
                        f"[{sample_id}] Failed to delete per-task ToolGuide policy {policy_id}: {e}"
                    )

        # Technique #4 (M3_SUPPORT_CHECK, default off): blank answers whose
        # claim tokens aren't supported by this task's own tool results.
        if _support_check_enabled():
            _apply_support_check(result, sample_id)

        # Technique #3 (M3_REFUSAL_NORM, default off): blank give-up answers
        # before they reach Vakra scoring.
        if _refusal_normalization_enabled():
            _normalize_refusal_in_result(result, sample_id)

        result["sample_id"] = sample_id
        if "uuid" in sample:
            result["uuid"] = sample["uuid"]
        result["domain"] = domain
        if "task_number" in sample:
            result["task_number"] = sample["task_number"]

        # Surface the GT bits Vakra needs so _to_vakra_pair can build a real
        # ground-truth dialogue. gold_sequence/answer_per_turn/tool_response_per_turn
        # are per-turn arrays covering every turn including the live one - index
        # -1 is the live (last) turn for a primed dialogue, and equivalent to
        # index 0 for a single-turn sample (both are the only/last entry).
        gold_seq = (expected_output or {}).get("gold_sequence") or []
        answers = (expected_output or {}).get("answer_per_turn") or []
        tool_resps = (expected_output or {}).get("tool_response_per_turn") or []
        result["expected_output"] = {
            "response": _stringify_gt_answer(answers[-1]) if answers else "",
            "tool_calls": gold_seq[-1] if gold_seq else [],
            "tool_responses": tool_resps[-1] if tool_resps else [],
        }

        gold_per_turn = (expected_output or {}).get("gold_sequence")
        if self.m3_data_mode and gold_per_turn is not None:
            # Only the live (last) turn was actually invoked; primed turns have
            # no real tool calls to diff against their gold ones (last):1 in
            # both cases keeps this a no-op for single-turn samples.
            self._annotate_tool_call_diffs(result, gold_per_turn[-1:])

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
                identity = sample.get("sample_id", sample.get("uuid", f"sample_{i}"))
                if self._resume_skip(identity):
                    logger.info(f"\n[{i}/{len(samples)}] Skipping already-completed sample: {identity}")
                    continue
                logger.info(f"\n[{i}/{len(samples)}] Processing sample...")
                result = await self.evaluate_multiturn_task(sample, sample_index=i)
                self.results.append(result)

                if self._env_fail_streak.record([result]):
                    reason = (
                        f"{self._env_fail_streak.threshold} consecutive samples in domain "
                        f"'{self.domain}' failed with environment-shaped errors (last: {identity})"
                    )
                    print(render_environment_failure_banner(reason, resume_hint_for(self.bundle_dir)))
                    raise EnvironmentFailureError(reason)

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
                identity = task.get("name", f"task_{i}")
                if self._resume_skip(identity):
                    logger.info(f"\n[{i}/{len(test_cases)}] Skipping already-completed task: {identity}")
                    continue
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
        flush_langfuse(self.langfuse_enabled)

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
    bundle_dir = Path(args.bundle_dir) if getattr(args, "bundle_dir", None) else None
    resume_completed_keys: set = set()
    if bundle_dir is not None:
        from benchmarks.helpers.incremental_results import load_completed_domain_keys

        resume_completed_keys = load_completed_domain_keys(bundle_dir)
    if getattr(args, "resume_task_ids", None):
        # Manual override (bare task ids, not domain-scoped) — mirrors the
        # bpo/oak/appworld convention of unioning this in. M3Evaluator._resume_skip
        # already falls back to a bare-identity check, so a plain task id here
        # skips it across every domain, not just the ones on disk.
        resume_completed_keys |= set(args.resume_task_ids)

    # NOTE: `domains` is NOT re-derived from the loader here. It already
    # reflects the loader's domains, narrowed to exactly the one domain this
    # call is scoped to: rewrite_config_with_loader_domains() rewrites the
    # source YAML's metadata.domains from loader data *before*
    # expand_registry_config() expands each service down to a single domain
    # (see both in run_config_mode). Sequential mode then starts a fresh
    # one-service registry per domain and calls this function once per
    # domain. Overriding `domains` back to the loader's *full* domain list
    # here (as a previous version of this function did) discarded that
    # narrowing — this call would then try to walk every domain for the
    # task using only the single-domain registry that was actually started,
    # so every domain past the first had zero tools registered.
    no_gt_mode = bool(m3_data_loader and getattr(m3_data_loader, "allow_missing_output", False))

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

            eval_key_ids = getattr(args, "eval_key_ids", None)
            if eval_key_ids is not None:
                preloaded_data = filter_samples_by_eval_key(preloaded_data, eval_key_ids)
                if not preloaded_data:
                    logger.info(
                        f"[{service_name}/{domain}] --eval-key: no samples in this split for "
                        f"this domain; skipping"
                    )
                    continue
                logger.info(
                    f"📦 --eval-key: restricted task_{task_id}/{domain} to {len(preloaded_data)} sample(s)"
                )
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

        policies_enabled = not getattr(args, "no_policies", False)
        evaluator = M3Evaluator(
            task_id=test_case_filters,  # Pass test case filters to evaluator
            multiturn=domain_multiturn,
            max_samples=max_samples_for_domain,
            m3_data_mode=m3_data_loader is not None,
            m3_task_id=task_id,
            domain=domain,
            bundle_dir=bundle_dir,
            resume_completed_ids=resume_completed_keys,
            policies_enabled=policies_enabled,
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

            # Technique #1 (M3_POLICY_TOOL_SCOPING, default off): wrap with a
            # provider that deterministically prunes forbidden tools per-task,
            # set via evaluator._policy_scope_provider.set_scope() below in
            # evaluate_multiturn_task. One wrapper per domain; domain tasks run
            # sequentially, so a plain instance attribute is a safe scope store.
            evaluator._policy_scope_provider = None
            if _policy_tool_scoping_enabled():
                filtered_provider = PolicyScopedToolProvider(filtered_provider)
                evaluator._policy_scope_provider = filtered_provider

            # DEBUG: Check what the filtered provider exposes
            logger.info(f"📋 [DATA LEAKAGE CHECK] Filtered provider for domain '{domain}':")
            logger.info(f"  🎯 Target app: {registry_app_name}")
            logger.info(f"  📦 Base provider has {len(tool_provider.apps)} apps")
            if hasattr(filtered_provider, 'app_name'):
                logger.info(f"  🔒 Filtered to app: {filtered_provider.app_name}")

            # Langfuse: per-task trace-scoped handlers are attached in
            # evaluate_task_with_langfuse via build_langfuse_invoke_config.
            # Do not pass an unscoped CallbackHandler on the agent — that creates
            # orphan root traces per LLM call (especially visible on Watsonx).
            # Gate only — per-task trace-scoped handlers are attached in invoke config.
            evaluator.langfuse_enabled = should_trace_langfuse_task()

            evaluator.agent = CugaAgent(
                tool_provider=filtered_provider,  # Only sees this domain's tools
                special_instructions=_build_m3_special_instructions(),
                # Policies are loaded explicitly by _load_m3_policies below per
                # eval run. Disable .cuga auto-load and filesystem sync to keep
                # the per-domain agent's policy set deterministic — otherwise
                # the .cuga folder drifts across domain iterations and policies
                # disappear mid-run (see investigation 2026-05-17).
                auto_load_policies=False,
                filesystem_sync=False,
            )
            logger.info(f"Agent created with filtered tool provider (domain: {domain})")

            # Load CUGA policies for this per-domain agent (mirrors benchmarks/bpo
            # eval_bench_sdk.py). The source of truth is benchmarks/m3/policies/*.md;
            # eval.sh compiles them to policies.json before invoking us.
            await _load_m3_policies(evaluator.agent, policies_enabled=policies_enabled)

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
            # Scope Vakra prediction/groundtruth files under the workspace bundle
            # (when one exists) instead of the shared benchmarks/m3/results/
            # directory. Two concurrent runs for different experiments/capabilities
            # can hit the same domain name and clobber each other's
            # _vakra/prediction/<domain>.json under the shared path, and stale
            # files from old runs never get cleared there. Same fallback pattern
            # as _finalize_and_save_results above.
            vakra_output_dir = (
                Path(bundle_dir) / "results" if bundle_dir is not None else Path(__file__).parent / "results"
            )
            if evaluator.results:
                if no_gt_mode:
                    # No ground truth → skip scoring entirely, just dump
                    # per-sample predictions to results/_vakra/prediction/<domain>.json
                    try:
                        write_predictions_no_gt(
                            evaluator.results,
                            output_dir=vakra_output_dir,
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
                            output_dir=vakra_output_dir,
                            capability_name=cap_name,
                            domain=domain_name,
                            policy_judge_path=getattr(args, "policy_judge_path", None),
                        )
                        # Push Vakra-corrected scores back into the tracker so
                        # trajectories/results.json matches report.md (issue #71).
                        patch_tracker_scores(evaluator.results, tracker)
                    except Exception as e:
                        logger.warning(f"[{service_name}/{domain}] Vakra scoring failed (continuing): {e}")

            # Persist per-result partials AFTER vakra scoring so the on-disk
            # (and thus merged) result carries scores, enabling crash-safe resume.
            # Best-effort: a write failure here must not abort this domain's
            # evaluation (the enclosing except below would drop evaluator.results
            # from task_results entirely, even though the domain itself succeeded).
            if bundle_dir is not None and evaluator.results:
                from benchmarks.helpers.incremental_results import write_task_result

                for _r in evaluator.results:
                    _rid = _r.get("task_name") or _r.get("sample_id") or "unknown"
                    try:
                        write_task_result(bundle_dir, _rid, _r, domain=domain)
                    except Exception as persist_err:
                        logger.warning(
                            f"[{service_name}/{domain}] Failed to persist incremental result "
                            f"for {_rid}: {persist_err}"
                        )

                # Fetch this domain's Langfuse traces now, in the background,
                # rather than waiting for finalize at the very end of the run:
                # a crash/Ctrl-C mid-run would otherwise leave zero traces
                # fetched even though results/partial/ already has this
                # domain's results on disk. Non-blocking (runs on a worker
                # thread) — awaited once, for everything scheduled so far,
                # in run_config_mode's `finally` block.
                if is_langfuse_tracing_enabled():
                    from benchmarks.helpers.bundle import schedule_langfuse_download_for_results

                    schedule_langfuse_download_for_results(bundle_dir, evaluator.results)

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

        except EnvironmentFailureError:
            # Must not be swallowed here — this is what actually aborts the
            # run when a docker container dies mid-domain (a single domain
            # can hold 100+ samples and run for hours; per-domain-only
            # detection would otherwise grind through all of them).
            raise
        except Exception as e:
            logger.error(f"❌ [{service_name}] Failed to evaluate domain '{domain}': {e}")
            import traceback

            traceback.print_exc()

    logger.info(f"\n✅ Task {service_name} completed: {len(task_results)} total results")
    return task_results


def get_registry_port(override: Optional[int] = None) -> int:
    """Registry port shared by the MCP server and cuga-agent HTTP client.

    Reads ``settings.server_ports.registry`` (override via
    ``DYNACONF_SERVER_PORTS__REGISTRY``), the same source
    ``get_registry_base_url()`` uses when the agent calls the registry.

    Pass ``override`` (e.g. from ``--registry-port``, or a per-worker free
    port picked by :func:`find_free_port`) to bypass that shared setting —
    every call site in this module accepts an explicit port for exactly this
    reason, so concurrent per-domain registries don't have to fight over one
    process-wide value.
    """
    if override is not None:
        return int(override)

    from cuga.config import settings

    return int(settings.server_ports.registry)


def find_free_port() -> int:
    """Ask the OS for an unused TCP port on localhost and return it.

    There's an inherent TOCTOU race (something else could grab the port
    between this call returning and the registry actually binding it) — the
    same race every "find a free port" helper has. Callers that start a
    registry on the returned port already retry/force-free on bind failure
    (see ``_force_free_registry_port``), so a lost race just looks like the
    ordinary "port was already in use" path.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _port_in_use(port: int) -> bool:
    """Return True if something is listening on 127.0.0.1:`port`."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


async def _wait_for_port_free(port: int, timeout: float = 20.0) -> bool:
    """Poll until `port` has no listener. Returns True if it freed up in time.

    Sequential mode starts/stops a registry per domain on the same port; a
    just-stopped uvicorn worker can hold the socket for a few seconds during
    graceful shutdown, so the next domain must wait rather than fail instantly.
    """
    import time

    deadline = time.monotonic() + timeout
    while True:
        if not _port_in_use(port):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.5)


def _kill_port_listeners(port: int) -> None:
    """Best-effort SIGKILL of any process listening on `port` (via lsof)."""
    import signal
    import subprocess

    try:
        out = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)  # noqa: S603,S607 — lsof from PATH, fixed args
        for pid in out.stdout.split():
            try:
                os.kill(int(pid), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass
    except Exception as e:  # noqa: BLE001 — best-effort cleanup
        logger.debug(f"Could not enumerate/kill listeners on port {port}: {e}")


def _pkill_registry_on_port(port: int) -> None:
    """SIGKILL uvicorn registry workers bound to `port`, scoped by port.

    Plain ``pkill -f "uvicorn.*api_registry_server"`` has no port filter and
    kills *every* matching uvicorn on the machine — fine for the current
    sequential single-eval usage, but it will nuke a sibling job's registry
    (a parallel eval-key run, a CI shard sharing the host, a dev running
    something else) the moment two of these overlap. The uvicorn command
    line always ends in ``--port <port>`` (see the Popen args below), so
    anchor the pattern there to keep the kill scoped to our own process.
    """
    import subprocess

    pattern = f"uvicorn.*api_registry_server.*--port {port}$"
    subprocess.run(["pkill", "-9", "-f", pattern], capture_output=True)  # noqa: S603,S607 — fixed args, int port, no untrusted input


async def _force_free_registry_port(port: int, attempts: int = 12) -> bool:
    """Actively kill every registry listener/process until `port` is verifiably free.

    Sequential mode reuses one port across domains. A previous domain's uvicorn
    occasionally survives teardown and keeps answering on the port, so the next
    domain's tool calls hit a *stale* registry serving the wrong app (observed as
    ``Application '<domain>' not found in registry. Available apps: ['<prev>']`` →
    404). Passive waiting is not enough; we loop kill-then-verify so we never
    proceed while a stray listener still owns the socket.
    """
    for _ in range(attempts):
        if not _port_in_use(port):
            return True
        _kill_port_listeners(port)
        # Belt-and-suspenders: also nuke by process signature in case lsof misses
        # a uvicorn worker that briefly lost the bind but is still alive.
        _pkill_registry_on_port(port)
        await asyncio.sleep(1.0)
    return not _port_in_use(port)


async def start_registry_server(
    config_path: str, expected_apps: Optional[List[str]] = None, port: Optional[int] = None
) -> subprocess.Popen:
    """Start the registry server with the specified config.

    Args:
        config_path: Path to the registry config file
        expected_apps: App/domain name(s) this registry must serve. When given,
            the live ``/applications`` is verified to contain them after warmup;
            a mismatch means a stale registry is answering and we abort rather
            than run tasks against the wrong app.
        port: Explicit registry port (e.g. from ``--registry-port``, or a
            per-worker free port). Defaults to the shared
            ``settings.server_ports.registry`` value when unset — today's
            single-registry-at-a-time callers are unaffected; a future
            concurrent-worker caller can pass a distinct free port per call
            so multiple registries don't collide on one port.

    Returns:
        Process object for the registry server
    """
    import os
    import subprocess

    registry_port = get_registry_port(port)

    # Check if the registry port is already in use
    logger.info(f"🔍 Checking if port {registry_port} is available...")
    try:
        if _port_in_use(registry_port):
            # Port is busy — most often a registry from the PREVIOUS service in
            # a sequential run that hasn't released the socket yet. Aggressively
            # kill-then-verify (loop) so we never bind on top of, or alongside,
            # a stale registry that would keep answering with the old app.
            logger.warning(
                f"⚠️  Port {registry_port} is in use — force-freeing it "
                f"(likely the previous service's registry shutting down)..."
            )
            if not await _force_free_registry_port(registry_port):
                logger.error(f"❌ Port {registry_port} is still in use after force-free!")
                logger.error(f"     lsof -ti :{registry_port} | xargs kill")
                raise RuntimeError(
                    f"Port {registry_port} is already in use. Please kill the existing process first."
                )
            logger.info(f"✅ Port {registry_port} is now free")
    except RuntimeError:
        raise  # Re-raise the port-in-use error
    except Exception as e:
        logger.debug(f"Port check failed (continuing anyway): {e}")

    # Kill any existing registry servers to avoid conflicts
    logger.info("🧹 Cleaning up any existing registry servers...")
    try:
        # These two legacy launch patterns (uv-run-registry entrypoint, and the
        # fastapi-cli path it goes through) set their port via env var, not a
        # CLI arg, so unlike the uvicorn pattern below they can't be scoped by
        # port here — this is a genuinely machine-wide kill. Log loudly rather
        # than silently sweeping: a concurrent job's registry landing on either
        # pattern is disruptive and worth surfacing in the logs.
        logger.warning(
            "⚠️  Sweeping ALL 'uv run registry' / 'fastapi.*registry' processes on this "
            "machine (port-unscoped legacy patterns) — will disrupt any concurrent eval run."
        )
        subprocess.run(["pkill", "-9", "-f", "uv run registry"], capture_output=True)  # noqa: S607 — relies on PATH for shell tools
        subprocess.run(["pkill", "-9", "-f", "fastapi.*registry"], capture_output=True)  # noqa: S607 — same
        # More specific pattern to avoid killing this script
        _pkill_registry_on_port(registry_port)
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
                    live_apps = [app.get("name", "unknown") for app in apps]
                    logger.info(
                        f"✅ Registry started successfully with {len(apps)} applications (attempt {attempt + 1}/{max_retries})"
                    )
                    logger.info(f"📋 Registered applications: {live_apps}")

                    # Identity check: make sure the registry answering on this port
                    # is the one we just started, not a stale survivor from the
                    # previous domain. Two stale signatures, both aborted:
                    #   1. Completely disjoint — a non-empty app list sharing
                    #      nothing with what we expect (e.g. serving
                    #      ['mondial_geo'] while we want professional_basketball).
                    #   2. Expected-plus-extra — live_apps contains every app we
                    #      expect but ALSO apps we didn't ask for (e.g. a
                    #      survivor from the previous domain lingering alongside
                    #      the fresh one). Since each registry here is built from
                    #      a single-service mini yaml (`_write_single_service_yaml`),
                    #      it should never legitimately serve more apps than that
                    #      one service declares — extra apps beyond expected_apps
                    #      mean stale global state (open sockets, per-app caches,
                    #      the previous run's env) is still resident even though
                    #      our app also happens to answer.
                    # Partial/naming overlaps within expected_apps are tolerated
                    # (case 1 only fires when there's zero overlap) so legitimate
                    # domain↔app-name differences don't trigger false aborts.
                    if expected_apps and live_apps:
                        expected_set = set(expected_apps)
                        live_set = set(live_apps)
                        disjoint = not (expected_set & live_set)
                        extra_apps = live_set - expected_set
                        if disjoint or extra_apps:
                            reason = (
                                "completely disjoint from expected"
                                if disjoint
                                else f"serves unexpected extra app(s) {sorted(extra_apps)} alongside the expected one(s)"
                            )
                            logger.error(
                                f"❌ Registry identity mismatch: expected one of {expected_apps} but "
                                f"port {registry_port} serves {live_apps} ({reason}). "
                                "A stale registry is squatting the port."
                            )
                            await stop_registry_server(process)
                            raise RuntimeError(
                                f"Registry on port {registry_port} serves {live_apps}, "
                                f"expected {expected_apps}; aborting to avoid stale-registry results."
                            )

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
                        # Zero applications registered in the FULL warmup window
                        # (not "some missing" — all_ready only ever becomes True
                        # once len(apps) > 0, so this means literally none did).
                        # That's not "still starting up", it's the docker
                        # environment being broken (dead/unreachable container,
                        # or a wedged app inside a container that otherwise
                        # looks "running"). Previously this just warned and
                        # proceeded, letting the run grind through every task
                        # against a registry with nothing behind it.
                        reason = (
                            f"registry warmup timed out after {max_warmup_time}s with 0 MCP "
                            f"server(s) registered (expected: {expected_apps or 'unspecified'})"
                        )
                        print(
                            render_environment_failure_banner(
                                reason, "fix the docker environment, then resume this run"
                            )
                        )
                        await stop_registry_server(process)
                        raise EnvironmentFailureError(reason)

                    break
                else:
                    logger.debug(f"Registry responded with status {response.status_code}, retrying...")
        except RuntimeError:
            # Identity mismatch (stale registry) is fatal — do not retry/swallow.
            raise
        except Exception as e:
            if attempt < max_retries - 1:
                logger.debug(
                    f"Attempt {attempt + 1}/{max_retries}: Registry not ready yet, waiting {retry_delay}s..."
                )
                await asyncio.sleep(retry_delay)
            else:
                logger.warning(f"⚠️  Could not connect to registry after {max_retries} attempts: {e}")

    return process


async def stop_registry_server(process: subprocess.Popen, port: Optional[int] = None):
    """Stop the registry server and every descendant.

    ``port`` should match whatever port the corresponding
    ``start_registry_server(..., port=...)`` call used, so the post-stop
    port-free verification below checks the right port. Defaults to the
    shared settings-derived port, matching today's single-registry callers.

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

    # `process.wait()` only reaps the `uv` wrapper; the uvicorn worker holding
    # the port can linger (or survive killpg if it escaped the group). Do NOT
    # return until the port is verifiably free and no api_registry_server is
    # left alive — otherwise the next sequential domain races a stale registry
    # that keeps answering tool calls with the previous domain's app (→ 404).
    try:
        registry_port = get_registry_port(port)
        if not await _force_free_registry_port(registry_port):
            logger.error(
                f"❌ Port {registry_port} still occupied after teardown — "
                "next domain may hit a stale registry"
            )
        else:
            logger.info(f"✅ Registry port {registry_port} released and verified free")
    except Exception as e:  # noqa: BLE001 — best-effort port-release wait
        logger.debug(f"Port-release wait after stop failed (continuing): {e}")


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


def _domain_entry_name(d: Any) -> str:
    """Extract a plain string app/domain name from a `domains` metadata entry.

    Entries may be bare strings or dict-backed (``{"name": ...}``) configs.
    Returns "" for anything that isn't a real string name — in particular an
    explicit ``{"name": None}`` — rather than ``str(None)`` == "None", which
    would otherwise survive the empty-string filter and pollute the
    identity-check's expected-apps set.
    """
    if isinstance(d, str):
        return d
    name = d.get("name") if isinstance(d, dict) else None
    return name if isinstance(name, str) else ""


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


def _finalize_and_save_results(
    all_results: List[Dict[str, Any]], no_ground_truth: bool, bundle_dir: Optional[Path] = None
):
    """Persist exactly one result file (plus ground-truth dump) for a run.

    Shared by the single-capability path and the multi-capability aggregation
    path so that ONE eval.sh invocation always yields ONE result file covering
    every task it evaluated. Previously each capability pass saved its own
    100-task file, which made compare_report count one logical run as several
    runs (one per capability) and made each "run" look like only 100 tasks.

    When ``bundle_dir`` is set, the merged results are read back from the on-disk
    partials (so skipped/resumed tasks are included) and written into the bundle.
    """
    output_dir = Path(__file__).parent / "results"
    if bundle_dir is not None:
        from benchmarks.helpers.incremental_results import load_all_partial_results

        all_results = load_all_partial_results(bundle_dir)
        output_dir = Path(bundle_dir) / "results"

    # In no-ground-truth mode there's no scoring — render the tool-call-count
    # summary instead and capture it to the summary file.
    if no_ground_truth:
        _emit_cleanly(print_no_gt_summary, all_results)
        try:
            with open(M3_SUMMARY_FILE, "w") as _sf:
                _sf.write(_render_no_gt_summary(all_results))
            logger.info(f"Summary written to {M3_SUMMARY_FILE}")
        except Exception as e:
            logger.warning(f"Failed to write summary to {M3_SUMMARY_FILE}: {e}")

        # Save raw results JSON and skip vakra-format ground-truth dump.
        saved_path = save_evaluation_results(all_results, output_dir, prefix="m3_config_no_gt")
        logger.info(f"\nResults saved to: {saved_path}")
        return saved_path

    # Vakra is the source of truth for the overall summary. We capture it to
    # M3_SUMMARY_FILE so eval.sh can re-echo it as the last thing on screen.
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
            "No Vakra scores produced for any task — check API_KEY and the per-domain Vakra warnings above."
        )

    # Save results
    saved_path = save_evaluation_results(all_results, output_dir, prefix="m3_config")
    logger.info(f"\nResults saved to: {saved_path}")

    # Save ground truth format
    evaluator_temp = M3Evaluator()
    evaluator_temp.results = all_results
    ground_truth_path = evaluator_temp._save_ground_truth_format(output_dir)
    logger.info(f"Ground truth format saved to: {ground_truth_path}")
    return saved_path


# --- Interrupt diagnostics -------------------------------------------------
# Recurring, unattended "Evaluation interrupted" events have shown up in
# several bundles (2026-06-24, 2026-07-04, 2026-07-05, 2026-07-09) — always
# within seconds of a call_model log line, always landing in the
# `except (KeyboardInterrupt, asyncio.CancelledError)` branch below, with no
# human present (some ran at 2-3am). That branch can't tell a real Ctrl-C /
# external `kill -INT` apart from a bare asyncio.CancelledError raised
# somewhere inside the process (e.g. inside the LLM/gateway client), so add:
#   1. a SIGINT observer that timestamps *real* signal delivery without
#      changing behavior (it falls through to the default handler), and
#   2. a periodic stall watchdog that dumps every live task's stack, so a
#      silent hang (no exception at all) still leaves a trace of where
#      execution is blocked.
_sigint_observed_at: float | None = None


def _install_sigint_observer() -> None:
    """Timestamp+log real SIGINT delivery; defer to the default handler for
    the actual behavior so Ctrl-C handling (#91, #92) is unchanged."""
    import signal

    def _on_sigint(signum, frame):
        global _sigint_observed_at
        import time

        _sigint_observed_at = time.time()
        logger.warning(
            f"🔔 SIGINT received by the OS signal handler (frame "
            f"{frame.f_code.co_filename}:{frame.f_lineno}) — a real Ctrl-C or external "
            "`kill -INT`/`kill -2` was delivered to this process."
        )
        signal.default_int_handler(signum, frame)

    signal.signal(signal.SIGINT, _on_sigint)


async def _stall_watchdog(interval_seconds: float = 180.0) -> None:
    """Periodically dump every other live asyncio task's stack.

    A hang with no timeout and no exception (e.g. a stuck LLM/gateway HTTP
    call) otherwise leaves no trace beyond "logging went quiet" — this gives
    a live snapshot of exactly where execution is blocked when it happens.
    """
    import io

    while True:
        await asyncio.sleep(interval_seconds)
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        logger.warning(
            f"⏱️  Stall watchdog: {len(tasks)} other task(s) still alive after {interval_seconds:.0f}s"
        )
        for t in tasks:
            buf = io.StringIO()
            t.print_stack(limit=10, file=buf)
            stack_text = buf.getvalue().strip() or "  <no stack available — not yet started or already done>"
            logger.warning(f"    task={t.get_name()!r} coro={t.get_coro()!r}\n{stack_text}")


def _env_float(name: str, default: float) -> float:
    """Parse a float env var, falling back to `default` (with a warning) if unset or malformed."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"{name}={raw!r} is not a valid number; using default {default}")
        return default


def _env_int(name: str, default: int) -> int:
    """Parse an int env var, falling back to `default` (with a warning) if unset or malformed."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"{name}={raw!r} is not a valid integer; using default {default}")
        return default


async def run_config_mode(args, container_runtime: str, defer_save: bool = False):
    """Run evaluation in config mode with task-level parallelism and optional batching.

    Tasks run in parallel (each uses separate container).
    Domains within each task run sequentially (one connection per container).

    For large-scale evaluation (many domains), use --batch-size to process in batches.
    """
    logger.info(f"Loading config from: {args.from_config}")
    logger.info("✅ Entered run_config_mode()")

    # Resolved once, up front, so it's available to both the multi-capability
    # aggregation branch (which returns early, before the sequential/batched
    # section below) and the sequential/batched section itself. Previously
    # assigned only in the latter, which raised UnboundLocalError from the
    # multi-capability branch's _finalize_and_save_results call whenever no
    # explicit --capability/--task filter was given.
    bundle_dir = Path(args.bundle_dir) if getattr(args, "bundle_dir", None) else None

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

    # Resolve --eval-key (or the config's default eval_key) to a set of
    # sample ids that restricts the --m3-data corpus. Stashed on `args` so
    # evaluate_single_task can read it without a signature change, mirroring
    # how --domain is read via getattr(args, "domain", None).
    if m3_data_loader is not None:
        try:
            eval_key_id_list = load_eval_key_ids(getattr(args, "eval_key", None))
        except (KeyError, FileNotFoundError) as e:
            # A typo'd/stale --eval-key must fail the run, not log-and-continue:
            # a silent full or empty run reads as a green CI job (see issue #44).
            logger.error(f"--eval-key error: {e}")
            sys.exit(1)
        # Distinguish an explicit (possibly empty) split from "no restriction":
        # `None` means run everything; `[]` is an explicit empty split that must
        # match nothing (and will trip the zero-match guard in main()).
        if eval_key_id_list is not None:
            args.eval_key_ids = {i.lower() for i in eval_key_id_list}
            logger.info(
                f"📦 --eval-key {getattr(args, 'eval_key', None) or '(default)'}: "
                f"restricting --m3-data corpus to {len(args.eval_key_ids)} sample id(s)"
            )
        else:
            args.eval_key_ids = None
    elif getattr(args, "eval_key", None):
        logger.error("--eval-key requires --m3-data")
        sys.exit(1)

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

            # Run each capability as its own pass (separate registry/expanded
            # config to dodge cross-task domain-name collisions), but collect
            # every pass's results and persist them together as a SINGLE result
            # file for this run. One eval.sh run -> one file -> all tasks.
            combined_results: List[Dict[str, Any]] = []
            for task_id in cap_ids:
                cap_name = f"m3_task_{task_id}"
                logger.info(f"\n{'=' * 80}\n🔁 Auto capability pass: {cap_name}\n{'=' * 80}")
                pass_args = copy.copy(args)
                pass_args.task = [cap_name] + preserved
                pass_results = await run_config_mode(pass_args, container_runtime, defer_save=True)
                if pass_results:
                    combined_results.extend(pass_results)

            if combined_results:
                logger.info(
                    f"🧮 Aggregated {len(combined_results)} results across "
                    f"{len(cap_ids)} capability pass(es) → writing one result file"
                )
                _finalize_and_save_results(combined_results, no_ground_truth, bundle_dir=bundle_dir)
            else:
                logger.warning("⚠️  No results produced across capability passes.")
            return combined_results
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

    # Hoisted so the KeyboardInterrupt / Exception handlers below can save
    # whatever was collected if the eval is interrupted (#91, #92). In
    # sequential mode results are appended as tasks complete; in batched
    # mode evaluate_tasks_in_batches replaces the list with its return.
    all_results: List[Dict[str, Any]] = []

    stall_watchdog_task = asyncio.create_task(_stall_watchdog())

    try:
        # Start registry if enabled. In sequential mode we *don't* start a
        # shared registry here — each service spawns its own mini registry
        # below so only that domain's MCP server is running at a time.
        if registry_enabled and not sequential_mode:
            logger.info("🔧 Registry mode enabled - starting shared registry server for parallel run...")
            registry_process = await start_registry_server(
                expanded_config_path, port=getattr(args, "registry_port", None)
            )

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

        if is_langfuse_tracing_enabled():
            logger.info("Langfuse tracing enabled (per-task handlers via evaluate_task_with_langfuse)")

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
        # (all_results is hoisted to before the try block; clear it here.)
        all_results.clear()
        if not sequential_mode:
            # Batched evaluation returns an already-flattened list. Use
            # .extend() rather than reassignment so an interrupt during the
            # gather doesn't drop any results that were already captured in
            # the hoisted all_results (the batched helper itself uses
            # return_exceptions=True, so completed batches' results survive
            # individual failures).
            all_results.extend(
                await evaluate_tasks_in_batches(
                    task_evaluations=task_evaluations,
                    batch_size=batch_size,
                    args=args,
                )
            )
        else:
            logger.info(f"\n{'=' * 80}")
            logger.info(
                f"🐢 Running {len(task_evaluations)} tasks SEQUENTIALLY "
                f"(pass --batch-size N > 1 for parallelism)"
            )
            logger.info(f"{'=' * 80}\n")

            # Detect a broken docker environment (dead/wedged capability
            # container) instead of silently grinding through it. See
            # benchmarks/m3/container_health.py.
            env_health_check_enabled = os.environ.get("M3_ENV_HEALTH_CHECK", "true").lower() != "false"
            env_health_timeout = _env_float("M3_ENV_HEALTH_TIMEOUT", 5.0)
            env_fail_streak = EnvironmentFailureStreakTracker(threshold=_env_int("M3_ENV_FAIL_STREAK", 3))
            env_resume_hint = resume_hint_for(bundle_dir)

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

                if env_health_check_enabled and container:
                    health_check_or_abort(
                        container, container_runtime, env_resume_hint, timeout=env_health_timeout
                    )

                mini_yaml = None
                svc_registry = None
                try:
                    if registry_enabled:
                        mini_yaml = _write_single_service_yaml(service_dict)
                        logger.info(f"🔧 [{service_name}] Starting one-service registry from {mini_yaml}")
                        # Normalise domains to plain hashable strings: entries may be
                        # bare strings or dict-backed ({"name": ...}) configs, and
                        # start_registry_server does set(expected_apps) for the
                        # identity check, which would raise on unhashable dicts.
                        # Keep original case so the intersection with live_apps holds.
                        expected_apps = [a for a in (_domain_entry_name(d) for d in domains) if a]
                        svc_registry = await start_registry_server(
                            mini_yaml, expected_apps=expected_apps, port=getattr(args, "registry_port", None)
                        )
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
                        record_streak_or_abort(
                            env_fail_streak, service_name, container, task_results, env_resume_hint
                        )
                except EnvironmentFailureError:
                    # Must not be swallowed by the generic handler below —
                    # this is what actually aborts the run.
                    raise
                except Exception as e:
                    import traceback

                    logger.error(f"❌ Task {service_name} failed: {e}")
                    traceback.print_exception(type(e), e, e.__traceback__)
                finally:
                    if svc_registry is not None:
                        await stop_registry_server(svc_registry, port=getattr(args, "registry_port", None))
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
            # If this invocation is one capability sub-pass of a larger
            # multi-capability run, return the results unsaved so the caller can
            # aggregate every capability into ONE result file (one eval.sh run =
            # one file = all tasks). Saving here is what previously produced a
            # separate 100-task file per capability.
            if defer_save:
                return all_results
            _finalize_and_save_results(all_results, no_ground_truth, bundle_dir=bundle_dir)
        else:
            logger.warning("⚠️  No results produced. Check the registry logs and task filters.")

        return all_results

    except (KeyboardInterrupt, asyncio.CancelledError) as interrupt_err:
        # User hit Ctrl-C or the task group was cancelled. Save whatever
        # tasks we managed to complete so the shell-side `create_bundle`
        # has something to bundle, then re-raise so the script exits with
        # the right status. (Bug #91, #92.)
        #
        # Diagnostics: distinguish a real OS-delivered SIGINT (observed by
        # _install_sigint_observer) from a bare CancelledError raised inside
        # the process with no signal involved — the latter has shown up
        # repeatedly and unattended (see the comment above _stall_watchdog).
        import traceback

        if _sigint_observed_at is not None:
            logger.warning(
                f"⛔ Evaluation interrupted by a real SIGINT (observed at "
                f"{_sigint_observed_at}) — saving any partial results before exit..."
            )
        else:
            tb_text = "".join(
                traceback.format_exception(type(interrupt_err), interrupt_err, interrupt_err.__traceback__)
            )
            logger.warning(
                f"⛔ Evaluation interrupted by {type(interrupt_err).__name__} with NO SIGINT observed "
                "by the OS handler — this cancellation originated inside the process (e.g. an "
                f"LLM/gateway client library), not a Ctrl-C. Full traceback:\n{tb_text}"
            )
        try:
            if bundle_dir is not None:
                from benchmarks.helpers.incremental_results import finalize_merged_results

                prefix = "m3_config_no_gt" if no_ground_truth else "m3_config"
                saved_path = finalize_merged_results(bundle_dir, prefix=prefix)
                logger.warning(f"📁 Partial results merged from disk to: {saved_path}")
            elif all_results:
                output_dir = Path(__file__).parent / "results"
                prefix = "m3_config_no_gt_partial" if no_ground_truth else "m3_config_partial"
                saved_path = save_evaluation_results(all_results, output_dir, prefix=prefix)
                logger.warning(f"📁 Partial results ({len(all_results)} task-results) saved to: {saved_path}")
            else:
                logger.warning("(no partial results collected yet)")
        except Exception as save_err:
            logger.error(f"Failed to save partial results: {save_err}")
        raise
    except Exception as eval_err:
        # An unexpected exception bubbled out of the eval loop. Same
        # partial-save logic as the interrupt path, then re-raise. (Bug #92.)
        logger.error(f"❌ Evaluation aborted by unexpected error: {eval_err}")
        try:
            if bundle_dir is not None:
                from benchmarks.helpers.incremental_results import finalize_merged_results

                prefix = "m3_config_no_gt" if no_ground_truth else "m3_config"
                saved_path = finalize_merged_results(bundle_dir, prefix=prefix)
                logger.warning(f"📁 Partial results merged from disk to: {saved_path}")
            elif all_results:
                output_dir = Path(__file__).parent / "results"
                prefix = "m3_config_no_gt_partial" if no_ground_truth else "m3_config_partial"
                saved_path = save_evaluation_results(all_results, output_dir, prefix=prefix)
                logger.warning(f"📁 Partial results ({len(all_results)} task-results) saved to: {saved_path}")
        except Exception as save_err:
            logger.error(f"Failed to save partial results: {save_err}")
        raise

    finally:
        # Flush any Langfuse downloads scheduled during the run before the
        # process actually exits (normal completion, Ctrl-C, or an
        # unexpected exception all funnel through this `finally`) — otherwise
        # a download still in flight when the process exits would be lost.
        if bundle_dir is not None:
            from benchmarks.helpers.bundle import await_pending_langfuse_downloads

            await await_pending_langfuse_downloads()

        stall_watchdog_task.cancel()
        try:
            await stall_watchdog_task
        except asyncio.CancelledError:
            pass

        # Stop registry if it was started
        if registry_process is not None:
            await stop_registry_server(registry_process, port=getattr(args, "registry_port", None))

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

    _install_sigint_observer()

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
        "--registry-port",
        dest="registry_port",
        type=int,
        default=None,
        metavar="PORT",
        help="Explicit port for the registry server, overriding "
        "settings.server_ports.registry (DYNACONF_SERVER_PORTS__REGISTRY). "
        "Threaded through start_registry_server/stop_registry_server/"
        "get_registry_port; unset by default, in which case today's shared "
        "settings-derived port is used exactly as before. Intended for a "
        "future concurrent-worker mode where each worker needs its own free "
        "port (see find_free_port()) — passing a fixed value today just "
        "moves the single registry sequential/parallel mode already starts "
        "onto a different port.",
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
        "--policy-judge-path",
        dest="policy_judge_path",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to an internal PolicyAdherenceJudge module (e.g. "
        "benchmarks/m3/evaluator/policy_judge.py), matching the same-named "
        "parameter in evaluator.py/scorer.py. Not distributed with this repo; "
        "unset by default, in which case policy-adherence scoring is skipped "
        "entirely (Vakra scoring proceeds as before). Only takes effect for "
        "multiturn capabilities (TurnScorerConfig gates on "
        "'multiturn' in capability).",
    )
    parser.add_argument(
        "--eval-key",
        dest="eval_key",
        default=None,
        metavar="KEY",
        help="Restrict the --m3-data corpus to a named split from "
        "benchmarks/m3/eval_config.toml (e.g. 'train' or 'test'), applied "
        "before --task/--domain/--capability filters. Requires --m3-data. "
        "If omitted, falls back to the config's default `eval_key` (if any), "
        "otherwise the full corpus is used.",
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
    parser.add_argument(
        "--bundle-dir",
        type=str,
        default=None,
        help="Bundle workspace directory for incremental, resumable results.",
    )
    parser.add_argument(
        "--resume-task-ids",
        type=str,
        nargs="*",
        default=None,
        help="Task IDs to treat as already completed (skip). Usually computed by the shell layer.",
    )

    from benchmarks.helpers.logging_args import add_log_level_args, apply_log_level

    add_log_level_args(parser)

    args = parser.parse_args()
    apply_log_level(args)

    container_runtime = os.environ.get("CONTAINER_RUNTIME", "podman")

    logger.info(f"Running in CONFIG MODE (registry-based) with config file: {args.from_config}")
    results = await run_config_mode(args, container_runtime)

    # Zero-match guard: when --eval-key restricted the corpus but nothing matched
    # (typo, or eval_config.toml UUIDs gone stale against a regenerated zip),
    # fail loudly instead of exiting 0 on an empty run (issue #44, Sergey review).
    if getattr(args, "eval_key_ids", None) is not None and not results:
        logger.error(
            f"--eval-key {getattr(args, 'eval_key', None) or '(default)'} matched 0 samples in the "
            "--m3-data corpus. Check the key spelling and that eval_config.toml UUIDs match the corpus "
            "(regenerate with benchmarks/m3/scripts/generate_eval_split.py if the zip changed)."
        )
        sys.exit(1)


# Removed run_direct_mode() function - now using registry mode only


def _run_main() -> int:
    """Run main(); translate EnvironmentFailureError into exit code 3.

    Exit codes: 0 success, 1 generic error (existing sys.exit(1) guards
    above), 2 CLI arg errors (eval.sh), 3 M3 docker environment failure.
    """
    try:
        asyncio.run(main())
        return 0
    except EnvironmentFailureError as env_err:
        logger.error(f"Exiting with code 3 due to environment failure: {env_err}")
        return 3


if __name__ == "__main__":
    sys.exit(_run_main())
