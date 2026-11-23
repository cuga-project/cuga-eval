"""tasks/verifier_revisions.json: corrected verifiers applied by eog_env.load_task, the oracle files left as published."""

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression  # CI runs "sanity or regression"

EOG = Path(__file__).resolve().parents[2] / "enterpriseops_gym"
TASKS = EOG / "tasks"
REVISIONS = TASKS / "verifier_revisions.json"
COMPARISONS = {"equals", "greater_than", "less_than", "contains"}


def _j(value):
    return json.loads(value) if isinstance(value, str) else value


def _revisions() -> dict:
    return {k: v for k, v in json.loads(REVISIONS.read_text()).items() if not k.startswith("_")}


def _oracle() -> dict:
    return {t["task_id"]: t for f in sorted(TASKS.glob("*_oracle.json")) for t in json.loads(f.read_text())}


def _eog_env():
    """The loader imports the benchmark's own code, which is a separate clone (SETUP.md, step 3)."""
    if not (EOG / "vendor" / "EnterpriseOps-Gym" / "benchmark").is_dir():
        pytest.skip("needs the EnterpriseOps-Gym clone under enterpriseops_gym/vendor (see SETUP.md)")
    if str(EOG) not in sys.path:
        sys.path.append(str(EOG))
    import eog_env

    return eog_env


def test_each_revision_names_a_task_and_changes_its_verifiers():
    oracle = _oracle()
    revisions = _revisions()
    assert revisions
    for task_id, revision in revisions.items():
        assert task_id in oracle, task_id
        assert revision["domain"] == oracle[task_id]["domain"]
        assert revision["source"].strip()
        assert revision["verifiers"] != _j(oracle[task_id]["verifiers"]), f"{task_id}: nothing to revise"
        for v in revision["verifiers"]:
            assert v["verifier_type"] == "database_state"
            config = v["validation_config"]
            assert config["query"].strip() and config["comparison_type"] in COMPARISONS
            assert "expected_value" in config


def test_revised_count_checks_expect_numbers():
    """A COUNT query returns a number, so a text expected value can never equal it."""
    for task_id, revision in _revisions().items():
        for v in revision["verifiers"]:
            config = v["validation_config"]
            if "count(" in config["query"].lower() and config["comparison_type"] == "equals":
                assert isinstance(config["expected_value"], int), task_id


def test_load_task_applies_a_revision():
    eog_env = _eog_env()
    task_id, revision = next(iter(_revisions().items()))
    task = eog_env.load_task(task_id)
    assert task["verifiers"] == revision["verifiers"]
    assert task["_revised"] is True


def test_load_task_leaves_other_tasks_as_published():
    eog_env = _eog_env()
    revisions = _revisions()
    oracle = _oracle()
    task_id = next(t for t in oracle if t not in revisions)
    assert eog_env.load_task(task_id)["verifiers"] == _j(oracle[task_id]["verifiers"])


def test_missing_revisions_file_means_no_revisions(tmp_path):
    eog_env = _eog_env()
    assert eog_env.verifier_revisions(tmp_path / "absent.json") == {}
