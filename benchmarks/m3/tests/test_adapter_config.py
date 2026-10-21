"""Adapter config: presets match the validated flag sets; env precedence; parsing."""

from dataclasses import replace

import pytest

from benchmarks.m3.adapter.config import (
    CAMPAIGN_CODEACT_SETTINGS,
    CAMPAIGN_CUGA_SETTINGS,
    ENV_PREFIX,
    MINILM_MODEL,
    MODEL_ROLES,
    PRESETS,
    AdapterConfig,
    cuga_setting_pins,
    execution_mode_configurable,
    parse_cuga_settings,
    resolve_adapter_config,
    runtime_configurable,
)

pytestmark = pytest.mark.sanity


def test_off_preset_is_fully_disabled():
    cfg = resolve_adapter_config(None, env={})
    assert cfg.preset == "off"
    assert cfg.enabled is False
    # every behavior switch is off
    assert not any(
        getattr(cfg, f)
        for f in (
            "gates",
            "answer_contract",
            "normalize",
            "bluff_map",
            "canonicalize",
            "demos",
            "cap1_protocol",
            "relist_after_switch",
            "cap2_verbatim",
            "discipline",
            "scope",
            "verbatim_on_retriever_scope",
            "evidence_gate",
            "support_check",
            "self_verify",
            "refusal_norm",
            "shortlist_pin_retrievers",
        )
    )
    assert cfg.tool_cap is None and cfg.shortlist_top_k is None


#: Every campaign setting the presets reproduce, per preset, with where the campaign set it.
#: Sources (vakra-main/cuga_runs): cap_estimate.sh (est2/est3 train scorecards), fc_canon_test.sh
#: (caps 2-3 test), fc_canon_proto_test.sh (the official cap1 run), cap4_test.sh (V3WX); defaults
#: from agents/cuga_clean_agent.py, benchmark_runner.py and the campaign's CUGA settings.toml.
_FC_CANON = {
    "gates": True,  # VAKRA_CUGA_GATES=1 (+GATES_CAPS=<cap>)
    "max_gate_rounds": 2,
    "answer_contract": True,  # VAKRA_CUGA_CONTRACT=1
    "normalize": True,  # VAKRA_CUGA_NORMALIZE=1
    "bluff_map": True,  # VAKRA_CUGA_BLUFF_MAP=1
    "canonicalize": True,  # DYNACONF_ADVANCED_FEATURES__FINAL_ANSWER_CANONICALIZE=true
    "demos": True,  # VAKRA_CUGA_DEMOS=1 VAKRA_CUGA_DEMOS_MODE=prose
    "demos_k": 2,  # VAKRA_DEMOS_K=2
    "shortlist_top_k": 128,  # --top-k-tools 128
    # deliberate departure: SDK shortlister + registry names (campaign's: 50.0% vs 60.0%, est3 dev set)
    "shortlist_strategy": "sdk",
    "execution_mode": "function_calling",  # VAKRA_CUGA_FC=1
    "fc_step_discipline": "one_tool_per_step",  # campaign FC preamble
    "fc_prompt_fragments": "evidence_first",  # campaign FC preamble
    "fc_answer_format": True,  # campaign FC preamble (answer-format line)
    "harness_instructions": False,  # the campaign had no eval_m3.py riders
    "expose_all_tools": True,  # shortlisting_tool_threshold = shortlisted + 1
    "max_steps": 70,  # CUGA default; VAKRA_CUGA_MAX_STEPS=40 was never read
    "llm_http_timeout": 150,  # LITELLM_REQUEST_TIMEOUT_SECONDS=150
    "agent_timeout": 220,  # AGENT_TIMEOUT_SECONDS=220
    "tool_cap": 100,  # RUNAWAY_TOOL_CAP default (VAKRA_CUGA_TOOL_CAP unset)
    "model_temperature": 1.0,  # --temperature 1.0
    "bare_tool_names": False,  # deliberate departure (see shortlist_strategy)
    "infra_retries": 1,  # beyond the campaign: re-run a turn that died on the LLM transport
    "demo_bound_names": True,
    "use_policy_system": False,  # DYNACONF_POLICY__ENABLED=false
    "cuga_settings": CAMPAIGN_CUGA_SETTINGS,  # autonomy / reflection / NL auto-continue off
    # cap4-only behaviors stay off
    "discipline": False,
    "scope": False,
    "evidence_gate": False,
    "support_check": False,
    "self_verify": False,
    "refusal_norm": False,
}
CAMPAIGN_PRESETS = {
    "cap1": dict(_FC_CANON, capability=1, cap1_protocol=True, relist_after_switch=True, cap2_verbatim=False),
    # VAKRA_CUGA_CAP2_VERBATIM: never set by cap_estimate.sh (est2), unset by fc_canon_test.sh
    "cap2_campaign": dict(
        _FC_CANON, capability=2, cap1_protocol=False, relist_after_switch=False, cap2_verbatim=False
    ),
    "cap3_campaign": dict(
        _FC_CANON, capability=3, cap1_protocol=False, relist_after_switch=False, cap2_verbatim=False
    ),
    "cap4_v3wx": {
        "capability": 4,
        "discipline": True,  # VAKRA_V2_DISCIPLINE=1
        "scope": True,  # VAKRA_V2_SCOPE=1
        "verbatim_on_retriever_scope": True,  # VAKRA_V2_VERBATIM=1
        "evidence_gate": True,  # VAKRA_V2_EVIDENCE_GATE=1
        "support_check": True,  # VAKRA_V2_SUPPORT_CHECK=1
        "self_verify": True,  # VAKRA_V2_SELF_VERIFY=1
        "refusal_norm": True,  # VAKRA_CUGA_REFUSAL_NORM=1
        "tool_cap": 16,  # VAKRA_CUGA_TOOL_CAP=16
        "shortlist_top_k": 40,  # --top-k-tools 40
        "shortlist_strategy": "sdk",
        "shortlist_pin_retrievers": True,
        "execution_mode": "codeact",  # no VAKRA_CUGA_FC
        "gates": False,
        "demos": False,
        "canonicalize": False,
        "answer_contract": False,
        "harness_instructions": False,
        "expose_all_tools": True,
        "max_steps": 70,
        "llm_http_timeout": 600,  # unset -> LiteLLM default
        "agent_timeout": 300,  # unset -> benchmark_runner.py default
        "model_temperature": 1.0,
        "bare_tool_names": False,
        "infra_retries": 1,
        "use_policy_system": False,
        "cuga_settings": CAMPAIGN_CODEACT_SETTINGS,  # + sandbox_execution_timeout=30 (CodeAct)
    },
}


@pytest.mark.parametrize("name", sorted(CAMPAIGN_PRESETS))
def test_preset_reproduces_every_campaign_setting(name):
    cfg = PRESETS[name]
    assert cfg.enabled and cfg.preset == name
    mismatches = {k: (getattr(cfg, k), v) for k, v in CAMPAIGN_PRESETS[name].items() if getattr(cfg, k) != v}
    assert not mismatches, f"{name}: (preset, campaign) differ for {mismatches}"


def test_off_preset_reproduces_nothing():
    off = PRESETS["off"]
    assert off.harness_instructions and off.use_policy_system and not off.expose_all_tools
    assert off.max_steps is off.agent_timeout is off.llm_http_timeout is off.model_temperature is None
    assert off.cuga_settings == "" and off.shortlist_strategy == "sdk" and not off.bare_tool_names
    assert off.tool_cap is None and off.infra_retries == 0
    assert off.require_tool_rounds == off.refusal_recovery_rounds == 0 and off.fact_check == "off"


def test_runtime_configurable_maps_fields_to_cuga_keys():
    assert runtime_configurable(PRESETS["cap3"]) == {
        "cuga_lite_step_discipline": "one_tool_per_step",
        "cuga_lite_fc_prompt_fragments": ["evidence_first"],
        "shortlisting_tool_threshold": 10**6,
        "cuga_lite_max_steps": 70,
    }
    # the FC prompt knobs exist only on the function-calling path
    codeact = replace(PRESETS["cap3"], execution_mode="codeact")
    assert runtime_configurable(codeact) == {"shortlisting_tool_threshold": 10**6, "cuga_lite_max_steps": 70}
    assert runtime_configurable(PRESETS["cap4_v3wx"]) == {
        "shortlisting_tool_threshold": 10**6,
        "cuga_lite_max_steps": 70,
    }
    assert runtime_configurable(PRESETS["off"]) == {}


def test_cuga_settings_parse_coerce_and_fail_fast():
    assert parse_cuga_settings("a.b=false, c.d=150 ,e.f=x") == [("a.b", False), ("c.d", 150), ("e.f", "x")]
    assert parse_cuga_settings("") == []
    for bad in ("nodot=1", "a.b", "=1"):
        with pytest.raises(ValueError):
            parse_cuga_settings(bad)
    pins = dict(cuga_setting_pins(PRESETS["cap3"]))
    assert pins["advanced_features.force_autonomous_mode"] is False
    assert pins["connections.llm_http_timeout"] == 150
    assert {pins[f"agent.{r}.model.temperature"] for r in MODEL_ROLES} == {1.0}
    cap4 = dict(cuga_setting_pins(PRESETS["cap4_v3wx"]))
    assert (
        cap4["advanced_features.sandbox_execution_timeout"] == 30
        and cap4["connections.llm_http_timeout"] == 600
    )
    assert cuga_setting_pins(PRESETS["off"]) == []
    with pytest.raises(ValueError):
        resolve_adapter_config("cap3", env={"M3_ADAPTER_CUGA_SETTINGS": "broken"})
    with pytest.raises(ValueError):
        resolve_adapter_config("cap3", env={"M3_ADAPTER_FC_STEP_DISCIPLINE": "two_per_step"})
    with pytest.raises(ValueError):
        resolve_adapter_config("cap3", env={"M3_ADAPTER_SHORTLIST_STRATEGY": "bm25"})


def test_float_overrides_parse_and_reset():
    assert (
        resolve_adapter_config("cap3", env={"M3_ADAPTER_MODEL_TEMPERATURE": "0.5"}).model_temperature == 0.5
    )
    assert (
        resolve_adapter_config("cap3", env={"M3_ADAPTER_MODEL_TEMPERATURE": "none"}).model_temperature is None
    )
    with pytest.raises(ValueError):
        resolve_adapter_config("cap3", env={"M3_ADAPTER_MODEL_TEMPERATURE": "warm"})


def test_cap4_v3wx_preset_matches_v3wx_flag_set():
    """Provenance: vakra-main cap4 V3WX run config."""
    cfg = PRESETS["cap4_v3wx"]
    assert cfg.enabled and cfg.capability == 4
    assert cfg.discipline and cfg.scope and cfg.verbatim_on_retriever_scope
    assert cfg.evidence_gate and cfg.support_check and cfg.self_verify and cfg.refusal_norm
    assert cfg.tool_cap == 16 and cfg.shortlist_top_k == 40
    assert cfg.shortlist_pin_retrievers is True
    assert cfg.use_policy_system is False
    # v3wx never enabled canonicalize / gates / demos
    assert not (cfg.canonicalize or cfg.gates or cfg.demos or cfg.answer_contract)


def test_unknown_preset_raises_with_valid_names():
    with pytest.raises(ValueError, match="cap4_v3wx"):
        resolve_adapter_config("nope", env={})


def test_preset_from_env_and_cli_precedence():
    env = {f"{ENV_PREFIX}PRESET": "cap2"}
    assert resolve_adapter_config(None, env=env).preset == "cap2"
    # explicit argument beats the env var
    assert resolve_adapter_config("cap3", env=env).preset == "cap3"


def test_field_env_overrides_beat_preset():
    env = {
        f"{ENV_PREFIX}SELF_VERIFY": "off",
        f"{ENV_PREFIX}TOOL_CAP": "32",
        f"{ENV_PREFIX}SHORTLIST_MODEL": "custom/model",
    }
    cfg = resolve_adapter_config("cap4_v3wx", env=env)
    assert cfg.self_verify is False
    assert cfg.tool_cap == 32
    assert cfg.shortlist_model == "custom/model"
    # untouched fields keep preset values
    assert cfg.support_check is True and cfg.shortlist_top_k == 40


def test_bool_parsing_accepts_on_off_and_rejects_garbage():
    assert resolve_adapter_config("cap1", env={f"{ENV_PREFIX}DEMOS": "off"}).demos is False
    assert resolve_adapter_config("off", env={f"{ENV_PREFIX}GATES": "yes"}).gates is True
    with pytest.raises(ValueError, match="not a boolean"):
        resolve_adapter_config("cap1", env={f"{ENV_PREFIX}DEMOS": "maybe"})
    with pytest.raises(ValueError, match="not an integer"):
        resolve_adapter_config("cap1", env={f"{ENV_PREFIX}DEMOS_K": "two"})


def test_capability_argument_wins():
    cfg = resolve_adapter_config("cap2", capability=3, env={})
    assert cfg.capability == 3


def test_default_shortlist_model_is_the_validated_minilm():
    assert AdapterConfig().shortlist_model == MINILM_MODEL
    assert "all-MiniLM-L6-v2" in MINILM_MODEL


def test_optional_int_env_override_resets_to_none_and_rejects_negatives():
    cfg = resolve_adapter_config("cap4_v3wx", env={f"{ENV_PREFIX}TOOL_CAP": "none"})
    assert cfg.tool_cap is None  # uncapped; 0 would block every tool call
    assert resolve_adapter_config("cap4_v3wx", env={f"{ENV_PREFIX}TOOL_CAP": ""}).tool_cap is None
    assert (
        resolve_adapter_config("cap2", env={f"{ENV_PREFIX}SHORTLIST_TOP_K": "null"}).shortlist_top_k is None
    )
    with pytest.raises(ValueError, match=">= 0"):
        resolve_adapter_config("cap4_v3wx", env={f"{ENV_PREFIX}TOOL_CAP": "-1"})
    with pytest.raises(ValueError, match=">= 0"):
        resolve_adapter_config("cap2", env={f"{ENV_PREFIX}DEMOS_K": "-2"})
    with pytest.raises(ValueError, match="not an integer"):
        resolve_adapter_config("cap2", env={f"{ENV_PREFIX}DEMOS_K": "none"})  # plain int: no reset


# ---------------------------- execution mode --------------------------------


def test_execution_mode_presets_and_override():
    for name in ("cap1", "cap2", "cap3"):
        assert PRESETS[name].execution_mode == "function_calling"  # VAKRA_CUGA_FC
    assert PRESETS["cap4_v3wx"].execution_mode == "codeact"  # V3WX ran CodeAct
    assert PRESETS["off"].execution_mode == "codeact"
    cfg = resolve_adapter_config("cap2", env={f"{ENV_PREFIX}EXECUTION_MODE": "codeact"})
    assert cfg.execution_mode == "codeact"  # the CodeAct arm of an FC A/B
    with pytest.raises(ValueError, match="EXECUTION_MODE"):
        resolve_adapter_config("cap2", env={f"{ENV_PREFIX}EXECUTION_MODE": "react"})


def test_execution_mode_configurable_mapping():
    assert execution_mode_configurable(PRESETS["cap3"]) == {
        "cuga_lite_execution_mode": "function_calling",
        "cuga_lite_bind_tools_mode": "all",
    }
    # the bind cap is a cuga *settings* knob (BIND_CAP_ENV), never a configurable key
    assert "cuga_lite_bind_tools_max_count" not in execution_mode_configurable(PRESETS["cap3"])
    assert execution_mode_configurable(PRESETS["cap4_v3wx"]) == {}
    assert execution_mode_configurable(AdapterConfig()) == {}


def test_defaults_are_the_campaign_configs_plus_the_ab_winners():
    """cap1 is the campaign's config; cap2-cap4 add only what won paired A/Bs (ADAPTER.md "Defaults");
    all four carry the two review fixes (lowercase retry, earlier draft on a re-ask timeout)."""
    FIXES = dict(lowercase_retry=True, keep_draft_on_timeout=True)
    assert PRESETS["cap2"] == replace(
        PRESETS["cap2_campaign"],
        preset="cap2",
        tool_pick=True,
        tool_pick_pool=48,  # safeguard C: pool 48 -> pick + LLM ranking -> bind 10, pick named
        tool_pick_bind=10,
        tool_pick_fill="llm",
        tool_pick_hint=True,
        require_tool_rounds=2,
        retry_unattempted_refusal=True,
        empty_result_hint=True,
        param_value_examples=6,
        **FIXES,
    )
    assert PRESETS["cap3"] == replace(
        PRESETS["cap3_campaign"], preset="cap3", fact_check="verify_and_retry", **FIXES
    )
    assert PRESETS["cap4"] == replace(
        PRESETS["cap4_v3wx"],
        preset="cap4",
        evidence_gate=False,
        support_check=False,
        self_verify=False,
        require_tool_rounds=2,
        fact_check="verify_and_retry",
        prefilter_top_k=40,
        prefilter_min_tools=400,
        **FIXES,
    )
    cap1 = PRESETS["cap1"]
    assert cap1.lowercase_retry and cap1.keep_draft_on_timeout and not cap1.fact_check_strict
    assert not any(PRESETS[p].lowercase_retry for p in ("off", "cap2_campaign", "cap3_campaign", "cap4_v3wx"))
    cap4 = PRESETS["cap4"]  # every tool (beat the top-40) unless the catalog is too big to show whole
    assert (cap4.prefilter_top_k, cap4.prefilter_min_tools, cap4.tool_pick) == (40, 400, False)
    assert {"cap2_campaign", "cap3_campaign", "cap4_v3wx"} <= set(PRESETS)
