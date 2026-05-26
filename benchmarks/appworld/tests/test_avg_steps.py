"""Regression test for issue #50.

Symptom: bundle summaries reported ``avg_steps = 0`` for every CUGA run.

Root cause (per issue #50): the cuga-agent ActivityTracker doesn't
increment ``actions_count`` and rarely calls ``collect_step``, so
``len(tracker.steps)`` is ~0 by the time the eval driver assigns
``task_result.steps``. Meanwhile, the agent runner returns a ``result``
whose ``.steps`` list contains every graph-node execution (planning,
reasoning, code, api_call, final answer) — but the eval loop filters
``result.steps`` to api_call-only *before* using its length, so the
"steps" metric collapses to the api_call count and the bundle's
avg_steps tally never accumulates anything useful.

Fix (in benchmarks/appworld/appworld_eval.py):

1. Capture ``total_steps = len(result.steps)`` **before** the api_call
   filtering line.
2. Use ``total_steps`` for both ``num_steps`` (passed to
   ``tracker.finish_task``) and ``task_result.steps`` (consumed by the
   experiment-manager summary that computes avg_steps).

This is a local mitigation. The proper fix lives upstream in cuga-agent
(incrementing ``actions_count`` from the graph nodes), but that's
out-of-tree for this repo and the local fix is enough to make
avg_steps meaningful again.

These AST-based tests assert the exact source structure required by the
fix — they fail before the fix is applied and pass after.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

_APPWORLD_EVAL = Path(__file__).resolve().parents[1] / "appworld_eval.py"


@pytest.fixture(scope="module")
def source() -> str:
    return _APPWORLD_EVAL.read_text()


@pytest.fixture(scope="module")
def tree(source) -> ast.Module:
    return ast.parse(source)


def _line_of(node: ast.AST) -> int:
    return getattr(node, "lineno", -1)


def _find_assign_to(tree: ast.Module, target_name: str) -> list[ast.Assign]:
    """All top-level assignments of the form ``<target_name> = <expr>`` in
    the module's body or any nested function body. Useful for catching
    statements regardless of indentation."""
    hits: list[ast.Assign] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id == target_name:
                hits.append(node)
            elif isinstance(tgt, ast.Attribute) and tgt.attr == target_name:
                hits.append(node)
    return hits


def test_total_steps_is_captured_before_filtering(tree):
    """``total_steps = len(result.steps)`` must come before
    ``filtered_steps = [step for step in result.steps if ...]``. If the
    order is reversed, the capture sees the already-filtered list and
    the fix is a no-op."""
    total_lines = [_line_of(n) for n in _find_assign_to(tree, "total_steps")]
    filtered_lines = [_line_of(n) for n in _find_assign_to(tree, "filtered_steps")]

    assert total_lines, "total_steps is never assigned — issue #50 fix missing"
    assert filtered_lines, "filtered_steps assignment removed?"

    # Pick the assignment of total_steps that is followed by a filtered_steps
    # assignment within the next ~10 lines (i.e. the cuga-task path; ignore
    # any helper code that might also use the name).
    pair_found = any(any(0 < f - t <= 20 for f in filtered_lines) for t in total_lines)
    assert pair_found, (
        "total_steps must be captured immediately before filtered_steps — "
        "if it's captured after the filter, the value is wrong (issue #50)."
    )


def test_task_result_steps_uses_total_steps_not_tracker(source):
    """``task_result.steps = len(tracker.steps)`` is the original bad
    pattern (cuga-agent never accumulates tracker.steps for this path,
    so it produces ~0). After the fix, the assignment uses ``total_steps``."""
    assert "task_result.steps = len(tracker.steps)" not in source, (
        "appworld_eval.py still assigns task_result.steps = len(tracker.steps) — "
        "this is the original avg_steps=0 bug (issue #50)."
    )
    assert "task_result.steps = total_steps" in source, (
        "Expected `task_result.steps = total_steps` in the cuga path — "
        "this is the avg_steps fix for issue #50."
    )


def test_num_steps_uses_total_steps_not_filtered(source):
    """``num_steps=len(result.steps)`` after the filter would pass the
    api_call count, not the total step count. After the fix the kwarg
    uses ``total_steps``."""
    assert "num_steps=total_steps" in source, (
        "Expected `num_steps=total_steps` in tracker.finish_task — issue #50 fix missing."
    )
    # Defensive: the legacy `num_steps=len(result.steps)` should be gone
    # (post-filter, this was the api_call count masquerading as steps).
    assert "num_steps=len(result.steps)" not in source, (
        "appworld_eval.py still passes num_steps=len(result.steps) after the "
        "api_call filter — this is the bug pattern from issue #50."
    )


def test_total_steps_initialised_outside_try(tree, source):
    """The capture lives inside a ``try`` block that may raise before
    reaching it. ``total_steps`` must be initialised to 0 outside the try
    so the exception-path code that consumes it doesn't NameError."""
    # AST check: there is an assignment ``total_steps = 0`` somewhere.
    init_assigns = [
        a
        for a in _find_assign_to(tree, "total_steps")
        if isinstance(a.value, ast.Constant) and a.value.value == 0
    ]
    assert init_assigns, (
        "total_steps must be initialised to 0 outside the try block so the "
        "exception-handling code can still reference it (issue #50)."
    )
