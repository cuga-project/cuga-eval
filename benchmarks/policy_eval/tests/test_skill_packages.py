"""The packages that fresh agents made with the skill (``packages/*/*/skill_v1``) validate with no error and run.

A package that validates but does not run is a failure, so each one is also built with ``build_runtime`` (no agent, no model:
``RecordingModels`` raises when called) on the gate profile, a guide profile and the rules profile. The code is in the gate repo,
so the checks run with the gate repo's Python. With ``EVAL_NO_SKIP=1`` a missing input is a failure, not a skip.
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
TOOLS = POLICY_EVAL / "tools"
SKILL_PACKAGES = sorted((POLICY_EVAL / "packages").glob("*/*/skill_v1/package.json"))
EXPECTED = {"handbook": 3, "itsm": 9, "tau2_airline": 1, "tau2_retail": 1, "tau2_telecom": 1}


def missing_input(reason):
    if os.environ.get("EVAL_NO_SKIP"):
        pytest.fail(f"EVAL_NO_SKIP is set: {reason}")
    pytest.skip(reason)


def run_python(code, *args):
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", code, str(TOOLS), *args], capture_output=True, text=True, timeout=900
    )
    assert done.returncode == 0, done.stdout[-2500:] + done.stderr[-3500:]
    return done.stdout


def need_gate():
    if not Path(GATE_PYTHON).is_file():
        missing_input(f"the gate repo's Python is missing: {GATE_PYTHON}")


def test_the_expected_skill_packages_are_there():
    found = {}
    for path in SKILL_PACKAGES:
        found[path.parts[-4]] = found.get(path.parts[-4], 0) + 1
        for kept in ("draft.json", "set.json"):
            assert (path.parent / kept).is_file(), f"{path}: {kept} is kept beside the package"
    assert found == EXPECTED


VALIDATE = r"""
import json, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, sys.argv[1])
import validate_all
from cuga.policy_layer.package import load_package
from cuga.policy_layer.validate import validate_package

out = {}
for path in sorted(validate_all.PACKAGES.glob("*/*/skill_v1/package.json")):
    bench, policy = path.parts[-4], path.parts[-3]
    specs = validate_all.specs_of(bench, policy)
    assert specs, f"no tool specs for {bench}/{policy}: the tool checks would be skipped"
    found = validate_package(load_package(path), specs, legacy=False)
    out[f"{bench}/{policy}"] = sorted({f"{f.code}:{f.message[:120]}" for f in found if f.severity == "error"})
print(json.dumps(out))
"""


def test_every_skill_package_validates_with_no_error_as_a_new_package():
    need_gate()
    if not SKILL_PACKAGES:
        missing_input("no skill_v1 package")
    errors = json.loads(run_python(VALIDATE).strip().splitlines()[-1])
    assert len(errors) == sum(EXPECTED.values())
    assert {k: v for k, v in errors.items() if v} == {}


BUILD = r"""
import json, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, sys.argv[1])
import runtime_check

rows = []
for bench, policy, path in runtime_check.combinations("skill_v1"):
    rows += runtime_check.check(bench, policy, path)
print(json.dumps(rows))
"""
WANTED = {"gate": {"gate", "procedure_tools"}, "guide": {"guide", "loop"}, "rules": {"rules"}}


def test_every_skill_package_builds_on_the_gate_a_guide_and_the_rules_profile():
    need_gate()
    if not SKILL_PACKAGES:
        missing_input("no skill_v1 package")
    rows = json.loads(run_python(BUILD).strip().splitlines()[-1])
    assert len(rows) == 3 * sum(EXPECTED.values())
    assert [r for r in rows if r["raised"]] == []
    for r in rows:  # a build that wires nothing is not a run
        assert WANTED[r["profile"]] <= set(r["components"]), r


def test_the_conversion_has_no_source_for_skill_packages_so_it_cannot_write_or_drop_them():
    need_gate()
    code = r"""
import sys
sys.path.insert(0, sys.argv[1])
import convert_all
print(sorted({a.source for a in convert_all.ARTIFACTS}))
"""
    sources = run_python(code).strip().splitlines()[-1]
    assert "skill_v1" not in sources


def test_every_skill_package_can_be_made_again_from_the_files_beside_it():
    need_gate()
    if not SKILL_PACKAGES:
        missing_input("no skill_v1 package")
    done = subprocess.run(
        [GATE_PYTHON, "-I", str(TOOLS / "import_skill_packages.py"), "--check"],
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert done.returncode == 0, done.stdout[-2500:] + done.stderr[-2500:]
    assert done.stdout.count(" same") == sum(EXPECTED.values())
