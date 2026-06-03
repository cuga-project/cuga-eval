"""Sanity checks for bundle report.md validation."""

import pytest

from benchmarks.helpers.validate_bundle_report import validate_report_md

pytestmark = pytest.mark.sanity


def test_validate_report_ok(tmp_path):
    report = tmp_path / "report.md"
    report.write_text(
        """# Evaluation Report

## Summary

- **Total Tokens**: 1,234
- **Total LLM Calls**: 5
- **Total Duration**: 12.5s

## Per-Task Results

| Task | Result | Tokens | Cost | LLM Calls | Cache Tokens | Duration | Steps |
|------|--------|--------|------|-----------|--------------|----------|-------|
| t1 | ✓ | 1,234 | -- | 5 | 0 | 12.5s | 3 |
"""
    )
    assert validate_report_md(report) == []


def test_validate_report_flags_missing_metrics(tmp_path):
    report = tmp_path / "report.md"
    report.write_text(
        """## Per-Task Results

| Task | Result | Tokens | Cost | LLM Calls | Cache Tokens | Duration | Steps |
|------|--------|--------|------|-----------|--------------|----------|-------|
| t1 | ✓ | -- | -- | -- | -- | -- | -- |
"""
    )
    errors = validate_report_md(report)
    assert errors
    assert any("Tokens" in e for e in errors)
