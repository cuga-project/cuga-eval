"""Factory for AppWorld external agent adapters."""

from __future__ import annotations

from typing import Any

from benchmarks.appworld.agents.base import AppWorldAgent
from benchmarks.appworld.agents.deepagents import DeepAgentsAppWorldAgent
from benchmarks.appworld.agents.hermes import HermesAppWorldAgent
from benchmarks.appworld.agents.openclaw import OpenClawAppWorldAgent

EXTERNAL_AGENT_NAMES = frozenset({"deepagents", "openclaw", "hermes"})


def create_appworld_agent(name: str, tools: list[Any], **kwargs: Any) -> AppWorldAgent:
    normalized = name.strip().lower()
    if normalized == "deepagents":
        return DeepAgentsAppWorldAgent(tools=tools, **kwargs)
    if normalized == "openclaw":
        return OpenClawAppWorldAgent(tools=tools, **kwargs)
    if normalized == "hermes":
        return HermesAppWorldAgent(tools=tools, **kwargs)
    raise ValueError(f"Unknown external agent {name!r}. Supported: {', '.join(sorted(EXTERNAL_AGENT_NAMES))}")
