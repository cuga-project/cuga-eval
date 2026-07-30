"""Tests for M3_POLICY_SCOPE_ABSOLUTE_ONLY (eval_m3.resolve_policy_tool_scope).

Context: measured head-to-head on the same 300 tasks, same evaluator and same
judge, cuga_vakra_agent beats us 206-186, and 12 of that 20-task gap is
single-turn - where they score 0.95, our no-scoping baseline scored 0.96, and our
current scoped config scores 0.86. Their change log states the design difference:
deterministic pruning for absolute rules only, conditional rules left
prompt-enforced. This flag makes that behaviour available for A/B.
"""

import asyncio
import importlib

import pytest

eval_m3 = importlib.import_module("benchmarks.m3.eval_m3")

ABSOLUTE = "Use document retrievers to answer questions. Do not use any other type of tool."
ABSOLUTE_NEGATIVE = "Do not use document retrievers to answer questions."
CONDITIONAL = (
    "If a user's query pertains to Sports & Athletics, which is/are about Topics covering "
    "various sports, athletes, games, and statistics, make sure you try answering them by "
    "only using document retrievers. Do not use other types of tools."
)


class _YesModel:
    """Topic classifier that always says the query is on-topic - the case where
    conditional scoping would prune."""

    async def ainvoke(self, prompt):
        class _R:
            content = "YES"

        return _R()


def _resolve(policy, query="who scored the most goals", model=None):
    return asyncio.run(eval_m3.resolve_policy_tool_scope(model or _YesModel(), policy, query))


@pytest.fixture(autouse=True)
def _clear_flag(monkeypatch):
    monkeypatch.delenv("M3_POLICY_SCOPE_ABSOLUTE_ONLY", raising=False)


def test_default_is_off():
    """Off by default: the current 300-task run's configuration must be
    unaffected until the flag is set explicitly."""
    assert eval_m3._policy_scope_absolute_only() is False
    assert _resolve(CONDITIONAL) == "retriever_only"


@pytest.mark.parametrize("val", ["1", "on", "true", "yes", "ON", "True"])
def test_flag_accepted_forms(monkeypatch, val):
    monkeypatch.setenv("M3_POLICY_SCOPE_ABSOLUTE_ONLY", val)
    assert eval_m3._policy_scope_absolute_only() is True


@pytest.mark.parametrize("val", ["0", "off", "false", "no", "", "garbage"])
def test_flag_rejected_forms(monkeypatch, val):
    monkeypatch.setenv("M3_POLICY_SCOPE_ABSOLUTE_ONLY", val)
    assert eval_m3._policy_scope_absolute_only() is False


def test_conditional_stops_pruning_when_on(monkeypatch):
    """The whole point: a conditional rule that WOULD prune (classifier says
    on-topic) must resolve to 'all' instead."""
    assert _resolve(CONDITIONAL) == "retriever_only"
    monkeypatch.setenv("M3_POLICY_SCOPE_ABSOLUTE_ONLY", "1")
    assert _resolve(CONDITIONAL) == "all"


def test_absolute_still_prunes_when_on(monkeypatch):
    """Absolute rules must be unaffected - this is not 'disable scoping'."""
    monkeypatch.setenv("M3_POLICY_SCOPE_ABSOLUTE_ONLY", "1")
    assert _resolve(ABSOLUTE) == "retriever_only"
    assert _resolve(ABSOLUTE_NEGATIVE) == "no_retriever"


def test_no_policy_is_unscoped_either_way(monkeypatch):
    for mode in ("0", "1"):
        monkeypatch.setenv("M3_POLICY_SCOPE_ABSOLUTE_ONLY", mode)
        assert _resolve("") == "all"
        assert _resolve("Answer concisely.") == "all"


def test_conditional_skips_the_classifier_when_on(monkeypatch):
    """Under the flag the topic classifier must not be consulted at all - it is
    an LLM call per task, and its result cannot change the outcome."""
    called = {"n": 0}

    class _Counting(_YesModel):
        async def ainvoke(self, prompt):
            called["n"] += 1
            return await super().ainvoke(prompt)

    monkeypatch.setenv("M3_POLICY_SCOPE_ABSOLUTE_ONLY", "1")
    assert _resolve(CONDITIONAL, model=_Counting()) == "all"
    assert called["n"] == 0

    monkeypatch.setenv("M3_POLICY_SCOPE_ABSOLUTE_ONLY", "0")
    assert _resolve(CONDITIONAL, model=_Counting()) == "retriever_only"
    assert called["n"] == 1


def test_unknown_policy_shape_fails_open(monkeypatch):
    """Every one of the 25 distinct policy strings in the full 664-task cap4 set
    is a retriever rule, but a future shape must not be silently pruned on."""
    for mode in ("0", "1"):
        monkeypatch.setenv("M3_POLICY_SCOPE_ABSOLUTE_ONLY", mode)
        assert _resolve("Always cite your sources and never guess.") == "all"


# --- the refusal rider must survive absolute-only mode -----------------------
#
# Regression guard for a bug found live: M3_RETRIEVER_ONLY_REFUSAL_RIDER was
# gated on the RESOLVED SCOPE (`scope == "retriever_only"`). Once
# M3_POLICY_SCOPE_ABSOLUTE_ONLY made conditional rules resolve to "all", the
# rider silently stopped firing on exactly those tasks - so the flag removed
# deterministic pruning AND the instruction to decline without naming tools.
# Observed: a refusal trap answered "Evidence: The bike-share query tool
# (bike_share_1_query_bike_share_1) returned only general documents...".
# The gate is now on the policy text instead.


def test_conditional_policy_still_requires_retriever_only():
    """The restricting clause is identical in conditional and absolute rules -
    only the 'if a user's query pertains to X' preamble differs - so the rider
    must recognise both."""
    assert eval_m3._policy_requires_retriever_only(CONDITIONAL) is True
    assert eval_m3._policy_requires_retriever_only(ABSOLUTE) is True


def test_negative_and_empty_policies_do_not_require_retriever_only():
    assert eval_m3._policy_requires_retriever_only(ABSOLUTE_NEGATIVE) is False
    assert eval_m3._policy_requires_retriever_only("") is False
    assert eval_m3._policy_requires_retriever_only(None) is False
    assert eval_m3._policy_requires_retriever_only("Answer concisely.") is False


def test_rider_condition_holds_when_absolute_only_resolves_to_all(monkeypatch):
    """The scenario that broke: conditional policy, absolute-only on, so scope
    is 'all' - the rider must still apply."""
    monkeypatch.setenv("M3_POLICY_SCOPE_ABSOLUTE_ONLY", "1")
    scope = _resolve(CONDITIONAL)
    assert scope == "all"
    assert scope == "retriever_only" or eval_m3._policy_requires_retriever_only(CONDITIONAL)
