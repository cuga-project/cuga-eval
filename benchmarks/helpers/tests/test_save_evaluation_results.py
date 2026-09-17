"""Unit tests for save_evaluation_results' filename/timestamp selection.

Covers the EVAL_RUN_ID env var fallback added to fix concurrent runs on the
same host clobbering each other's result-file selection in eval.sh (PR #98
review from Sergey-Zeltyn).
"""

import json

import pytest

from benchmarks.helpers.sdk_eval_helpers import save_evaluation_results


@pytest.fixture
def no_results():
    return [{"success": True, "match_rate": 1.0}]


def test_explicit_run_timestamp_wins(tmp_path, no_results, monkeypatch):
    monkeypatch.setenv("EVAL_RUN_ID", "should_not_be_used")
    saved = save_evaluation_results(no_results, tmp_path, prefix="bpo", run_timestamp="explicit_ts")
    assert saved.name == "bpo_explicit_ts.json"


def test_eval_run_id_env_var_used_when_no_explicit_timestamp(tmp_path, no_results, monkeypatch):
    monkeypatch.setenv("EVAL_RUN_ID", "20260702_130925_54321")
    saved = save_evaluation_results(no_results, tmp_path, prefix="bpo")
    assert saved.name == "bpo_20260702_130925_54321.json"


def test_falls_back_to_now_when_no_run_id_or_timestamp(tmp_path, no_results, monkeypatch):
    monkeypatch.delenv("EVAL_RUN_ID", raising=False)
    saved = save_evaluation_results(no_results, tmp_path, prefix="bpo")
    # No fixed value to assert on other than "some timestamp-shaped name" —
    # just confirm it didn't silently pick up a leftover env var.
    assert saved.name.startswith("bpo_")
    assert saved.name != "bpo_.json"


def test_concurrent_run_ids_produce_distinct_files(tmp_path, no_results, monkeypatch):
    monkeypatch.setenv("EVAL_RUN_ID", "run_a")
    saved_a = save_evaluation_results(no_results, tmp_path, prefix="bpo")
    monkeypatch.setenv("EVAL_RUN_ID", "run_b")
    saved_b = save_evaluation_results(no_results, tmp_path, prefix="bpo")
    assert saved_a != saved_b
    assert saved_a.exists() and saved_b.exists()
    assert json.loads(saved_a.read_text())["metrics"]["timestamp"] == "run_a"
    assert json.loads(saved_b.read_text())["metrics"]["timestamp"] == "run_b"
