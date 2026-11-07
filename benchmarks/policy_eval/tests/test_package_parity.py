"""The package path gives the same results as the old path on real data (``tools/package_parity.py``).

The checks run with the gate repo's Python, because ``cuga.policy_layer`` is not in this venv.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

POLICY_EVAL = Path(__file__).resolve().parents[1]
TOOL = POLICY_EVAL / "tools" / "package_parity.py"
GATE_PYTHON = os.environ.get("POLICY_GATE_PYTHON") or str(Path.home() / "dev/cuga-agent-gate/.venv/bin/python")


def run_check(check):
    done = subprocess.run([GATE_PYTHON, "-I", str(TOOL), check], capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    return done.stdout


@pytest.mark.skipif(
    not list((POLICY_EVAL / "graphs_handbook" / "claude_v1").glob("*.json"))
    or not (POLICY_EVAL / "packages" / "handbook").exists(),
    reason="HANDBOOK graphs or packages are missing",
)
def test_procedure_store_text_is_the_same_from_the_graph_and_from_the_package():
    out = run_check("store")
    assert len([x for x in out.splitlines() if "differ 0" in x]) >= 3
    assert "store differences: 0" in out


@pytest.mark.skipif(
    not (POLICY_EVAL / "packages" / "itsm").exists() or not (POLICY_EVAL / "builds_v4").exists(),
    reason="converted packages or builds are missing",
)
def test_rule_outcomes_are_the_same_from_the_build_and_from_the_package():
    out = run_check("rules")
    assert int(re.search(r"(\d+) builds", out).group(1)) >= 42
    assert "raised calls: 0" in out
    assert "rule differences: 0" in out
    assert re.search(r"rules that fire under breaking_call: \d+ of \d+", out)


@pytest.mark.skipif(
    not (POLICY_EVAL / "packages" / "handbook").exists() or not (POLICY_EVAL / "packages" / "itsm").exists(),
    reason="converted packages are missing",
)
def test_store_gate_builds_only_from_packages_it_can_check():
    out = run_check("gate")
    built = re.search(r"gates that build: (\d+); packages that raise: (\d+)", out)
    assert int(built.group(1)) >= 3 and int(built.group(2)) >= 34
    assert "gate differences: 0" in out


@pytest.mark.skipif(not (POLICY_EVAL / "packages").exists(), reason="converted packages are missing")
def test_the_gate_scope_from_routers_is_the_scope_the_gate_always_had_on_every_package():
    out = run_check("scope")
    found = re.search(r"(\d+) packages, (\d+) comparisons, (\d+) rule lines, scope differences: (\d+)", out)
    assert found, out
    assert int(found.group(1)) >= 80 and int(found.group(2)) >= 2000 and int(found.group(3)) >= 5000
    assert found.group(4) == "0"


@pytest.mark.skipif(not (POLICY_EVAL / "packages").exists(), reason="converted packages are missing")
def test_k_hops_has_something_to_walk_on_the_skill_packages_that_link_and_nothing_on_the_hand_built_graphs():
    out = run_check("hops")
    pairs = {
        m.group(1): int(m.group(2))
        for m in re.finditer(r"^(\S+/skill_v1)\s+procedures\s+\d+\s+pairs\s+(\d+)\s+gate True", out, re.M)
    }
    assert pairs == {
        "handbook/hr_crestwood_university_79786c46/skill_v1": 1,
        "handbook/insurance_vanguard_shield_mutual_9b2f7a29/skill_v1": 12,
        "handbook/medical_careig_specialty_pharmacy_f5947c33/skill_v1": 8,
        "tau2_retail/retail/skill_v1": 2,
    }
    assert "claude_v1" not in out  # the hand-built graphs have no link to walk
    found = re.search(
        r"(\d+) packages with procedures, (\d+) with a pair to walk and (\d+) where one hop adds a procedure; "
        r"the gate builds on (\d+), and (\d+) of those have a pair; hop differences: (\d+)",
        out,
    )
    assert found and found.group(1) == "49" and found.group(2) == found.group(3) == "8"
    assert (found.group(4), found.group(5), found.group(6)) == ("18", "4", "0")
