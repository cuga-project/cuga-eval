"""The brief of a rule list on the τ² airline and retail packages and on the best ITSM build (``tools/rule_list_brief.py``).

The check runs with the gate repo's Python, because ``cuga.policy_layer`` is not in this venv. It builds each package through
``build_runtime`` with no model call.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

POLICY_EVAL = Path(__file__).resolve().parents[1]
TOOL = POLICY_EVAL / "tools" / "rule_list_brief.py"
GATE_PYTHON = os.environ.get("POLICY_GATE_PYTHON") or str(Path.home() / "dev/cuga-agent-gate/.venv/bin/python")


@pytest.fixture(scope="module")
def rows():
    done = subprocess.run(
        [GATE_PYTHON, "-I", str(TOOL), "--json"], capture_output=True, text=True, timeout=600
    )
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    data = json.loads(done.stdout)
    return {**{r["package"]: r for r in data["rows"]}, "_trackers": data["trackers"]}


@pytest.mark.skipif(
    not (POLICY_EVAL / "packages/tau2_airline").exists(), reason="the τ² airline package is missing"
)
def test_airline_brief_shows_its_exception_under_the_rule_and_barely_grows(rows):
    row = rows["airline"]
    assert row["exception_links"] == 1
    assert row["measured"]["exception_lines"] == 0
    assert row["rule list"]["exception_lines"] == 1
    assert row["measured"]["guidance_shown"] == 0 and row["rule list"]["guidance_shown"] == 0
    assert row["rule list + guidance"]["guidance_shown"] == row["guidance"] == 4
    # the exception moves under its rule: one item less, one line more, a few characters of indent and label
    assert row["rule list"]["items"] == row["measured"]["items"] - 1
    assert 0 < row["rule list"]["chars"] - row["measured"]["chars"] < 100
    assert row["rule list + guidance"]["chars"] < row["measured"]["chars"] * 1.2


@pytest.mark.skipif(
    not (POLICY_EVAL / "packages/tau2_retail").exists(), reason="the τ² retail package is missing"
)
def test_retail_exceptions_are_folded_so_the_brief_shows_none_and_guidance_adds_three_items(rows):
    # both exception_of links join statements that every rule of the target also holds: the rules have the exception in their own text
    row = rows["retail"]
    assert row["exception_links"] == 2
    assert row["rule list"]["exception_lines"] == 0 and row["rule list"]["chars"] == row["measured"]["chars"]
    assert row["rule list + guidance"]["guidance_shown"] == row["guidance"] == 4
    assert row["rule list + guidance"]["chars"] < row["measured"]["chars"] * 1.2


@pytest.mark.skipif(
    not (POLICY_EVAL / "packages/itsm/e2891a7b98/builds_v4_v4A").exists(), reason="the ITSM build is missing"
)
def test_the_switch_shows_the_22_of_23_guidance_rules_that_never_appeared(rows):
    row = rows["itsm v4A"]
    assert row["guidance"] == 23 and row["guidance_with_tool"] == 1
    assert row["measured"]["guidance_shown"] == 1  # 22 of 23 never appear
    assert row["rule list"]["chars"] == row["measured"]["chars"]  # no exception link in that build: the brief is the same
    assert row["rule list + guidance"]["guidance_shown"] == 23


@pytest.mark.skipif(
    not (POLICY_EVAL / "packages/tau2_airline").exists(), reason="the τ² airline package is missing"
)
def test_a_declared_airline_rule_list_builds_no_pending_check_part(rows):
    row = rows["airline"]
    assert row["measured"]["pending_parts"] == ["ProcedureMonitor"]  # shapes procedures: the monitor of change 87
    assert row["rule list"]["pending_parts"] == [] and row["rule list + guidance"]["pending_parts"] == []
    assert rows["retail"]["rule list"]["pending_parts"] == []


def test_the_sop_tracker_under_auto_needs_a_declared_flow_on_all_15_skill_packages(rows):
    trackers = rows["_trackers"]
    assert len(trackers) == 15
    for t in trackers:
        assert all(t[f"inferred level {n}"] == "off" for n in (1, 2, 3)), t["package"]
        assert t["declared flow level 1"] == "off"
        assert t["declared flow level 2"] == "on" and t["declared flow level 3"] == "on", t["package"]
    assert any("flow" in t["inferred shapes"] for t in trackers)  # the structure says flow for some: it does not count
