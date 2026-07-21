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


def test_environment_failure_error_is_a_runtime_error():
    # start_registry_server's registry-warmup-timeout abort relies on this:
    # it reuses the existing `except RuntimeError: raise` passthrough
    # (originally added for a stale-registry mismatch) rather than needing a
    # separate `except EnvironmentFailureError` clause. If this stopped being
    # true, that reuse would silently break and the timeout abort could be
    # swallowed by the function's generic `except Exception` handler.
    assert issubclass(EnvironmentFailureError, RuntimeError)


def test_registry_warmup_timeout_aborts_instead_of_proceeding():
    content = EVAL_M3_PY.read_text()
    assert "Proceeding anyway" not in content
    assert "raise EnvironmentFailureError(reason)" in content
    assert "registry warmup timed out after" in content


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
    # Anchor on the SECOND occurrence — the one belonging to run_config_mode —
    # not evaluate_single_task's earlier clause (covered by the other test below).
    first_occurrence = content.index("except EnvironmentFailureError:")
    env_except_idx = content.index("except EnvironmentFailureError:", first_occurrence + 1)
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


async def test_m3_evaluator_aborts_after_consecutive_environment_shaped_sample_failures(monkeypatch):
    from benchmarks.m3.container_health import EnvironmentFailureError
    from benchmarks.m3.eval_m3 import M3Evaluator

    monkeypatch.setenv("M3_ENV_FAIL_STREAK", "3")
    evaluator = M3Evaluator(m3_data_mode=True, domain="hockey", bundle_dir=None)

    async def fake_evaluate_multiturn_task(sample, sample_index):
        return {
            "sample_id": sample["sample_id"],
            "error": "Error calling MCP server tool: Connection refused",
        }

    monkeypatch.setattr(evaluator, "evaluate_multiturn_task", fake_evaluate_multiturn_task)

    samples = [{"sample_id": f"s{i}"} for i in range(1, 6)]  # 5 samples total

    with pytest.raises(EnvironmentFailureError):
        await evaluator.evaluate_all(preloaded_data=samples)

    # Must abort after exactly 3 consecutive failures, NOT grind through all 5 —
    # this is the whole point of the fix.
    assert len(evaluator.results) == 3


async def test_m3_evaluator_does_not_abort_on_mixed_sample_results(monkeypatch):
    from benchmarks.m3.eval_m3 import M3Evaluator

    monkeypatch.setenv("M3_ENV_FAIL_STREAK", "3")
    evaluator = M3Evaluator(m3_data_mode=True, domain="hockey", bundle_dir=None)

    call_count = 0

    async def fake_evaluate_multiturn_task(sample, sample_index):
        nonlocal call_count
        call_count += 1
        # Every other sample "succeeds" (no error), so the streak keeps resetting.
        if call_count % 2 == 0:
            return {
                "sample_id": sample["sample_id"],
                "error": "Error calling MCP server tool: Connection refused",
            }
        return {"sample_id": sample["sample_id"], "error": None}

    monkeypatch.setattr(evaluator, "evaluate_multiturn_task", fake_evaluate_multiturn_task)

    samples = [{"sample_id": f"s{i}"} for i in range(1, 6)]  # 5 samples

    await evaluator.evaluate_all(preloaded_data=samples)  # must NOT raise

    assert len(evaluator.results) == 5


def test_evaluate_single_task_domain_exception_is_not_swallowed():
    content = EVAL_M3_PY.read_text()
    generic_except_idx = content.index("Failed to evaluate domain")
    # There are two `except EnvironmentFailureError:` clauses in this file.
    # `evaluate_single_task` (containing the generic handler anchored above)
    # is defined *earlier* in the file than `run_config_mode`, so the clause
    # that must precede THIS specific generic handler is the FIRST
    # occurrence of "except EnvironmentFailureError:" in the file — not the
    # second. The second occurrence belongs to the separate, pre-existing
    # clause in run_config_mode (already covered by
    # test_environment_failure_error_is_not_swallowed_by_the_generic_handler
    # above, anchored on run_config_mode's own generic handler) and appears
    # later in the file, so it's irrelevant to this assertion.
    env_except_idx = content.index("except EnvironmentFailureError:")
    assert env_except_idx < generic_except_idx, (
        "the EnvironmentFailureError passthrough clause in evaluate_single_task "
        "must come before its generic `except Exception` clause, or Python will "
        "match the generic clause first and swallow the per-domain abort"
    )
