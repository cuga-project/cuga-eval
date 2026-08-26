"""Regression tests for issue #115's log-file fallback in create_eval_bundle.py.

_default_log_files() checks a run-scoped M3_RUN_TMP_DIR first and falls back to
the legacy fixed /tmp paths for logs left by pre-#115 runs. A CodeRabbit review
on PR #121 flagged that the original implementation appended *both* candidates
when they both existed, producing duplicate log-file entries in the bundle.
These tests pin the fixed behavior: at most one path per log name, preferring
the run-scoped directory.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.sanity

_SPEC = importlib.util.spec_from_file_location(
    "create_eval_bundle", Path(__file__).resolve().parents[1] / "scripts" / "create_eval_bundle.py"
)
create_eval_bundle = importlib.util.module_from_spec(_SPEC)
sys.modules["create_eval_bundle"] = create_eval_bundle
_SPEC.loader.exec_module(create_eval_bundle)


@pytest.fixture
def legacy_dir(tmp_path):
    d = tmp_path / "legacy"
    d.mkdir()
    return d


def test_prefers_run_scoped_dir_over_legacy(tmp_path, legacy_dir, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "m3_registry.log").write_text("run-scoped registry log\n")
    (run_dir / "m3_console.log").write_text("run-scoped console log\n")
    (legacy_dir / "m3_registry.log").write_text("stale legacy registry log\n")
    (legacy_dir / "m3_console.log").write_text("stale legacy console log\n")
    monkeypatch.setenv("M3_RUN_TMP_DIR", str(run_dir))

    logs = create_eval_bundle._default_log_files("m3", legacy_tmp_dir=legacy_dir)

    assert logs == [run_dir / "m3_registry.log", run_dir / "m3_console.log"]


def test_falls_back_to_legacy_when_run_scoped_missing(tmp_path, legacy_dir, monkeypatch):
    (legacy_dir / "m3_registry.log").write_text("stale legacy registry log\n")
    (legacy_dir / "m3_console.log").write_text("stale legacy console log\n")
    monkeypatch.setenv("M3_RUN_TMP_DIR", str(tmp_path / "does_not_exist"))

    logs = create_eval_bundle._default_log_files("m3", legacy_tmp_dir=legacy_dir)

    assert logs == [legacy_dir / "m3_registry.log", legacy_dir / "m3_console.log"]


def test_no_m3_run_tmp_dir_set_uses_legacy_only(legacy_dir, monkeypatch):
    (legacy_dir / "m3_registry.log").write_text("stale legacy registry log\n")
    monkeypatch.delenv("M3_RUN_TMP_DIR", raising=False)

    logs = create_eval_bundle._default_log_files("m3", legacy_tmp_dir=legacy_dir)

    assert logs == [legacy_dir / "m3_registry.log"]


def test_empty_or_missing_files_are_skipped(tmp_path, legacy_dir, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "m3_registry.log").write_text("")  # empty, should be skipped
    monkeypatch.setenv("M3_RUN_TMP_DIR", str(run_dir))

    logs = create_eval_bundle._default_log_files("m3", legacy_tmp_dir=legacy_dir)

    assert logs == []
