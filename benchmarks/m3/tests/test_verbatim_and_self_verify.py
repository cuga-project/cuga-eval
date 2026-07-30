"""Tests for M3_VERBATIM_RIDER and M3_SELF_VERIFY.

Both ported from cuga_vakra_agent's FULL_GUARDS preset (VAKRA_V2_VERBATIM,
VAKRA_V2_SELF_VERIFY). They target the 24 multi-turn tasks where we called the
right tool, got real data, and were still judged wrong - the only slice of the
multi-turn gap their guard stack plausibly addresses.

Note their own config ships a recommended preset with self-verify OFF ("Preferred
for rate-limited providers"), so it is the least certain of the two and costs one
extra LLM call per task.
"""

import asyncio
import importlib

import pytest

eval_m3 = importlib.import_module("benchmarks.m3.eval_m3")


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    monkeypatch.delenv("M3_VERBATIM_RIDER", raising=False)
    monkeypatch.delenv("M3_SELF_VERIFY", raising=False)


class _Model:
    """Stub judge. `verdict=None` raises, to exercise the fail-open path."""

    def __init__(self, verdict="SUPPORTED"):
        self.verdict = verdict
        self.calls = 0

    async def ainvoke(self, prompt):
        self.calls += 1
        if self.verdict is None:
            raise RuntimeError("judge unavailable")

        class _R:
            content = self.verdict

        return _R()


def _result(answer="Tokyo has 13,960,236 residents.", evidence="Tokyo population 13,960,236"):
    return {
        "response": answer,
        "final_response": answer,
        "all_responses": [{"response": answer}],
        "tool_calls": [{"name": "get_population", "result": evidence}],
    }


def _run(res, model):
    asyncio.run(eval_m3._apply_self_verify(res, model, "test"))
    return res


# --- flags ------------------------------------------------------------------


def test_both_flags_default_off():
    assert eval_m3._verbatim_rider_enabled() is False
    assert eval_m3._self_verify_enabled() is False


@pytest.mark.parametrize("val", ["1", "on", "true", "yes", "ON"])
def test_flags_accepted_forms(monkeypatch, val):
    monkeypatch.setenv("M3_VERBATIM_RIDER", val)
    monkeypatch.setenv("M3_SELF_VERIFY", val)
    assert eval_m3._verbatim_rider_enabled() is True
    assert eval_m3._self_verify_enabled() is True


@pytest.mark.parametrize("val", ["0", "off", "false", "no", "", "junk"])
def test_flags_rejected_forms(monkeypatch, val):
    monkeypatch.setenv("M3_VERBATIM_RIDER", val)
    monkeypatch.setenv("M3_SELF_VERIFY", val)
    assert eval_m3._verbatim_rider_enabled() is False
    assert eval_m3._self_verify_enabled() is False


def test_verbatim_rule_text_is_self_contained():
    """It must state the exact refusal string, since that is what the scorer
    compares against for refusal-ground-truth tasks."""
    assert "I can not answer." in eval_m3.M3_VERBATIM_RULE
    assert "word-for-word" in eval_m3.M3_VERBATIM_RULE
    # And it must push against premature refusal - the opposite pressure from
    # M3_RETRIEVER_ONLY_REFUSAL_RULE, which is why the two are not merged.
    assert "Before refusing" in eval_m3.M3_VERBATIM_RULE


# --- self-verify behaviour --------------------------------------------------


def test_supported_answer_is_untouched():
    r = _run(_result(), _Model("SUPPORTED"))
    assert r["response"] != ""
    assert r["all_responses"][-1]["response"] != ""


def test_unsupported_answer_is_blanked_everywhere():
    r = _run(_result(), _Model("UNSUPPORTED"))
    assert r["response"] == ""
    assert r["final_response"] == ""
    assert r["all_responses"][-1]["response"] == ""


def test_fails_open_when_the_judge_errors():
    """A verification step that deletes answers when the model is unavailable
    would recreate cuga-eval#143 / IBM/vakra#25 - an API failure scored as a
    wrong answer."""
    r = _run(_result(), _Model(None))
    assert r["response"] != ""


def test_fails_open_on_an_unparseable_verdict():
    r = _run(_result(), _Model("I'm not sure, possibly?"))
    assert r["response"] != ""


def test_skipped_when_there_is_no_evidence():
    """No tool results means nothing to verify against - and no LLM call."""
    res = _result(evidence="")
    res["tool_calls"] = []
    m = _Model("UNSUPPORTED")
    _run(res, m)
    assert res["response"] != ""
    assert m.calls == 0


def test_skipped_on_an_already_giveup_answer():
    """Do not spend a call re-verifying a refusal."""
    m = _Model("UNSUPPORTED")
    res = _result(answer="I'm unable to answer that.")
    _run(res, m)
    assert m.calls == 0


def test_skipped_on_an_empty_answer():
    m = _Model("UNSUPPORTED")
    res = _result(answer="")
    res["response"] = res["final_response"] = ""
    res["all_responses"] = [{"response": ""}]
    _run(res, m)
    assert m.calls == 0


def test_one_llm_call_per_task():
    m = _Model("SUPPORTED")
    _run(_result(), m)
    assert m.calls == 1


def test_structured_content_blocks_are_handled():
    """gpt-oss through some proxies returns a block list, not a string."""

    class _BlockModel:
        calls = 0

        async def ainvoke(self, prompt):
            class _R:
                content = [{"type": "text", "text": "UNSUPPORTED"}]

            return _R()

    r = _run(_result(), _BlockModel())
    assert r["response"] == ""
