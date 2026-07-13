"""Unit tests for benchmarks/m3/container_health.py — M3 docker environment
health detection (dead/wedged capability containers). See
docs/superpowers/specs/2026-07-13-m3-docker-env-health-check-design.md.
"""

from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import patch

import pytest

from benchmarks.m3.container_health import (
    check_container_health,
    is_environment_shaped_error,
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
