"""Recovery pass: find an arm's infra-failed tasks, write the recovery subset, merge re-run predictions."""

import json

import pytest

from benchmarks.m3.parity import recover

pytestmark = pytest.mark.sanity


def _pred(uuid, answer, error=None):
    rec = {
        "uuid": uuid,
        "output": [{"turn_id": 0, "query": "q", "answer": answer, "sequence": {"tool_call": []}}],
    }
    if error is not None:
        rec["error"] = error
    return rec


def _manifest(task_id=2):
    return {
        "subset": "parity_x",
        "task_id": task_id,
        "ids_by_domain": {"hockey": ["H-1", "H-2", "H-3"], "books": ["B-1", "B-2"]},
        "reference": {
            "pass_by_uuid": {"on": {"H-1": True, "H-2": False, "H-3": True, "B-1": True, "B-2": False}}
        },
    }


def _arm(tmp_path, native, preds):
    arm = tmp_path / "run_1" / "cuga_eval_cap2_fc"
    (arm / "prediction").mkdir(parents=True)
    (arm / "native_results.all.json").write_text(json.dumps({"results": native}))
    for dom, recs in preds.items():
        (arm / "prediction" / f"{dom}.json").write_text(json.dumps(recs))
    (arm / "meta.json").write_text(json.dumps({"subset": "parity_x"}))
    return arm


def test_failed_tasks_are_errors_empty_answers_and_missing_predictions(tmp_path):
    native = [
        {"uuid": "H-1", "error": None, "all_responses": [{"response": "42"}]},
        {"uuid": "H-2", "error": "agent_timeout 300s exceeded", "all_responses": []},
        {
            "uuid": "H-3",
            "error": None,
            "all_responses": [{"response": "I can not answer"}],
        },  # a refusal is an answer
        {"uuid": "B-1", "error": "Connection error.", "all_responses": [{"response": ""}]},
    ]
    preds = {
        "hockey": [_pred("H-1", "42"), _pred("H-2", ""), _pred("H-3", "I can not answer")],
        "books": [_pred("B-1", "")],
    }
    arm = _arm(tmp_path, native, preds)
    assert recover.failed_tasks(arm, _manifest()) == {
        "books": ["B-1", "B-2"],
        "hockey": ["H-2"],
    }  # B-2: no prediction


def test_cap1_failures_come_from_the_newest_raw_output_per_domain(tmp_path):
    arm = tmp_path / "run_1" / "cuga_eval_cap1_fc"
    old, new = (
        arm / "raw" / "hockey" / "m3_task1_enterprise_20990101.json",
        arm / "raw" / "hockey" / "m3_task1_enterprise_20990102.json",
    )
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"results": [{"uuid": "H-1", "error": "boom", "response": ""}]}))
    new.write_text(
        json.dumps(
            {
                "results": [
                    {"uuid": "H-1", "error": None, "response": "7"},
                    {"uuid": "H-2", "error": "x", "response": ""},
                ]
            }
        )
    )
    import os

    os.utime(old, (1, 1))  # the older file
    (arm / "prediction").mkdir()
    (arm / "prediction" / "hockey.json").write_text(
        json.dumps([_pred("H-1", "7"), _pred("H-2", ""), _pred("H-3", "1")])
    )
    m = _manifest(task_id=1)
    m["ids_by_domain"] = {"hockey": ["H-1", "H-2", "H-3"]}
    assert recover.failed_tasks(arm, m) == {"hockey": ["H-2"]}


def test_recovery_subset_holds_only_the_failed_tasks(tmp_path):
    manifests, local = tmp_path / "manifests", tmp_path / "local"
    manifests.mkdir()
    (manifests / "parity_x.json").write_text(json.dumps(_manifest()))
    (manifests / "uuid_map_parity_x.json").write_text(
        json.dumps(
            {
                "subset": "parity_x",
                "zip_to_vakra": {u: {"vakra_uuid": u} for u in ("H-1", "H-2", "H-3", "B-1", "B-2")},
            }
        )
    )
    native = [{"uuid": "H-2", "error": "agent_timeout 300s exceeded", "all_responses": []}]
    preds = {
        "hockey": [_pred("H-1", "1"), _pred("H-2", ""), _pred("H-3", "3")],
        "books": [_pred("B-1", "1"), _pred("B-2", "2")],
    }
    arm = _arm(tmp_path, native, preds)
    s = recover.write_recovery_subset(arm.parent, arm.name, manifests, local)
    assert s["n"] == 1 and s["subset"].startswith(recover.PREFIX) and s["failed_by_domain"] == {"hockey": 1}
    sub = json.loads((manifests / f"{s['subset']}.json").read_text())
    assert sub["ids_by_domain"] == {"hockey": ["H-2"]} and sub["reference"]["pass_by_uuid"]["on"] == {
        "H-2": False
    }
    umap = json.loads((manifests / f"uuid_map_{s['subset']}.json").read_text())
    assert list(umap["zip_to_vakra"]) == ["H-2"]
    assert '"H-2"' in (local / f"{s['subset']}.toml").read_text()
    assert recover.clean(s["subset"], manifests) == [f"{s['subset']}.json", f"uuid_map_{s['subset']}.json"]
    with pytest.raises(ValueError):
        recover.clean("parity_x", manifests)


def test_merge_replaces_only_records_that_now_have_an_answer(tmp_path):
    arm = _arm(tmp_path, [], {"hockey": [_pred("H-1", "1"), _pred("H-2", ""), _pred("H-3", "")]})
    rec_arm = tmp_path / "run_1_recover" / "cuga_eval_cap2_fc"
    (rec_arm / "prediction").mkdir(parents=True)
    (rec_arm / "prediction" / "hockey.json").write_text(
        json.dumps([_pred("H-2", "22"), _pred("H-3", "", error="timeout")])
    )
    assert recover.merge_predictions(arm, rec_arm) == {"replaced": 1, "still_failed": 1}
    merged = {
        r["uuid"]: r["output"][-1]["answer"]
        for r in json.loads((arm / "prediction" / "hockey.json").read_text())
    }
    assert merged == {"H-1": "1", "H-2": "22", "H-3": ""}
    backup = json.loads((arm / "prediction_pre_recover" / "hockey.json").read_text())
    assert backup[1]["output"][-1]["answer"] == ""  # the original kept
