"""Unit tests for benchmarks.helpers.compare_state (M4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.helpers.compare_state import (
    already_completed_combo_runs,
    eval_flags_for_combo,
    format_compare_progress,
    init_compare_state,
    is_combo_done,
    mark_combo_run_completed,
    mark_combo_run_started,
    sub_experiment_name,
    workspace_bundle_inputs,
)


@pytest.mark.sanity
def test_sub_experiment_name_sanitizes_config():
    name = sub_experiment_name("cmp", "gpt-oss:cuga:policies", 2)
    assert name == "cmp__gpt-oss_cuga_policies__r2"


@pytest.mark.sanity
def test_init_and_mark_completed(tmp_path: Path):
    init_compare_state(
        tmp_path,
        total_planned=2,
        configs=["a:b:c"],
        runs_per_config=1,
        compare_experiment="cmp",
    )
    mark_combo_run_started(tmp_path, "a:b:c", 1, sub_experiment="cmp__a_b_c__r1")
    mark_combo_run_completed(tmp_path, "a:b:c", 1, exit_code=0)
    assert is_combo_done(tmp_path, "a:b:c", 1)
    assert already_completed_combo_runs(tmp_path) == {("a:b:c", 1)}


@pytest.mark.sanity
def test_eval_flags_resume_after_start(tmp_path: Path):
    init_compare_state(
        tmp_path,
        total_planned=1,
        configs=["m:a:p"],
        runs_per_config=1,
        compare_experiment="cmp",
    )
    mark_combo_run_started(tmp_path, "m:a:p", 1, sub_experiment="cmp__m_a_p__r1")
    flags = eval_flags_for_combo("cmp", "m:a:p", 1, compare_dir=tmp_path)
    assert flags == ["--resume-experiment", "cmp__m_a_p__r1"]


@pytest.mark.sanity
def test_format_compare_progress(tmp_path: Path):
    init_compare_state(
        tmp_path,
        total_planned=3,
        configs=["x"],
        runs_per_config=3,
        compare_experiment="cmp",
    )
    text = format_compare_progress(tmp_path)
    assert "compare bundle:" in text
    assert "0/3 completed" in text


def _make_sub_bundle(compare_dir: Path, sub_experiment: str, *, result_file: str | None = None) -> Path:
    sub_dir = compare_dir.parent / sub_experiment
    if result_file is not None:
        results_dir = sub_dir / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / result_file).write_text('{"metrics": {}, "results": []}')
        (sub_dir / "trajectories").mkdir(exist_ok=True)
        (sub_dir / "logs").mkdir(exist_ok=True)
        (sub_dir / "logs" / "console.log").write_text("log")
    else:
        sub_dir.mkdir(parents=True, exist_ok=True)
    return sub_dir


@pytest.mark.sanity
def test_workspace_bundle_inputs_sources_from_combo_sub_bundles(tmp_path: Path):
    compare_dir = tmp_path / "my-compare"
    compare_dir.mkdir()
    init_compare_state(
        compare_dir,
        total_planned=2,
        configs=["gpt-oss:cuga"],
        runs_per_config=2,
        compare_experiment="my-compare",
    )
    sub1 = "my-compare__gpt-oss_cuga__r1"
    sub2 = "my-compare__gpt-oss_cuga__r2"
    mark_combo_run_started(compare_dir, "gpt-oss:cuga", 1, sub_experiment=sub1)
    mark_combo_run_completed(compare_dir, "gpt-oss:cuga", 1, exit_code=0)
    mark_combo_run_started(compare_dir, "gpt-oss:cuga", 2, sub_experiment=sub2)
    mark_combo_run_completed(compare_dir, "gpt-oss:cuga", 2, exit_code=0)

    _make_sub_bundle(compare_dir, sub1, result_file="bpo_20260101_000000.json")
    _make_sub_bundle(compare_dir, sub2, result_file="bpo_20260101_000100.json")

    inputs = workspace_bundle_inputs(compare_dir)

    assert set(inputs["config_results"].keys()) == {"gpt-oss:cuga"}
    result_files = inputs["config_results"]["gpt-oss:cuga"]
    assert len(result_files) == 2
    assert any("000000" in f for f in result_files)
    assert any("000100" in f for f in result_files)

    traj_groups = inputs["trajectory_dirs"]["gpt-oss:cuga"]
    assert len(traj_groups) == 2  # one group per run, in run order

    log_groups = inputs["log_files"]["gpt-oss:cuga"]
    assert len(log_groups) == 2
    assert all(any("console.log" in f for f in group) for group in log_groups)


@pytest.mark.sanity
def test_workspace_bundle_inputs_skips_combo_without_results(tmp_path: Path):
    compare_dir = tmp_path / "cmp2"
    compare_dir.mkdir()
    init_compare_state(
        compare_dir,
        total_planned=1,
        configs=["m:a"],
        runs_per_config=1,
        compare_experiment="cmp2",
    )
    sub = "cmp2__m_a__r1"
    mark_combo_run_started(compare_dir, "m:a", 1, sub_experiment=sub)
    # Sub-bundle exists but has no results yet (still running / never produced output).
    _make_sub_bundle(compare_dir, sub)

    inputs = workspace_bundle_inputs(compare_dir)

    assert inputs["config_results"] == {}
    assert inputs["trajectory_dirs"] == {}
    assert inputs["log_files"] == {}
