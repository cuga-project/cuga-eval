"""Improvements beyond the campaign: require-tool, refusal recovery, fact-check, transport retries."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from benchmarks.m3.adapter.agent import VakraAdapterAgent, is_transient_error
from benchmarks.m3.adapter.config import AdapterConfig, TaskContext, resolve_adapter_config
from benchmarks.m3.adapter.guards import (
    FACT_CHECK_MAX_CALLS,
    REFUSAL_RECOVERY_CORRECTION,
    REQUIRE_TOOL_CORRECTION,
    VALUES_CHECK_CORRECTION,
    format_tool_evidence,
    parse_fact_check,
    run_answer_pipeline,
    unsupported_values,
)
from benchmarks.m3.adapter.recording import RESULT_MAX_CHARS, RecordingScopedToolProvider

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


# ------------------------------------------------------------------ answer distillation


async def test_answer_distill_rewrites_a_prose_draft_to_the_value():
    prompts = []
    invoke_round, sent = _rounds()
    out = await run_answer_pipeline(
        invoke_round,
        _result("The total number of flights on that day was 42 according to the data."),
        AdapterConfig(answer_distill=True),
        TaskContext(),
        [OK_CALL],
        _checker("42", prompts),
        question="How many flights?",
    )
    assert out == "42" and sent == []
    assert "How many flights?" in prompts[0] and 'get_x({"id": 1}) -> {"x": 42}' in prompts[0]


async def test_answer_distill_leaves_refusals_unevidenced_drafts_and_failures_alone():
    cfg = AdapterConfig(answer_distill=True)
    for draft, calls, reply in (
        ("I can not answer.", [OK_CALL], "42"),  # a refusal is not rewritten
        ("42 flights", [], "42"),  # no tool evidence
        ("42 flights", [OK_CALL], RuntimeError("proxy down")),  # the distiller failed
        ("42 flights", [OK_CALL], "I can not answer."),  # the distiller gave up
        ("42 flights", [OK_CALL], "  "),  # empty rewrite
    ):
        invoke_round, _ = _rounds()
        out = await run_answer_pipeline(
            invoke_round, _result(draft), cfg, TaskContext(), calls, _checker(reply)
        )
        assert out == draft


# ------------------------------------------------------------------ values check

COURSES = (
    "{'course_levels': ['Level_300', 'Level_400', 'Level_400']} {'count': 27} {'avg': 651.7844451569706}"
)


def test_unsupported_values_finds_what_no_tool_returned():
    q = "How many courses does professor 331 teach since 2003?"
    assert unsupported_values("5", q + COURSES) == ["5"]  # counted by the model, not returned by a tool
    assert unsupported_values("27", q + COURSES) == []
    assert unsupported_values("651.78", q + COURSES) == []  # a rounding of a returned value
    assert unsupported_values("65178.44", q + COURSES) == ["65178.44"]  # rescaled: not a returned value
    assert unsupported_values("331, 2003", q + COURSES) == []  # values the question states
    assert unsupported_values("Level_300, Level_500", q + COURSES) == ["Level_500"]
    assert unsupported_values("27 courses", q + COURSES) == []  # a unit around a returned number
    assert unsupported_values("Yes", q + COURSES) == []  # yes/no is derived by nature
    sentence = "The professor with the most courses is Douglas Christie with 27 courses in total."
    assert unsupported_values(sentence, q + COURSES) == ["Douglas Christie"]
    assert unsupported_values("1,234", "{'n': 1234}") == []  # thousands separators


async def test_values_check_sends_an_unreturned_value_back_once():
    calls = [{"tool_name": "get_count", "arguments": {"p": 1}, "result": "{'count': 27}"}]
    invoke_round, sent = _rounds("27")
    out = await run_answer_pipeline(
        invoke_round,
        _result("5"),
        AdapterConfig(values_check_rounds=1),
        TaskContext(),
        calls,
        question="How many?",
    )
    assert out == "27"
    assert sent == [VALUES_CHECK_CORRECTION.format(values="5", it="it")]


async def test_values_check_keeps_the_draft_when_the_reask_gives_up_and_skips_what_it_cannot_judge():
    calls = [{"tool_name": "get_count", "arguments": {}, "result": "{'count': 27}"}]
    cfg = AdapterConfig(values_check_rounds=1)
    for reply in ("I can not answer.", ""):
        invoke_round, sent = _rounds(reply)
        assert await run_answer_pipeline(invoke_round, _result("5"), cfg, TaskContext(), calls) == "5"
        assert len(sent) == 1
    big = [{"tool_name": "get_rows", "arguments": {}, "result": "x" * RESULT_MAX_CHARS}]
    for draft, evidence in (("27", calls), ("I can not answer.", calls), ("5", []), ("5", big)):
        invoke_round, sent = _rounds("27")
        assert await run_answer_pipeline(invoke_round, _result(draft), cfg, TaskContext(), evidence) == draft
        assert sent == []  # supported, a refusal, no tool evidence, or a truncated result
    invoke_round, sent = _rounds("27")
    off = AdapterConfig()
    assert (
        await run_answer_pipeline(invoke_round, _result("5"), off, TaskContext(), calls) == "5" and sent == []
    )


# ------------------------------------------------------------------ strict fact-check


async def test_strict_fact_check_keeps_a_correction_drawn_from_outside_the_results():
    """v1 cap3 college_completion: the draft "New Hampshire" (gold) was "corrected" to a name that only
    appeared in a call's arguments. Strict mode keeps the draft; a correction found in the results applies."""
    calls = [
        {
            "tool_name": "get_state",
            "arguments": {"college": "Dartmouth College"},
            "result": "{'state': 'New Hampshire'}",
        }
    ]
    for strict, expected in ((True, "New Hampshire"), (False, "Dartmouth College")):
        invoke_round, _ = _rounds()
        cfg = AdapterConfig(fact_check="verify", fact_check_strict=strict)
        out = await run_answer_pipeline(
            invoke_round,
            _result("New Hampshire"),
            cfg,
            TaskContext(),
            calls,
            _checker("CORRECTED: Dartmouth College"),
            question="Which state?",
        )
        assert out == expected
    calls = [{"tool_name": "get_n", "arguments": {}, "result": "{'count': 8911}"}]
    invoke_round, _ = _rounds()
    cfg = AdapterConfig(fact_check="verify", fact_check_strict=True)
    out = await run_answer_pipeline(
        invoke_round, _result("891891"), cfg, TaskContext(), calls, _checker("CORRECTED: 8911")
    )
    assert out == "8911"  # a garbled copy is still repaired from the results


# ------------------------------------------------------------------ keep the draft on a re-ask timeout


class _HangingFollowUp:
    """First invoke answers "42" with a tool call recorded; every re-ask hangs past the agent timeout."""

    def __init__(self):
        self.calls = 0

    async def invoke(self, message=None, thread_id=None, config=None, **kwargs):
        import asyncio

        self.calls += 1
        if self.calls > 1:
            await asyncio.sleep(30)
        return SimpleNamespace(
            answer="42", tool_calls=[{"name": "d_get_x", "arguments": {}}], thread_id=thread_id, error=None
        )


async def test_a_reask_cut_by_the_timeout_answers_with_the_earlier_draft():
    base = AdapterConfig(enabled=True, agent_timeout=1, require_tool_rounds=1)  # 0 recorded calls -> a re-ask
    out = await _agent(replace(base, keep_draft_on_timeout=True), _HangingFollowUp()).invoke(
        "q", thread_id="t"
    )
    assert out.answer == "42" and out.tool_calls == [{"name": "d_get_x", "arguments": {}}]
    with pytest.raises(TimeoutError):  # off: the task fails empty, as before
        await _agent(base, _HangingFollowUp()).invoke("q", thread_id="t")
