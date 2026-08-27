"""Unit tests for the RunReceipt -> eval-result flattening helpers.

Covers cuga-eval issue #95: consistent, cache-aware token tracking sourced
from CugaAgent.invoke()'s receipt instead of Langfuse. invoke_result.receipt
is duck-typed (a plain object with the RunReceipt attributes) so these tests
don't need cuga-agent installed with a particular shape beyond attribute names.
"""

from types import SimpleNamespace

import pytest

from benchmarks.helpers.sdk_eval_helpers import (
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


def test_accumulate_sums_across_turns():
    r1 = SimpleNamespace(answer="a", receipt=_receipt(total_tokens=100, input_tokens=70, output_tokens=30))
    r2 = SimpleNamespace(answer="b", receipt=_receipt(total_tokens=50, input_tokens=30, output_tokens=20))

    acc = _accumulate_receipt_metrics(None, r1)
    acc = _accumulate_receipt_metrics(acc, r2)

    assert acc["total_tokens"] == 150
    assert acc["input_tokens"] == 100
    assert acc["output_tokens"] == 50
    assert acc["total_llm_calls"] == 6  # 3 + 3
    assert acc["models"] == ["gpt-oss-120b"]  # deduped, not doubled
    assert len(acc["tool_timings"]) == 2  # one per turn, concatenated


def test_accumulate_returns_none_once_any_turn_lacks_a_receipt():
    r1 = SimpleNamespace(answer="a", receipt=_receipt())
    r2 = SimpleNamespace(answer="b", receipt=None)

    acc = _accumulate_receipt_metrics(None, r1)
    acc = _accumulate_receipt_metrics(acc, r2)

    assert acc is None
