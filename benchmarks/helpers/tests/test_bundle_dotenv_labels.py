"""Tests for --dotenv bundle directory labels (issue #89)."""

import pytest

from benchmarks.helpers.bundle import _bundle_profile_label, _sanitize_model_slug
from benchmarks.helpers.compare_report import _format_config_label

pytestmark = pytest.mark.regression


def test_sanitize_model_slug_strips_org_prefix():
    assert _sanitize_model_slug("google/gemma-4-31b") == "gemma-4-31b"


def test_bundle_profile_label_uses_model_name_under_dotenv(monkeypatch):
    monkeypatch.setenv("USE_DOTENV", "true")
    monkeypatch.setenv("MODEL_NAME", "google/gemma-4-31b")
    assert _bundle_profile_label("gpt-oss") == "gemma-4-31b"


def test_bundle_profile_label_keeps_profile_without_dotenv(monkeypatch):
    monkeypatch.delenv("USE_DOTENV", raising=False)
    monkeypatch.setenv("MODEL_NAME", "google/gemma-4-31b")
    assert _bundle_profile_label("gpt-oss") == "gpt-oss"
    assert _bundle_profile_label(None) == "default"


def test_compare_report_label_uses_resolved_model_key():
    assert _format_config_label("gemma-4-31b:cuga") == "cuga (gemma-4-31b)"
