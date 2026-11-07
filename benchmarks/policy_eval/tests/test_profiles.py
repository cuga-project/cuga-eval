"""The profiles in ``profiles/`` load, each has an entry in ``best_profiles.json``, and they read the packages of the measured runs.
That each profile gives the measured wiring is in ``test_runtime_golden.py``. ``switches`` of an entry is a record of what was
measured: the function that compared them with a profile left with task 6.1.

The config code is in the gate repo (``cuga.policy_layer.policy_config``), which is not in this venv, so the loading runs
with the gate repo's Python and prints plain data.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

POLICY_EVAL = Path(__file__).resolve().parents[1]
BENCHMARKS = POLICY_EVAL.parent
PROFILES = POLICY_EVAL / "profiles"
PACKAGES = POLICY_EVAL / "packages"
GATE_PYTHON = os.environ.get("POLICY_GATE_PYTHON") or str(
    Path.home() / "dev/cuga-agent-gate/.venv/bin/python"
)
ENTRIES = json.loads((POLICY_EVAL / "best_profiles.json").read_text())["profiles"]

LOAD = r"""
import json, sys
from pathlib import Path
from cuga.policy_layer.policy_config import load_config

root = Path(sys.argv[1])
names = [e["profile"] for e in json.loads((root / "best_profiles.json").read_text())["profiles"]] + ["baseline"]
out = {"profiles": {name: {"yaml": load_config(root / "profiles" / (name + ".yaml")).to_dict()} for name in names}}
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def loaded():
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", LOAD, str(POLICY_EVAL)], capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-3000:]
    return json.loads(done.stdout)


def paths_with_auto(value, prefix=""):
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in paths_with_auto(v, f"{prefix}.{k}" if prefix else k)]
    return [prefix] if value == "auto" else []


def test_each_entry_names_one_profile_file_and_each_file_has_an_entry():
    names = [e["profile"] for e in ENTRIES]
    assert len(names) == len(set(names))
    # the seven entries of the best-profile list; one of them (N, the navigator) is not measured live yet
    assert len([e for e in ENTRIES if e.get("best", True)]) == 7
    assert sorted(p.stem for p in PROFILES.glob("*.yaml")) == sorted(names + ["baseline"])


def test_the_itsm_entry_says_it_is_not_a_best_profile():
    entry = next(e for e in ENTRIES if e["profile"] == "itsm-rules")
    assert entry["best"] is False
    assert "nothing beat CUGA alone" in entry["why_not_best"]


def test_the_itsm_profile_reads_the_builds_that_the_old_runs_read(loaded):
    entry = next(e for e in ENTRIES if e["profile"] == "itsm-rules")
    assert entry["switches"] == {"POLICY_BUILDS_DIR": "policy_eval/builds"}
    assert loaded["profiles"]["itsm-rules"]["yaml"]["package"] == "packages/itsm/{policy}/builds/package.json"
    filtered = [
        p for p in (POLICY_EVAL / "builds").glob("*.json") if not p.name.endswith(".before_filters.json")
    ]
    assert len(filtered) == 8
    for path in filtered:
        assert (PACKAGES / "itsm" / path.stem / "builds" / "package.json").is_file(), path.name


def test_the_navigator_entry_holds_the_hand_off_values_and_the_module_does_not(loaded):
    entry = next(e for e in ENTRIES if e["profile"] == "tau2-telecom-gptoss-navigator")
    assert entry["switches"]["SOP_NAVIGATOR_HANDOFF_TOOLS"] == "transfer_to_human_agents"
    navigator = loaded["profiles"][entry["profile"]]["yaml"]["organizers"]["navigator"]
    assert navigator["handoff_tools"] == ["transfer_to_human_agents"]
    assert navigator["handoff_text"] == entry["switches"]["SOP_NAVIGATOR_HANDOFF_TEXT"].split("|")


@pytest.mark.parametrize("name", [e["profile"] for e in ENTRIES] + ["baseline"])
def test_a_profile_lists_every_component_on_or_off_and_never_auto(loaded, name):
    assert paths_with_auto(loaded["profiles"][name]["yaml"]) == []


def test_the_baseline_adds_nothing(loaded):
    config = loaded["profiles"]["baseline"]["yaml"]
    assert config["package"] is None
    assert not any(config["sources"].values()) and config["obligations"]["producers"] == []
    modes = [
        config["checkers"]["rules"],
        config["checkers"]["gate"]["mode"],
        config["checkers"]["verifier"]["mode"],
        config["organizers"]["procedure_tools"],
        *(
            config["organizers"][name]["mode"]
            for name in ("guide", "loop", "sop_tracker", "navigator", "requirements_tracker")
        ),
        config["decisions"]["mode"],
    ]
    assert modes == ["off"] * 10
    # CUGA alone is the best for Gemini on this benchmark, and it is the same as the baseline
    assert loaded["profiles"]["automationbench-gemini-alone"]["yaml"] == config


EXPECTED_POLICIES = {
    "handbook": 3,
    "itsm": 8,
}  # packages that exist per benchmark and source; 80cd3ebb50 has no build


@pytest.mark.parametrize("entry", [e for e in ENTRIES], ids=[e["profile"] for e in ENTRIES])
def test_the_package_of_a_profile_exists_for_each_policy(loaded, entry):
    package = loaded["profiles"][entry["profile"]]["yaml"]["package"]
    if package is None:
        return
    bench = entry["benchmark"].replace("-", "_")
    assert package.startswith(f"packages/{bench}/")
    if "{policy}" not in package:
        assert (POLICY_EVAL / package).is_file()
        return
    found = [
        d.name
        for d in (PACKAGES / bench).iterdir()
        if (POLICY_EVAL / package.format(policy=d.name)).is_file()
    ]
    assert len(found) == EXPECTED_POLICIES[bench], found
