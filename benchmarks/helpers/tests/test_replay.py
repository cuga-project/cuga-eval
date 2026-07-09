"""Unit tests for benchmarks.helpers.replay (M5)."""

from __future__ import annotations

import pytest

from benchmarks.helpers.replay import cli_args_from_metadata, format_replay_command


@pytest.mark.sanity
def test_cli_args_from_metadata_basic():
    metadata = {
        "benchmark": "bpo",
        "experiment_name": "alpha",
        "run": {
            "model_profile": "gpt-oss",
            "agent": "cuga_sdk",
            "policies_enabled": False,
            "task_ids": ["1", "2"],
        },
    }
    args = cli_args_from_metadata(metadata)
    assert args == [
        "--model-profile",
        "gpt-oss",
        "--no-policies",
        "--task",
        "1",
        "2",
        "--resume-experiment",
        "alpha",
    ]


@pytest.mark.sanity
def test_cli_args_appworld_sdk():
    metadata = {
        "benchmark": "appworld",
        "run": {"agent": "cuga_sdk", "model_profile": "gpt4o"},
    }
    args = cli_args_from_metadata(metadata)
    assert "--sdk" in args
    assert "--model-profile" in args


@pytest.mark.sanity
def test_format_replay_command():
    metadata = {"benchmark": "bpo", "run": {"model_profile": "gpt-oss", "agent": "cuga_sdk"}}
    text = format_replay_command(metadata)
    assert text.startswith("# Replay for bpo")
    assert "./eval.sh" in text


@pytest.mark.sanity
def test_format_replay_command_notes_resume_when_experiment_name_present():
    metadata = {
        "benchmark": "bpo",
        "experiment_name": "alpha",
        "run": {"model_profile": "gpt-oss", "agent": "cuga_sdk"},
    }
    text = format_replay_command(metadata)
    assert "resumes the existing bundle 'alpha'" in text
    assert "--experiment <new-name>" in text


@pytest.mark.sanity
def test_format_replay_command_surfaces_unmapped_run_fields():
    metadata = {
        "benchmark": "bpo",
        "run": {
            "model_profile": "gpt-oss",
            "agent": "cuga_sdk",
            "task_files": ["custom_tasks.json"],
        },
    }
    text = format_replay_command(metadata)
    assert "cannot map" in text
    assert "task_files" in text


@pytest.mark.sanity
def test_format_replay_command_no_note_when_nothing_unmapped():
    metadata = {"benchmark": "bpo", "run": {"model_profile": "gpt-oss", "agent": "cuga_sdk"}}
    text = format_replay_command(metadata)
    assert "cannot map" not in text
    assert "resumes the existing bundle" not in text
