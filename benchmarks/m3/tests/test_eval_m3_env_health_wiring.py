"""Tests for eval_m3.py's M3 docker-environment-failure wiring: the
exit-code-3 wrapper and the sequential-loop call-site ordering. See
docs/superpowers/specs/2026-07-13-m3-docker-env-health-check-design.md.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from benchmarks.m3.container_health import EnvironmentFailureError

pytestmark = pytest.mark.sanity

ROOT = Path(__file__).resolve().parents[3]
EVAL_M3_PY = ROOT / "benchmarks" / "m3" / "eval_m3.py"


def test_run_main_returns_0_on_success():
    from benchmarks.m3.eval_m3 import _run_main

    with patch("benchmarks.m3.eval_m3.main", new=AsyncMock(return_value=None)):
        assert _run_main() == 0


def test_run_main_returns_3_on_environment_failure():
    from benchmarks.m3.eval_m3 import _run_main

    with patch(
        "benchmarks.m3.eval_m3.main",
        new=AsyncMock(side_effect=EnvironmentFailureError("container dead")),
    ):
        assert _run_main() == 3
