"""Offline test for the tau2 entrypoint reporting (Phase 6). No LLM.

Stubs _run_one_task with a fixed reward and runs the REAL entrypoint end-to-end
(get_tasks + ActivityTracker + save_evaluation_results) to prove the reporting plumbing:
per-task result dicts and a results JSON in the expected shape — without a live model.
"""

import json
from argparse import Namespace
from types import SimpleNamespace

import pytest

pytest.importorskip("tau2")

pytestmark = pytest.mark.sanity


def test_result_dict_shape():
    from benchmarks.tau2.eval_tau2_sdk import _result_dict

    task = SimpleNamespace(id="create_task_1")
    d = _result_dict("mock", task, 1.0, 2.5)
    assert d["task_id"] == "create_task_1"
    assert d["task_name"] == "create_task_1"
    assert d["success"] is True
    assert d["score"] == 1.0 and d["reward"] == 1.0
    assert d["full_execution_time"] == 2.5
    # a sub-1.0 reward is not success; None reward is not success
    assert _result_dict("mock", task, 0.0, 1.0)["success"] is False
    assert _result_dict("mock", task, None, 1.0)["success"] is False


def test_run_emits_results_json(monkeypatch, tmp_path):
    import benchmarks.tau2.eval_tau2_sdk as sdk

    # No LLM: replace the per-task run with a fixed reward.
    monkeypatch.setattr("benchmarks.tau2.cuga_runner._run_one_task", lambda *a, **k: 1.0)
    # Write results into a temp dir instead of CUGA_LOGGING_DIR.
    monkeypatch.setattr(sdk, "cuga_logging_dir", str(tmp_path))

    args = Namespace(
        subset="mock",
        task_ids=None,
        num_tasks=1,
        user_sim_model="fake/model",
        max_steps=5,
        max_workers=1,
        run_id="testrun",
        agent="cuga",
        agent_model=None,
    )
    results = sdk.run(args)

    assert len(results) == 1
    assert results[0]["reward"] == 1.0 and results[0]["success"] is True

    files = list((tmp_path / "results").glob("tau2_*.json"))
    assert files, "no results JSON written"
    text = files[0].read_text()
    json.loads(text)  # valid JSON
    assert "create_task_1" in text  # our task id made it into the file


def test_run_rejects_multiple_workers():
    import benchmarks.tau2.eval_tau2_sdk as sdk

    args = Namespace(
        subset="mock", task_ids=None, num_tasks=1, user_sim_model="m", max_steps=5, max_workers=4, run_id=None
    )
    with pytest.raises(SystemExit):
        sdk.run(args)
