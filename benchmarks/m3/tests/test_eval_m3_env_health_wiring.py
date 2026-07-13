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


def test_health_check_runs_before_registry_restart():
    content = EVAL_M3_PY.read_text()
    health_idx = content.index("health_check_or_abort(")
    registry_idx = content.index("svc_registry = await start_registry_server(mini_yaml")
    assert health_idx < registry_idx, (
        "health_check_or_abort must run before the per-domain registry restart "
        "so a dead container is caught before wasting a restart on it"
    )


def test_streak_check_runs_after_task_results_are_collected():
    content = EVAL_M3_PY.read_text()
    extend_idx = content.index("all_results.extend(task_results)")
    streak_idx = content.index("record_streak_or_abort(")
    assert extend_idx < streak_idx


def test_environment_failure_error_is_not_swallowed_by_the_generic_handler():
    content = EVAL_M3_PY.read_text()
    generic_except_idx = content.index('logger.error(f"❌ Task {service_name} failed: {e}")')
    env_except_idx = content.index("except EnvironmentFailureError:")
    assert env_except_idx < generic_except_idx, (
        "the EnvironmentFailureError passthrough clause must come before the "
        "generic `except Exception` clause, or Python will match the generic "
        "clause first and swallow the abort"
    )


def test_env_int_valid_string():
    from benchmarks.m3.eval_m3 import _env_int

    assert _env_int("TEST_INT_VAR", 10) == 10  # unset returns default


def test_env_int_parses_valid_int_string(monkeypatch):
    from benchmarks.m3.eval_m3 import _env_int

    monkeypatch.setenv("TEST_INT_VAR", "42")
    assert _env_int("TEST_INT_VAR", 10) == 42


def test_env_int_returns_default_on_malformed(monkeypatch):
    from benchmarks.m3.eval_m3 import _env_int

    monkeypatch.setenv("TEST_INT_VAR", "three")
    # Key test: malformed value should return default, not raise
    result = _env_int("TEST_INT_VAR", 10)
    assert result == 10


def test_env_float_returns_default_when_unset():
    from benchmarks.m3.eval_m3 import _env_float

    assert _env_float("TEST_FLOAT_VAR", 5.0) == 5.0


def test_env_float_parses_valid_float_string(monkeypatch):
    from benchmarks.m3.eval_m3 import _env_float

    monkeypatch.setenv("TEST_FLOAT_VAR", "3.14")
    assert _env_float("TEST_FLOAT_VAR", 5.0) == 3.14


def test_env_float_returns_default_on_malformed(monkeypatch):
    from benchmarks.m3.eval_m3 import _env_float

    monkeypatch.setenv("TEST_FLOAT_VAR", "abc")
    # Key test: malformed value should return default, not raise
    result = _env_float("TEST_FLOAT_VAR", 5.0)
    assert result == 5.0
