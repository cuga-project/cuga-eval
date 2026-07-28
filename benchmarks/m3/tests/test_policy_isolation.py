"""Tests for per-task ToolGuide policy scoping (cuga-agent#564 workaround).

The bug: ``PolicyAgent.check_tool_guide_policies()`` lists every enabled
ToolGuide in a process-shared ``PolicyStorage`` collection and match-scores each
one, with nothing tying a policy back to the task that loaded it. eval_m3
manages policies per task, so under ``--batch-size > 1`` concurrent domain
wrappers get matched against each other's guides — measured at 81% of tasks on
a cap4-300 run, foreign matches outnumbering legitimate ones 351 to 77.

As with the sibling tracker-isolation suite, the regression to keep catching is
the *concurrent* one, so the core test genuinely interleaves two asyncio tasks
rather than running them back to back — a sequential test passes even with the
bug present.
"""

import asyncio
import types

import pytest

from benchmarks.helpers import policy_isolation
from benchmarks.helpers.policy_isolation import isolated_policies

pytestmark = pytest.mark.sanity


@pytest.fixture(autouse=True)
def _clean():
    policy_isolation._uninstall_for_tests()
    yield
    policy_isolation._uninstall_for_tests()


@pytest.fixture()
def fake_agent(monkeypatch):
    """A stand-in PolicyAgent whose unscoped check returns every stored guide.

    This reproduces the upstream shape: the store is process-global, so the
    unpatched method hands back whatever any concurrent task happens to have
    loaded.
    """
    from cuga.backend.cuga_graph.policy.agent import PolicyAgent

    store = []

    async def _unscoped(self, context, *a, **kw):
        # Mimic list_policies() returning the whole shared collection.
        return [
            types.SimpleNamespace(policy=types.SimpleNamespace(name=name), matched=True) for name in store
        ]

    monkeypatch.setattr(PolicyAgent, "check_tool_guide_policies", _unscoped, raising=False)
    agent = PolicyAgent.__new__(PolicyAgent)
    return agent, store


def _names(matches):
    return [m.policy.name for m in matches]


@pytest.mark.asyncio
async def test_concurrent_tasks_do_not_see_each_others_policies(fake_agent):
    agent, store = fake_agent
    assert policy_isolation.install()
    store.extend(["cap4_policy_task-a", "cap4_policy_task-b"])

    async def run(task_id):
        with isolated_policies(task_id):
            # Yield so the two tasks genuinely interleave; without scoping both
            # would observe the union of the shared store either way.
            await asyncio.sleep(0)
            return _names(await agent.check_tool_guide_policies(object()))

    a, b = await asyncio.gather(run("task-a"), run("task-b"))
    assert a == ["cap4_policy_task-a"]
    assert b == ["cap4_policy_task-b"]
    assert policy_isolation.dropped_count() == 2


@pytest.mark.asyncio
async def test_policy_free_task_gets_nothing(fake_agent):
    """The real-world case: a task with no additional_instructions of its own
    was handed a sibling's guide, which rewrote its tool set pre-find_tools."""
    agent, store = fake_agent
    assert policy_isolation.install()
    store.append("cap4_policy_1f58b1e965af-ca944c9c34da")

    with isolated_policies("1f58b1e965af-d86dc7049333"):
        assert _names(await agent.check_tool_guide_policies(object())) == []
    assert policy_isolation.dropped_count() == 1


@pytest.mark.asyncio
async def test_unrecognised_policy_names_are_kept(fake_agent):
    """Only the harness's own cap4_policy_<id> names are ours to judge."""
    agent, store = fake_agent
    assert policy_isolation.install()
    store.extend(["some_other_policy", "cap4_policy_task-b"])

    with isolated_policies("task-a"):
        assert _names(await agent.check_tool_guide_policies(object())) == ["some_other_policy"]


@pytest.mark.asyncio
async def test_unbound_calls_preserve_upstream_behaviour(fake_agent):
    """Outside a task binding we must not guess — return what upstream returned."""
    agent, store = fake_agent
    assert policy_isolation.install()
    store.extend(["cap4_policy_task-a", "cap4_policy_task-b"])

    assert len(await agent.check_tool_guide_policies(object())) == 2
    assert policy_isolation.dropped_count() == 0


@pytest.mark.asyncio
async def test_binding_survives_copied_context(fake_agent):
    """LangGraph copy_context()es every node dispatch; the binding must survive."""
    import contextvars

    agent, store = fake_agent
    assert policy_isolation.install()
    store.extend(["cap4_policy_outer", "cap4_policy_other"])

    with isolated_policies("outer"):
        ctx = contextvars.copy_context()
        got = ctx.run(lambda: policy_isolation._current_task.get())
        assert got == "outer"
        assert _names(await agent.check_tool_guide_policies(object())) == ["cap4_policy_outer"]


@pytest.mark.asyncio
async def test_disabled_by_env(monkeypatch, fake_agent):
    agent, store = fake_agent
    monkeypatch.setenv("M3_POLICY_ISOLATION", "0")
    assert policy_isolation.is_enabled() is False
    assert policy_isolation.install() is False

    store.extend(["cap4_policy_task-a", "cap4_policy_task-b"])
    # isolated_policies must degrade to a no-op, leaving the bug reproducible.
    with isolated_policies("task-a") as bound:
        assert bound == ""
        assert len(await agent.check_tool_guide_policies(object())) == 2


def test_install_is_idempotent(fake_agent):
    assert policy_isolation.install()
    assert policy_isolation.install()
