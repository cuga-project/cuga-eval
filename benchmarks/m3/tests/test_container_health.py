"""Unit tests for benchmarks/m3/container_health.py — M3 docker environment
health detection (dead/wedged capability containers). See
docs/superpowers/specs/2026-07-13-m3-docker-env-health-check-design.md.
"""

from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import patch

import pytest

from benchmarks.m3.container_health import (
    EnvironmentFailureError,
    EnvironmentFailureStreakTracker,
    check_container_health,
    health_check_or_abort,
    is_environment_shaped_error,
    is_environment_shaped_result,
    record_streak_or_abort,
    render_environment_failure_banner,
    resume_hint_for,
)

pytestmark = pytest.mark.sanity


# --- is_environment_shaped_error --------------------------------------------


def test_classifies_connection_refused_as_environment_shaped():
    assert is_environment_shaped_error("Error calling MCP server tool: Connection refused")


def test_classifies_docker_not_running_as_environment_shaped():
    assert is_environment_shaped_error("Error response from daemon: Container abc is not running")


def test_does_not_classify_bare_timeout_as_environment_shaped():
    # A slow-but-healthy SQL query over a live container can raise a
    # client-side timeout too; only a channel-death signal should count.
    assert not is_environment_shaped_error("httpx.ReadTimeout: timed out")


def test_does_not_classify_validation_error_as_environment_shaped():
    # The c4 case: a live server returns this as tool call *data*, not a
    # raised exception, so in practice it never reaches this classifier —
    # but the classifier must also reject it defensively.
    assert not is_environment_shaped_error(
        "Error calling MCP server tool: Input validation error: 'director' is a required property"
    )


def test_none_and_empty_error_text_is_not_environment_shaped():
    assert not is_environment_shaped_error(None)
    assert not is_environment_shaped_error("")


def test_classifies_connection_closed_as_environment_shaped():
    assert is_environment_shaped_error("Error calling MCP server tool: Connection closed")


# --- is_environment_shaped_result --------------------------------------------
#
# Regression coverage for the case a live run surfaced: the registry/agent
# layer is still reachable (find_tools still works), but the MCP transport to
# the dead container itself is closed. The call doesn't raise — it returns
# "Connection closed" as its own value — the agent retries a few times, then
# gives up and produces a normal-looking "I couldn't retrieve the data"
# final answer. result["error"] stays unset the whole time.


def test_result_with_only_top_level_error_is_environment_shaped():
    assert is_environment_shaped_result({"error": "Connection refused"})


def test_result_with_no_error_and_no_tool_calls_is_not_environment_shaped():
    assert not is_environment_shaped_result({"error": None, "tool_calls": []})


def test_result_with_successful_tool_calls_is_not_environment_shaped():
    result = {
        "error": None,
        "tool_calls": [{"name": "hockey_get_players", "result": {"count": 7}}],
    }
    assert not is_environment_shaped_result(result)


def test_multiturn_result_with_connection_closed_tool_call_result_is_environment_shaped():
    # error is unset (no exception was raised) — only the tool call's own
    # *return value* carries the connection-closed text, exactly like the
    # live failure this test guards against.
    result = {
        "error": None,
        "all_responses": [
            {
                "turn": 1,
                "tool_calls": [
                    {
                        "name": "hockey_get_players_by_position_no_shoot_catch",
                        "result": "Error calling MCP server tool: Connection closed",
                    }
                ],
            }
        ],
    }
    assert is_environment_shaped_result(result)


def test_single_turn_result_with_connection_closed_tool_call_result_is_environment_shaped():
    result = {
        "error": None,
        "tool_calls": [
            {"name": "hockey_get_players", "result": "Error calling MCP server tool: Connection closed"}
        ],
    }
    assert is_environment_shaped_result(result)


def test_result_with_validation_error_tool_call_result_is_not_environment_shaped():
    # The c4 case, at the tool-call level this time: a live server's own
    # validation error, returned as data — must not be misclassified.
    result = {
        "error": None,
        "tool_calls": [
            {
                "name": "disney_get_count_movies_by_director",
                "result": "Error calling MCP server tool: Input validation error: 'director' is a required property",
            }
        ],
    }
    assert not is_environment_shaped_result(result)


def test_tool_call_as_object_with_result_attribute_is_environment_shaped():
    class FakeToolCall:
        result = "Error calling MCP server tool: Connection closed"
        error = None

    result = {"error": None, "tool_calls": [FakeToolCall()]}
    assert is_environment_shaped_result(result)


# --- check_container_health --------------------------------------------


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> CompletedProcess:
    return CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_check_container_health_healthy():
    with patch("benchmarks.m3.container_health.subprocess.run") as run:
        run.side_effect = [_completed(0, stdout="true\n"), _completed(0)]
        healthy, reason = check_container_health("capability_2_dashboard_apis", "docker")
    assert healthy is True
    assert reason == ""


def test_check_container_health_not_running():
    with patch("benchmarks.m3.container_health.subprocess.run") as run:
        run.side_effect = [_completed(0, stdout="false\n")]
        healthy, reason = check_container_health("capability_2_dashboard_apis", "docker")
    assert healthy is False
    assert "not running" in reason


def test_check_container_health_exec_fails():
    with patch("benchmarks.m3.container_health.subprocess.run") as run:
        run.side_effect = [_completed(0, stdout="true\n"), _completed(1, stderr="OCI runtime exec failed")]
        healthy, reason = check_container_health("capability_2_dashboard_apis", "docker")
    assert healthy is False
    assert "docker exec failed" in reason


def test_check_container_health_inspect_times_out():
    with patch("benchmarks.m3.container_health.subprocess.run") as run:
        run.side_effect = TimeoutExpired(cmd=["docker"], timeout=5.0)
        healthy, reason = check_container_health("capability_2_dashboard_apis", "docker", timeout=5.0)
    assert healthy is False
    assert "timed out" in reason


# --- EnvironmentFailureStreakTracker --------------------------------------------


def test_streak_tracker_trips_at_threshold():
    tracker = EnvironmentFailureStreakTracker(threshold=3)
    env_err = [{"error": "Connection refused"}]
    assert tracker.record(env_err) is False
    assert tracker.record(env_err) is False
    assert tracker.record(env_err) is True


def test_streak_tracker_resets_on_healthy_domain():
    tracker = EnvironmentFailureStreakTracker(threshold=3)
    env_err = [{"error": "Connection refused"}]
    healthy = [{"error": None}]
    tracker.record(env_err)
    tracker.record(env_err)
    tracker.record(healthy)  # resets the streak
    assert tracker.record(env_err) is False
    assert tracker.record(env_err) is False
    assert tracker.record(env_err) is True


def test_streak_tracker_empty_results_does_not_count_as_environment_shaped():
    tracker = EnvironmentFailureStreakTracker(threshold=1)
    assert tracker.record([]) is False


def test_streak_tracker_mixed_results_do_not_count():
    tracker = EnvironmentFailureStreakTracker(threshold=1)
    mixed = [{"error": "Connection refused"}, {"error": None}]
    assert tracker.record(mixed) is False


# --- resume_hint_for / render_environment_failure_banner --------------------------------------------


def test_resume_hint_with_bundle_dir():
    hint = resume_hint_for(Path("/home/user/experiments/20260713_120000_default"))
    assert hint == "--resume-experiment 20260713_120000_default"


def test_resume_hint_without_bundle_dir():
    hint = resume_hint_for(None)
    assert "--resume" in hint


def test_banner_contains_reason_and_resume_hint():
    banner = render_environment_failure_banner("container X unhealthy", "--resume-experiment abc")
    assert "container X unhealthy" in banner
    assert "--resume-experiment abc" in banner
    assert "ENVIRONMENT FAILURE" in banner


# --- health_check_or_abort / record_streak_or_abort --------------------------------------------


def test_health_check_or_abort_raises_when_unhealthy(capsys):
    with patch(
        "benchmarks.m3.container_health.check_container_health",
        return_value=(False, "container not running"),
    ):
        with pytest.raises(EnvironmentFailureError):
            health_check_or_abort("capability_2_dashboard_apis", "docker", "--resume-experiment abc")
    assert "ENVIRONMENT FAILURE" in capsys.readouterr().out


def test_health_check_or_abort_does_not_raise_when_healthy():
    with patch(
        "benchmarks.m3.container_health.check_container_health",
        return_value=(True, ""),
    ):
        health_check_or_abort("capability_2_dashboard_apis", "docker", "--resume-experiment abc")


def test_record_streak_or_abort_raises_once_threshold_hit(capsys):
    tracker = EnvironmentFailureStreakTracker(threshold=1)
    with pytest.raises(EnvironmentFailureError):
        record_streak_or_abort(
            tracker,
            "hockey",
            "capability_2_dashboard_apis",
            [{"error": "Connection refused"}],
            "--resume-experiment abc",
        )
    assert "ENVIRONMENT FAILURE" in capsys.readouterr().out


def test_record_streak_or_abort_does_not_raise_below_threshold():
    tracker = EnvironmentFailureStreakTracker(threshold=3)
    record_streak_or_abort(
        tracker,
        "hockey",
        "capability_2_dashboard_apis",
        [{"error": "Connection refused"}],
        "--resume-experiment abc",
    )
