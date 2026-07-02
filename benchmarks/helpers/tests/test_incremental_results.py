"""Unit tests for benchmarks.helpers.incremental_results (Slice A).

These are pure-stdlib tests: the module under test has no cuga dependency, so
the suite runs fast and in isolation. ``finalize_merged_results`` (which lazily
imports the heavy eval stack) is covered separately in the resume-integration
test where that import is available.
"""

from __future__ import annotations

import json

import pytest

from benchmarks.helpers import incremental_results as ir


def _write(bundle, task_id, *, error=None, domain=None, extra=None):
    result = {"task_name": task_id, "success": error is None, "error": error}
    if extra:
        result.update(extra)
    return ir.write_task_result(bundle, task_id, result, domain=domain)


@pytest.mark.sanity
def test_atomic_write_json_roundtrip(tmp_path):
    path = tmp_path / "sub" / "data.json"
    ir.atomic_write_json(path, {"a": 1, "b": [1, 2, 3]})
    assert json.loads(path.read_text()) == {"a": 1, "b": [1, 2, 3]}


@pytest.mark.sanity
def test_atomic_write_json_overwrites_and_leaves_no_temp(tmp_path):
    path = tmp_path / "data.json"
    ir.atomic_write_json(path, {"v": 1})
    ir.atomic_write_json(path, {"v": 2})
    assert json.loads(path.read_text()) == {"v": 2}
    # No leftover temp files from the mkstemp/replace dance.
    assert list(path.parent.glob("*.tmp")) == []


@pytest.mark.sanity
def test_write_task_result_sanitizes_filename(tmp_path):
    path = ir.write_task_result(tmp_path, "group/task\\x", {"task_name": "group/task\\x", "error": None})
    assert path.name == "group_task_x.json"
    assert path.parent == ir.partial_dir(tmp_path)


@pytest.mark.sanity
def test_write_task_result_domain_composite_filename(tmp_path):
    path = ir.write_task_result(tmp_path, "svc", {"task_name": "svc", "error": None}, domain="orders")
    assert path.name == "svc__orders.json"


@pytest.mark.sanity
def test_completed_excludes_errored_tasks(tmp_path):
    _write(tmp_path, "ok1")
    _write(tmp_path, "ok2")
    _write(tmp_path, "bad", error="boom")
    assert ir.load_completed_task_ids(tmp_path) == {"ok1", "ok2"}


@pytest.mark.sanity
def test_retry_overwrites_partial_file(tmp_path):
    # First attempt fails ...
    _write(tmp_path, "t", error="timeout")
    assert ir.load_completed_task_ids(tmp_path) == set()
    # ... retry succeeds and overwrites the same file.
    _write(tmp_path, "t")
    assert ir.load_completed_task_ids(tmp_path) == {"t"}
    assert len(ir.load_all_partial_results(tmp_path)) == 1


@pytest.mark.sanity
def test_load_all_includes_failures(tmp_path):
    _write(tmp_path, "ok")
    _write(tmp_path, "bad", error="boom")
    results = ir.load_all_partial_results(tmp_path)
    assert {r["task_name"] for r in results} == {"ok", "bad"}


@pytest.mark.sanity
def test_completed_domain_keys(tmp_path):
    _write(tmp_path, "svc", domain="orders")
    _write(tmp_path, "svc", domain="returns", error="boom")
    _write(tmp_path, "svc2", domain="orders")
    assert ir.load_completed_domain_keys(tmp_path) == {("svc", "orders"), ("svc2", "orders")}


@pytest.mark.sanity
def test_domain_injected_into_content_when_missing(tmp_path):
    ir.write_task_result(tmp_path, "svc", {"task_name": "svc", "error": None}, domain="orders")
    data = json.loads((ir.partial_dir(tmp_path) / "svc__orders.json").read_text())
    assert data["domain"] == "orders"


@pytest.mark.sanity
def test_load_helpers_empty_when_no_partial_dir(tmp_path):
    assert ir.load_completed_task_ids(tmp_path) == set()
    assert ir.load_completed_domain_keys(tmp_path) == set()
    assert ir.load_all_partial_results(tmp_path) == []


@pytest.mark.sanity
def test_corrupt_partial_file_is_ignored(tmp_path):
    _write(tmp_path, "ok")
    (ir.partial_dir(tmp_path) / "corrupt.json").write_text("{not json")
    assert ir.load_completed_task_ids(tmp_path) == {"ok"}
    assert len(ir.load_all_partial_results(tmp_path)) == 1


@pytest.mark.sanity
async def test_write_task_result_async(tmp_path):
    await ir.write_task_result_async(tmp_path, "t", {"task_name": "t", "error": None})
    assert ir.load_completed_task_ids(tmp_path) == {"t"}
