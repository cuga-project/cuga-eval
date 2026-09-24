"""Adapter config: presets match the validated flag sets; env precedence; parsing."""

import pytest

from benchmarks.m3.adapter.config import (
    ENV_PREFIX,
    MINILM_MODEL,
    PRESETS,
    AdapterConfig,
    execution_mode_configurable,
    resolve_adapter_config,
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


def test_caps123_presets_match_fc_canon_flag_set():
    """Provenance: vakra-main cuga_runs/fc_canon_test.sh (minus function-calling)."""
    for name, cap in (("cap1", 1), ("cap2", 2), ("cap3", 3)):
        cfg = PRESETS[name]
        assert cfg.enabled and cfg.capability == cap
        assert cfg.gates and cfg.answer_contract and cfg.normalize and cfg.bluff_map
        assert cfg.canonicalize and cfg.demos and cfg.demos_k == 2
        assert cfg.shortlist_top_k == 128
        assert cfg.use_policy_system is True
        # cap4-only behaviors stay off
        assert not (cfg.discipline or cfg.scope or cfg.evidence_gate or cfg.support_check)
        assert not (cfg.self_verify or cfg.refusal_norm) and cfg.tool_cap is None
    assert PRESETS["cap1"].cap1_protocol and PRESETS["cap1"].relist_after_switch
    assert not PRESETS["cap2"].cap1_protocol and PRESETS["cap2"].cap2_verbatim
    assert not PRESETS["cap3"].cap1_protocol and not PRESETS["cap3"].cap2_verbatim


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
        "cuga_lite_bind_tools_max_count": 0,
    }
    assert execution_mode_configurable(PRESETS["cap4_v3wx"]) == {}
    assert execution_mode_configurable(AdapterConfig()) == {}
