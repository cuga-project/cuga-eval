"""Tests for the bundle-as-workspace functions and Langfuse repair logic (M1).

These avoid the heavy ``cuga`` import chain: ``bundle.py`` and
``compare_report.py`` are both pure-stdlib at import time, and Langfuse network
access is mocked.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from benchmarks.helpers import bundle


def _write_merged_results(bundle_dir, results):
    results_dir = bundle_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "metrics": {
            "total_tasks": len(results),
            "passed": sum(1 for r in results if r.get("success")),
        },
        "results": results,
    }
    (results_dir / "m3_merged.json").write_text(json.dumps(payload))


# --------------------------------------------------------------------------
# create/finalize workspace
# --------------------------------------------------------------------------


@pytest.mark.sanity
def test_create_workspace_bundle_initial(tmp_path):
    bd = tmp_path / "exp"
    bundle.create_workspace_bundle(bd, "m3", experiment_name="exp")
    assert (bd / "results" / "partial").is_dir()
    meta = json.loads((bd / "metadata.json").read_text())
    assert meta["status"] == "in_progress"
    assert meta["experiment_name"] == "exp"
    assert meta["benchmark"] == "m3"
    assert len(meta["resume_history"]) == 1


@pytest.mark.sanity
def test_create_workspace_bundle_resume_appends_history(tmp_path):
    bd = tmp_path / "exp"
    bundle.create_workspace_bundle(bd, "m3", experiment_name="exp")
    created_at = json.loads((bd / "metadata.json").read_text())["created_at"]
    bundle.create_workspace_bundle(bd, "m3", experiment_name="exp")
    meta = json.loads((bd / "metadata.json").read_text())
    assert len(meta["resume_history"]) == 2
    assert meta["created_at"] == created_at  # preserved across resume
    assert meta["experiment_name"] == "exp"


@pytest.mark.sanity
def test_finalize_workspace_bundle_flips_status_and_reports(tmp_path):
    bd = tmp_path / "exp"
    bundle.create_workspace_bundle(bd, "m3", experiment_name="exp")
    _write_merged_results(bd, [{"task_name": "t1", "success": True}, {"task_name": "t2", "success": False}])
    bundle.finalize_workspace_bundle(bd, "m3", fetch_langfuse=False)
    meta = json.loads((bd / "metadata.json").read_text())
    assert meta["status"] == "completed"
    assert meta["experiment_name"] == "exp"  # preserved
    assert "finalized_at" in meta
    assert (bd / "report.md").exists()
    assert (bd / "report.md").read_text().strip() != ""


@pytest.mark.sanity
def test_finalize_workspace_bundle_directory_task_file(tmp_path):
    # --m3-data runs pass a dataset *directory* as the task source (issue seen
    # on every rwPG-* run: IsADirectoryError killed finalization). Directories
    # must be recorded as a pointer + "dir:" hash, not copied.
    bd = tmp_path / "exp"
    bundle.create_workspace_bundle(bd, "m3", experiment_name="exp")
    _write_merged_results(bd, [{"task_name": "t1", "success": True}])
    data_dir = tmp_path / "capability_3_multihop_reasoning"
    (data_dir / "input").mkdir(parents=True)
    (data_dir / "input" / "chicago_crime.json").write_text("[]")
    regular = tmp_path / "hockey.json"
    regular.write_text("[]")
    bundle.finalize_workspace_bundle(bd, "m3", task_files=[data_dir, regular], fetch_langfuse=False)
    meta = json.loads((bd / "metadata.json").read_text())
    assert meta["status"] == "completed"
    hashes = meta["ground_truth"]["task_file_hashes"]
    assert hashes["capability_3_multihop_reasoning"].startswith("dir:")
    assert hashes["hockey.json"].startswith("sha256:")
    pointer = bd / "tasks" / "capability_3_multihop_reasoning.source"
    assert pointer.exists()
    assert str(data_dir.resolve()) in pointer.read_text()
    assert (bd / "tasks" / "hockey.json").exists()


@pytest.mark.sanity
def test_record_task_file_regular_file(tmp_path):
    tasks_dir = tmp_path / "tasks"
    tf = tmp_path / "hockey.json"
    tf.write_text("[]")
    entry = bundle._record_task_file(tf, tasks_dir)
    # Known digest of the literal content "[]", independent of _file_sha256.
    assert entry == "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    assert (tasks_dir / "hockey.json").read_text() == "[]"


@pytest.mark.sanity
def test_record_task_file_directory(tmp_path):
    tasks_dir = tmp_path / "tasks"
    data_dir = tmp_path / "capability_3_multihop_reasoning"
    data_dir.mkdir()
    entry = bundle._record_task_file(data_dir, tasks_dir)
    assert entry == f"dir:{data_dir.resolve()}"
    pointer = tasks_dir / "capability_3_multihop_reasoning.source"
    assert pointer.exists()
    assert pointer.read_text() == f"{data_dir.resolve()}\n"


@pytest.mark.sanity
def test_record_task_file_nonexistent_returns_none(tmp_path):
    tasks_dir = tmp_path / "tasks"
    missing = tmp_path / "does_not_exist.json"
    assert bundle._record_task_file(missing, tasks_dir) is None
    assert not tasks_dir.exists()


@pytest.mark.sanity
def test_record_task_file_no_tasks_dir_skips_write(tmp_path):
    tf = tmp_path / "hockey.json"
    tf.write_text("[]")
    entry = bundle._record_task_file(tf, None)
    assert entry == "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    # No tasks_dir given: nothing written to disk beyond the source file itself.
    assert list(tmp_path.iterdir()) == [tf]


@pytest.mark.sanity
def test_finalize_workspace_bundle_partial_status(tmp_path):
    bd = tmp_path / "exp"
    bundle.create_workspace_bundle(bd, "m3")
    _write_merged_results(bd, [{"task_name": "t1", "success": True}])
    bundle.finalize_workspace_bundle(bd, "m3", partial=True, fetch_langfuse=False)
    meta = json.loads((bd / "metadata.json").read_text())
    assert meta["status"] == "partial"


# --------------------------------------------------------------------------
# Langfuse retry / skip-existing
# --------------------------------------------------------------------------


def _http_error(code, retry_after=None):
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("http://x", code, "err", headers, None)


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


@pytest.mark.sanity
def test_retry_after_seconds_numeric():
    err = _http_error(429, retry_after="7")
    assert bundle._retry_after_seconds(err, 2.0) == 7.0


@pytest.mark.sanity
def test_retry_after_seconds_default_when_missing():
    err = _http_error(429)
    assert bundle._retry_after_seconds(err, 2.0) == 2.0


@pytest.mark.sanity
def test_langfuse_retries_on_429(tmp_path, monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    _write_merged_results(tmp_path, [{"task_name": "t1", "success": True, "trace_id": "tr1"}])

    calls = {"n": 0}

    def fake_urlopen(req, timeout=30):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _http_error(429, retry_after="0")
        return _FakeResp({"id": "tr1", "data": "ok"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    ok = bundle._download_langfuse_traces(tmp_path, [str(tmp_path / "results" / "m3_merged.json")])
    assert ok is True
    assert calls["n"] == 3  # two 429s then success, not abandoned after one
    traces = list((tmp_path / "langfuse_traces").glob("*.json"))
    assert len(traces) == 1


@pytest.mark.sanity
def test_langfuse_skip_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    _write_merged_results(tmp_path, [{"task_name": "t1", "success": True, "trace_id": "tr1"}])

    # Pre-create the destination trace file.
    dest = tmp_path / "langfuse_traces"
    dest.mkdir(parents=True)
    (dest / "t1_tr1.json").write_text("{}")

    def boom(*a, **k):
        raise AssertionError("urlopen should not be called when file exists")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    bundle._download_langfuse_traces(
        tmp_path, [str(tmp_path / "results" / "m3_merged.json")], skip_existing=True
    )  # must not raise


@pytest.mark.sanity
def test_langfuse_429_gives_up_after_max_and_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    _write_merged_results(tmp_path, [{"task_name": "t1", "success": True, "trace_id": "tr1"}])

    monkeypatch.setattr("time.sleep", lambda *_: None)
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(_http_error(429, "0"))
    )
    ok = bundle._download_langfuse_traces(tmp_path, [str(tmp_path / "results" / "m3_merged.json")])
    assert ok is False
    # No file left behind -> a later retry-langfuse will simply try again.
    assert not (tmp_path / "langfuse_traces" / "t1_tr1.json").exists()


# --------------------------------------------------------------------------
# assemble_compare_bundle bundle_dir_override (M4 compare-workspace fix)
# --------------------------------------------------------------------------


@pytest.mark.sanity
def test_assemble_compare_bundle_without_override_creates_timestamped_dir(tmp_path):
    result_file = tmp_path / "r1.json"
    result_file.write_text(json.dumps({"metrics": {}, "results": []}))
    bundle_dir = bundle.assemble_compare_bundle(
        report_content="report",
        config_results={"gpt-oss:cuga": [str(result_file)]},
        benchmark_name="bpo",
        bundle_root=tmp_path / "evaluation_bundles",
    )
    assert bundle_dir.parent == tmp_path / "evaluation_bundles"
    assert "_compare_" in bundle_dir.name


@pytest.mark.sanity
def test_assemble_compare_bundle_with_override_writes_in_place(tmp_path):
    result_file = tmp_path / "r1.json"
    result_file.write_text(json.dumps({"metrics": {}, "results": []}))
    existing_dir = tmp_path / "evaluation_bundles" / "my-compare-experiment"
    existing_dir.mkdir(parents=True)
    (existing_dir / "compare_state.json").write_text("{}")  # pre-existing workspace state

    bundle_dir = bundle.assemble_compare_bundle(
        report_content="report",
        config_results={"gpt-oss:cuga": [str(result_file)]},
        benchmark_name="bpo",
        bundle_root=tmp_path / "evaluation_bundles",
        bundle_dir_override=existing_dir,
    )

    assert bundle_dir == existing_dir
    assert (existing_dir / "metadata.json").exists()
    assert (existing_dir / "report.md").exists()
    # Finalizing in place must not disturb the pre-existing compare_state.json.
    assert (existing_dir / "compare_state.json").exists()
    # Result file must land under runs/, not a second freshly-timestamped dir.
    assert any(existing_dir.glob("runs/*/results/r1.json"))


@pytest.mark.sanity
def test_resume_history_records_eval_key(tmp_path):
    from benchmarks.helpers.bundle import create_workspace_bundle

    create_workspace_bundle(tmp_path, "appworld", experiment_name="x", args={"eval_key": "b1"})
    create_workspace_bundle(
        tmp_path, "appworld", experiment_name="x", args={"eval_key": "b1_uncompleted_tasks"}
    )
    meta = json.loads((tmp_path / "metadata.json").read_text())
    assert [h["eval_key"] for h in meta["resume_history"]] == ["b1", "b1_uncompleted_tasks"]


@pytest.mark.sanity
def test_run_eval_key_survives_a_keyless_resume(tmp_path):
    """eval.sh reads run.eval_key back to pick the official AppWorld evaluate.

    Clobbering it to None on any invocation that omits --eval-key made that
    fallback dead on arrival; model_profile and task_ids already preserved.
    """
    from benchmarks.helpers.bundle import create_workspace_bundle

    create_workspace_bundle(
        tmp_path, "appworld", experiment_name="x", args={"eval_key": "b1", "task_ids": ["a_1"]}
    )
    create_workspace_bundle(tmp_path, "appworld", experiment_name="x", args={})
    run = json.loads((tmp_path / "metadata.json").read_text())["run"]
    assert run["eval_key"] == "b1"
    assert run["task_ids"] == ["a_1"]
    # The per-invocation truth still lives in resume_history.
    hist = json.loads((tmp_path / "metadata.json").read_text())["resume_history"]
    assert [h["eval_key"] for h in hist] == ["b1", None]


@pytest.mark.sanity
def test_finalize_does_not_clobber_run_eval_key(tmp_path):
    """finalize runs before eval.sh reads the key back, so it must preserve too."""
    from benchmarks.helpers.bundle import create_workspace_bundle, finalize_workspace_bundle

    create_workspace_bundle(
        tmp_path, "appworld", experiment_name="x", args={"eval_key": "b1", "task_ids": ["a_1"]}
    )
    finalize_workspace_bundle(tmp_path, "appworld", args={})
    run = json.loads((tmp_path / "metadata.json").read_text())["run"]
    assert run["eval_key"] == "b1"
    assert run["task_ids"] == ["a_1"]
