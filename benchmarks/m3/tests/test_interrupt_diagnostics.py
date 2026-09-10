"""Tests for the interrupt-diagnostics instrumentation in eval_m3.py.

Several M3 bundles (2026-06-24, 2026-07-04, 2026-07-05, 2026-07-09) show
`run_config_mode` hitting its `except (KeyboardInterrupt, asyncio.CancelledError)`
branch unattended, seconds after a `call_model` log line, with no human
present. That branch alone can't tell a real Ctrl-C / external `kill -INT`
apart from a bare `asyncio.CancelledError` raised inside the process (e.g. by
an LLM/gateway client library). `_install_sigint_observer` and
`_stall_watchdog` (added to eval_m3.py) exist to gather evidence the next
time this happens, per the systematic-debugging "add diagnostic
instrumentation" step — these tests just verify the instrumentation itself
works before it's relied on in the field.
"""

import asyncio
import os
import signal

import pytest
from loguru import logger

from benchmarks.m3 import eval_m3

pytestmark = pytest.mark.regression


@pytest.fixture(autouse=True)
def _reset_sigint_state():
    original_handler = signal.getsignal(signal.SIGINT)
    eval_m3._sigint_observed_at = None
    yield
    signal.signal(signal.SIGINT, original_handler)
    eval_m3._sigint_observed_at = None


def _capture_warnings():
    messages: list[str] = []
    handler_id = logger.add(lambda msg: messages.append(str(msg)), level="WARNING")
    return messages, handler_id


def test_sigint_observer_timestamps_signal_and_preserves_default_behavior():
    """Installing the observer must not break Ctrl-C: SIGINT still raises
    KeyboardInterrupt (so #91/#92 partial-save behavior is unchanged), and
    it must record that a *real* signal was observed."""
    # Isolate from pytest's own SIGINT handler: if _install_sigint_observer
    # is ever changed to delegate to whatever handler was previously
    # installed (rather than calling signal.default_int_handler directly),
    # delegating to pytest's own handler here would flag the test session
    # to abort instead of just raising KeyboardInterrupt in this test.
    original_pytest_handler = signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        eval_m3._install_sigint_observer()
        messages, handler_id = _capture_warnings()

        try:
            with pytest.raises(KeyboardInterrupt):
                os.kill(os.getpid(), signal.SIGINT)
        finally:
            logger.remove(handler_id)

        assert eval_m3._sigint_observed_at is not None
        assert any("SIGINT received by the OS signal handler" in m for m in messages)
    finally:
        signal.signal(signal.SIGINT, original_pytest_handler)


def test_sigint_not_observed_when_never_delivered():
    """The flag stays None if no signal arrives — this is what lets the
    except-branch tell a real interrupt apart from a bare CancelledError."""
    eval_m3._install_sigint_observer()
    assert eval_m3._sigint_observed_at is None


async def test_stall_watchdog_dumps_other_live_task_stacks():
    async def _hang():
        await asyncio.sleep(10)

    hung_task = asyncio.create_task(_hang(), name="hung-task-under-test")
    await asyncio.sleep(0)  # let it actually start and suspend on the sleep

    messages, handler_id = _capture_warnings()
    watchdog = asyncio.create_task(eval_m3._stall_watchdog(interval_seconds=0.05))
    try:
        await asyncio.sleep(0.2)
    finally:
        watchdog.cancel()
        hung_task.cancel()
        for t in (watchdog, hung_task):
            try:
                await t
            except asyncio.CancelledError:
                pass
        logger.remove(handler_id)

    assert any("Stall watchdog" in m for m in messages)
    assert any("hung-task-under-test" in m for m in messages)
