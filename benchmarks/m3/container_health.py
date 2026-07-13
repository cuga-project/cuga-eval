"""Detect a broken M3 docker environment (dead/wedged capability containers)
and abort the eval run cleanly instead of grinding through it, contaminating
results with environment noise scored as ordinary task failures.

Used only by the sequential (default) path of benchmarks/m3/eval_m3.py's
run_config_mode(). See
docs/superpowers/specs/2026-07-13-m3-docker-env-health-check-design.md.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class EnvironmentFailureError(RuntimeError):
    """Raised when the M3 docker environment is detected as broken mid-run."""


# Substrings that can ONLY mean the channel to a capability container never
# existed or broke outright — not a slow-but-healthy call. A bare "timed out"
# is deliberately excluded: a legitimately slow SQL query over a live,
# healthy container can raise a client-side timeout too, and that's a real
# (if slow) task outcome, not an environment failure.
_ENV_FAILURE_MARKERS = (
    "Connection refused",
    "Broken pipe",
    "BrokenPipeError",
    "ConnectionResetError",
    "No such container",
    "is not running",
)


def is_environment_shaped_error(error_text: Optional[str]) -> bool:
    """True when `error_text` can only mean the container channel was dead."""
    if not error_text:
        return False
    return any(marker in error_text for marker in _ENV_FAILURE_MARKERS)


def check_container_health(container: str, container_runtime: str, timeout: float = 5.0) -> Tuple[bool, str]:
    """Check whether `container` is running and its exec path responds.

    Two cheap subprocess checks: `inspect` catches the container being
    stopped/removed/never-existed; `exec ... true` catches a container
    that's "running" per docker but whose exec path is wedged (daemon
    overloaded, defunct process) — a case `inspect` alone would miss.

    Returns (healthy, reason). reason is "" when healthy.
    """
    try:
        inspect = subprocess.run(  # noqa: S603 — fixed args, container name is config-controlled
            [container_runtime, "inspect", "-f", "{{.State.Running}}", container],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"docker inspect timed out after {timeout}s"

    if inspect.returncode != 0 or inspect.stdout.strip() != "true":
        detail = inspect.stderr.strip() or inspect.stdout.strip() or f"exit code {inspect.returncode}"
        return False, f"container not running: {detail}"

    try:
        exec_check = subprocess.run(  # noqa: S603
            [container_runtime, "exec", container, "true"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"docker exec timed out after {timeout}s"

    if exec_check.returncode != 0:
        detail = exec_check.stderr.strip() or f"exit code {exec_check.returncode}"
        return False, f"docker exec failed: {detail}"

    return True, ""


class EnvironmentFailureStreakTracker:
    """Counts consecutive domains whose every result is environment-shaped."""

    def __init__(self, threshold: int):
        self.threshold = threshold
        self._streak = 0

    def record(self, domain_results: List[Dict]) -> bool:
        """Feed one domain's results. Returns True once the streak hits threshold.

        An empty result list does NOT count toward the streak (and resets
        it) — there's nothing to classify, so it can't be evidence of an
        environment failure.
        """
        if domain_results and all(is_environment_shaped_error(r.get("error")) for r in domain_results):
            self._streak += 1
        else:
            self._streak = 0
        return self._streak >= self.threshold

    def reset(self) -> None:
        self._streak = 0


def resume_hint_for(bundle_dir: Optional[Path]) -> str:
    """Build the CLI hint printed in the abort banner."""
    if bundle_dir is not None:
        return f"--resume-experiment {Path(bundle_dir).name}"
    return "--resume (or --resume-experiment <id>) once the containers are back up"


def render_environment_failure_banner(reason: str, resume_hint: str) -> str:
    border = "#" * 72
    return "\n".join(
        [
            "",
            border,
            "#  M3 ENVIRONMENT FAILURE DETECTED — ABORTING RUN",
            f"#  {reason}",
            "#  Fix the docker environment, then resume with:",
            f"#    {resume_hint}",
            border,
            "",
        ]
    )


def health_check_or_abort(
    container: str, container_runtime: str, resume_hint: str, timeout: float = 5.0
) -> None:
    """Raise EnvironmentFailureError (after printing a banner) if unhealthy."""
    healthy, reason = check_container_health(container, container_runtime, timeout=timeout)
    if not healthy:
        message = f"container '{container}' unhealthy: {reason}"
        print(render_environment_failure_banner(message, resume_hint))
        raise EnvironmentFailureError(message)


def record_streak_or_abort(
    streak: EnvironmentFailureStreakTracker,
    service_name: str,
    container: str,
    task_results: List[Dict],
    resume_hint: str,
) -> None:
    """Feed one domain's results into `streak`; abort if it just tripped."""
    if streak.record(task_results):
        message = (
            f"{streak.threshold} consecutive domains failed with environment-shaped "
            f"errors (last: {service_name}/{container})"
        )
        print(render_environment_failure_banner(message, resume_hint))
        raise EnvironmentFailureError(message)
