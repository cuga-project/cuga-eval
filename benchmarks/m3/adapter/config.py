"""Typed configuration for the M3 (VAKRA) CUGA adapter.

The adapter layers benchmark-validated behaviors on an UNMODIFIED CugaAgent
("configured CUGA, never bare main"): instruction blocks, deterministic answer
post-processing, evidence-based answer guards, tool recording/scoping, and
shortlisting — all through public SDK surfaces (``special_instructions``,
``final_answer``, ``shortlister``, ``mcp_few_shot_examples``, a tool provider).

Every field maps 1:1 to a flag from the validated VAKRA submission runs
(vakra-main ``cuga_runs/fc_canon_test.sh`` for capabilities 1-3 and
``cap4 V3WX`` for capability 4). Presets bundle them per capability; any field
can be overridden with an ``M3_ADAPTER_<FIELD>`` env var. The ``off`` preset
(the default) disables everything — the eval then constructs a plain CugaAgent
exactly as it does today.

This module deliberately imports nothing from ``cuga`` so config parsing and
its tests run without a configured CUGA environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace
from typing import Mapping, Optional

_TRUE = frozenset({"1", "on", "true", "yes"})
_FALSE = frozenset({"0", "off", "false", "no"})

#: cap1's generic data tools: every train ground-truth chain is built from them (plus at most a
#: domain-specific get_* tool). Pinned at bind time when a universe re-lists more than 128 tools.
CAP1_DATA_TOOLS_PATTERN = (
    r"initialize_active_data|get_data|filter_data|retrieve_data|aggregate_data|truncate|Calculator"
    r"|select_unique_values|select_data_\w+|compute_data_\w+|sort_data(?:_\w+)?|transform_data(?:_\w+)?"
)

#: The exact embedding model the validated VAKRA runs shortlisted with.
MINILM_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

ENV_PREFIX = "M3_ADAPTER_"

EXECUTION_MODES = ("codeact", "function_calling")
STEP_DISCIPLINES = ("off", "one_tool_per_step")  # cuga-agent#777 model_runtime_profile.py

#: Configurable keys that switch CugaLite to native function calling (cuga-agent#777:
#: ``cuga_lite_execution_mode`` resolved in model_runtime_profile.py, the bind mode in
#: graph_adapter._resolved_bind_mode). Verified on that branch before it merged —
#: re-check once it lands (tests/test_adapter_cuga_integration.py does, when the
#: checkout has native FC). The provider-safe bind cap is NOT configurable-driven: it is
#: the settings key below (bind_tools/cap.py). Leave it at its default (128): above it the
#: bind-time shortlister — which reads the adapter's ``Shortlister`` (MiniLM) at the
#: ``bind_cap`` seam — reduces a large domain to the top 128, which is what the validated
#: runs bound. The factory warns when the cap is disabled (0) or raised.
FUNCTION_CALLING_CONFIGURABLE: Mapping[str, object] = {
    "cuga_lite_execution_mode": "function_calling",
    "cuga_lite_bind_tools_mode": "all",
}
BIND_CAP_SETTING = "cuga_lite_bind_tools_max_count"  # settings.advanced_features.<this>, default 128
BIND_CAP_ENV = "DYNACONF_ADVANCED_FEATURES__CUGA_LITE_BIND_TOOLS_MAX_COUNT"
CAMPAIGN_BIND_CAP = 128  # the validated runs bound at most this many MiniLM-ranked tools per call

#: CUGA settings the campaign ran with that differ from what ``benchmarks/m3/config/m3.env`` sets
#: for every m3 run. The campaign's CUGA (main @cc8f9197 + private FC code) used its settings.toml
#: defaults for these; m3.env flips them on. ``force_autonomous_mode`` adds an autonomy line to the
#: FC and CodeAct prompts; the other two only act on CodeAct turns. Pinned in-process at agent
#: build time by the presets that reproduce the campaign runtime (see ``cuga_settings``).
CAMPAIGN_CUGA_SETTINGS = (
    "advanced_features.force_autonomous_mode=false,"
    "advanced_features.reflection_enabled=false,"
    "advanced_features.cuga_lite_nl_auto_continue=false"
)
#: cap4 ran CodeAct, where CUGA's own sandbox timeout (settings default 30 s; m3.env: 90) applied.
CAMPAIGN_CODEACT_SETTINGS = CAMPAIGN_CUGA_SETTINGS + ",advanced_features.sandbox_execution_timeout=30"
CAMPAIGN_MAX_STEPS = 70  # cuga_lite_max_steps default; VAKRA_CUGA_MAX_STEPS=40 was never read by cuga_v2
CAMPAIGN_LLM_TIMEOUT = 150  # LITELLM_REQUEST_TIMEOUT_SECONDS in cap_estimate.sh / fc_canon(_proto)_test.sh
CAMPAIGN_AGENT_TIMEOUT = 220  # AGENT_TIMEOUT_SECONDS: per-item wall clock in the same scripts
CAP4_LLM_TIMEOUT = 600  # cap4_test.sh sets none: LiteLLM's default request timeout
CAP4_AGENT_TIMEOUT = 300  # cap4_test.sh sets none: benchmark_runner.py's AGENT_TIMEOUT_SECONDS default
CAMPAIGN_RUNAWAY_TOOL_CAP = 100  # cuga_clean_agent.py RUNAWAY_TOOL_CAP default (VAKRA_CUGA_TOOL_CAP unset)
CAMPAIGN_TEMPERATURE = 1.0  # --temperature 1.0 on every run; the passed model drove every CUGA call
#: The model blocks CUGA reads sampling settings from (configurations/models/settings.*.toml).
MODEL_ROLES = ("planner", "chat", "final_answer", "code", "qa", "action")
SHORTLIST_STRATEGIES = ("sdk", "campaign")
FACT_CHECK_MODES = ("off", "verify", "verify_and_retry")
TOOL_PICK_FILLS = ("cosine", "llm")


@dataclass(frozen=True)
class AdapterConfig:
    """One switch per validated VAKRA behavior (see module docstring).

    Comments name the originating VAKRA flag for provenance/auditability.
    """

    preset: str = "off"
    enabled: bool = False
    capability: Optional[int] = None  # 1..4; filled from the m3 task id at the call site

    # --- capabilities 1-3 ("fc_canon" config, minus function-calling) ---
    gates: bool = False  # VAKRA_CUGA_GATES (+GATES_CAPS=<cap> per run)
    max_gate_rounds: int = 2  # ReAct MAX_GATE_ROUNDS
    answer_contract: bool = False  # VAKRA_CUGA_CONTRACT
    normalize: bool = False  # VAKRA_CUGA_NORMALIZE
    bluff_map: bool = False  # VAKRA_CUGA_BLUFF_MAP
    canonicalize: bool = False  # DYNACONF_ADVANCED_FEATURES__FINAL_ANSWER_CANONICALIZE (re-implemented)
    demos: bool = False  # VAKRA_CUGA_DEMOS (prose mode)
    demos_k: int = 2  # VAKRA_DEMOS_K
    cap1_protocol: bool = False  # VAKRA_CUGA_CAP1_PROTOCOL (handle/data_label instructions)
    relist_after_switch: bool = False  # VAKRA_RELIST_AFTER_SWITCH (cap1 runner option)
    cap2_verbatim: bool = False  # VAKRA_CUGA_CAP2_VERBATIM (rule + value extraction)

    # --- capability 4 ("V3WX" config) ---
    discipline: bool = False  # VAKRA_V2_DISCIPLINE
    scope: bool = False  # VAKRA_V2_SCOPE (deterministic policy tool scoping)
    verbatim_on_retriever_scope: bool = False  # VAKRA_V2_VERBATIM
    evidence_gate: bool = False  # VAKRA_V2_EVIDENCE_GATE
    support_check: bool = False  # VAKRA_V2_SUPPORT_CHECK
    self_verify: bool = False  # VAKRA_V2_SELF_VERIFY
    refusal_norm: bool = False  # VAKRA_CUGA_REFUSAL_NORM
    tool_cap: Optional[int] = None  # VAKRA_CUGA_TOOL_CAP (16 in V3WX; None = uncapped)

    # --- shortlisting (SDK Shortlister; exact VAKRA model) ---
    shortlist_top_k: Optional[int] = None  # --top-k-tools (128 caps 1-3, 40 cap4)
    shortlist_model: str = MINILM_MODEL
    shortlist_pin_retrievers: bool = False  # "sdk" strategy: pin query_* tools (the campaign always did)
    # Tool names (regex, full match) kept in the bind-time shortlist ahead of the ranked rest ("" = none).
    # Only acts when the catalog exceeds the bind cap (128): a cap1 test domain re-listing 151-436 tools
    # otherwise loses the generic data tools every chain needs (see CAP1_DATA_TOOLS_PATTERN).
    shortlist_pin_pattern: str = ""
    # cap1: call retrieve_data / aggregate_data / compute_data_* with distinct=False. The train ground
    # truth keeps duplicates in ~94% of those calls; our agent deduplicated in 42% of retrieve_data calls.
    force_distinct_false: bool = False
    # cap1: tell the agent that filter/sort/retrieve results are handles with a 3-value preview, and that
    # a column's full values come from its get_<Table>_<Column> tool (list questions passed 2/22 on train).
    cap1_getter_rule: bool = False
    # Answer composer: one LLM pass after CUGA answers, over the question + every tool result (full, up to
    # composer_result_chars each; skipped when one is longer) that writes the answer in the benchmark's form.
    # Kept only when every value it states appears in the tool results or the question.
    answer_composer: bool = False
    composer_result_chars: int = 30000
    # The composer leaves a refusal draft alone (cap4 has policy / unanswerable tasks whose gold answer is the
    # refusal; the composer would answer them from whatever the tools returned).
    composer_keep_refusals: bool = False
    # "sdk": CUGA's embedding strategy (embeds name + description + params + returns);
    # "campaign": vakra-main ToolShortlister as an SDK strategy ("name: description", query_* pinned)
    shortlist_strategy: str = "sdk"

    # --- harness behavior ---
    use_policy_system: bool = True  # False => the eval clears the policy DB and loads nothing

    # --- demos source (never the split under evaluation; see demos.load_demo_corpus) ---
    demo_data: Optional[str] = None  # M3_ADAPTER_DEMO_DATA / --demo-data; None = bundled data/small_train.zip

    # --- execution mode (VAKRA_CUGA_FC; caps 1-3 presets use FC, cap4/V3WX is CodeAct) ---
    execution_mode: str = "codeact"  # "codeact" | "function_calling" (native FC: cuga-agent#777)

    # --- campaign runtime (what the campaign's own CUGA ran with, beyond the VAKRA_* flags) ---
    # Its private FC code hard-coded a system preamble (cuga-agent-main graph_adapter.py
    # _FC_SYSTEM_PREAMBLE). cuga-agent#777 ships the same text, with two lines behind opt-in
    # knobs and the answer-format line dropped; these fields restore all three.
    fc_step_discipline: str = "off"  # configurable cuga_lite_step_discipline ("one_tool_per_step")
    fc_prompt_fragments: str = ""  # configurable cuga_lite_fc_prompt_fragments, comma-separated
    fc_answer_format: bool = False  # the preamble's answer-format line (no #777 knob; adapter text)
    harness_instructions: bool = True  # False => the eval's own special_instructions are not passed
    expose_all_tools: bool = False  # no find_tools wall (campaign: shortlisting_tool_threshold = count+1)
    max_steps: Optional[int] = None  # configurable cuga_lite_max_steps (campaign: 70)
    llm_http_timeout: Optional[int] = None  # settings connections.llm_http_timeout, seconds (campaign: 150)
    agent_timeout: Optional[int] = None  # per-task wall clock, seconds (campaign AGENT_TIMEOUT_SECONDS: 220)
    demo_bound_names: bool = False  # demo chains name tools as bound (registry: <domain>_<tool>)
    bare_tool_names: bool = False  # bind registry tools under their bare MCP names (no <domain>_ prefix)
    model_temperature: Optional[float] = None  # pinned on every CUGA model block (campaign: 1.0)
    cuga_settings: str = ""  # "dotted.key=value,..." pinned in-process before the agent is built

    # --- improvements beyond the campaign's submitted configs (each A/B-gated) ---
    # Retries on the SAME thread (the checkpointer appends the follow-up turn):
    require_tool_rounds: int = (
        0  # VAKRA_CUGA_REQUIRE_TOOL(_ROUNDS): factual answer, 0 successful calls -> force a tool
    )
    retry_unattempted_refusal: bool = False  # also force a tool when a give-up came with no tool call at all
    refusal_recovery_rounds: int = (
        0  # give-up although tools returned data -> "extract the value from the results"
    )
    # Task-level retry (fresh thread) when the turn dies on the LLM transport (proxy drop, 5xx, timeout):
    infra_retries: int = 0
    # LLM fact-check of the draft against the recorded tool results:
    # "off" | "verify" (OK / CORRECTED: <answer>) | "verify_and_retry" (+ MISSING: <need> -> one re-ask)
    fact_check: str = "off"
    # One LLM pass rewrites the final draft as only the requested value(s), copied from the tool
    # results (prose answers dilute the correctness match and add claims the groundedness judge checks).
    answer_distill: bool = False
    # Deterministic values check: a draft stating a value (number, name, list item) that appears in
    # no tool result and not in the question is sent back once, asking for the tool-returned values.
    values_check_rounds: int = 0
    # After every re-ask: a draft that is the model's working notes ("We need ...", "Let's call ...")
    # instead of an answer is sent back (up to max_gate_rounds). FC ends on any reply without tool calls.
    plan_text_gate: bool = False
    # A call that returns no rows or only zeros is retried once with its text arguments lowercased:
    # many tables store names in lowercase ("murray ave", "asian", "michael jackson").
    lowercase_retry: bool = False
    # Fact-check: accept a CORRECTED value only when every value in it appears in a tool result (a
    # correction drawn from the call arguments replaced a right draft).
    fact_check_strict: bool = False
    # A re-ask cut by agent_timeout returns the answer from before the re-ask instead of nothing.
    keep_draft_on_timeout: bool = False
    # The demos show each solved example's reply as "Chain used: <tools>\nFinal answer: <value>". A model that
    # copies the layout (GLM-5.3-Flash: 77/120 cap3 answers) has correct values failed by the groundedness
    # judge, which reads the tool chain as unsupported claims; the final_answer fn keeps only the text after
    # the last "Final answer:" label. gpt-oss never wrote the layout (0/354 answers, caps 1-3). On in cap1-cap3.
    strip_demo_layout: bool = False
    # cap1 data tools answer a filter that matched nothing with a handle, {"handle": ..., "num_records": 0}: the
    # empty-result checks saw a value, so lowercase_retry and empty_result_hint never fired on cap1 (gpt-oss: 30
    # such calls on 119 tasks, cased values like "Oakland"). On, a 0-record handle counts as empty.
    empty_handle_is_empty: bool = False
    # A fact-check "MISSING" re-ask that ends in a give-up keeps the earlier draft (GLM-5.3-Flash cap3: two
    # ground-truth values turned into refusals).
    fact_check_keep_draft_on_giveup: bool = False
    # Two-stage tool narrowing (single-tool tasks, cap2): cosine top-``tool_pick_pool``, then one LLM
    # call picks THE tool; only the first ``tool_pick_bind`` of [pick, runner-up, cosine order] are
    # bound (the bind cap). Offline on est2_ref30: gold tool picked 29/30 vs the agent's 79% first call.
    tool_pick: bool = False
    tool_pick_pool: int = 32
    tool_pick_bind: int = 3
    # FC tool pick, further options. widen: after a failure in the task (a call returned no rows or
    # failed, or the answer checks re-ask), later model calls bind this many tools instead (0 = never).
    # fill: what follows [pick, runner-up] in the bound list — "cosine" order, or a second LLM call's
    # ranking ("llm"). hint: the adapter picks before the call and names the pick in the instructions.
    tool_pick_widen: int = 0
    tool_pick_fill: str = "cosine"
    tool_pick_hint: bool = False
    # A call that returns no rows gets a note: the argument values may not match the database's
    # format (codes, abbreviations, fractions, LIKE patterns) -> retry with stored-format values.
    empty_result_hint: bool = False
    # With the note, up to this many values other solved examples of the domain (the demo corpus,
    # never the asked question) passed for the same parameter names, e.g. cohort: '2y all'. 0 = off.
    param_value_examples: int = 0
    # Each tool's description gains up to this many solved train questions its gold calls answered (the
    # demo source's caps 2-4 samples of the domain — the API catalogue they share; never the asked
    # question). A tool's name often hides what it is for; the questions it answered show it. 0 = off.
    tool_usage_examples: int = 0
    # Per user turn, expose ONLY the top-K tools to the agent (the campaign's ranking: MiniLM over
    # "name: description" on the latest user turn, query_* retrievers pinned). The campaign rebuilt
    # CUGA per utterance with its top-k (40 for cap4); in CodeAct mode CUGA itself never narrows the
    # catalog (expose_all_tools lifts the find_tools wall), so without this the agent sees every tool.
    prefilter_top_k: Optional[int] = None
    # ... only when the domain has MORE than this many tools (0 = whenever prefilter_top_k is set). Every
    # tool beat the top-40 on cap4 (66.7 vs 56.7, 2026-10-17) wherever the catalog fits the model; past
    # ~400 tools it does not (test movie: 707 tools, a 534k-char CodeAct prompt, over the 131k context).
    prefilter_min_tools: int = 0


#: What every campaign run shared (VAKRA_CAMPAIGN_CONFIG.md §1): the model at temperature 1.0 drove
#: every call, no find_tools step, CUGA's default 70 steps, and CUGA's policy system off. Two
#: deliberate departures: tools keep their registry names and the SDK shortlister (the campaign's
#: bare names + own shortlister scored 50.0% vs 60.0% on the est3 dev set, 2026-10-14 — the
#: ``campaign_tools`` parity variant re-tests them), and a turn that dies on the LLM transport is
#: re-run once (the campaign re-ran empties only for cap1, in separate recovery passes).
_CAMPAIGN_SHARED = dict(
    harness_instructions=False,
    expose_all_tools=True,
    max_steps=CAMPAIGN_MAX_STEPS,
    model_temperature=CAMPAIGN_TEMPERATURE,
    use_policy_system=False,
    infra_retries=1,
)

#: The fc_canon runtime (caps 1-3: cap_estimate.sh, fc_canon_test.sh, fc_canon_proto_test.sh).
_FC_CANON_RUNTIME = dict(
    _CAMPAIGN_SHARED,
    fc_step_discipline="one_tool_per_step",
    fc_prompt_fragments="evidence_first",
    fc_answer_format=True,
    llm_http_timeout=CAMPAIGN_LLM_TIMEOUT,
    agent_timeout=CAMPAIGN_AGENT_TIMEOUT,
    tool_cap=CAMPAIGN_RUNAWAY_TOOL_CAP,
    demo_bound_names=True,
    cuga_settings=CAMPAIGN_CUGA_SETTINGS,
)


#: The campaign's submitted configs, kept for parity runs (cap1's is also the default).
_CAP2_CAMPAIGN = AdapterConfig(
    preset="cap2_campaign",
    enabled=True,
    execution_mode="function_calling",
    capability=2,
    gates=True,
    answer_contract=True,
    normalize=True,
    bluff_map=True,
    canonicalize=True,
    demos=True,
    # VAKRA_CUGA_CAP2_VERBATIM was not part of fc_canon: cap_estimate.sh (est2, the cap2
    # train scorecard) never sets it and fc_canon_test.sh unsets it.
    cap2_verbatim=False,
    shortlist_top_k=128,
    **_FC_CANON_RUNTIME,
)

_CAP3_CAMPAIGN = AdapterConfig(
    preset="cap3_campaign",
    enabled=True,
    execution_mode="function_calling",
    capability=3,
    gates=True,
    answer_contract=True,
    normalize=True,
    bluff_map=True,
    canonicalize=True,
    demos=True,
    shortlist_top_k=128,
    **_FC_CANON_RUNTIME,
)

_CAP4_V3WX = AdapterConfig(
    preset="cap4_v3wx",
    enabled=True,
    capability=4,
    discipline=True,
    scope=True,
    verbatim_on_retriever_scope=True,
    evidence_gate=True,
    support_check=True,
    self_verify=True,
    refusal_norm=True,
    tool_cap=16,
    shortlist_top_k=40,
    shortlist_pin_retrievers=True,
    # cap4_test.sh: CodeAct, no timeouts set (runner/LiteLLM defaults), CUGA settings defaults
    **_CAMPAIGN_SHARED,
    llm_http_timeout=CAP4_LLM_TIMEOUT,
    agent_timeout=CAP4_AGENT_TIMEOUT,
    cuga_settings=CAMPAIGN_CODEACT_SETTINGS,
)

#: Two fixes from the 2026-10-19 review of every cap2/cap3 validation failure, adopted after the
#: four-cap A/B: the tasks they changed were gains (lowercase retry: 4 tasks on caps 2-4, stored
#: lowercase values; earlier draft on a re-ask timeout: 2 cap4 tasks) with no attributable loss.
#: fact_check_strict stays off (no attributable gain, one probable cap4 loss).
_REVIEW_FIXES = dict(lowercase_retry=True, keep_draft_on_timeout=True)
# caps 1-3 show demos: a reply copied in their layout is cut to its final answer (a no-op for gpt-oss,
# which never writes it; GLM-5.3-Flash cap2 56.8 -> 73.0 re-judged, live 30-task 46.7 -> 73.3).
_DEMO_FIXES = dict(strip_demo_layout=True)
# caps 1-3: the answer composer (one LLM pass over the question + full tool results, values must come from
# the results). Two offline A/Bs on the full train sets, same trajectories: 17 gained / 4 lost, no cap below 0.
_COMPOSER = dict(answer_composer=True)

PRESETS: dict[str, AdapterConfig] = {
    "off": AdapterConfig(),
    "cap1": AdapterConfig(
        preset="cap1",
        enabled=True,
        execution_mode="function_calling",
        capability=1,
        gates=True,
        answer_contract=True,
        normalize=True,
        bluff_map=True,
        canonicalize=True,
        demos=True,
        cap1_protocol=True,
        relist_after_switch=True,
        shortlist_top_k=128,
        **_FC_CANON_RUNTIME,  # the official cap1 run: fc_canon_proto_test.sh (protocol + re-list)
        **_REVIEW_FIXES,
        **_DEMO_FIXES,
        **_COMPOSER,
    ),
    # Defaults: the campaign configs plus the changes that won paired A/Bs on two disjoint
    # train slices each (parity kit, 2026-10-15/17; benchmarks/m3/ADAPTER.md "Defaults").
    "cap2": replace(
        _CAP2_CAMPAIGN,
        preset="cap2",
        tool_pick=True,  # cosine top-k -> one LLM pick -> bind few (+10 / +17 pts at pool 32 / bind 3)
        # pool 48 -> pick + LLM ranking -> bind 10, the pick named in the instructions: ties bind 3 on
        # 60 tasks (69.5% each) and keeps the gold tool bound when a harder test question defeats the pick.
        tool_pick_pool=48,
        tool_pick_bind=10,
        tool_pick_fill="llm",
        tool_pick_hint=True,
        require_tool_rounds=2,  # a give-up with no tool call is re-asked (the pick binds few tools)
        retry_unattempted_refusal=True,
        empty_result_hint=True,  # no rows -> the data's value conventions (+3.5 pts)
        param_value_examples=6,
        **_REVIEW_FIXES,
        **_DEMO_FIXES,
        **_COMPOSER,
    ),
    "cap3": replace(
        _CAP3_CAMPAIGN,
        preset="cap3",
        fact_check="verify_and_retry",
        # 120-task train A/B (2026-10-25, one scoring session): 59.2 -> 65.8; all gold tools called 58 -> 73.
        tool_usage_examples=2,
        **_REVIEW_FIXES,
        **_DEMO_FIXES,
        **_COMPOSER,
    ),  # +10 / +13
    "cap4": replace(
        _CAP4_V3WX,
        preset="cap4",
        # soft2 (the campaign's best unsubmitted cap4 config): the three refusal guards off,
        # REQUIRE_TOOL with 2 rounds; plus the fact-check retry (66.7% vs V3WX answers 46.7%).
        evidence_gate=False,
        support_check=False,
        self_verify=False,
        require_tool_rounds=2,
        fact_check="verify_and_retry",
        # Every tool (the A/B winner over the campaign's top-40) unless the catalog cannot fit the
        # model: past 400 tools, the campaign's per-turn top-40 (test movie, 707 tools, overflowed).
        prefilter_top_k=40,
        prefilter_min_tools=400,
        **_REVIEW_FIXES,
    ),
    "cap2_campaign": _CAP2_CAMPAIGN,
    "cap3_campaign": _CAP3_CAMPAIGN,
    "cap4_v3wx": _CAP4_V3WX,
}


@dataclass
class TaskContext:
    """Mutable per-task state the runner hands the adapter before each sample.

    Safe because each per-domain agent evaluates its tasks sequentially.
    """

    additional_instructions: str = ""  # cap4 policy string, verbatim
    initial_data_handle: Optional[str] = None  # cap1: set after the universe switch
    initial_data_peek: Optional[dict] = None  # cap1: the get_data peek payload
    domain: str = ""
    last_scope: str = "all"  # set per invoke when cfg.scope resolves a policy


def _parse_bool(raw: str, key: str) -> bool:
    low = raw.strip().lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    raise ValueError(f"{key}={raw!r} is not a boolean (use one of {sorted(_TRUE | _FALSE)})")


def resolve_adapter_config(
    preset: Optional[str] = None,
    *,
    capability: Optional[int] = None,
    env: Optional[Mapping[str, str]] = None,
    demo_data: Optional[str] = None,
) -> AdapterConfig:
    """Resolve the effective adapter config.

    Precedence: ``M3_ADAPTER_<FIELD>`` env override > preset value > dataclass
    default. The preset name itself: explicit argument (CLI) > ``M3_ADAPTER_PRESET``
    env > ``"off"``. ``capability``, when given (from the m3 task id), always wins;
    so does an explicit ``demo_data`` (the ``--demo-data`` CLI flag) over
    ``M3_ADAPTER_DEMO_DATA``. Unknown preset names and malformed overrides raise
    immediately (fail fast).
    """
    env = os.environ if env is None else env
    name = preset or env.get(f"{ENV_PREFIX}PRESET") or "off"
    if name not in PRESETS:
        raise ValueError(f"Unknown adapter preset {name!r}; valid presets: {sorted(PRESETS)}")
    cfg = PRESETS[name]

    overrides: dict = {}
    for f in fields(AdapterConfig):
        if f.name == "preset":
            continue
        raw = env.get(f"{ENV_PREFIX}{f.name.upper()}")
        if raw is None:
            continue
        key = f"{ENV_PREFIX}{f.name.upper()}"
        if f.type in ("bool", bool):
            overrides[f.name] = _parse_bool(raw, key)
        elif f.type in ("Optional[int]", "int", int):
            if f.type == "Optional[int]" and raw.strip().lower() in ("", "none", "null"):
                overrides[f.name] = None  # e.g. M3_ADAPTER_TOOL_CAP=none lifts the cap (0 blocks every call)
                continue
            try:
                value = int(raw)
            except ValueError as exc:
                raise ValueError(f"{key}={raw!r} is not an integer") from exc
            if value < 0:
                raise ValueError(f"{key}={raw!r} must be >= 0")
            overrides[f.name] = value
        elif f.type in ("Optional[float]", "float", float):
            if f.type == "Optional[float]" and raw.strip().lower() in ("", "none", "null"):
                overrides[f.name] = None
                continue
            try:
                overrides[f.name] = float(raw)
            except ValueError as exc:
                raise ValueError(f"{key}={raw!r} is not a number") from exc
        else:
            overrides[f.name] = raw
    if capability is not None:
        overrides["capability"] = capability
    if demo_data:
        overrides["demo_data"] = demo_data
    cfg = replace(cfg, **overrides) if overrides else cfg
    if cfg.execution_mode not in EXECUTION_MODES:
        raise ValueError(f"{ENV_PREFIX}EXECUTION_MODE={cfg.execution_mode!r} is not one of {EXECUTION_MODES}")
    if cfg.fc_step_discipline not in STEP_DISCIPLINES:
        raise ValueError(
            f"{ENV_PREFIX}FC_STEP_DISCIPLINE={cfg.fc_step_discipline!r} is not one of {STEP_DISCIPLINES}"
        )
    if cfg.shortlist_strategy not in SHORTLIST_STRATEGIES:
        raise ValueError(
            f"{ENV_PREFIX}SHORTLIST_STRATEGY={cfg.shortlist_strategy!r} is not one of {SHORTLIST_STRATEGIES}"
        )
    if cfg.fact_check not in FACT_CHECK_MODES:
        raise ValueError(f"{ENV_PREFIX}FACT_CHECK={cfg.fact_check!r} is not one of {FACT_CHECK_MODES}")
    if cfg.tool_pick_fill not in TOOL_PICK_FILLS:
        raise ValueError(f"{ENV_PREFIX}TOOL_PICK_FILL={cfg.tool_pick_fill!r} is not one of {TOOL_PICK_FILLS}")
    if (
        cfg.tool_pick
        and cfg.tool_pick_widen
        and not cfg.tool_pick_bind < cfg.tool_pick_widen <= cfg.tool_pick_pool
    ):
        raise ValueError(
            f"{ENV_PREFIX}TOOL_PICK_WIDEN={cfg.tool_pick_widen} must be above TOOL_PICK_BIND and at most TOOL_PICK_POOL"
        )
    if cfg.tool_pick and not 1 <= cfg.tool_pick_bind <= cfg.tool_pick_pool:
        raise ValueError(
            f"{ENV_PREFIX}TOOL_PICK_BIND={cfg.tool_pick_bind} must be between 1 and "
            f"{ENV_PREFIX}TOOL_PICK_POOL={cfg.tool_pick_pool}"
        )
    parse_cuga_settings(cfg.cuga_settings)  # fail fast on a malformed pin list
    return cfg


def execution_mode_configurable(cfg: AdapterConfig) -> dict:
    """Per-invoke ``configurable`` entries for the preset's execution mode.

    ``function_calling`` sets the three FC keys; ``codeact`` sets nothing, so the
    CodeAct arm of an FC A/B is exactly the run that was validated (CUGA's own
    default). On a cuga main that predates native FC the keys are ignored and the
    run stays CodeAct.
    """
    if cfg.execution_mode == "function_calling":
        return dict(FUNCTION_CALLING_CONFIGURABLE)
    return {}


def runtime_configurable(cfg: AdapterConfig) -> dict:
    """Per-invoke ``configurable`` entries for the campaign-runtime fields.

    The two FC prompt knobs only exist on the function-calling path, so a CodeAct
    run sends neither. Unset fields send nothing (CUGA's settings apply).
    """
    conf: dict = {}
    if cfg.execution_mode == "function_calling":
        if cfg.fc_step_discipline != "off":
            conf["cuga_lite_step_discipline"] = cfg.fc_step_discipline
        fragments = [f.strip() for f in cfg.fc_prompt_fragments.split(",") if f.strip()]
        if fragments:
            conf["cuga_lite_fc_prompt_fragments"] = fragments
    if cfg.expose_all_tools:
        conf["shortlisting_tool_threshold"] = 10**6
    if cfg.max_steps:
        conf["cuga_lite_max_steps"] = cfg.max_steps
    return conf


def _coerce_setting(raw: str):
    low = raw.strip().lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    try:
        return int(raw)
    except ValueError:
        return raw.strip()


def parse_cuga_settings(spec: str) -> list[tuple[str, object]]:
    """``"a.b=false,c.d=150"`` -> ``[("a.b", False), ("c.d", 150)]`` (booleans and ints coerced)."""
    pins: list[tuple[str, object]] = []
    for item in (p.strip() for p in spec.split(",")):
        if not item:
            continue
        key, sep, value = item.partition("=")
        if not sep or not key.strip() or "." not in key:
            raise ValueError(f"{ENV_PREFIX}CUGA_SETTINGS entry {item!r} is not 'section.key=value'")
        pins.append((key.strip(), _coerce_setting(value)))
    return pins


def cuga_setting_pins(cfg: AdapterConfig) -> list[tuple[str, object]]:
    """Every settings pin the config asks for: ``cuga_settings``, the LLM timeout, the temperature.

    The temperature goes on every model block CUGA builds models from, so the run samples at the
    campaign's temperature whatever models TOML is loaded (a block that does not exist is skipped).
    """
    pins = parse_cuga_settings(cfg.cuga_settings)
    if cfg.tool_pick and cfg.execution_mode == "function_calling":  # FC: the bind cap calls the shortlister
        pins.append((f"advanced_features.{BIND_CAP_SETTING}", max(cfg.tool_pick_bind, cfg.tool_pick_widen)))
    if cfg.llm_http_timeout:
        pins.append(("connections.llm_http_timeout", cfg.llm_http_timeout))
    if cfg.model_temperature is not None:
        pins += [(f"agent.{role}.model.temperature", cfg.model_temperature) for role in MODEL_ROLES]
    return pins
