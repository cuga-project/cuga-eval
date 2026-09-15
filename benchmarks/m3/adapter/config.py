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

#: The exact embedding model the validated VAKRA runs shortlisted with.
MINILM_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

ENV_PREFIX = "M3_ADAPTER_"


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
    shortlist_pin_retrievers: bool = False  # vakra ToolShortlister pinned query_* tools (cap4)

    # --- harness behavior ---
    use_policy_system: bool = True  # False => the eval skips _load_m3_policies (cap4 preset)

    # --- demos source (never the split under evaluation; see demos.load_demo_corpus) ---
    demo_data: Optional[str] = None  # M3_ADAPTER_DEMO_DATA / --demo-data; None = bundled data/small_train.zip


PRESETS: dict[str, AdapterConfig] = {
    "off": AdapterConfig(),
    "cap1": AdapterConfig(
        preset="cap1",
        enabled=True,
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
    ),
    "cap2": AdapterConfig(
        preset="cap2",
        enabled=True,
        capability=2,
        gates=True,
        answer_contract=True,
        normalize=True,
        bluff_map=True,
        canonicalize=True,
        demos=True,
        cap2_verbatim=True,
        shortlist_top_k=128,
    ),
    "cap3": AdapterConfig(
        preset="cap3",
        enabled=True,
        capability=3,
        gates=True,
        answer_contract=True,
        normalize=True,
        bluff_map=True,
        canonicalize=True,
        demos=True,
        shortlist_top_k=128,
    ),
    "cap4_v3wx": AdapterConfig(
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
        use_policy_system=False,
    ),
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
            try:
                overrides[f.name] = int(raw)
            except ValueError as exc:
                raise ValueError(f"{key}={raw!r} is not an integer") from exc
        else:
            overrides[f.name] = raw
    if capability is not None:
        overrides["capability"] = capability
    if demo_data:
        overrides["demo_data"] = demo_data
    return replace(cfg, **overrides) if overrides else cfg
