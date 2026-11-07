"""The ledger reads every obligation of the 15 ``skill_v1`` packages (``tools/obligation_shapes.py``), offline.

These packages were written before the ledger existed, so this is the check that their shapes fit it. The code is in the gate
repo, so the tool runs with the gate repo's Python. With ``EVAL_NO_SKIP=1`` a missing input is a failure, not a skip.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

POLICY_EVAL = Path(__file__).resolve().parents[1]
GATE_PYTHON = os.environ.get("POLICY_GATE_PYTHON") or str(
    Path.home() / "dev/cuga-agent-gate/.venv/bin/python"
)
TOOL = POLICY_EVAL / "tools" / "obligation_shapes.py"


def missing_input(reason):
    if os.environ.get("EVAL_NO_SKIP"):
        pytest.fail(f"EVAL_NO_SKIP is set: {reason}")
    pytest.skip(reason)


@pytest.fixture(scope="module")
def shapes():
    if not Path(GATE_PYTHON).is_file():
        missing_input(f"the gate repo's Python is missing: {GATE_PYTHON}")
    done = subprocess.run([GATE_PYTHON, "-I", str(TOOL)], capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stdout[-2500:] + done.stderr[-3500:]
    return json.loads(done.stdout)


def test_all_15_packages_go_through_the_ledger_with_no_raise(shapes):
    assert shapes["errors"] == []
    assert shapes["packages"] == 15
    assert shapes["obligations"] == sum(row["obligations"] for row in shapes["rows"]) > 0
    assert all(row["final_reply"]["items"] > 0 for row in shapes["rows"])


def test_a_call_written_from_a_pattern_meets_it_or_is_unknown_when_its_value_has_no_code(shapes):
    for row in shapes["rows"]:
        for miss in row["not_met"]:
            assert miss["status"] == "unknown", (row["package"], miss)
            assert row["gaps"].get("computed_no_code"), (row["package"], miss)


def test_what_the_ledger_cannot_check_has_a_name_for_each_reason(shapes):
    assert set(shapes["gaps"]) <= {"code_tool_no_pattern", "computed_no_code", "file_no_tool", "reply_no_tool"}


def test_the_cards_of_a_package_fit_in_one_binding_call(shapes):
    assert all(row["cards_chars"] < 40_000 for row in shapes["rows"])


def test_the_producer_package_gives_every_obligation_and_the_ones_of_each_case(shapes):
    """The tool asserts it per package (``obligations_from_package`` equals the package's list; a case gets only its own
    procedure's items and the cross-cutting ones), so a violation is an error here."""
    assert shapes["errors"] == []
    assert all(row["obligations"] > 0 for row in shapes["rows"])


def test_the_limits_of_the_old_packages_are_counted_for_the_replay(shapes):
    """The skill now says: a file obligation lists every tool that can write a file, and a tool the agent does not have gets
    no obligation. The 15 packages were made before that. Task 4.3 carries these counts as a known limit."""
    assert shapes["limits"] == {"code_only_with_file_tool": 138, "user_tool_only": 17}
    where = {row["package"]: row["limits"] for row in shapes["rows"] if any(row["limits"].values())}
    assert set(where) == {
        "handbook/hr_crestwood_university_79786c46",
        "handbook/insurance_vanguard_shield_mutual_9b2f7a29",
        "handbook/medical_careig_specialty_pharmacy_f5947c33",
        "tau2_telecom/telecom",
    }


def test_the_procedure_monitor_makes_no_empty_or_conditional_line_on_any_of_the_15_packages():
    """The monitor on a package written from a skill: after each tool of each step, every line of its brief and its reply has a
    description, and none is a conditional step or a reply (which no tool call can show done)."""
    if not Path(GATE_PYTHON).is_file():
        missing_input(f"the gate repo's Python is missing: {GATE_PYTHON}")
    code = r"""
import json, sys
from pathlib import Path
from cuga.policy_layer.package import load_package
from cuga.policy_layer.procedure_monitor import ProcedureMonitor
bad, lines, packages = [], 0, 0
for path in sorted(Path(sys.argv[1]).glob("*/*/skill_v1/package.json")):
    pkg = load_package(path)
    packages += 1
    for proc in pkg.procedures:
        for step in proc.steps:
            if not step.action:
                continue
            monitor = ProcedureMonitor(pkg.procedures)
            monitor.after_tool_call(step.action, {}, {"ok": True})
            messages = [monitor.before_llm_call(None).message, monitor.before_reply("done").message]
            text = "\n".join(m or "" for m in messages)
            for message in messages:
                for line in (message or "").splitlines()[1:]:
                    lines += 1
                    shown = line.split("] ", 1)[-1].rsplit(" (`", 1)[0].strip()
                    if not shown:
                        bad.append(f"{path.parts[-3]}: an empty line {line!r}")
            for p in pkg.procedures:
                for s in p.steps:
                    if (s.condition or s.action == "reply") and s.text and f"] {s.text} (`" in text:
                        bad.append(f"{path.parts[-3]}: a line for the step {s.id} of {p.id}: {s.text[:60]}")
print(json.dumps({"packages": packages, "lines": lines, "bad": bad[:10]}))
"""
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", code, str(POLICY_EVAL / "packages")], capture_output=True, text=True, timeout=600
    )
    assert done.returncode == 0, done.stdout[-1500:] + done.stderr[-2500:]
    out = json.loads(done.stdout)
    assert out["packages"] == 15 and out["lines"] > 0 and out["bad"] == []


def test_the_procedure_monitor_is_unchanged_on_the_packages_of_measured_profiles():
    """Base commit and head give the same brief, reply and records on builds, v3, v4, Telecom builds and the pipeline packages."""
    if not Path(GATE_PYTHON).is_file():
        missing_input(f"the gate repo's Python is missing: {GATE_PYTHON}")
    done = subprocess.run(
        [GATE_PYTHON, "-I", str(POLICY_EVAL / "tools" / "monitor_base_vs_head.py")],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert done.returncode == 0, done.stdout[-1500:] + done.stderr[-2500:]
    assert "differences 0" in done.stdout and "packages 0" not in done.stdout
