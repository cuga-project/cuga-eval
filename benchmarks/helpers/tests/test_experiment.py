"""Unit tests for benchmarks.helpers.experiment (Slice B)."""

from __future__ import annotations

import json

import pytest

from benchmarks.helpers.experiment import (
    ExperimentError,
    last_experiment_pointer_path,
    new_or_resume_bundle_dir,
    prepare_workspace,
    resolve_experiment_bundle_dir,
    resolve_last_experiment,
    validate_experiment_name,
    write_last_experiment_pointer,
)

BENCH = "bpo"


@pytest.mark.sanity
def test_validate_experiment_name_rejects_timestamp_shape():
    with pytest.raises(ExperimentError, match="timestamp"):
        validate_experiment_name("20260701_120000_default")


@pytest.mark.sanity
def test_validate_experiment_name_rejects_path_chars():
    with pytest.raises(ExperimentError, match="may only contain"):
        validate_experiment_name("foo/bar")


@pytest.mark.sanity
def test_validate_experiment_name_rejects_shell_metacharacters():
    with pytest.raises(ExperimentError, match="may only contain"):
        validate_experiment_name("foo; rm -rf /")


@pytest.mark.sanity
def test_validate_experiment_name_accepts_safe_chars():
    # Should not raise for the allowed character class.
    validate_experiment_name("my-exp.v2_final+1")


@pytest.mark.sanity
def test_resolve_experiment_bundle_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "benchmarks.helpers.experiment.bundle_root",
        lambda benchmark_name, compare=False: tmp_path / "bundles",
    )
    path = resolve_experiment_bundle_dir(BENCH, "my-exp")
    assert path == tmp_path / "bundles" / "my-exp"


@pytest.mark.sanity
def test_new_or_resume_no_flags_returns_legacy():
    bundle_dir, is_resume = new_or_resume_bundle_dir(BENCH)
    assert bundle_dir is None
    assert is_resume is False


@pytest.mark.sanity
def test_new_experiment_creates_path(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "benchmarks.helpers.experiment.bundle_root",
        lambda benchmark_name, compare=False: tmp_path / "bundles",
    )
    bundle_dir, is_resume = new_or_resume_bundle_dir(BENCH, experiment="alpha")
    assert bundle_dir == tmp_path / "bundles" / "alpha"
    assert is_resume is False


@pytest.mark.sanity
def test_existing_experiment_without_resume_errors(tmp_path, monkeypatch):
    root = tmp_path / "bundles"
    (root / "alpha").mkdir(parents=True)
    monkeypatch.setattr(
        "benchmarks.helpers.experiment.bundle_root",
        lambda benchmark_name, compare=False: root,
    )
    with pytest.raises(ExperimentError, match="already exists"):
        new_or_resume_bundle_dir(BENCH, experiment="alpha")


@pytest.mark.sanity
def test_resume_experiment_requires_existing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "benchmarks.helpers.experiment.bundle_root",
        lambda benchmark_name, compare=False: tmp_path / "bundles",
    )
    with pytest.raises(ExperimentError, match="not found"):
        new_or_resume_bundle_dir(BENCH, resume_experiment="missing")


@pytest.mark.sanity
def test_resume_experiment_opens_existing(tmp_path, monkeypatch):
    root = tmp_path / "bundles"
    (root / "alpha").mkdir(parents=True)
    monkeypatch.setattr(
        "benchmarks.helpers.experiment.bundle_root",
        lambda benchmark_name, compare=False: root,
    )
    bundle_dir, is_resume = new_or_resume_bundle_dir(BENCH, resume_experiment="alpha")
    assert bundle_dir == root / "alpha"
    assert is_resume is True


@pytest.mark.sanity
def test_bare_resume_uses_pointer(tmp_path, monkeypatch):
    root = tmp_path / "bundles"
    bundle = root / "alpha"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(
        "benchmarks.helpers.experiment.bundle_root",
        lambda benchmark_name, compare=False: root,
    )
    write_last_experiment_pointer(BENCH, bundle)
    resolved = resolve_last_experiment(BENCH)
    assert resolved == bundle.resolve()
    bundle_dir, is_resume = new_or_resume_bundle_dir(BENCH, resume=True)
    assert bundle_dir == bundle
    assert is_resume is True


@pytest.mark.sanity
def test_resolve_last_experiment_returns_none_when_target_missing(tmp_path, monkeypatch):
    root = tmp_path / "bundles"
    bundle = root / "alpha"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(
        "benchmarks.helpers.experiment.bundle_root",
        lambda benchmark_name, compare=False: root,
    )
    write_last_experiment_pointer(BENCH, bundle)
    # The pointed-to directory is removed after the pointer was written (e.g.
    # the bundle was deleted out from under it) — resolve_last_experiment
    # should report "no usable pointer" rather than a dangling path.
    import shutil

    shutil.rmtree(bundle)
    assert resolve_last_experiment(BENCH) is None


@pytest.mark.sanity
def test_conflicting_flags_error():
    with pytest.raises(ExperimentError, match="only one"):
        new_or_resume_bundle_dir(
            BENCH,
            experiment="a",
            resume=True,
        )


@pytest.mark.sanity
def test_prepare_workspace_creates_metadata_and_pointer(tmp_path, monkeypatch):
    root = tmp_path / "bundles"
    monkeypatch.setattr(
        "benchmarks.helpers.experiment.bundle_root",
        lambda benchmark_name, compare=False: root,
    )
    path = prepare_workspace(BENCH, experiment="run1", model_profile="gpt4o")
    assert path.is_dir()
    assert (path / "results" / "partial").is_dir()
    meta = json.loads((path / "metadata.json").read_text())
    assert meta["status"] == "in_progress"
    assert meta["experiment_name"] == "run1"
    pointer = last_experiment_pointer_path(BENCH)
    assert pointer.is_file()
    assert resolve_last_experiment(BENCH) == path.resolve()


@pytest.mark.sanity
def test_prepare_workspace_resume_appends_history(tmp_path, monkeypatch):
    root = tmp_path / "bundles"
    monkeypatch.setattr(
        "benchmarks.helpers.experiment.bundle_root",
        lambda benchmark_name, compare=False: root,
    )
    first = prepare_workspace(BENCH, experiment="run1")
    created_at = json.loads((first / "metadata.json").read_text())["created_at"]
    second = prepare_workspace(BENCH, resume_experiment="run1")
    assert second == first
    meta = json.loads((first / "metadata.json").read_text())
    assert meta["created_at"] == created_at
    assert len(meta["resume_history"]) == 2
