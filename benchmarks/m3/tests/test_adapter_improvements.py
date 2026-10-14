"""Improvements beyond the campaign: require-tool, refusal recovery, fact-check, transport retries."""

from types import SimpleNamespace

import pytest

from benchmarks.m3.adapter.agent import VakraAdapterAgent, is_transient_error
from benchmarks.m3.adapter.config import AdapterConfig, TaskContext, resolve_adapter_config
from benchmarks.m3.adapter.guards import (
    FACT_CHECK_MAX_CALLS,
    REFUSAL_RECOVERY_CORRECTION,
    REQUIRE_TOOL_CORRECTION,
    format_tool_evidence,
    parse_fact_check,
    run_answer_pipeline,
)
from benchmarks.m3.adapter.recording import RecordingScopedToolProvider

pytestmark = pytest.mark.sanity

OK_CALL = {"tool_name": "get_x", "arguments": {"id": 1}, "result": '{"x": 42}'}
ERR_CALL = {"tool_name": "get_x", "arguments": {}, "result": "Error: boom"}


def _result(answer, error=None):
    return SimpleNamespace(answer=answer, error=error, tool_calls=[])


def _rounds(*answers, on_round=None):
    sent = []
    queue = list(answers)

    async def invoke_round(correction):
        sent.append(correction)
        if on_round:
            on_round()
        return _result(queue.pop(0) if queue else "")

    return invoke_round, sent


# ------------------------------------------------------------------ require-tool


async def test_require_tool_reasks_an_ungrounded_answer_until_a_tool_succeeds():
    calls = []
    invoke_round, sent = _rounds("43", on_round=lambda: calls.append(OK_CALL))
    cfg = AdapterConfig(require_tool_rounds=2)
    out = await run_answer_pipeline(invoke_round, _result("42"), cfg, TaskContext(), calls)
    assert sent == [REQUIRE_TOOL_CORRECTION]  # one round: the retry produced a successful call
    assert out == "43"


async def test_require_tool_leaves_grounded_answers_and_refusals_alone():
    cfg = AdapterConfig(require_tool_rounds=1)
    invoke_round, sent = _rounds("x")
    assert await run_answer_pipeline(invoke_round, _result("42"), cfg, TaskContext(), [OK_CALL]) == "42"
    assert await run_answer_pipeline(invoke_round, _result("I can not answer."), cfg, TaskContext(), []) == (
        "I can not answer."
    )
    assert sent == []  # campaign semantics: a give-up is not re-asked


async def test_retry_unattempted_refusal_reasks_a_give_up_that_never_tried_a_tool():
    cfg = AdapterConfig(require_tool_rounds=1, retry_unattempted_refusal=True)
    invoke_round, sent = _rounds("7")
    assert (
        await run_answer_pipeline(invoke_round, _result("I can not answer."), cfg, TaskContext(), []) == "7"
    )
    assert sent == [REQUIRE_TOOL_CORRECTION]
    invoke_round, sent = _rounds("7")  # a give-up after failed calls is not "unattempted"
    out = await run_answer_pipeline(
        invoke_round, _result("I can not answer."), cfg, TaskContext(), [ERR_CALL]
    )
    assert out == "I can not answer." and sent == []


# ------------------------------------------------------------- refusal recovery


async def test_refusal_recovery_reasks_a_give_up_when_tools_returned_data():
    cfg = AdapterConfig(refusal_recovery_rounds=1)
    invoke_round, sent = _rounds("42")
    out = await run_answer_pipeline(
        invoke_round, _result("I am unable to find it."), cfg, TaskContext(), [OK_CALL]
    )
    assert out == "42" and sent == [REFUSAL_RECOVERY_CORRECTION]
    invoke_round, sent = _rounds("42")  # no data to recover from: leave the refusal
    out = await run_answer_pipeline(
        invoke_round, _result("I am unable to find it."), cfg, TaskContext(), [ERR_CALL]
    )
    assert sent == []


# ------------------------------------------------------------------ fact-check


def _checker(reply, prompts=None):
    async def llm(prompt):
        if prompts is not None:
            prompts.append(prompt)
        if isinstance(reply, Exception):
            raise reply
        return reply

    return llm


async def test_fact_check_corrects_from_tool_results_and_canonicalizes():
    prompts = []
    cfg = AdapterConfig(fact_check="verify", canonicalize=True)
    invoke_round, sent = _rounds()
    out = await run_answer_pipeline(
        invoke_round,
        _result("41"),
        cfg,
        TaskContext(),
        [OK_CALL],
        _checker("CORRECTED: [[42]]", prompts),
        question="What is x?",
    )
    assert out == "42" and sent == []
    assert "What is x?" in prompts[0] and 'get_x({"id": 1}) -> {"x": 42}' in prompts[0]


async def test_fact_check_ok_keeps_the_draft_and_failures_never_change_it():
    cfg = AdapterConfig(fact_check="verify")
    for reply in ("OK", "looks fine to me", RuntimeError("proxy down")):
        invoke_round, _ = _rounds()
        out = await run_answer_pipeline(
            invoke_round, _result("42"), cfg, TaskContext(), [OK_CALL], _checker(reply)
        )
        assert out == "42"


async def test_fact_check_missing_reasks_only_in_verify_and_retry_mode():
    invoke_round, sent = _rounds("99")
    out = await run_answer_pipeline(
        invoke_round,
        _result("41"),
        AdapterConfig(fact_check="verify"),
        TaskContext(),
        [OK_CALL],
        _checker("MISSING: the 2008 count"),
    )
    assert out == "41" and sent == []
    invoke_round, sent = _rounds("99")
    out = await run_answer_pipeline(
        invoke_round,
        _result("41"),
        AdapterConfig(fact_check="verify_and_retry"),
        TaskContext(),
        [OK_CALL],
        _checker("MISSING: the 2008 count"),
    )
    assert out == "99" and "the 2008 count" in sent[0]


async def test_fact_check_skips_refusals_and_answers_without_evidence():
    cfg = AdapterConfig(fact_check="verify_and_retry")
    never = _checker(AssertionError("must not be called"))
    for draft, calls in (("I can not answer.", [OK_CALL]), ("42", []), ("42", [ERR_CALL])):
        invoke_round, sent = _rounds()
        assert (
            await run_answer_pipeline(invoke_round, _result(draft), cfg, TaskContext(), calls, never) == draft
        )


def test_parse_fact_check_and_evidence_formatting():
    assert parse_fact_check("CORRECTED: Paris") == ("CORRECTED", "Paris")
    assert parse_fact_check("**MISSING:** the year\nmore") == ("MISSING", "the year")
    assert parse_fact_check("OK") == ("OK", "") and parse_fact_check("") == ("OK", "")
    assert parse_fact_check("CORRECTED:") == ("OK", "")  # nothing to correct with
    calls = [{"tool_name": f"t{i}", "arguments": {}, "result": "r" * 5000} for i in range(30)]
    text = format_tool_evidence(calls)
    assert text.count("\n") == FACT_CHECK_MAX_CALLS - 1 and text.startswith("1. t10(")  # the last 20
    assert max(len(line) for line in text.splitlines()) < 1600  # results truncated
    assert resolve_adapter_config("cap3", env={"M3_ADAPTER_FACT_CHECK": "verify"}).fact_check == "verify"
    with pytest.raises(ValueError):
        resolve_adapter_config("cap3", env={"M3_ADAPTER_FACT_CHECK": "always"})


# --------------------------------------------------------------- infra retries


class APIConnectionError(Exception):
    """Stand-in carrying the openai SDK's class name."""


class _FlakyInner:
    def __init__(self, failures, exc=APIConnectionError("Connection error.")):
        self.failures, self.exc, self.threads = failures, exc, []

    async def invoke(self, message=None, thread_id=None, config=None, **kwargs):
        self.threads.append((thread_id, (config or {}).get("configurable", {}).get("thread_id")))
        if self.failures:
            self.failures -= 1
            raise self.exc
        return SimpleNamespace(answer="42", tool_calls=[], thread_id=thread_id, error=None)


class _Provider:
    async def get_all_tools(self):
        return []


def _agent(cfg, inner):
    return VakraAdapterAgent(inner, cfg, RecordingScopedToolProvider(_Provider()))


async def test_infra_retry_reruns_the_task_on_a_fresh_thread():
    inner = _FlakyInner(failures=1)
    out = await _agent(AdapterConfig(enabled=True, infra_retries=1), inner).invoke(
        "q", thread_id="t", config={"configurable": {"thread_id": "t"}}
    )
    assert out.answer == "42"
    assert inner.threads == [("t", "t"), ("t-retry1", "t-retry1")]


async def test_infra_retry_is_off_by_default_and_never_retries_the_agent_timeout():
    with pytest.raises(APIConnectionError):
        await _agent(AdapterConfig(enabled=True), _FlakyInner(failures=1)).invoke("q", thread_id="t")
    inner = _FlakyInner(failures=1, exc=TimeoutError("agent_timeout 220s exceeded"))
    with pytest.raises(TimeoutError):
        await _agent(AdapterConfig(enabled=True, infra_retries=2), inner).invoke("q", thread_id="t")
    assert len(inner.threads) == 1


def test_transient_errors_are_recognized_through_the_cause_chain():
    try:
        try:
            raise APIConnectionError("Connection error.")
        except APIConnectionError as inner:
            raise RuntimeError("graph failed") from inner
    except RuntimeError as outer:
        assert is_transient_error(outer)
    assert not is_transient_error(ValueError("bad input"))
    assert not is_transient_error(TimeoutError("agent_timeout 220s exceeded"))
