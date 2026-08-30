"""Unit tests for the RunReceipt -> eval-result flattening helpers.

Covers cuga-eval issue #95: consistent, cache-aware token tracking sourced
from CugaAgent.invoke()'s receipt instead of Langfuse. invoke_result.receipt
is duck-typed (a plain object with the RunReceipt attributes) so these tests
don't need cuga-agent installed with a particular shape beyond attribute names.
"""

from types import SimpleNamespace

import pytest

from benchmarks.helpers.sdk_eval_helpers import (
    _RECEIPT_ACCUMULATION_FAILED,
    _accumulate_receipt_metrics,
    receipt_fields_from_invoke_result,
)

pytestmark = pytest.mark.unit


def _tool_timing(name, calls, total_ms):
    return SimpleNamespace(
        name=name,
        calls=calls,
        total_ms=total_ms,
        model_dump=lambda: {
            "name": name,
            "calls": calls,
            "total_ms": total_ms,
        },
    )


def _receipt(**overrides):
    defaults = dict(
        models=["gpt-oss-120b"],
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        cache_read_tokens=20,
        reasoning_tokens=5,
        llm_calls=3,
        tool_call_count=2,
        llm_time_s=1.5,
        tool_time_s=0.5,
        wall_time_s=2.5,
        slowest_tool="search",
        tool_timings=[_tool_timing("search", 2, 500.0)],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_returns_none_when_invoke_result_has_no_receipt():
    invoke_result = SimpleNamespace(answer="ok")  # no .receipt attribute at all
    assert receipt_fields_from_invoke_result(invoke_result) is None


def test_returns_none_when_receipt_is_none():
    invoke_result = SimpleNamespace(answer="ok", receipt=None)
    assert receipt_fields_from_invoke_result(invoke_result) is None


def test_flattens_all_receipt_fields():
    invoke_result = SimpleNamespace(answer="ok", receipt=_receipt())
    fields = receipt_fields_from_invoke_result(invoke_result)

    assert fields["token_source"] == "receipt"
    # Existing/reused keys
    assert fields["total_tokens"] == 150
    assert fields["total_llm_calls"] == 3
    assert fields["total_cache_input_tokens"] == 20
    # New keys
    assert fields["input_tokens"] == 100
    assert fields["output_tokens"] == 50
    assert fields["cache_read_tokens"] == 20
    assert fields["reasoning_tokens"] == 5
    assert fields["tool_call_count"] == 2
    assert fields["llm_time_s"] == 1.5
    assert fields["tool_time_s"] == 0.5
    assert fields["wall_time_s"] == 2.5
    assert fields["models"] == ["gpt-oss-120b"]
    assert fields["slowest_tool"] == "search"
    assert fields["tool_timings"] == [{"name": "search", "calls": 2, "total_ms": 500.0}]


def test_full_execution_time_mirrors_wall_time_s():
    """cuga-eval#95 regression: report.md's Total Duration column reads
    r.get("full_execution_time") or r.get("duration"); without this key the
    receipt path silently renders "--" for every run."""
    invoke_result = SimpleNamespace(answer="ok", receipt=_receipt(wall_time_s=2.5))
    fields = receipt_fields_from_invoke_result(invoke_result)

    assert fields["full_execution_time"] == 2.5
    assert fields["full_execution_time"] == fields["wall_time_s"]


def test_accumulate_sums_across_turns():
    r1 = SimpleNamespace(
        answer="a",
        receipt=_receipt(total_tokens=100, input_tokens=70, output_tokens=30, wall_time_s=1.5),
    )
    r2 = SimpleNamespace(
        answer="b",
        receipt=_receipt(total_tokens=50, input_tokens=30, output_tokens=20, wall_time_s=1.0),
    )

    acc = _accumulate_receipt_metrics(None, r1)
    acc = _accumulate_receipt_metrics(acc, r2)

    assert acc["total_tokens"] == 150
    assert acc["input_tokens"] == 100
    assert acc["output_tokens"] == 50
    assert acc["total_llm_calls"] == 6  # 3 + 3
    assert acc["models"] == ["gpt-oss-120b"]  # deduped, not doubled
    # Same tool name ("search") in both turns' default tool_timings merges
    # into one entry, calls/total_ms summed -- not concatenated per-turn
    # (Sergey review, PR #182 follow-up).
    assert len(acc["tool_timings"]) == 1
    assert acc["tool_timings"][0] == {"name": "search", "calls": 4, "total_ms": 1000.0}
    assert acc["full_execution_time"] == pytest.approx(2.5)  # 1.5 + 1.0, summed like wall_time_s


def test_accumulate_merges_slowest_tool_across_turns_by_name():
    """A tool called once per turn must rank by its summed total_ms across
    turns, not by any single turn's entry -- otherwise a tool called once for
    150ms outranks one called 3x for 100ms each (300ms total), the exact
    inversion cuga-agent's build_run_receipt avoids by merging timings by
    name before picking the max (Sergey review, PR #182 follow-up)."""
    turns = [
        _receipt(tool_timings=[_tool_timing("frequent", 1, 100.0), _tool_timing("rare", 1, 150.0)]),
        _receipt(tool_timings=[_tool_timing("frequent", 1, 100.0)]),
        _receipt(tool_timings=[_tool_timing("frequent", 1, 100.0)]),
    ]

    acc = None
    for r in turns:
        acc = _accumulate_receipt_metrics(acc, SimpleNamespace(answer="x", receipt=r))

    timings_by_name = {t["name"]: t for t in acc["tool_timings"]}
    assert timings_by_name["frequent"] == {"name": "frequent", "calls": 3, "total_ms": 300.0}
    assert timings_by_name["rare"] == {"name": "rare", "calls": 1, "total_ms": 150.0}
    assert acc["slowest_tool"] == "frequent"


def test_accumulate_returns_failure_sentinel_once_any_turn_lacks_a_receipt():
    """Once any turn lacks a receipt, accumulation permanently gives up —
    represented by a dedicated sentinel distinct from None (cuga-eval#182
    CodeRabbit review), not by None itself. Callers should treat anything
    that isn't a dict (None or the sentinel) as "no valid receipt"."""
    r1 = SimpleNamespace(answer="a", receipt=_receipt())
    r2 = SimpleNamespace(answer="b", receipt=None)

    acc = _accumulate_receipt_metrics(None, r1)
    acc = _accumulate_receipt_metrics(acc, r2)

    assert acc is _RECEIPT_ACCUMULATION_FAILED
    assert not isinstance(acc, dict)


def test_accumulate_stays_failed_once_a_later_turn_has_a_receipt_again():
    """Regression for the bug this sentinel fixes: turn 1 has a receipt,
    turn 2 does not (accumulation fails), turn 3 has one again. Before the
    fix, turn 3 saw ``acc is None`` and wrongly started a brand-new,
    turn-3-only total. Now the failure is permanent: turn 3's receipt must
    not resurrect a partial total."""
    r1 = SimpleNamespace(answer="a", receipt=_receipt())
    r2 = SimpleNamespace(answer="b", receipt=None)
    r3 = SimpleNamespace(answer="c", receipt=_receipt())

    acc = _accumulate_receipt_metrics(None, r1)
    acc = _accumulate_receipt_metrics(acc, r2)
    acc = _accumulate_receipt_metrics(acc, r3)

    assert acc is _RECEIPT_ACCUMULATION_FAILED
    assert not isinstance(acc, dict)
