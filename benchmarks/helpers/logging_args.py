"""Shared ``--verbose`` / ``--quiet`` CLI handling for the eval entrypoints.

Each eval.sh forwards unrecognized flags to its Python evaluator. Before
this helper, ``./eval.sh --verbose`` worked for some evaluators (m3 had a
no-op declaration) and crashed for others — argparse rejects unknown args
and the process exits non-zero (issue #63).

Usage in any evaluator's argparse setup::

    from benchmarks.helpers.logging_args import add_log_level_args, apply_log_level

    parser = argparse.ArgumentParser(...)
    # ... other add_argument calls ...
    add_log_level_args(parser)
    args = parser.parse_args()
    apply_log_level(args)  # reconfigures the loguru sink

``--verbose`` / ``-v``  → loguru sink at DEBUG.
``--quiet``   / ``-q``  → loguru sink at WARNING.
Default (neither flag) leaves the sink alone — typically INFO, or whatever
``LOGURU_LEVEL`` env var was set to before the process started.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional


def add_log_level_args(parser: argparse.ArgumentParser) -> None:
    """Add mutually-exclusive ``--verbose`` / ``--quiet`` flags to *parser*."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose (DEBUG-level) output.",
    )
    group.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress INFO-level output (WARNING and above only).",
    )


def resolve_log_level(args: argparse.Namespace) -> Optional[str]:
    """Return the loguru level implied by *args*, or ``None`` to leave the
    sink unchanged. Kept separate from ``apply_log_level`` so callers that
    want to set the level via env var before importing loguru can do so.
    """
    if getattr(args, "verbose", False):
        return "DEBUG"
    if getattr(args, "quiet", False):
        return "WARNING"
    return None


def apply_log_level(args: argparse.Namespace) -> Optional[str]:
    """Reconfigure the loguru sink based on *args*.

    Returns the level that was applied, or ``None`` if no change was made.
    Safe to call before any ``logger.info`` etc. — only touches the sink
    when the user actually passed a flag.
    """
    level = resolve_log_level(args)
    if level is None:
        return None

    # Import here so this module remains importable without loguru
    # (useful when the helper itself is unit-tested in isolation).
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level=level)
    # Also push through LOGURU_LEVEL for any subprocess we spawn (e.g.,
    # the registry server) so it inherits the chosen level.
    os.environ["LOGURU_LEVEL"] = level
    return level
