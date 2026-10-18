"""Cross-repo parity kit: manifests/maps/eval-keys integrity and the pure helpers (no runs)."""

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from benchmarks.m3.eval_config_loader import load_eval_key_ids
from benchmarks.m3.parity import compare, models, snapshot

pytestmark = pytest.mark.sanity

PARITY = Path(__file__).resolve().parents[1] / "parity"
MANIFESTS = PARITY / "manifests"
ZIP = Path(__file__).resolve().parents[1] / "data" / "small_train.zip"
SUBSETS = (
    "parity_smoke_hockey",
    "parity_cap2_30",
    "parity_cap3_20",
    "parity_smoke_cap3",
    "parity_est3_cap3",
    "parity_est3_smoke",
    "parity_est3_ref30",
    "parity_est2_ref30",
    "parity_est1_ref30",
    "parity_est1_smoke",
    "parity_est4_ref30",
    "parity_est4_smoke",
    "parity_est3_fresh30",
    "parity_est1_smoke3",
    "parity_est2_smoke2",
    "parity_est2_fresh30",
    "parity_est2_60",
)
BASH = shutil.which("bash") or "/bin/bash"


def _manifest(name):
    return json.loads((MANIFESTS / f"{name}.json").read_text())


def _uuid_map(name):
    return json.loads((MANIFESTS / f"uuid_map_{name}.json").read_text())


def _zip_uuids(capdir, domain):
    with zipfile.ZipFile(ZIP) as z:
        return {r["uuid"] for r in json.loads(z.read(f"small_{capdir}/input/{domain}.json"))}


# ------------------------------- manifests ---------------------------------


@pytest.mark.parametrize("name", SUBSETS)
def test_manifest_ids_are_unique_complete_and_in_their_data_source(name):
    m = _manifest(name)
    ids = snapshot.manifest_uuids(m)
    assert m["n"] == len(ids) == len(set(ids))
    if not str(m.get("m3_data", "")).startswith("local:"):  # zip-sourced subsets: ids live in the bundled zip
        for domain, dom_ids in m["ids_by_domain"].items():
            assert set(dom_ids) <= _zip_uuids(m["capability_dir"], domain), (
                f"{name}/{domain}: id not in small_train.zip"
            )
    assert m["reference"]["pass_by_uuid"], "a reference needs at least one arm"
    for arm in m["reference"]["pass_by_uuid"]:
        flags = m["reference"]["pass_by_uuid"][arm]
        # the headline arms cover every task; a secondary recorded run may miss a few
        assert set(flags) == set(ids) if arm in ("on", "off") else set(flags) <= set(ids)
        assert abs(sum(flags.values()) / len(flags) - m["reference"]["pass_rate"][arm]) < 0.01


@pytest.mark.parametrize("name", SUBSETS)
def test_eval_key_matches_manifest(name):
    assert set(load_eval_key_ids(name)) == set(snapshot.manifest_uuids(_manifest(name)))


@pytest.mark.parametrize("name", SUBSETS)
def test_uuid_map_covers_manifest_without_duplicate_targets(name):
    m, um = _manifest(name), _uuid_map(name)
    ids = set(snapshot.manifest_uuids(m))
    mapped = set(um["zip_to_vakra"])
    unmatched = {u["zip_uuid"] for u in um["unmatched"]}
    assert mapped | unmatched == ids and not (mapped & unmatched)
    targets = [v["vakra_uuid"] for v in um["zip_to_vakra"].values()]
    assert len(targets) == len(set(targets))
    assert all(v["domain"] in m["ids_by_domain"] for v in um["zip_to_vakra"].values())


def test_expected_subset_sizes():
    assert _manifest("parity_cap2_30")["n"] == 30 and len(_uuid_map("parity_cap2_30")["zip_to_vakra"]) == 28
    assert _manifest("parity_cap3_20")["n"] == 20 and len(_uuid_map("parity_cap3_20")["zip_to_vakra"]) == 19
    assert _manifest("parity_smoke_hockey")["ids_by_domain"] == {"hockey": ["308738b8195d-5bd16a8893c5"]}
    assert (
        _manifest("parity_smoke_cap3")["n"] == 1 and len(_uuid_map("parity_smoke_cap3")["zip_to_vakra"]) == 1
    )


# --------------------------------- models -----------------------------------


def test_temperature_variant_rewrites_every_model_block_only(tmp_path):
    src = tmp_path / "settings.toml"
    src.write_text(
        "[agent.planner.model]\nplatform = \"openai\"\ntemperature = 0.1\n\n"
        "[agent.code.model]\ntemperature = 0.1  # keep\nmax_tokens = 10\n\n"
        "[other.section]\ntemperature = 0.1\n"
    )
    dst = tmp_path / "out" / "settings.temp1.0.toml"
    assert models.write_temperature_variant(src, dst, 1.0) == 2
    text = dst.read_text()
    assert text.count("temperature = 1.0") == 2
    assert "temperature = 1.0  # keep" in text  # trailing comment kept
    assert "[other.section]\ntemperature = 0.1" in text  # non-model block untouched


def test_temperature_variant_cli_fails_without_model_blocks(tmp_path):
    src = tmp_path / "s.toml"
    src.write_text("[misc]\nx = 1\n")
    assert models.main(["--src", str(src), "--dst", str(tmp_path / "o.toml"), "--temperature", "1.0"]) == 2


# --------------------------------- snapshot ---------------------------------


def _pred(uuid, answer="42"):
    return {
        "uuid": uuid,
        "domain": "hockey",
        "output": [{"turn_id": 0, "query": "q", "answer": answer, "sequence": {"tool_call": []}}],
    }


def test_remap_rewrites_uuids_and_drops_unmapped():
    um = {"zip_to_vakra": {"A-1": {"vakra_uuid": "V-1", "domain": "hockey", "match": "exact"}}}
    remapped, dropped = snapshot.remap_records([_pred("A-1"), _pred("a-1"), _pred("B-2")], um["zip_to_vakra"])
    assert [r["uuid"] for r in remapped] == ["V-1", "V-1"] and dropped == ["B-2"]


def test_gt_subset_and_snapshot_filtering(tmp_path):
    keep = {"V-1"}
    assert [r["uuid"] for r in snapshot.gt_subset([_pred("V-1"), _pred("V-9")], keep)] == ["V-1"]
    results = tmp_path / "results"
    (results / "_vakra" / "prediction").mkdir(parents=True)
    (results / "_vakra" / "prediction" / "hockey.json").write_text(json.dumps([_pred("A-1"), _pred("Z-0")]))
    (results / "m3_config_20990101_000000.json").write_text(
        json.dumps(
            {
                "metrics": {},
                "results": [{"sample_id": "A-1", "domain": "hockey", "success": True, "match_rate": 1.0}],
            }
        )
    )
    manifest = {"ids_by_domain": {"hockey": ["A-1"], "books": ["B-1"]}}
    summary = snapshot.snapshot_cuga_eval(manifest, results, since=0, out_dir=tmp_path / "arm")
    assert summary["predictions"] == {"hockey": {"expected": 1, "found": 1}}
    assert summary["missing_prediction_files"] == ["books"]
    assert json.loads((tmp_path / "arm" / "native_scores.json").read_text())["A-1"]["success"] is True
    assert [r["uuid"] for r in json.loads((tmp_path / "arm" / "prediction" / "hockey.json").read_text())] == [
        "A-1"
    ]


# --------------------------------- compare ----------------------------------


def _vendor(scores):
    return {"domains": {"hockey": {"dialogues": [{"uuid": u, "score": s} for u, s in scores.items()]}}}


def test_pass_rate_and_agreement():
    a = compare.vendor_scores(_vendor({"V-1": 1.0, "V-2": 0.0, "V-3": 1.0}))
    b = compare.vendor_scores(_vendor({"V-1": 1.0, "V-2": 1.0, "V-4": 0.0}))
    assert compare.pass_rate(a) == (2, 3, pytest.approx(2 / 3))
    ag = compare.agreement(a, b)
    assert (
        ag["n_common"] == 2
        and ag["both_pass"] == ["V-1"]
        and ag["only_b"] == ["V-2"]
        and ag["agree_rate"] == 0.5
    )
    assert (
        compare.noise_note(10, 1.0).startswith("noise-level") and compare.noise_note(40, 5.0) == "above noise"
    )


def test_render_report_lists_arms_and_reference(tmp_path):
    run = tmp_path / "run"
    for arm, preset, s in (("cuga_eval_off", "off", 0.0), ("cuga_eval_cap2", "cap2", 1.0)):
        d = run / arm
        d.mkdir(parents=True)
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "stack": "cuga-eval",
                    "adapter_preset": preset,
                    "cuga_agent": {"branch": "main", "commit": "abc", "dirty_files": "0"},
                }
            )
        )
        (d / "vendor_results.json").write_text(json.dumps(_vendor({"V-1": s})))
    manifest = {
        "n": 1,
        "ids_by_domain": {"hockey": ["A-1"]},
        "reference": {
            "description": "ref",
            "pass_rate": {"off": 0.0, "on": 1.0},
            "pass_by_uuid": {"off": {"A-1": False}, "on": {"A-1": True}},
        },
    }
    um = {"zip_to_vakra": {"A-1": {"vakra_uuid": "V-1", "domain": "hockey"}}, "unmatched": []}
    arms = compare.load_run(run, manifest, um)
    report = compare.render_report("parity_smoke_hockey", manifest, um, arms)
    assert "| cuga_eval_cap2 | cuga-eval | cap2 | 1 | 100.0% (1/1)" in report
    assert "| cuga_eval_off | off | 1 | 1 (100.0%)" in report  # agrees with the reference
    assert "noise-level" in report


# --------------------------------- scripts ----------------------------------


@pytest.mark.parametrize(
    "script",
    [
        "env.sh",
        "preflight.sh",
        "run_cuga_eval_arm.sh",
        "run_vakra_main_arm.sh",
        "rescore.sh",
        "run_parity.sh",
    ],
)
def test_shell_scripts_parse(script):
    subprocess.run([BASH, "-n", str(PARITY / script)], check=True)  # noqa: S603  (fixed, trusted args)


def test_dry_run_prints_the_pipeline():
    out = subprocess.run(  # noqa: S603  (fixed, trusted args)
        [BASH, str(PARITY / "run_parity.sh"), "--subset", "parity_cap2_30", "--dry-run", "--run-id", "x"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert (
        "run_cuga_eval_arm.sh x parity_cap2_30 off" in out
        and "run_cuga_eval_arm.sh x parity_cap2_30 cap2" in out
    )
    assert "run_vakra_main_arm.sh x parity_cap2_30 fc_canon" in out and "rescore.sh x parity_cap2_30" in out


def test_snapshot_per_domain_resume_merges_native_scores(tmp_path):
    results = tmp_path / "results"
    (results / "_vakra" / "prediction").mkdir(parents=True)
    manifest = {"ids_by_domain": {"hockey": ["A-1"], "books": ["B-1"]}}
    arm = tmp_path / "arm"
    (results / "_vakra" / "prediction" / "hockey.json").write_text(json.dumps([_pred("A-1")]))
    (results / "m3_config_20990101_000001.json").write_text(
        json.dumps({"metrics": {}, "results": [{"sample_id": "A-1", "domain": "hockey", "success": True}]})
    )
    s1 = snapshot.snapshot_cuga_eval(manifest, results, since=0, out_dir=arm, domains=["hockey"])
    assert s1["domains"] == ["hockey"] and s1["missing_prediction_files"] == []
    # a later run for the second domain must merge, not clobber, the first domain's scores
    (results / "_vakra" / "prediction" / "books.json").write_text(json.dumps([_pred("B-1")]))
    (results / "m3_config_20990101_000002.json").write_text(
        json.dumps({"metrics": {}, "results": [{"sample_id": "B-1", "domain": "books", "success": False}]})
    )
    s2 = snapshot.snapshot_cuga_eval(manifest, results, since=0, out_dir=arm, domains=["books"])
    native = json.loads((arm / "native_scores.json").read_text())
    assert (
        set(native) == {"A-1", "B-1"}
        and native["A-1"]["success"] is True
        and native["B-1"]["success"] is False
    )
    assert s2["native_results"]["n_total"] == 2
    assert sorted(p.name for p in arm.glob("native_results.*.json")) == [
        "native_results.books.json",
        "native_results.hockey.json",
    ]


def test_fc_ab_dry_run_pairs_each_recipe_with_its_fc_arm():
    out = subprocess.run(  # noqa: S603  (fixed, trusted args)
        [
            BASH,
            str(PARITY / "run_parity.sh"),
            "--subset",
            "parity_cap3_20",
            "--fc-ab",
            "--dry-run",
            "--run-id",
            "x",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "PARITY_FC=0 bash" in out and "run_cuga_eval_arm.sh x parity_cap3_20 cap3" in out
    assert "PARITY_FC=1 bash" in out and out.count("run_cuga_eval_arm.sh x parity_cap3_20 cap3") == 2
    assert out.count("run_vakra_main_arm.sh x parity_cap3_20 fc_canon") == 2


def test_report_has_an_fc_effect_row_for_each_recipe_pair(tmp_path):
    run = tmp_path / "run"
    for arm, fc, scores in (
        ("cuga_eval_cap3", "0", {"V-1": 0.0, "V-2": 1.0}),
        ("cuga_eval_cap3_fc", "1", {"V-1": 1.0, "V-2": 1.0}),
    ):
        d = run / arm
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"stack": "cuga-eval", "adapter_preset": "cap3", "fc": fc}))
        (d / "vendor_results.json").write_text(json.dumps(_vendor(scores)))
    manifest = {"n": 2, "ids_by_domain": {"hockey": ["A-1", "A-2"]}}
    um = {
        "zip_to_vakra": {
            "A-1": {"vakra_uuid": "V-1", "domain": "hockey"},
            "A-2": {"vakra_uuid": "V-2", "domain": "hockey"},
        },
        "unmatched": [],
    }
    report = compare.render_report("s", manifest, um, compare.load_run(run, manifest, um))
    assert "| cuga_eval_cap3_fc | cuga-eval | cap3 +FC |" in report
    assert "## FC effect" in report
    assert "| cuga_eval_cap3 |  50.0% | 100.0% | 2 | +50.0pt | 1 | 0 |" in report


# ------------------------- vakra-main-sourced subsets -------------------------


def test_est3_is_the_campaign_cap3_scorecard_sample():
    m = _manifest("parity_est3_cap3")
    assert m["n"] == 120 and len(m["ids_by_domain"]) == 22
    assert m["no_ground_truth"] is True and m["m3_data"] == m["demo_data"] == "local:vakra_train"
    assert sum(m["reference"]["pass_by_uuid"]["on"].values()) == 68  # the campaign's 56.7%
    um = _uuid_map("parity_est3_cap3")
    assert all(k == v["vakra_uuid"] for k, v in um["zip_to_vakra"].items())  # defined in vakra-main uuids


def test_validation_manifests_are_the_campaign_scorecards_and_held_out():
    est2 = _manifest("parity_est2_cap2")  # the whole est2 sample (115 of its 120 items carry a verdict)
    assert est2["n"] == 115 and len(est2["ids_by_domain"]) == 35
    assert round(100 * sum(est2["reference"]["pass_by_uuid"]["on"].values()) / est2["n"], 1) == 62.6
    val4 = _manifest("parity_est4_val120")  # cap4 validation: none of the 30 items the defaults were tuned on
    tuned = {u for ids in _manifest("parity_est4_ref30")["ids_by_domain"].values() for u in ids}
    held = {u for ids in val4["ids_by_domain"].values() for u in ids}
    assert val4["n"] == len(held) == 120 and not held & tuned


def test_prepare_converts_vakra_output_to_the_loader_layout(tmp_path):
    from benchmarks.m3.m3_data_loader import M3DataLoader
    from benchmarks.m3.parity import prepare_vakra_train

    capdir = "capability_3_multihop_reasoning"
    src = tmp_path / "vakra" / "data" / "train" / capdir
    (src / "input").mkdir(parents=True)
    (src / "output").mkdir(parents=True)
    turn = {"turn_id": 0, "query": "q?"}
    (src / "input" / "dom.json").write_text(
        json.dumps([{"uuid": "u-1", "domain": "dom", "num_turns": 1, "dialogue": {"turns": [turn]}}])
    )
    seq = {"tool_call": [{"name": "get_x", "arguments": {"a": 1}}], "tool_response": [{"x": 2}]}
    (src / "output" / "dom.json").write_text(
        json.dumps([{"uuid": "u-1", "domain": "dom", "output": [{**turn, "answer": "2", "sequence": seq}]}])
    )
    counts = prepare_vakra_train.prepare(tmp_path / "vakra", capdir, ["dom"], tmp_path / "out")
    assert counts == {"dom": 1}
    sample = M3DataLoader(tmp_path / "out").load_domain(3, "dom")[0]  # the converted copy loads with its GT
    assert sample["sample_id"] == "u-1"
    assert sample["expected_output"]["gold_sequence"][0][0]["name"] == "get_x"
    assert sample["expected_output"]["answer_per_turn"] == ["2"]


def test_strip_registry_prefix_only_touches_the_domain_prefix():
    rec = {
        "uuid": "u",
        "output": [
            {
                "sequence": {
                    "tool_call": [
                        {"name": "hockey_get_x"},
                        [{"name": "hockey_get_y"}],
                        {"name": "find_tools"},
                    ]
                }
            }
        ],
    }
    out = snapshot.strip_registry_prefix([rec], "hockey")[0]
    calls = out["output"][0]["sequence"]["tool_call"]
    assert calls[0]["name"] == "get_x" and calls[1][0]["name"] == "get_y" and calls[2]["name"] == "find_tools"
    assert rec["output"][0]["sequence"]["tool_call"][0]["name"] == "hockey_get_x"  # input not mutated


def _calls_rec(uuid, *names):
    return {
        "uuid": uuid,
        "domain": "hockey",
        "output": [
            {
                "turn_id": 0,
                "query": "q",
                "answer": "a",
                "sequence": {"tool_call": [{"name": n} for n in names]},
            }
        ],
    }


def test_restore_live_tool_names_fixes_only_case_differences():
    """cuga's registry lowercases tool names; the evaluator's replay needs the live spelling."""
    rec = _calls_rec("u", "get_goalies_with_null_shootcatch", "get_players", "not_live", "get_dup")
    live = ["get_goalies_with_null_shootCatch", "get_players", "get_Dup", "get_DUP"]
    out, fixed = snapshot.restore_live_tool_names([rec], live)
    names = [c["name"] for c in out[0]["output"][0]["sequence"]["tool_call"]]
    # one fix; exact and unknown names untouched; a case-ambiguous name left alone
    assert names == ["get_goalies_with_null_shootCatch", "get_players", "not_live", "get_dup"]
    assert fixed == 1
    assert rec["output"][0]["sequence"]["tool_call"][0]["name"] == "get_goalies_with_null_shootcatch"


def test_snapshot_restores_live_tool_names_in_predictions_only_mode(tmp_path):
    results = tmp_path / "results"
    (results / "_vakra" / "prediction").mkdir(parents=True)
    raw = [_calls_rec("A-1", "hockey_get_goalies_with_null_shootcatch", "hockey_get_players")]
    (results / "_vakra" / "prediction" / "hockey.json").write_text(json.dumps(raw))
    manifest = {"ids_by_domain": {"hockey": ["A-1"]}, "no_ground_truth": True, "task_id": 2}
    asked = []

    def live(domain):
        asked.append(domain)
        return ["get_goalies_with_null_shootCatch", "get_players"]

    summary = snapshot.snapshot_cuga_eval(
        manifest, results, since=0, out_dir=tmp_path / "arm", live_names=live
    )
    pred = json.loads((tmp_path / "arm" / "prediction" / "hockey.json").read_text())
    names = [c["name"] for c in pred[0]["output"][0]["sequence"]["tool_call"]]
    assert names == ["get_goalies_with_null_shootCatch", "get_players"] and asked == ["hockey"]
    assert summary["tool_names_restored"] == {"hockey": 1}
    # unreachable servers keep the prefix-stripped names
    summary = snapshot.snapshot_cuga_eval(
        manifest, results, since=0, out_dir=tmp_path / "arm2", live_names=lambda d: None
    )
    pred = json.loads((tmp_path / "arm2" / "prediction" / "hockey.json").read_text())
    assert pred[0]["output"][0]["sequence"]["tool_call"][0]["name"] == "get_goalies_with_null_shootcatch"
    assert "tool_names_restored" not in summary


def test_campaign_recorded_arm_filters_to_the_manifest(tmp_path):
    pred = tmp_path / "vakra" / "output" / "est3_treat"
    pred.mkdir(parents=True)
    (pred / "dom.json").write_text(json.dumps([_pred("u-1"), _pred("u-9")]))
    manifest = {"subset": "s", "campaign_predictions": "output/est3_treat", "ids_by_domain": {"dom": ["u-1"]}}
    summary = snapshot.campaign_recorded_arm(manifest, tmp_path / "vakra", tmp_path / "arm")
    assert summary == {"domains": 1, "items": 1}
    assert [r["uuid"] for r in json.loads((tmp_path / "arm" / "prediction" / "dom.json").read_text())] == [
        "u-1"
    ]
    meta = json.loads((tmp_path / "arm" / "meta.json").read_text())
    assert meta["stack"] == "vakra-main" and meta["fc"] == "1"


def test_report_handles_a_reference_with_only_an_on_arm(tmp_path):
    run = tmp_path / "run"
    for arm, meta in (
        ("cuga_eval_cap3_fc", {"adapter_preset": "cap3", "fc": "1"}),
        ("vakra_main_campaign_recorded", {"recipe": "fc_canon", "fc": "1"}),
    ):
        (run / arm).mkdir(parents=True)
        (run / arm / "meta.json").write_text(json.dumps({"stack": "x", **meta}))
        (run / arm / "vendor_results.json").write_text(json.dumps(_vendor({"V-1": 1.0})))
    manifest = {
        "n": 1,
        "ids_by_domain": {"d": ["V-1"]},
        "reference": {
            "description": "campaign",
            "pass_rate": {"on": 1.0},
            "pass_by_uuid": {"on": {"V-1": True}},
        },
    }
    um = {"zip_to_vakra": {"V-1": {"vakra_uuid": "V-1", "domain": "d"}}, "unmatched": []}
    report = compare.render_report("s", manifest, um, compare.load_run(run, manifest, um))
    assert "Reference (campaign): on 100.0%." in report
    assert "| vakra_main_campaign_recorded | on | 1 | 1 (100.0%)" in report


def test_est3_dry_run_uses_the_manifest_default_arms():
    out = subprocess.run(  # noqa: S603  (fixed, trusted args)
        [BASH, str(PARITY / "run_parity.sh"), "--subset", "parity_est3_cap3", "--dry-run", "--run-id", "x"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "PARITY_FC=1 bash" in out and "run_cuga_eval_arm.sh x parity_est3_cap3 cap3" in out
    assert "run_vakra_main_arm.sh x parity_est3_cap3 fc_canon" in out


# ------------------------- reference subsets / variants / chunked scoring -------------------------


def test_reference_selection_keeps_the_pass_rate_spreads_domains_and_is_deterministic():
    from benchmarks.m3.parity.make_reference import select

    items = [(f"d{d}-{i}", f"d{d}", (d + i) % 3 != 0) for d in range(10) for i in range(12)]
    rate = sum(p for *_, p in items) / len(items)
    picked = select(items, 30, seed=0)
    assert len(picked) == 30 and len(set(picked)) == 30
    assert sum(p for *_, p in picked) == round(30 * rate)  # outcome quota
    per_domain = {}
    for _, d, _ in picked:
        per_domain[d] = per_domain.get(d, 0) + 1
    assert max(per_domain.values()) <= 3  # ceil(30 / 10)
    assert select(items, 30, seed=0) == picked and select(items, 30, seed=1) != picked


@pytest.mark.parametrize("name,cap,n_pass", [("parity_est3_ref30", 3, 17), ("parity_est2_ref30", 2, 19)])
def test_reference_subsets_are_slices_of_the_campaign_scorecards(name, cap, n_pass):
    m, um = _manifest(name), _uuid_map(name)
    ids = [u for us in m["ids_by_domain"].values() for u in us]
    assert m["n"] == len(ids) == 30 and m["task_id"] == cap and m["no_ground_truth"] is True
    assert m["campaign_predictions"] == f"output/est{cap}_treat"
    assert sum(m["reference"]["pass_by_uuid"]["on"].values()) == n_pass  # the scorecard's rate, kept
    assert set(m["reference"]["pass_by_uuid"]["on"]) == set(ids)
    assert m["default_arms"] == f"cuga_eval_cap{cap}_fc@pre_parity,cuga_eval_cap{cap}_fc"
    assert all(k == v["vakra_uuid"] for k, v in um["zip_to_vakra"].items()) and set(
        um["zip_to_vakra"]
    ) == set(ids)


def test_est3_reference_ids_come_from_the_full_est3_manifest():
    full = _manifest("parity_est3_cap3")["reference"]["pass_by_uuid"]["on"]
    ref = _manifest("parity_est3_ref30")["reference"]["pass_by_uuid"]["on"]
    assert set(ref) <= set(full) and all(full[u] == v for u, v in ref.items())


def test_fresh_est3_slice_is_disjoint_from_the_first_and_keeps_the_rate():
    full = _manifest("parity_est3_cap3")["reference"]["pass_by_uuid"]["on"]
    ref = _manifest("parity_est3_ref30")["reference"]["pass_by_uuid"]["on"]
    fresh = _manifest("parity_est3_fresh30")
    flags = fresh["reference"]["pass_by_uuid"]["on"]
    assert len(flags) == 30 and not set(flags) & set(ref) and set(flags) <= set(full)
    assert sum(flags.values()) == 17 and all(full[u] == v for u, v in flags.items())
    assert fresh["selection"]["excluding"] == ["parity_est3_ref30"]


def test_exclude_leaves_the_excluded_items_out_of_the_pool(monkeypatch, tmp_path):
    from benchmarks.m3.parity import make_reference as mr

    items = {f"d{d}": [f"u{d}-{i}" for i in range(4)] for d in range(5)}
    (tmp_path / "sample.json").write_text(json.dumps(items))
    monkeypatch.setitem(mr.SOURCES, 3, {**mr.SOURCES[3], "sample": "sample.json", "scores": "scores"})
    monkeypatch.setattr(mr, "load_verdicts", lambda _p: {u: True for us in items.values() for u in us})
    first, _ = mr.build(3, 8, "a", tmp_path)
    first_ids = [u for us in first["ids_by_domain"].values() for u in us]
    second, um = mr.build(3, 8, "b", tmp_path, exclude={"a": first_ids})
    second_ids = [u for us in second["ids_by_domain"].values() for u in us]
    assert (
        len(second_ids) == 8
        and not set(second_ids) & set(first_ids)
        and set(um["zip_to_vakra"]) == set(second_ids)
    )


def test_variant_arms_dry_run_and_unknown_variant_is_rejected():
    out = subprocess.run(  # noqa: S603  (fixed, trusted args)
        [BASH, str(PARITY / "run_parity.sh"), "--subset", "parity_est3_ref30", "--dry-run", "--run-id", "x"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "PARITY_FC=1 PARITY_VARIANT=pre_parity bash" in out
    assert "PARITY_FC=1 bash" in out  # the shipped preset: no variant
    assert out.count("run_cuga_eval_arm.sh x parity_est3_ref30 cap3") == 2
    bad = subprocess.run(  # noqa: S603
        [BASH, str(PARITY / "run_parity.sh"), "--subset", "parity_est3_ref30", "--arms", "cuga_eval_cap3_fc@nope",
         "--dry-run", "--run-id", "x"],
        capture_output=True,
        text=True,
    )  # fmt: skip
    assert bad.returncode == 2 and "unknown variant nope" in bad.stderr


def test_pre_parity_variant_restores_the_gate_config():
    from benchmarks.m3.adapter.config import cuga_setting_pins, resolve_adapter_config, runtime_configurable

    env = {}
    for line in (PARITY / "variants" / "pre_parity.env").read_text().splitlines():
        if line and not line.startswith("#"):
            k, _, v = line.partition("=")
            env[k] = v
    cfg = resolve_adapter_config("cap3", env=env)
    assert runtime_configurable(cfg) == {} and cuga_setting_pins(cfg) == []
    assert cfg.harness_instructions and not cfg.fc_answer_format and cfg.agent_timeout is None
    assert resolve_adapter_config("cap2", env=env).cap2_verbatim is True


def test_report_has_a_variant_effect_row_and_rows_per_reference_recipe(tmp_path):
    run = tmp_path / "run"
    for arm, variant, scores in (
        ("cuga_eval_cap3_fc@pre_parity", "pre_parity", {"V-1": 0.0, "V-2": 1.0}),
        ("cuga_eval_cap3_fc", "", {"V-1": 1.0, "V-2": 1.0}),
    ):
        d = run / arm
        d.mkdir(parents=True)
        meta = {"stack": "cuga-eval", "adapter_preset": "cap3", "fc": "1", "variant": variant}
        (d / "meta.json").write_text(json.dumps(meta))
        (d / "vendor_results.json").write_text(json.dumps(_vendor(scores)))
    manifest = {
        "n": 2,
        "ids_by_domain": {"hockey": ["V-1", "V-2"]},
        "reference": {
            "pass_rate": {"on": 0.5, "codeact_stepwise": 0.0},
            "pass_by_uuid": {
                "on": {"V-1": True, "V-2": False},
                "codeact_stepwise": {"V-1": False, "V-2": False},
            },
        },
    }
    um = {"zip_to_vakra": {u: {"vakra_uuid": u, "domain": "hockey"} for u in ("V-1", "V-2")}, "unmatched": []}
    report = compare.render_report("s", manifest, um, compare.load_run(run, manifest, um))
    assert "| cuga_eval_cap3_fc@pre_parity | cuga-eval | cap3 +FC @pre_parity |" in report
    assert "## Variant effect" in report
    assert (
        "| cuga_eval_cap3_fc | cuga_eval_cap3_fc@pre_parity |  50.0% | 100.0% | 2 | +50.0pt | 1 | 0 |"
        in report
    )
    assert "| cuga_eval_cap3_fc | on |" in report and "| cuga_eval_cap3_fc | codeact_stepwise |" in report


def _chunk_fixture(tmp_path, n=12, missing=()):
    gt, pred = tmp_path / "gt", tmp_path / "pred"
    gt.mkdir()
    pred.mkdir()
    uuids = [f"V-{i}" for i in range(n)]
    (gt / "hockey.json").write_text(json.dumps([{"uuid": u} for u in uuids]))
    (pred / "hockey.json").write_text(json.dumps([{"uuid": u} for u in uuids if u not in missing]))
    return gt, pred, uuids


def test_chunked_scoring_runs_chunks_of_five_and_merges_dialogues(tmp_path):
    from benchmarks.m3.parity import rescore_chunked

    gt, pred, uuids = _chunk_fixture(tmp_path, missing={"V-11"})
    calls, restarts = [], []

    def evaluate(g, p, out):
        part = [r["uuid"] for r in json.loads((p / "hockey.json").read_text())]
        calls.append(part)
        dialogues = [{"uuid": u, "score": 1.0 if u.endswith(("0", "2")) else 0.0} for u in part]
        out.write_text(json.dumps({"domains": {"hockey": {"dialogues": dialogues}}}))
        return True

    block = rescore_chunked.score_domain(
        "hockey", gt, pred, tmp_path / "work", evaluate, lambda: restarts.append(1)
    )
    assert [len(c) for c in calls] == [5, 5, 1] and len(restarts) == 3  # fresh container per chunk
    assert block["missing_prediction_uuids"] == ["V-11"] and block["n_paired"] == 11
    merged = rescore_chunked.merge("cap", gt, pred, [block])
    assert merged["summary"]["n_samples"] == 11 and merged["summary"]["n_unscored"] == 0
    assert compare.vendor_scores(merged)["V-10"] == 1.0  # compare.py reads the merged file


def test_chunked_scoring_retries_then_reports_a_wedged_chunk_as_unscored(tmp_path):
    from benchmarks.m3.parity import rescore_chunked

    gt, pred, uuids = _chunk_fixture(tmp_path, n=7)
    attempts = []

    def evaluate(g, p, out):
        part = [r["uuid"] for r in json.loads((p / "hockey.json").read_text())]
        attempts.append(part[0])
        if part[0] == "V-0":  # the first chunk wedges every time
            return False
        out.write_text(
            json.dumps({"domains": {"hockey": {"dialogues": [{"uuid": u, "score": 1.0} for u in part]}}})
        )
        return True

    block = rescore_chunked.score_domain(
        "hockey", gt, pred, tmp_path / "w", evaluate, lambda: None, retries=1
    )
    assert attempts == ["V-0", "V-0", "V-5"]  # one retry for the wedged chunk
    assert block["unscored_uuids"] == uuids[:5] and block["n_paired"] == 2


def test_report_lists_tasks_left_out_of_the_pass_rates(tmp_path):
    run = tmp_path / "run"
    d = run / "cuga_eval_cap3_fc"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"stack": "cuga-eval", "adapter_preset": "cap3", "fc": "1"}))
    vr = _vendor({"V-1": 1.0})
    vr["domains"]["hockey"].update(unscored_uuids=["V-2"], missing_prediction_uuids=["V-3"])
    (d / "vendor_results.json").write_text(json.dumps(vr))
    manifest = {"n": 3, "ids_by_domain": {"hockey": ["V-1", "V-2", "V-3"]}}
    um = {
        "zip_to_vakra": {u: {"vakra_uuid": u, "domain": "hockey"} for u in ("V-1", "V-2", "V-3")},
        "unmatched": [],
    }
    report = compare.render_report("s", manifest, um, compare.load_run(run, manifest, um))
    assert (
        "cuga_eval_cap3_fc: 1 unscored (scoring or the judge failed after its retry), 1 without a prediction"
        in report
    )
    assert "| cuga_eval_cap3_fc | cuga-eval | cap3 +FC | 1 | 100.0% (1/1) |" in report


def _git_cmd(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)  # noqa: S603, S607


def test_cuga_identity_tells_the_shared_main_checkout_from_a_pinned_worktree(tmp_path):
    from benchmarks.m3.parity import cuga_identity

    main = tmp_path / "cuga-agent"
    (main / "src" / "cuga").mkdir(parents=True)
    (main / "src" / "cuga" / "__init__.py").write_text("")
    _git_cmd("init", "-q", cwd=main)
    _git_cmd("-c", "user.name=t", "-c", "user.email=t@t", "add", ".", cwd=main)
    _git_cmd("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c", cwd=main)
    _git_cmd("worktree", "add", "-q", "--detach", str(tmp_path / "pinned"), "HEAD", cwd=main)

    shared = cuga_identity.identity(str(main / "src" / "cuga"))
    pinned = cuga_identity.identity(str(tmp_path / "pinned" / "src" / "cuga"))
    assert shared["main_worktree"] is True and pinned["main_worktree"] is False
    assert shared["commit"] == pinned["commit"] and pinned["dirty"] == 0
    assert cuga_identity.as_line(pinned).endswith(f"{pinned['commit']} HEAD 0 0")
    (tmp_path / "pinned" / "src" / "cuga" / "x.py").write_text("")
    assert (
        cuga_identity.identity(str(tmp_path / "pinned" / "src" / "cuga"))["dirty"] == 1
    )  # edits change the id


def test_stacked_variants_dry_run_and_each_part_must_exist():
    out = subprocess.run(  # noqa: S603  (fixed, trusted args)
        [BASH, str(PARITY / "run_parity.sh"), "--subset", "parity_est3_ref30", "--arms",
         "cuga_eval_cap3_fc@stage1+require_tool,cuga_eval_cap3_fc@stage1", "--dry-run", "--run-id", "x"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout  # fmt: skip
    assert "PARITY_FC=1 PARITY_VARIANT=stage1+require_tool bash" in out
    assert "PARITY_FC=1 PARITY_VARIANT=stage1 bash" in out
    bad = subprocess.run(  # noqa: S603
        [BASH, str(PARITY / "run_parity.sh"), "--subset", "parity_est3_ref30", "--arms",
         "cuga_eval_cap3_fc@stage1+nope", "--dry-run", "--run-id", "x"],
        capture_output=True,
        text=True,
    )  # fmt: skip
    assert bad.returncode == 2 and "unknown variant nope" in bad.stderr


@pytest.mark.parametrize("variant", sorted(p.stem for p in (PARITY / "variants").glob("*.env")))
def test_every_variant_resolves_on_its_presets(variant):
    from benchmarks.m3.adapter.config import resolve_adapter_config

    env = {}
    for line in (PARITY / "variants" / f"{variant}.env").read_text().splitlines():
        if line and not line.startswith("#"):
            k, _, v = line.partition("=")
            assert k.startswith("M3_ADAPTER_"), f"{variant}: {k}"
            env[k] = v
    for preset in ("cap1", "cap2", "cap3", "cap4_v3wx"):
        resolve_adapter_config(preset, env=env)  # raises on a malformed or unknown value


# ------------------------------------------------------------------------- cap4


def test_cap4_campaign_history_uses_the_gold_answers_of_earlier_turns():
    from benchmarks.m3.parity.eval_m3_cap4 import campaign_history

    turns = [
        {"turn_id": 0, "query": "q1", "answer": "a1"},
        {"turn_id": 1, "query": "q2", "answer": ["a2"]},
        {"turn_id": 2, "query": "q3"},
    ]
    hist = campaign_history(turns)
    assert [(m.type, m.content) for m in hist] == [
        ("human", "q1"),
        ("ai", "a1"),
        ("human", "q2"),
        ("ai", "['a2']"),
    ]
    assert campaign_history(turns[-1:]) == []


async def test_cap4_runs_only_the_last_turn_with_the_history_prepended(monkeypatch):
    from langchain_core.messages import HumanMessage

    from benchmarks.m3.parity import eval_m3_cap4

    seen = {}

    async def fake_original(agent, turns, *args, **kwargs):
        seen["turns"] = turns
        await agent.invoke([HumanMessage(content=turns[-1]["query"])], thread_id="t")
        return {"all_responses": [{"turn": 1, "response": "x"}]}

    class _Agent:
        async def invoke(self, message, **kwargs):
            seen["messages"] = [m.content for m in message]
            return None

    monkeypatch.setattr(eval_m3_cap4, "_original_multiturn", fake_original)
    turns = [{"turn_id": 0, "query": "q1", "answer": "a1"}, {"turn_id": 1, "query": "q2"}]
    result = await eval_m3_cap4.last_turn_with_campaign_history(agent=_Agent(), turns=turns, task_name="s")
    assert seen["turns"] == turns[-1:] and seen["messages"] == ["q1", "a1", "q2"]
    assert result["all_responses"][0]["turn"] == 2  # eval_m3 writes turn_id 1: the last GT turn


async def test_cap4_failed_call_still_predicts_the_last_turn_empty(monkeypatch):
    from benchmarks.m3.parity import eval_m3_cap4

    async def timed_out(agent, turns, *args, **kwargs):  # the helper's error path: no all_responses
        return {"response": "", "success": False, "error": "agent_timeout 300s exceeded"}

    monkeypatch.setattr(eval_m3_cap4, "_original_multiturn", timed_out)
    turns = [{"turn_id": 0, "query": "q1", "answer": "a1"}, {"turn_id": 1, "query": "q2"}]
    result = await eval_m3_cap4.last_turn_with_campaign_history(agent=object(), turns=turns, task_name="s")
    assert result["all_responses"] == [{"turn": 2, "query": "q2", "response": "", "tool_calls": []}]
    assert result["error"] == "agent_timeout 300s exceeded"  # the failure itself is kept


def test_snapshot_keeps_only_the_last_predicted_turn_for_cap4():
    recs = [{"uuid": "u", "output": [{"turn_id": 0}, {"turn_id": 1}]}]
    assert snapshot.last_turn_only(recs) == [{"uuid": "u", "output": [{"turn_id": 1}]}]


def test_prepare_reads_the_manifest_train_data_path(tmp_path):
    from benchmarks.m3.parity import prepare_vakra_train

    src = tmp_path / "vm" / "cap4_train" / "data"
    for sub, body in (
        ("input", [{"uuid": "u", "dialogue": {"turns": []}}]),
        ("output", [{"uuid": "u", "output": []}]),
    ):
        (src / sub).mkdir(parents=True)
        (src / sub / "hockey.json").write_text(json.dumps(body))
    counts = prepare_vakra_train.prepare(
        tmp_path / "vm", "capability_4_multiturn", ["hockey"], tmp_path / "out", "cap4_train/data"
    )
    assert counts == {"hockey": 1}
    assert (tmp_path / "out" / "capability_4_multiturn" / "output" / "hockey.json").exists()


def test_cap4_dry_run_plans_its_arms():
    out = subprocess.run(  # noqa: S603  (fixed, trusted args)
        [BASH, str(PARITY / "run_parity.sh"), "--subset", "parity_est4_ref30", "--arms",
         "cuga_eval_cap4_v3wx,cuga_eval_cap4_v3wx@soft2", "--dry-run", "--run-id", "x"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout  # fmt: skip
    assert "PARITY_FC=0 bash" in out and "PARITY_FC=0 PARITY_VARIANT=soft2 bash" in out
    assert out.count("run_cuga_eval_arm.sh x parity_est4_ref30 cap4_v3wx") == 2


def test_chunked_scoring_retries_judge_errors_and_never_counts_them_as_failures(tmp_path):
    from benchmarks.m3.parity import rescore_chunked

    gt, pred, uuids = _chunk_fixture(tmp_path, n=3)
    attempts = []

    def evaluate(g, p, out):
        attempts.append(1)
        bad = {"per_turn": [{"metadata": {"score_explanation": {"answer": "Judge Error {e}."}}}]}
        dialogues = [{"uuid": "V-0", "score": 1.0}, {"uuid": "V-1", "score": 0.0, "details": bad}]
        if len(attempts) > 1:  # the retry still errors on V-1, V-2 is fine
            dialogues.append({"uuid": "V-2", "score": 0.0})
        out.write_text(json.dumps({"domains": {"hockey": {"dialogues": dialogues}}}))
        return True

    block = rescore_chunked.score_domain(
        "hockey", gt, pred, tmp_path / "w", evaluate, lambda: None, retries=1
    )
    assert len(attempts) == 2  # judge errors triggered one retry
    assert block["judge_error_uuids"] == ["V-1"] and [d["uuid"] for d in block["dialogues"]] == ["V-0", "V-2"]
    merged = rescore_chunked.merge("cap", gt, pred, [block])
    assert merged["summary"]["n_judge_errors"] == 1 and merged["summary"]["n_samples"] == 2
