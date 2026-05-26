"""Tests for bundle.py reproducibility bundle creation.

Covers:
- Single-run bundle structure and metadata
- Compare bundle structure with per-model config
- Policy metadata collection (policies.json hash)
- Git info collection
- Environment variable collection with Dynaconf prefixes
- Settings file resolution
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from benchmarks.bpo.bundle import (
    BUNDLE_VERSION,
    _file_sha256,
    _resolve_cuga_settings_path,
    assemble_bundle,
    assemble_compare_bundle,
    collect_environment,
    collect_policy_metadata,
)

pytestmark = pytest.mark.regression


@pytest.fixture
def tmp_bundle_root(tmp_path):
    """Temporary directory for bundle output."""
    return tmp_path / "bundles"


@pytest.fixture
def mock_result_file(tmp_path):
    """Create a temporary result JSON file."""
    f = tmp_path / "results_test.json"
    f.write_text(json.dumps({"total_tasks": 5, "final_score_passes": 3}))
    return f


@pytest.fixture
def mock_task_file(tmp_path):
    """Create a temporary task JSON file."""
    f = tmp_path / "tasks.json"
    f.write_text(json.dumps([{"name": "test", "test_cases": []}]))
    return f


class TestCollectEnvironment:
    def test_captures_allowlisted_vars(self):
        with patch.dict(os.environ, {"MODEL_NAME": "test-model", "AGENT_SETTING_CONFIG": "settings.toml"}):
            env = collect_environment()
            assert env["MODEL_NAME"] == "test-model"
            assert env["AGENT_SETTING_CONFIG"] == "settings.toml"

    def test_skips_unset_vars(self):
        with patch.dict(os.environ, {}, clear=True):
            env = collect_environment()
            assert "MODEL_NAME" not in env

    def test_captures_dynaconf_overrides(self):
        with patch.dict(os.environ, {"DYNACONF_POLICY__ENABLED": "true"}):
            env = collect_environment()
            assert env["DYNACONF_POLICY__ENABLED"] == "true"

    def test_ignores_non_dynaconf_vars(self):
        with patch.dict(os.environ, {"RANDOM_VAR": "hello"}, clear=True):
            env = collect_environment()
            assert "RANDOM_VAR" not in env


class TestCollectPolicyMetadata:
    def test_returns_hash_when_policies_json_exists(self):
        policies_dir = Path(__file__).resolve().parents[1] / "policies"
        meta = collect_policy_metadata(policies_dir)
        policies_json = policies_dir / "policies.json"
        if policies_json.exists():
            assert meta["policies_json_hash"] is not None
            assert meta["policies_json_hash"].startswith("sha256:")
        else:
            assert meta["policies_json_hash"] is None

    def test_returns_none_when_dir_missing(self, tmp_path):
        meta = collect_policy_metadata(policies_dir=tmp_path / "nonexistent")
        assert meta["policies_json_hash"] is None


class TestResolveSettingsPath:
    def test_finds_settings_in_bpo_config(self):
        benchmark_dir = Path(__file__).resolve().parents[1]
        config_dir = benchmark_dir / "config"
        if (config_dir / "settings.groq.toml").exists():
            with patch.dict(os.environ, {"AGENT_SETTING_CONFIG": "settings.groq.toml"}):
                result = _resolve_cuga_settings_path(benchmark_dir=benchmark_dir)
                assert result is not None
                assert result.name == "settings.groq.toml"

    def test_returns_none_when_no_config_env(self):
        with patch.dict(os.environ, {}, clear=True):
            result = _resolve_cuga_settings_path()
            assert result is None

    def test_returns_none_for_nonexistent_file(self):
        with patch.dict(os.environ, {"AGENT_SETTING_CONFIG": "nonexistent.toml"}):
            result = _resolve_cuga_settings_path()
            assert result is None


class TestAssembleBundle:
    def test_creates_bundle_directory(self, mock_result_file, mock_task_file, tmp_bundle_root):
        bundle_dir = assemble_bundle(
            result_files=[mock_result_file],
            task_files=[mock_task_file],
            args={"agent": "test"},
            benchmark_name="bpo",
            model_profile="test-model",
            bundle_root=tmp_bundle_root,
        )
        assert bundle_dir.exists()
        assert (bundle_dir / "metadata.json").exists()
        assert (bundle_dir / "results" / mock_result_file.name).exists()
        assert (bundle_dir / "tasks" / mock_task_file.name).exists()

    def test_metadata_has_required_fields(self, mock_result_file, mock_task_file, tmp_bundle_root):
        bundle_dir = assemble_bundle(
            result_files=[mock_result_file],
            task_files=[mock_task_file],
            args={"agent": "test"},
            benchmark_name="bpo",
            model_profile="test-model",
            bundle_root=tmp_bundle_root,
        )
        meta = json.loads((bundle_dir / "metadata.json").read_text())
        assert meta["bundle_version"] == BUNDLE_VERSION
        assert meta["benchmark"] == "bpo"
        assert "run" in meta
        assert meta["run"]["agent"] == "test"
        assert meta["run"]["model_profile"] == "test-model"

    def test_copies_policies_json(self, mock_result_file, mock_task_file, tmp_bundle_root):
        policies_dir = Path(__file__).resolve().parents[1] / "policies"
        bundle_dir = assemble_bundle(
            result_files=[mock_result_file],
            task_files=[mock_task_file],
            args={},
            benchmark_name="bpo",
            bundle_root=tmp_bundle_root,
            policies_dir=policies_dir,
        )
        policies_json = Path(__file__).resolve().parents[1] / "policies" / "policies.json"
        if policies_json.exists():
            assert (bundle_dir / "policies" / "policies.json").exists()


class TestAssembleCompareBundle:
    def test_creates_compare_bundle(self, mock_result_file, tmp_bundle_root):
        config_results = {"test:policies": [str(mock_result_file)]}
        bundle_dir = assemble_compare_bundle(
            report_content="# Test Report",
            config_results=config_results,
            bundle_root=tmp_bundle_root,
        )
        assert bundle_dir.exists()
        assert (bundle_dir / "report.md").exists()
        assert (bundle_dir / "metadata.json").exists()

        meta = json.loads((bundle_dir / "metadata.json").read_text())
        assert meta["bundle_type"] == "comparison"
        assert "test:policies" in meta["configs"]

    def test_per_model_config_files(self, mock_result_file, tmp_bundle_root):
        """When model_envs is provided, bundle should have per-model .env and settings."""
        config_results = {
            "gpt-oss:policies": [str(mock_result_file)],
            "gpt4.1:policies": [str(mock_result_file)],
        }
        # Create a fake settings file
        fake_settings = tmp_bundle_root / "settings.test.toml"
        fake_settings.parent.mkdir(parents=True, exist_ok=True)
        fake_settings.write_text("[agent]\nmodel = 'test'")

        model_envs = {
            "gpt-oss": {
                "MODEL_NAME": "openai/gpt-oss-120b",
                "AGENT_SETTING_CONFIG": "settings.groq.toml",
                "settings_path": str(fake_settings),
            },
            "gpt4.1": {
                "MODEL_NAME": "Azure/gpt-4.1",
                "AGENT_SETTING_CONFIG": "settings.openai.toml",
                "settings_path": str(fake_settings),
            },
        }
        bundle_dir = assemble_compare_bundle(
            report_content="# Test",
            config_results=config_results,
            model_envs=model_envs,
            bundle_root=tmp_bundle_root,
        )

        config_dir = bundle_dir / "config"
        assert config_dir.exists()
        assert (config_dir / "run_gpt-oss.env").exists()
        assert (config_dir / "run_gpt4.1.env").exists()
        assert (config_dir / "settings.test.toml").exists()

        # Verify env file contents
        env_content = (config_dir / "run_gpt-oss.env").read_text()
        assert "MODEL_NAME=openai/gpt-oss-120b" in env_content

    def test_fallback_single_model(self, mock_result_file, tmp_bundle_root):
        """Without model_envs, falls back to current env."""
        config_results = {"test:policies": [str(mock_result_file)]}
        with patch.dict(os.environ, {"MODEL_NAME": "fallback-model", "AGENT_SETTING_CONFIG": "x.toml"}):
            bundle_dir = assemble_compare_bundle(
                report_content="# Test",
                config_results=config_results,
                bundle_root=tmp_bundle_root,
            )
        # Should still create bundle (config/ may or may not exist depending on env)
        assert bundle_dir.exists()
        assert (bundle_dir / "metadata.json").exists()


class TestFileSha256:
    def test_consistent_hash(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        h1 = _file_sha256(f)
        h2 = _file_sha256(f)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest length
