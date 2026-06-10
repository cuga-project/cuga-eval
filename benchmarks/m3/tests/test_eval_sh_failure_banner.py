"""Regression test for issue #55.

``benchmarks/m3/eval.sh`` runs under ``set -e`` with ``trap cleanup EXIT INT
TERM ERR``. The evaluator invocation (``uv run python -m
benchmarks.m3.eval_m3[...]``) is the *body* of an ``if``/``elif``/``else``
block, not a condition, so a non-zero exit there is a context where ``-e``
applies: the ERR trap fires, ``cleanup()`` runs and calls ``exit
$exit_code`` immediately. The script never reaches ``EVAL_EXIT=$?`` or the
"M3 evaluation failed" banner below it.

The fix wraps the evaluator-selection block with ``trap '' ERR`` + ``set
+e`` (suppressing both the trap *and* errexit for that invocation only),
captures ``EVAL_EXIT=$?``, then restores ``set -e`` and ``trap cleanup ERR``
before the success/failure banners run.

These tests reproduce that exact guard idiom in an isolated harness (no `uv`
/ registry / Python toolchain required) and verify:

- with the guard, both the success and failure banners are reachable and
  ``cleanup`` still runs via the EXIT trap with the right exit code;
- without the guard (the pre-fix idiom), the failure banner is unreachable
  — i.e. this harness would have caught the original bug.

A static check then confirms ``benchmarks/m3/eval.sh`` itself still wraps
the evaluator-selection block with this guard, in the right order.
"""

import subprocess
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.sanity

EVAL_SH = Path(__file__).resolve().parents[1] / "eval.sh"

# Minimal harness reproducing the cleanup/trap structure of eval.sh.
# MODE=guarded applies the issue #55 fix; MODE=unguarded reproduces the
# pre-fix behavior.
HARNESS = textwrap.dedent(
    """\
    #!/bin/bash
    set -e

    MODE="$1"
    shift

    cleanup() {
        local exit_code=$?
        echo "CLEANUP:$exit_code"
        exit $exit_code
    }
    trap cleanup EXIT INT TERM ERR

    echo "BEFORE"

    if [ "$MODE" = "guarded" ]; then
        trap '' ERR
        set +e
    fi

    "$@"
    EVAL_EXIT=$?

    if [ "$MODE" = "guarded" ]; then
        set -e
        trap cleanup ERR
    fi

    if [ $EVAL_EXIT -eq 0 ]; then
        echo "BANNER:success"
    else
        echo "BANNER:failure:$EVAL_EXIT"
    fi

    exit $EVAL_EXIT
    """
)


@pytest.fixture
def harness(tmp_path: Path) -> Path:
    script = tmp_path / "harness.sh"
    script.write_text(HARNESS)
    script.chmod(0o755)
    return script


def _run(harness: Path, mode: str, *cmd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — fixed args, no shell, no untrusted input
        ["bash", str(harness), mode, *cmd],  # noqa: S607 — bash resolved from PATH
        capture_output=True,
        text=True,
    )


def test_guarded_failure_reaches_banner_and_cleanup_runs(harness: Path) -> None:
    result = _run(harness, "guarded", "false")

    assert result.returncode == 1
    assert "BEFORE" in result.stdout
    assert "BANNER:failure:1" in result.stdout
    assert result.stdout.count("CLEANUP:") == 1
    assert "CLEANUP:1" in result.stdout


def test_guarded_success_reaches_banner_and_cleanup_runs(harness: Path) -> None:
    result = _run(harness, "guarded", "true")

    assert result.returncode == 0
    assert "BEFORE" in result.stdout
    assert "BANNER:success" in result.stdout
    assert result.stdout.count("CLEANUP:") == 1
    assert "CLEANUP:0" in result.stdout


def test_unguarded_failure_banner_is_unreachable(harness: Path) -> None:
    """Demonstrates the bug: without the guard, ERR+set -e exits via
    cleanup() before the failure banner is ever printed."""
    result = _run(harness, "unguarded", "false")

    assert result.returncode == 1
    assert "BEFORE" in result.stdout
    assert "BANNER" not in result.stdout


def test_eval_sh_wraps_evaluator_selection_with_err_trap_guard() -> None:
    """Static check that eval.sh still applies the issue #55 guard around
    the evaluator-selection block, in the right order."""
    content = EVAL_SH.read_text()

    block_start_idx = content.index('if [ "$M3_DATA" = "true" ]; then')
    guard_on_idx = content.index("trap '' ERR")
    set_minus_e_idx = content.index("set +e", guard_on_idx)
    eval_exit_idx = content.index("EVAL_EXIT=$?", block_start_idx)
    set_plus_e_idx = content.index("set -e", eval_exit_idx)
    guard_off_idx = content.index("trap cleanup ERR", set_plus_e_idx)

    assert guard_on_idx < set_minus_e_idx < block_start_idx, (
        "expected `trap '' ERR` then `set +e` immediately before the evaluator-selection block"
    )
    assert block_start_idx < eval_exit_idx < set_plus_e_idx < guard_off_idx, (
        "expected EVAL_EXIT=$? to be captured before `set -e` / "
        "`trap cleanup ERR` are restored, after the evaluator-selection block"
    )
