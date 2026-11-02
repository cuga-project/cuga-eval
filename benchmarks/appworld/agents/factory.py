"""Factory for AppWorld external agent adapters."""

from __future__ import annotations

from typing import Any

from benchmarks.appworld.agents.base import AppWorldAgent
from benchmarks.appworld.agents.deepagents import DeepAgentsAppWorldAgent
from benchmarks.appworld.agents.hermes import HermesAppWorldAgent
from benchmarks.appworld.agents.openclaw import OpenClawAppWorldAgent
from benchmarks.appworld.agents.stub import StubAppWorldAgent

# `stub` is the template in stub.py, not a real framework. It is registered so a
# new harness can be checked end to end before any agent code is written — see
# the module docstring in stub.py.
EXTERNAL_AGENT_NAMES = frozenset({"deepagents", "openclaw", "hermes", "stub"})


def create_appworld_agent(name: str, tools: list[Any], **kwargs: Any) -> AppWorldAgent:
    normalized = name.strip().lower()
    if normalized == "deepagents":
        return DeepAgentsAppWorldAgent(tools=tools, **kwargs)
    if normalized == "openclaw":
        return OpenClawAppWorldAgent(tools=tools, **kwargs)
    if normalized == "hermes":
        return HermesAppWorldAgent(tools=tools, **kwargs)
    if normalized == "stub":
        return StubAppWorldAgent(tools=tools, **kwargs)
    raise ValueError(f"Unknown external agent {name!r}. Supported: {', '.join(sorted(EXTERNAL_AGENT_NAMES))}")
