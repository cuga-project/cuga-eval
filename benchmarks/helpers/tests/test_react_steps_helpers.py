"""ReAct step helpers used by the eval harness."""

from benchmarks.helpers.react_agent import ReactInvokeResult
from benchmarks.helpers.sdk_eval_helpers import (
    _accumulate_react_steps,
    _react_steps_from_invoke_result,
)


def test_react_steps_from_invoke_result():
    assert _react_steps_from_invoke_result(ReactInvokeResult(answer="ok", react_steps=4)) == 4
    assert _react_steps_from_invoke_result("plain-string") is None


def test_accumulate_react_steps():
    total = 0
    total = _accumulate_react_steps(total, ReactInvokeResult(answer="a", react_steps=3))
    total = _accumulate_react_steps(total, ReactInvokeResult(answer="b", react_steps=2))
    assert total == 5
