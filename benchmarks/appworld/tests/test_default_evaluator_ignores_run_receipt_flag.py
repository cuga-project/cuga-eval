"""Verifies DYNACONF_ADVANCED_FEATURES__RUN_RECEIPT is harmless for the
default (non ``--sdk``) AppWorld evaluator (cuga-eval#95, Sergey's review
comment on eval.sh unconditionally exporting the flag).

``benchmarks/appworld/appworld_eval.py``'s ``run_agent_on_task`` routes
through ``cuga.backend.cuga_graph.utils.controller.AgentRunner.
run_task_generic`` — a completely different code path from
``CugaAgent.invoke()``, which is the only place a ``RunReceipt`` is ever
built. The controller module has zero references to
``run_receipt``/``RunMetricsCollector``/``RunReceipt``, so the flag exported
unconditionally by ``eval.sh`` is structurally unreachable from this path.
These tests pin that fact rather than just asserting it in a comment.
"""

from __future__ import annotations

import inspect

import pytest

pytest.importorskip(
    "appworld",
    reason="AppWorld package not installed; run ./setup_appworld.sh to enable this test.",
)

pytestmark = pytest.mark.unit


def test_default_evaluator_imports_cleanly_with_run_receipt_flag_set(monkeypatch):
    """Importing the default evaluator module with the flag set must not
    error, and its entry point must remain present and callable — the flag
    should have zero observable effect on this module."""
    monkeypatch.setenv("DYNACONF_ADVANCED_FEATURES__RUN_RECEIPT", "true")

    from benchmarks.appworld import appworld_eval

    assert callable(appworld_eval.run_agent_on_task)
    assert inspect.iscoroutinefunction(appworld_eval.run_agent_on_task)


def test_agent_runner_controller_has_no_run_receipt_references():
    """Pins the structural fact this fix relies on: the graph-based
    AgentRunner controller (used by the default evaluator's
    ``run_task_generic`` call) never references run_receipt /
    RunMetricsCollector / RunReceipt, so the flag genuinely cannot reach it
    regardless of how it's set."""
    from cuga.backend.cuga_graph.utils import controller

    source = inspect.getsource(controller)
    for needle in ("run_receipt", "RunMetricsCollector", "RunReceipt"):
        assert needle not in source, (
            f"controller.py now references {needle!r} — DYNACONF_ADVANCED_FEATURES__RUN_RECEIPT "
            "may no longer be harmless for the default AppWorld evaluator; re-examine eval.sh."
        )
