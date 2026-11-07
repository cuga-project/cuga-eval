import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sets"))
import build_registry as br  # noqa: E402


def entry(set_id, benchmark, ids, status="heldout"):
    return {
        "id": set_id,
        "benchmark": benchmark,
        "ids": ids,
        "status": status,
        "path": "x",
        "key": None,
        "id_field": None,
    }


def test_seen_by_matches_task_ids_not_run_names():
    entries = [entry("held", "automationbench", ["t.a", "t.b"]), entry("other", "automationbench", ["t.c"])]
    records = [
        br.Record("automationbench", "m1", "t.a", "smoke_x"),  # a run name unrelated to the set: still seen
        br.Record(
            "automationbench", "m1", "t.zzz", "held_run"
        ),  # a run named like the set, another task: not seen
        br.Record("automationbench", "m2", "t.c", "p_A"),
    ]
    seen_by, seen_n, counts = br.compute_seen(entries, records)
    assert seen_by == {"held": {"m1": ["smoke_x"]}, "other": {"m2": ["p_A"]}}
    assert seen_n == {"held": {"m1": 1}, "other": {"m2": 1}}
    assert counts == {"m1": 2, "m2": 1}


def test_same_id_in_another_benchmark_does_not_match_and_unknown_model_is_kept():
    entries = [entry("air", "tau2-airline", ["2", "6"])]
    records = [
        br.Record("tau2-retail", "m1", "2", "r"),  # retail also has a task "2"
        br.Record("tau2-airline", "unknown", "6", "a"),
        br.Record("tau2-airline", "m1", "6", "a"),
        br.Record("tau2-airline", "m1", "6", "b"),  # the same task twice counts once, both prefixes listed
    ]
    seen_by, seen_n, _ = br.compute_seen(entries, records)
    assert seen_by == {"air": {"m1": ["a", "b"], "unknown": ["a"]}}
    assert seen_n == {"air": {"m1": 1, "unknown": 1}}


def seen_entries():
    entries = [entry("held", "automationbench", ["t.a", "t.b"]), entry("new", "automationbench", ["t.c"])]
    return entries


def test_a_rebuild_keeps_what_a_missing_folder_held():
    existing = {
        "sets": [
            {
                "id": "held",
                "seen_by": {"m1": ["gone", "here"], "m2": ["gone2"]},
                "seen_n": {"m1": 2, "m2": 1},
            },
            {"id": "a set that left the list", "seen_by": {"m9": ["x"]}, "seen_n": {"m9": 1}},
        ]
    }
    entries = seen_entries()
    seen_by, seen_n, _ = br.compute_seen(entries, [br.Record("automationbench", "m1", "t.a", "here")])
    kept = br.keep_seen(entries, seen_by, seen_n, existing)
    assert seen_by == {"held": {"m1": ["gone", "here"], "m2": ["gone2"]}, "new": {}}
    assert seen_n == {"held": {"m1": 2, "m2": 1}, "new": {}}
    assert len(kept) == 2 and "gone" in kept[0] and "1 of its tasks found, 2 kept" in kept[0]


def test_a_rebuild_adds_what_it_finds_and_says_nothing_when_nothing_is_lost():
    existing = {"sets": [{"id": "held", "seen_by": {"m1": ["a"]}, "seen_n": {"m1": 1}}]}
    entries = seen_entries()
    records = [
        br.Record("automationbench", "m1", "t.a", "a"),
        br.Record("automationbench", "m1", "t.b", "b"),
        br.Record("automationbench", "m2", "t.c", "c"),
    ]
    seen_by, seen_n, _ = br.compute_seen(entries, records)
    assert br.keep_seen(entries, seen_by, seen_n, existing) == []
    assert seen_by == {"held": {"m1": ["a", "b"]}, "new": {"m2": ["c"]}}
    assert seen_n == {"held": {"m1": 2}, "new": {"m2": 1}}


def test_a_scan_that_finds_nothing_leaves_a_seen_set_seen(monkeypatch, tmp_path):
    """The whole path: the real set list, no result folder found, the labels stay as they were."""
    before = br.load_registry()
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(before))
    monkeypatch.setattr(br, "REGISTRY", path)
    monkeypatch.setattr(br, "scan_results", lambda stats=None: iter(()))
    said = []
    after = br.build(write=False, out=said.append)
    old = {e["id"]: e for e in before["sets"]}
    for e in after["sets"]:
        assert e["seen_by"] == old[e["id"]]["seen_by"] and e["seen_n"] == old[e["id"]]["seen_n"]
        assert e["label"] == old[e["id"]]["label"]
    assert any("a folder is missing" in line for line in said)


def test_a_first_build_with_no_file_has_only_what_the_scan_finds(monkeypatch, tmp_path):
    monkeypatch.setattr(br, "REGISTRY", tmp_path / "no_file.json")
    monkeypatch.setattr(br, "scan_results", lambda stats=None: iter(()))
    after = br.build(write=False, out=lambda line: None)
    assert all(e["seen_by"] == {} for e in after["sets"])


def test_prefixes_and_handbook_model():
    assert br.run_prefix("ph_AF_t1") == "ph_AF"
    assert br.run_prefix("tune_A_t1_discarded_sandbox") == "tune_A"
    assert br.run_prefix("smoke") == "smoke"
    assert br.tau2_prefix("logging_test1_A_s0") == "test1_A"
    assert (
        br._hb_model({"model": None, "receipt": {"models": ["azure/DeepSeek-V4-Pro"]}})
        == "azure/DeepSeek-V4-Pro"
    )
    assert br._hb_model({"model": None, "receipt": {"models": ["a", "b"]}}) == "unknown"
    assert br._hb_model({"model": None}) == "unknown"


def test_task_ids_follow_key_and_id_field(tmp_path):
    f = tmp_path / "set.json"
    f.write_text(json.dumps({"x": {"tune": ["a", "b"]}, "tasks": [{"task": "c"}, {"task": "d"}]}))
    assert br.task_ids({"path": str(f), "key": "x.tune", "id_field": None}) == ["a", "b"]
    assert br.task_ids({"path": str(f), "key": "tasks", "id_field": "task"}) == ["c", "d"]


def test_registry_file_has_the_agreed_entries():
    reg = br.load_registry()
    by_id = {e["id"]: e for e in reg["sets"]}
    assert (
        by_id["ab-policy-types-holdout2"]["status"] == "heldout"
        and by_id["ab-policy-types-holdout2"]["n"] == 31
    )
    assert {"gcp/gemini-3.8-flash", "aws/gpt-oss-120b"} <= set(by_id["ab-policy-types-holdout2"]["seen_by"])
    assert by_id["tau2-telecom-fresh40"]["n"] == 40 and by_id["tau2-telecom-fresh40"]["status"] == "heldout"
    assert br.get_entry("itsm-unseen3", reg)["n"] == len(br.task_ids(br.get_entry("itsm-unseen3", reg)))


def test_a_harness_result_counts_and_a_wiring_stop_does_not(tmp_path):
    run = tmp_path / "harness" / "smk_t1"
    run.mkdir(parents=True)
    (run / "a.json").write_text(
        json.dumps(
            {"benchmark": "tau2-telecom", "task": "t1", "agent_model": "aws/gpt-oss-120b", "error": None}
        )
    )
    (run / "b.json").write_text(
        json.dumps({"benchmark": "itsm", "task": "t2", "agent_model": "m", "error": "wiring: no package"})
    )
    records = list(br.scan_results(bench=tmp_path, tau2_root=tmp_path / "none", harness=tmp_path / "harness"))
    assert [(r.benchmark, r.model, r.task, r.prefix) for r in records] == [
        ("tau2-telecom", "aws/gpt-oss-120b", "t1", "smk")
    ]
