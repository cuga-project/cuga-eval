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
SUBSETS = ("parity_smoke_hockey", "parity_cap2_30", "parity_cap3_20")
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
def test_manifest_ids_are_unique_complete_and_in_the_bundled_zip(name):
    m = _manifest(name)
    ids = snapshot.manifest_uuids(m)
    assert m["n"] == len(ids) == len(set(ids))
    for domain, dom_ids in m["ids_by_domain"].items():
        assert set(dom_ids) <= _zip_uuids(m["capability_dir"], domain), (
            f"{name}/{domain}: id not in small_train.zip"
        )
    for arm in ("off", "on"):
        flags = m["reference"]["pass_by_uuid"][arm]
        assert set(flags) == set(ids)
        assert abs(sum(flags.values()) / len(ids) - m["reference"]["pass_rate"][arm]) < 0.01


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
