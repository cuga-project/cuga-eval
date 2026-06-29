"""Unit tests for ConversationBridge — the queue/Future ping-pong + DONE.

No LLM, no τ², no cuga. These port the Phase-0 spike
(spikes/step_a_future_bridge.py) into the repo: cross-thread Future completion
via call_soon_threadsafe, event-loop responsiveness while a decoy awaits, strict
ping-pong, and clean shutdown.

Retry-aware coalescing (§11.1b) is a separate test, added with that feature.
"""

import asyncio
import threading
import time

import pytest

from benchmarks.tau2.tau2_bridge import ConversationBridge, FinalAnswer, ToolAction

pytestmark = pytest.mark.sanity


def _fake_orchestrator(bridge: ConversationBridge, delay: float, results: list) -> None:
    """Stand-in for τ²'s proxy/orchestrator on a background thread: receive an
    action, simulate the real tool with sleep(delay), complete the pending Future."""
    while True:
        action = bridge.wait_for_action()
        if action is None:  # DONE
            return
        if isinstance(action, FinalAnswer):
            results.append(("final", action.text))
            continue
        time.sleep(delay)
        bridge.complete_pending({"echo": action.arguments})


async def _cuga_sim(bridge: ConversationBridge, n: int) -> list:
    """Stand-in for CUGA's generated code: call the decoy path n times in sequence."""
    out = []
    for i in range(n):
        fut = bridge.register_action(ToolAction(name="get", arguments={"i": i}))
        out.append(await fut)
    return out


async def _heartbeat(stop: asyncio.Event, ticks: list) -> None:
    while not stop.is_set():
        ticks.append(time.monotonic())
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_cross_thread_round_trip_and_order():
    """Future completed from another thread returns the right value, in order."""
    bridge = ConversationBridge()
    bridge.bind_loop(asyncio.get_running_loop())
    t = threading.Thread(target=_fake_orchestrator, args=(bridge, 0.0, []), daemon=True)
    t.start()

    results = await _cuga_sim(bridge, 3)

    assert results == [{"echo": {"i": 0}}, {"echo": {"i": 1}}, {"echo": {"i": 2}}]
    bridge.close()
    t.join(timeout=5)
    assert not t.is_alive()


@pytest.mark.asyncio
async def test_event_loop_stays_responsive_during_wait():
    """While a decoy awaits a slow (1s) action, the loop must keep ticking."""
    bridge = ConversationBridge()
    bridge.bind_loop(asyncio.get_running_loop())
    t = threading.Thread(target=_fake_orchestrator, args=(bridge, 1.0, []), daemon=True)
    t.start()

    ticks: list = []
    stop = asyncio.Event()
    hb = asyncio.create_task(_heartbeat(stop, ticks))

    result = await _cuga_sim(bridge, 1)

    stop.set()
    await hb
    bridge.close()
    t.join(timeout=5)

    assert result == [{"echo": {"i": 0}}]
    # If the loop had blocked on the Future, there'd be a ~1s gap between ticks.
    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    assert ticks, "heartbeat never ran"
    assert max(gaps) < 0.5, f"event loop stalled; max tick gap was {max(gaps):.3f}s"


@pytest.mark.asyncio
async def test_emit_final_routes_without_awaiting():
    """emit_final puts a FinalAnswer on the action queue (no result to await)."""
    bridge = ConversationBridge()
    bridge.bind_loop(asyncio.get_running_loop())
    seen: list = []
    t = threading.Thread(target=_fake_orchestrator, args=(bridge, 0.0, seen), daemon=True)
    t.start()

    bridge.emit_final("done, re-enabled data")
    # Give the orchestrator thread a moment to drain the queue.
    for _ in range(50):
        if seen:
            break
        await asyncio.sleep(0.01)

    bridge.close()
    t.join(timeout=5)
    assert seen == [("final", "done, re-enabled data")]


@pytest.mark.asyncio
async def test_close_unblocks_both_sides():
    """close() unblocks a thread parked in wait_for_action and is idempotent."""
    bridge = ConversationBridge()
    bridge.bind_loop(asyncio.get_running_loop())

    parked = threading.Event()
    returned = {}

    def waiter():
        parked.set()
        returned["action"] = bridge.wait_for_action()  # should return None on close

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    assert parked.wait(timeout=2)

    bridge.close()
    bridge.close()  # idempotent
    t.join(timeout=5)

    assert not t.is_alive()
    assert returned["action"] is None


@pytest.mark.asyncio
async def test_register_after_close_returns_cancelled_future():
    """A decoy that registers after shutdown gets a cancelled Future (unwinds)."""
    bridge = ConversationBridge()
    bridge.bind_loop(asyncio.get_running_loop())
    bridge.close()

    fut = bridge.register_action(ToolAction(name="late", arguments={}))
    assert fut.cancelled()


# NOTE: retry-aware coalescing was intentionally removed (2026-06-29) — see the
# "Why no coalescing?" note in tau2_bridge.py and plan §11.1b (mitigation 3). The
# timeout->retry->double-exec hazard is now prevented upstream (mitigations 1/2/4).
# If coalescing is ever restored, its tests come back with it.
