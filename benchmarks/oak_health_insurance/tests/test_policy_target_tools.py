"""Regression test: policy tool-guide ``target_tools`` must match real tool names.

A ToolGuide only attaches when one of its ``target_tools`` matches a runtime
tool name exactly. The registry names oak tools by operationId (e.g.
``oak_health_insurance_get_coverage_period_get_coverage_period_post``), so a
short-form target silently never attaches and the guide's content never reaches
the tool — while the run still reports success.

This test pins every ``target_tools`` entry against the tool names recorded in
the benchmark's own test suite, so a future rename fails here instead of
silently degrading an evaluation run. The runtime guardrail in
``eval_bench_sdk._load_oak_policies`` enforces the same invariant against the
live registry; this is its offline counterpart.
"""

import json
from pathlib import Path
from typing import Set

import pytest

from benchmarks.oak_health_insurance.oak_policies import get_all_oak_policies

pytestmark = pytest.mark.regression

_SUITE = Path(__file__).parent.parent / "oak_health_test_suite_v1.json"
_TOOL_PREFIX = "oak_health_insurance_"


def _real_tool_names() -> Set[str]:
    """Collect the real oak tool names referenced anywhere in the test suite.

    Tool calls in the suite record tools by their runtime name (operationId
    form), so every string that starts with the oak tool prefix is an authentic
    tool name. Task/case names do not carry the prefix and are excluded.
    """
    with open(_SUITE) as f:
        data = json.load(f)

    names: Set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str) and node.startswith(_TOOL_PREFIX):
            names.add(node)

    walk(data)
    return names


def test_suite_exposes_tool_names():
    """Guard the guard: the suite must actually contain oak tool names."""
    assert _real_tool_names(), "No oak tool names found in the test suite; extraction is broken."


def test_policies_define_tool_guides():
    """There should be tool guides with target_tools to validate."""
    guides = [p for p in get_all_oak_policies() if getattr(p, "target_tools", None)]
    assert guides, "No tool-guide policies with target_tools found in oak_policies.py."


def test_every_target_tool_matches_a_real_tool_name():
    """Every target_tools entry must be an actual runtime tool name."""
    real = _real_tool_names()
    unknown = {
        target
        for policy in get_all_oak_policies()
        for target in (getattr(policy, "target_tools", None) or [])
        if target not in real
    }
    assert not unknown, (
        "These policy target_tools do not match any real oak tool name and would "
        f"never attach at runtime: {sorted(unknown)}. "
        f"Known tool names: {sorted(real)}"
    )
