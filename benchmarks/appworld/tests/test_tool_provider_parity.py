"""Pin how the external agent adapters reach AppWorld tools against how CUGA does.

A comparison between CUGA and another agent is only meaningful if both are
handed the same toolbox by the same code. These tests assert the parts that
really are shared, and pin the two places where the paths deliberately differ
so that a future change to either has to be a conscious one.

Deliberately no registry here: every provider is a stub. These tests are about
which calls each path makes, not about what a live registry returns.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from benchmarks.appworld.agents import tools as agent_tools
from benchmarks.appworld.utils import registry_auth


class _StubProvider:
    """Records how it was constructed and which methods were called."""

    instances: list["_StubProvider"] = []

    def __init__(self, app_names: list[str] | None = None, **kwargs: Any) -> None:
        self.app_names = app_names
        self.kwargs = kwargs
        self.calls: list[str] = []
        _StubProvider.instances.append(self)

    async def initialize(self) -> None:
        self.calls.append("initialize")

    async def get_all_tools(self) -> list[Any]:
        self.calls.append("get_all_tools")
        return [object(), object()]


@pytest.fixture(autouse=True)
def _reset_instances():
    _StubProvider.instances = []
    yield
    _StubProvider.instances = []


def test_registry_helpers_are_the_same_objects():
    """The adapters must not carry their own copy of the registry address logic.

    They did, and it had already drifted: the copy omitted the
    `server_ports.registry_host` branch, so a config pointing the registry at a
    non-localhost host sent CUGA to that host and the adapters to
    http://localhost:8001.
    """
    assert agent_tools.get_registry_base_url is registry_auth.get_registry_base_url
    assert agent_tools.authenticate_apps is registry_auth.authenticate_apps


async def test_external_path_builds_tools_through_combined_tool_provider(monkeypatch):
    """`setup_appworld_tools` must go through CombinedToolProvider, like the SDK."""
    monkeypatch.setattr(agent_tools, "CombinedToolProvider", _StubProvider)

    provider, tools = await agent_tools.setup_appworld_tools(app_names=["gmail", "phone"])

    assert isinstance(provider, _StubProvider)
    assert provider.calls == ["initialize", "get_all_tools"]
    assert len(tools) == 2


async def test_sdk_path_builds_tools_through_combined_tool_provider(monkeypatch):
    """`setup_agent_with_tools` must make the same two calls on the same class."""
    import benchmarks.helpers.sdk_eval_helpers as helpers

    monkeypatch.setattr(helpers, "CombinedToolProvider", _StubProvider)
    monkeypatch.setattr(helpers, "setup_langfuse", lambda: None)
    monkeypatch.setattr(helpers, "CugaAgent", lambda **kwargs: kwargs)

    agent, langfuse = await helpers.setup_agent_with_tools()

    assert langfuse is None
    provider = _StubProvider.instances[0]
    assert provider.calls == ["initialize", "get_all_tools"]
    # The provider object itself is handed to the agent, not just its tools.
    assert agent["tool_provider"] is provider


async def test_sdk_loads_all_apps_and_external_loads_only_the_task_apps(monkeypatch):
    """The one real asymmetry in the toolbox, pinned.

    CUGA gets every app and has to locate the right tools itself (that is what
    `find_tools` is for). The external adapters get a provider already filtered
    to the apps the task declares, so tool selection across apps is solved for
    them before the agent runs.

    That is not a bug — a plain tool loop cannot hold every app's tools in its
    prompt — but it is a head start CUGA does not get, and any score comparison
    has to be read with it in mind. If you change either side, change this test
    on purpose.
    """
    import benchmarks.helpers.sdk_eval_helpers as helpers

    monkeypatch.setattr(helpers, "CombinedToolProvider", _StubProvider)
    monkeypatch.setattr(helpers, "setup_langfuse", lambda: None)
    monkeypatch.setattr(helpers, "CugaAgent", lambda **kwargs: kwargs)
    await helpers.setup_agent_with_tools()
    sdk_provider = _StubProvider.instances[0]

    monkeypatch.setattr(agent_tools, "CombinedToolProvider", _StubProvider)
    await agent_tools.setup_appworld_tools(app_names=["gmail", "phone"])
    external_provider = _StubProvider.instances[1]

    assert sdk_provider.app_names is None, "SDK path must load all apps"
    assert external_provider.app_names == ["gmail", "phone"], "external path is task-scoped"


async def test_both_paths_refuse_to_run_with_zero_tools(monkeypatch):
    """Zero tools must abort on both paths, not produce a run full of zeros.

    The registry yields no tools when it could not reach the app API server at
    startup. An agent with no tools still finishes every task and still gets
    scored, so the run looks like a real bad result instead of a broken setup
    (issue #148). The SDK path has guarded this since then; the external path
    now does too.
    """
    import benchmarks.helpers.sdk_eval_helpers as helpers

    class _EmptyProvider(_StubProvider):
        async def get_all_tools(self) -> list[Any]:
            self.calls.append("get_all_tools")
            return []

    monkeypatch.setattr(helpers, "CombinedToolProvider", _EmptyProvider)
    monkeypatch.setattr(helpers, "setup_langfuse", lambda: None)
    monkeypatch.setattr(helpers, "CugaAgent", lambda **kwargs: kwargs)
    with pytest.raises(RuntimeError, match="0 tools"):
        await helpers.setup_agent_with_tools(require_tools=True)

    monkeypatch.setattr(agent_tools, "CombinedToolProvider", _EmptyProvider)
    with pytest.raises(RuntimeError, match="0 tools"):
        await agent_tools.setup_appworld_tools(app_names=["gmail"])


def test_require_tools_defaults_match_the_appworld_call_sites():
    """AppWorld cannot run toolless, so the external default is on.

    The SDK helper serves other benchmarks too and so defaults to off; its
    AppWorld caller passes `require_tools=True` explicitly.
    """
    import benchmarks.helpers.sdk_eval_helpers as helpers

    assert inspect.signature(agent_tools.setup_appworld_tools).parameters["require_tools"].default is True
    assert inspect.signature(helpers.setup_agent_with_tools).parameters["require_tools"].default is False
