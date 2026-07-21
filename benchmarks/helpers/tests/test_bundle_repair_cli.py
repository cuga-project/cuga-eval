"""Smoke tests for the M1 bundle-repair CLI wiring.

Exercises the two new ``bundle.py`` subcommands and the
``create_eval_bundle.py --bundle-dir`` dispatch as real subprocesses, so the
argument plumbing (not just the underlying functions) is covered. Langfuse is
never configured here, so ``retry-langfuse`` is a no-op network-wise.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _seed_bundle(bundle_dir: Path) -> None:
    results_dir = bundle_dir / "results"
    results_dir.mkdir(parents=True)
    payload = {
        "metrics": {"total_tasks": 2, "passed": 1},
        "results": [
            {"task_name": "t1", "success": True},
            {"task_name": "t2", "success": False},
        ],
    }
    (results_dir / "m3_merged.json").write_text(json.dumps(payload))
    (bundle_dir / "metadata.json").write_text(json.dumps({"benchmark": "m3"}))


@pytest.mark.regression
def test_regenerate_report_subcommand(tmp_path):
    bd = tmp_path / "exp"
    _seed_bundle(bd)
    r = subprocess.run(  # noqa: S603 — fixed argv, no shell, no untrusted input
        [sys.executable, "-m", "benchmarks.helpers.bundle", "regenerate-report", "--bundle-dir", str(bd)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert (bd / "report.md").exists()
    assert (bd / "report.md").read_text().strip() != ""


@pytest.mark.regression
def test_retry_langfuse_subcommand_no_keys(tmp_path):
    bd = tmp_path / "exp"
    _seed_bundle(bd)
    r = subprocess.run(  # noqa: S603 — fixed argv, no shell, no untrusted input
        [sys.executable, "-m", "benchmarks.helpers.bundle", "retry-langfuse", "--bundle-dir", str(bd)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    # No Langfuse keys -> download is skipped, but the command must exit cleanly.
    assert r.returncode == 0, r.stderr


@pytest.mark.regression
def test_create_eval_bundle_bundle_dir_mode(tmp_path):
    bd = tmp_path / "exp"
    _seed_bundle(bd)
    r = subprocess.run(  # noqa: S603 — fixed argv, no shell, no untrusted input
        [
            sys.executable,
            "scripts/create_eval_bundle.py",
            "--bundle-dir",
            str(bd),
            "--no-langfuse",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert (bd / "report.md").exists()


@pytest.mark.regression
def test_create_eval_bundle_rejects_conflicting_modes(tmp_path):
    bd = tmp_path / "exp"
    _seed_bundle(bd)
    r = subprocess.run(  # noqa: S603 — fixed argv, no shell, no untrusted input
        [
            sys.executable,
            "scripts/create_eval_bundle.py",
            "--bundle-dir",
            str(bd),
            "--latest",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "cannot be combined" in (r.stderr + r.stdout)
