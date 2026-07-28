"""Tests for per-task ActivityTracker isolation (cuga-agent#552 workaround).

The bug these guard against: ActivityTracker is a process-wide singleton whose
``steps``/``task_id``/counters are shared mutable attributes. Under
``--batch-size > 1`` eval_m3 runs tasks concurrently in one event loop, so each
task's ``tracker.reset()`` wiped its siblings' in-progress state and every read
of ``tracker.steps`` returned the interleaved union.

The regression these tests must keep catching is specifically the *concurrent*
one, so the core test genuinely interleaves two asyncio tasks with awaits between
each step append -- a sequential two-task test would pass even with the bug
present, which is exactly how the sibling contextvar work in cuga-agent shipped a
"verified" fix that did nothing (see that repo's
docs/issues/task-tool-call-history-contextvar-isolation.md §4).
"""

import asyncio
import contextvars

import pytest

from benchmarks.helpers import tracker_isolation
from benchmarks.helpers.tracker_isolation import ISOLATED_FIELDS, isolated_task


@pytest.fixture(autouse=True)
def _clean_isolation():
    tracker_isolation._uninstall_for_tests()
    yield
    tracker_isolation._uninstall_for_tests()


@pytest.fixture()
def tracker():
    from cuga.backend.activity_tracker.tracker import ActivityTracker

    return ActivityTracker()


def _step(name):
    from cuga.backend.activity_tracker.tracker import Step

    return Step(name=name, data=name)


def _api_call_step(payload):
    """A step in the shape ``_extract_tool_calls_from_tracker`` looks for."""
    from cuga.backend.activity_tracker.tracker import Step

    return Step(name="api_call", data=payload)


@pytest.mark.asyncio
async def test_concurrent_tasks_do_not_share_steps_or_task_id(tracker):
    """Two interleaved tasks each see only their own steps and task_id."""

    async def run(task_id, marker, n_steps):
        with isolated_task(label=task_id):
            tracker.reset(intent=f"intent-{marker}", task_id=task_id)
            for i in range(n_steps):
                # Yield between every append so the two tasks genuinely
                # interleave on the event loop. Without isolation this is what
                # makes each task observe the other's steps.
                await asyncio.sleep(0)
                tracker.collect_step(_step(f"{marker}{i}"))
            await asyncio.sleep(0)
            return {
                "task_id": tracker.task_id,
                "intent": tracker.intent,
                "names": [s.name for s in tracker.steps],
            }

    a, b = await asyncio.gather(run("task-a", "A", 5), run("task-b", "B", 7))

    assert a["task_id"] == "task-a"
    assert b["task_id"] == "task-b"
    assert a["intent"] == "intent-A"
    assert b["intent"] == "intent-B"

    assert a["names"] == [f"A{i}" for i in range(5)]
    assert b["names"] == [f"B{i}" for i in range(7)]

    # The specific corruption seen in real runs: a task's extracted history
    # containing another domain's calls.
    assert not any(n.startswith("B") for n in a["names"])
    assert not any(n.startswith("A") for n in b["names"])


@pytest.mark.asyncio
async def test_sibling_reset_does_not_wipe_in_flight_task(tracker):
    """A late-starting task's reset() must not clear an already-running one."""
    started = asyncio.Event()

    async def long_task():
        with isolated_task(label="long"):
            tracker.reset(intent="long", task_id="long")
            tracker.collect_step(_step("L0"))
            started.set()
            await asyncio.sleep(0.05)  # sibling resets during this window
            tracker.collect_step(_step("L1"))
            return [s.name for s in tracker.steps]

    async def late_task():
        await started.wait()
        with isolated_task(label="late"):
            tracker.reset(intent="late", task_id="late")
            tracker.collect_step(_step("X0"))
            return [s.name for s in tracker.steps]

    long_names, late_names = await asyncio.gather(long_task(), late_task())

    assert long_names == ["L0", "L1"], "sibling reset() wiped an in-flight task's steps"
    assert late_names == ["X0"]


@pytest.mark.asyncio
async def test_counters_are_per_task(tracker):
    """token_usage/actions_count accumulate per task, not across siblings."""

    async def run(task_id, n):
        with isolated_task(label=task_id):
            tracker.reset(intent=task_id, task_id=task_id)
            for _ in range(n):
                await asyncio.sleep(0)
                tracker.collect_tokens_usage(10)
            return tracker.token_usage

    a, b = await asyncio.gather(run("a", 3), run("b", 5))
    assert a == 30
    assert b == 50


@pytest.mark.asyncio
async def test_binding_is_visible_through_copied_contexts(tracker):
    """The key survives copy_context(), which is how LangGraph dispatches nodes.

    Pregel's AsyncBackgroundExecutor.submit() runs every node under
    ``copy_context()``. Steps are collected inside those dispatches, so a binding
    that did not survive the copy would silently drop every step.
    """
    with isolated_task(label="outer"):
        tracker.reset(intent="outer", task_id="outer")

        def dispatch_like_langgraph():
            tracker.collect_step(_step("from-copied-context"))

        ctx = contextvars.copy_context()
        ctx.run(dispatch_like_langgraph)

        assert [s.name for s in tracker.steps] == ["from-copied-context"]
        assert tracker.task_id == "outer"


@pytest.mark.asyncio
async def test_binding_survives_langgraph_threadpool_dispatch(tracker):
    """Mimic langgraph's real sync dispatch: ThreadPoolExecutor + ctx.run.

    ``langgraph.pregel._executor.BackgroundExecutor.submit`` does
    ``ctx = copy_context()`` then ``executor.submit(ctx.run, fn, ...)`` -- an
    actual OS thread hop. Contextvars do not cross a bare thread boundary, so
    this only works because langgraph copies the context explicitly. If that ever
    changes, steps collected inside node dispatches would land unattributed
    rather than in the running task, and this test is what would catch it.
    """
    from concurrent.futures import ThreadPoolExecutor

    with isolated_task(label="outer"):
        tracker.reset(intent="outer", task_id="outer")

        def dispatch():
            tracker.collect_step(_step("from-worker-thread"))
            return tracker.task_id

        ctx = contextvars.copy_context()
        with ThreadPoolExecutor(max_workers=1) as pool:
            seen_task_id = pool.submit(ctx.run, dispatch).result()

        assert seen_task_id == "outer"
        assert [s.name for s in tracker.steps] == ["from-worker-thread"]
        assert tracker_isolation.unbound_write_count() == 0


@pytest.mark.asyncio
async def test_tool_call_extraction_is_per_task(tracker):
    """The payoff: the fallback extractor stops mixing in siblings' tool calls.

    ``_extract_tool_calls_from_tracker()`` reads ``tracker.steps`` unfiltered and
    fires whenever the primary (LangGraph-state-scoped) extraction comes back
    empty -- 54 times in the cap4-300 baseline, non-empty on 48 of those. Under
    concurrency it was returning other domains' calls, which is what produced the
    hockey-task-with-food_inspection-calls results.
    """
    import json

    from benchmarks.helpers.sdk_eval_helpers import _extract_tool_calls_from_tracker

    async def run(task_id, tool_name, n):
        with isolated_task(label=task_id):
            tracker.reset(intent=task_id, task_id=task_id)
            for i in range(n):
                await asyncio.sleep(0)
                tracker.collect_step(
                    _api_call_step(json.dumps({"function_name": tool_name, "args": {"i": i}}))
                )
            await asyncio.sleep(0)
            return [tc["name"] for tc in _extract_tool_calls_from_tracker()]

    hockey, food = await asyncio.gather(
        run("hockey-task", "ice_hockey_draft_query", 3),
        run("food-task", "food_inspection_query", 4),
    )

    assert hockey == ["ice_hockey_draft_query"] * 3
    assert food == ["food_inspection_query"] * 4


def test_unbound_access_still_works(tracker):
    """Non-M3 callers with no binding keep the old shared-singleton behaviour."""
    assert tracker_isolation.install()

    tracker.reset(intent="plain", task_id="plain")
    tracker.collect_step(_step("S0"))

    assert tracker.task_id == "plain"
    assert [s.name for s in tracker.steps] == ["S0"]
    assert tracker_isolation.unbound_write_count() > 0


@pytest.mark.asyncio
async def test_unbound_write_count_is_zero_for_fully_bound_work(tracker):
    """The escape-hatch counter is a real signal, not always-on noise."""

    async def run(task_id):
        with isolated_task(label=task_id):
            tracker.reset(intent=task_id, task_id=task_id)
            tracker.collect_step(_step("s"))

    await asyncio.gather(run("a"), run("b"))
    assert tracker_isolation.unbound_write_count() == 0


def test_install_is_idempotent(tracker):
    assert tracker_isolation.install()
    assert tracker_isolation.install()

    from cuga.backend.activity_tracker.tracker import ActivityTracker

    for name in ISOLATED_FIELDS:
        assert isinstance(ActivityTracker.__dict__[name], property)


def test_install_declines_when_upstream_owns_the_fields(monkeypatch):
    """If cuga-agent#552 is fixed with descriptors, defer to the native fix."""
    from cuga.backend.activity_tracker.tracker import ActivityTracker

    monkeypatch.setattr(ActivityTracker, "steps", property(lambda self: []), raising=False)

    assert tracker_isolation.install() is False
    assert not tracker_isolation._installed


def test_disabled_by_env(monkeypatch, tracker):
    monkeypatch.setenv("M3_TRACKER_ISOLATION", "0")

    assert tracker_isolation.is_enabled() is False
    assert tracker_isolation.install() is False

    # isolated_task must degrade to a no-op rather than raising.
    with isolated_task(label="x") as key:
        assert key == ""
        tracker.reset(intent="x", task_id="x")
        tracker.collect_step(_step("S"))
        assert [s.name for s in tracker.steps] == ["S"]


@pytest.mark.asyncio
async def test_buckets_are_released_after_each_task(tracker):
    async def run(task_id):
        with isolated_task(label=task_id):
            tracker.reset(intent=task_id, task_id=task_id)
            tracker.collect_step(_step("s"))

    await asyncio.gather(*(run(f"t{i}") for i in range(20)))
    assert tracker_isolation._buckets == {}, "per-task buckets leaked; long runs would grow unboundedly"
