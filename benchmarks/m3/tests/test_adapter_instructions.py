"""Instruction composition: per-preset blocks, order, cap1 handle info."""

from dataclasses import replace

import pytest

from benchmarks.m3.adapter.config import PRESETS, AdapterConfig, TaskContext
from benchmarks.m3.adapter.instructions import (
    ANSWER_DISCIPLINE,
    CAP1_PROTOCOL,
    CAP2_VERBATIM_RULE,
    FC_ANSWER_FORMAT_LINE,
    build_handle_info,
    compose_instruction_block,
)

pytestmark = pytest.mark.sanity


def test_off_config_and_empty_ctx_compose_to_empty():
    assert compose_instruction_block(AdapterConfig(), TaskContext()) == ""


def test_cap4_block_is_policy_then_discipline_in_order():
    ctx = TaskContext(additional_instructions="POLICY TEXT")
    block = compose_instruction_block(PRESETS["cap4_v3wx"], ctx)
    assert block.startswith("POLICY TEXT")
    assert ANSWER_DISCIPLINE in block
    assert block.index("POLICY TEXT") < block.index("TOOL USE RULES")
    # v3wx composes no contract / cap1 / cap2 blocks
    assert "FINAL-ANSWER RULES" not in block
    assert "CHAIN PROTOCOL" not in block


def test_contract_carries_cuga_refusal_not_impossible():
    block = compose_instruction_block(PRESETS["cap3"], TaskContext())
    assert 'answer exactly "I can not answer."' in block
    assert "answer exactly IMPOSSIBLE" not in block


def test_contract_requires_gates_active():
    # Faithful to the source: contract only applied while gates are active.
    cfg = AdapterConfig(answer_contract=True, gates=False)
    assert "FINAL-ANSWER RULES" not in compose_instruction_block(cfg, TaskContext())


def test_cap1_block_includes_handle_info_and_protocol():
    ctx = TaskContext(
        initial_data_handle="retrieved_zip_1",
        initial_data_peek={
            "num_records": 50807,
            "key_details": [{"name": "zip"}, {"name": "city"}],
        },
    )
    block = compose_instruction_block(PRESETS["cap1"], ctx)
    assert 'handle "retrieved_zip_1"' in block
    assert "Total records: 50807" in block
    assert "'zip'" in block and "'city'" in block
    assert CAP1_PROTOCOL in block
    assert block.index("INITIAL DATA") < block.index("CHAIN PROTOCOL")


def test_cap1_protocol_without_handle_still_composes():
    block = compose_instruction_block(PRESETS["cap1"], TaskContext())
    assert CAP1_PROTOCOL in block
    assert "INITIAL DATA" not in block


def test_cap2_rule_only_for_capability_2():
    # Off in the cap2 preset (not part of fc_canon); the rule still composes when enabled.
    assert CAP2_VERBATIM_RULE not in compose_instruction_block(PRESETS["cap2"], TaskContext())
    cap2_verbatim = replace(PRESETS["cap2"], cap2_verbatim=True)
    assert CAP2_VERBATIM_RULE in compose_instruction_block(cap2_verbatim, TaskContext())
    cap3_verbatim = replace(PRESETS["cap3"], cap2_verbatim=True)
    assert CAP2_VERBATIM_RULE not in compose_instruction_block(cap3_verbatim, TaskContext())


def test_fc_answer_format_line_leads_the_block_in_function_calling_only():
    block = compose_instruction_block(PRESETS["cap3"], TaskContext())
    assert block.startswith(FC_ANSWER_FORMAT_LINE)
    codeact = replace(PRESETS["cap3"], execution_mode="codeact")
    assert FC_ANSWER_FORMAT_LINE not in compose_instruction_block(codeact, TaskContext())
    assert FC_ANSWER_FORMAT_LINE not in compose_instruction_block(
        replace(PRESETS["cap3"], fc_answer_format=False), TaskContext()
    )


def test_fc_answer_format_line_is_the_campaign_preamble_text():
    # Verbatim from cuga-agent-main graph_adapter._FC_SYSTEM_PREAMBLE (the campaign's FC code).
    assert FC_ANSWER_FORMAT_LINE == (
        "- Match the answer format shown in the examples (e.g. [[value]] for a single value, "
        "[[a], [b]] for several). Output only that answer — no explanation, no restating the "
        "question, and never repeat the value."
    )


def test_handle_info_degrades_gracefully():
    assert build_handle_info(None, None) == ""
    assert build_handle_info("", {"num_records": 3}) == ""
    text = build_handle_info("h1", None)
    assert 'handle "h1"' in text and "Total records" not in text
    # malformed peek keeps the handle line, drops the columns
    text2 = build_handle_info("h1", {"key_details": [{"wrong": 1}]})
    assert 'handle "h1"' in text2 and "Columns" not in text2
