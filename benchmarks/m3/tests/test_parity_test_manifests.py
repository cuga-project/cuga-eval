"""make_test_manifests: every test task id per domain, identity uuid map, eval-key TOML (merged)."""

import json
import tomllib

import pytest

from benchmarks.m3.parity import make_test_manifests as mtm

pytestmark = pytest.mark.sanity


def _vakra(tmp_path):
    src = tmp_path / "vakra" / "data" / "test" / "capability_3_multihop_reasoning" / "input"
    src.mkdir(parents=True)
    (src / "zoo.json").write_text(json.dumps([{"uuid": "z-1"}, {"uuid": "z-2"}]))
    (src / "aqua.json").write_text(json.dumps([{"uuid": "a-1"}]))
    (src / "empty.json").write_text("[]")
    return tmp_path / "vakra"


def test_manifest_lists_every_test_task_and_a_one_task_smoke(tmp_path):
    out, keys = tmp_path / "manifests", tmp_path / "keys.toml"
    keys.write_text('other = [\n  "x",\n]\n')
    rc = mtm.main(
        [
            "--caps",
            "3",
            "--smoke",
            "--vakra-main",
            str(_vakra(tmp_path)),
            "--manifests",
            str(out),
            "--keys-out",
            str(keys),
        ]
    )
    assert rc == 0
    m = json.loads((out / "test_cap3.json").read_text())
    assert m["ids_by_domain"] == {"aqua": ["a-1"], "zoo": ["z-1", "z-2"]} and m["n"] == 3
    assert (
        m["no_ground_truth"]
        and m["m3_data"] == "local:vakra_test"
        and m["default_arms"] == "cuga_eval_cap3_fc"
    )
    assert m["vakra_train_data"] == "data/test/capability_3_multihop_reasoning"
    smoke = json.loads((out / "test_cap3_smoke.json").read_text())
    assert smoke["ids_by_domain"] == {"aqua": ["a-1"]} and smoke["n"] == 1
    umap = json.loads((out / "uuid_map_test_cap3.json").read_text())
    assert umap["zip_to_vakra"]["z-2"] == {"vakra_uuid": "z-2", "domain": "zoo", "match": "identity"}
    lists = tomllib.loads(keys.read_text())
    assert lists == {"other": ["x"], "test_cap3": ["a-1", "z-1", "z-2"], "test_cap3_smoke": ["a-1"]}


def test_missing_test_inputs_fail_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        mtm.test_ids(tmp_path, 1)
