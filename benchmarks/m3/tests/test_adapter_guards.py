"""Guards pipeline: order, gating, retries, and evidence semantics (stubbed agent)."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from benchmarks.m3.adapter.config import PRESETS, AdapterConfig, TaskContext
from benchmarks.m3.adapter.final_answer import REFUSAL
from benchmarks.m3.adapter.guards import run_answer_pipeline, simple_gate_correction

pytestmark = pytest.mark.sanity


def _result(answer, error=None):
    return SimpleNamespace(answer=answer, error=error, tool_calls=[])


def _rounds(*answers):
    """invoke_round stub yielding scripted answers; records corrections sent."""
    sent = []
    queue = list(answers)

    async def invoke_round(correction):
        sent.append(correction)
        return _result(queue.pop(0) if queue else "")

    return invoke_round, sent


OK_CALL = {"tool_name": "t", "arguments": {}, "result": "value 42"}
ERR_CALL = {"tool_name": "t", "arguments": {}, "result": "Error: boom"}


async def test_everything_off_returns_stripped_answer():
    cfg = AdapterConfig()
    invoke_round, sent = _rounds()
    out = await run_answer_pipeline(invoke_round, _result("<|channel|> 42 "), cfg, TaskContext(), [])
    assert out == "42"
    assert sent == []


async def test_gates_retry_empty_then_stop_and_same_correction_text():
    cfg = replace(PRESETS["cap3"], demos=False)
    invoke_round, sent = _rounds("the value is 7")
    out = await run_answer_pipeline(invoke_round, _result(""), cfg, TaskContext(), [OK_CALL])
    assert out == "the value is 7"
    assert len(sent) == 1 and sent[0] == simple_gate_correction("")


async def test_gates_cap_at_max_rounds():
    cfg = replace(PRESETS["cap3"], max_gate_rounds=2)
    invoke_round, sent = _rounds("", "")  # keeps coming back empty
    await run_answer_pipeline(invoke_round, _result(""), cfg, TaskContext(), [OK_CALL])
    assert len(sent) == 2  # bounded


async def test_gates_stop_on_error_result():
    cfg = PRESETS["cap3"]
    calls = []

    async def invoke_round(correction):
        calls.append(correction)
        return _result("", error="boom")

    out = await run_answer_pipeline(invoke_round, _result(""), cfg, TaskContext(), [OK_CALL])
    assert len(calls) == 1  # error aborts the loop despite still-empty answer
    assert out == ""


async def test_gate_retry_error_keeps_the_pre_retry_draft():
    cfg = PRESETS["cap3"]
    calls = []

    async def invoke_round(correction):
        calls.append(correction)
        return _result("", error="boom")

    out = await run_answer_pipeline(invoke_round, _result("Approximately 42"), cfg, TaskContext(), [OK_CALL])
    assert len(calls) == 1
    assert out == "Approximately 42"  # the errored retry does not wipe the hedged draft


async def test_hedged_answer_triggers_restate_correction():
    cfg = PRESETS["cap3"]
    invoke_round, sent = _rounds("42")
    out = await run_answer_pipeline(
        invoke_round, _result("It might be 42, however..."), cfg, TaskContext(), [OK_CALL]
    )
    assert out == "42"
    assert "Restate the final answer" in sent[0]


async def test_refusal_norm_maps_giveup_phrasings():
    cfg = AdapterConfig(refusal_norm=True)
    invoke_round, _ = _rounds()
    out = await run_answer_pipeline(
        invoke_round, _result("I'm unable to find that data"), cfg, TaskContext(), [OK_CALL]
    )
    assert out == REFUSAL


async def test_evidence_gate_refuses_only_without_successful_calls():
    cfg = AdapterConfig(evidence_gate=True)
    invoke_round, _ = _rounds()
    refused = await run_answer_pipeline(invoke_round, _result("42"), cfg, TaskContext(), [ERR_CALL])
    assert refused == REFUSAL
    kept = await run_answer_pipeline(invoke_round, _result("42"), cfg, TaskContext(), [OK_CALL])
    assert kept == "42"


async def test_support_check_on_retriever_scope():
    cfg = AdapterConfig(support_check=True)
    ctx = TaskContext(last_scope="retriever_only")
    evidence = [{"tool_name": "query_d", "arguments": {}, "result": "Paris population 2161000"}]
    invoke_round, _ = _rounds()
    kept = await run_answer_pipeline(invoke_round, _result("Paris 2161000"), cfg, ctx, evidence)
    assert kept == "Paris 2161000"
    refused = await run_answer_pipeline(
        invoke_round, _result("Berlin 999999 Madrid 888888"), cfg, ctx, evidence
    )
    assert refused == REFUSAL
    # scope != retriever_only => support check never fires
    kept2 = await run_answer_pipeline(
        invoke_round, _result("Berlin 999999 Madrid 888888"), cfg, TaskContext(), evidence
    )
    assert kept2 == "Berlin 999999 Madrid 888888"


async def test_self_verify_unsupported_refuses_and_failure_keeps_draft():
    cfg = AdapterConfig(self_verify=True)
    ctx = TaskContext(last_scope="retriever_only")
    evidence = [{"tool_name": "query_d", "arguments": {}, "result": "some chunk"}]
    invoke_round, _ = _rounds()

    async def verdict_unsupported(prompt):
        assert "Draft answer" in prompt
        return "UNSUPPORTED"

    async def verdict_boom(prompt):
        raise RuntimeError("llm down")

    refused = await run_answer_pipeline(
        invoke_round, _result("claim"), cfg, ctx, evidence, verdict_unsupported
    )
    assert refused == REFUSAL
    kept = await run_answer_pipeline(invoke_round, _result("claim"), cfg, ctx, evidence, verdict_boom)
    assert kept == "claim"


async def test_cap2_extract_and_normalize_order():
    cfg = AdapterConfig(capability=2, cap2_verbatim=True, normalize=True)
    invoke_round, _ = _rounds()
    out = await run_answer_pipeline(
        invoke_round, _result('{"count": 36526.0}'), cfg, TaskContext(), [OK_CALL]
    )
    assert out == "36526"


async def test_bluff_map_only_when_unsupported():
    cfg = AdapterConfig(bluff_map=True)
    invoke_round, _ = _rounds()
    refused = await run_answer_pipeline(invoke_round, _result("n/a"), cfg, TaskContext(), [ERR_CALL])
    assert refused == REFUSAL
    kept = await run_answer_pipeline(invoke_round, _result("0"), cfg, TaskContext(), [OK_CALL])
    assert kept == "0"  # a genuinely-supported 0 is preserved


async def test_canonicalize_fallback_when_final_answer_not_installed():
    cfg = AdapterConfig(canonicalize=True)
    invoke_round, _ = _rounds()
    out = await run_answer_pipeline(
        invoke_round, _result("[[42]]"), cfg, TaskContext(), [], final_answer_installed=False
    )
    assert out == "42"
    out2 = await run_answer_pipeline(
        invoke_round, _result("[[42]]"), cfg, TaskContext(), [], final_answer_installed=True
    )
    assert out2 == "[[42]]"  # in-graph function already did it; no double-processing
