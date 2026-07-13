"""Detect a broken M3 docker environment (dead/wedged capability containers)
and abort the eval run cleanly instead of grinding through it, contaminating
results with environment noise scored as ordinary task failures.

Used only by the sequential (default) path of benchmarks/m3/eval_m3.py's
run_config_mode(). See
docs/superpowers/specs/2026-07-13-m3-docker-env-health-check-design.md.
"""

from __future__ import annotations

from typing import Optional


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
