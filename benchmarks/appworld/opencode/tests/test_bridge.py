"""Smoke test for the in-process AppWorld MCP bridge.

Starts the FastMCP bridge over a FAKE `world` (no AppWorld servers required), connects with a
real MCP client, calls the `execute_python` tool, and asserts the call routes to `world.execute`,
that state is captured, and that `complete_task` is detected.

Skipped if `appworld` (pulled in transitively via utils.appworld_utils) cannot be imported in this
environment — the bridge's logic is exercised whenever the AppWorld deps are present.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

APPWORLD_DIR = Path(__file__).resolve().parents[2]
for p in (APPWORLD_DIR, APPWORLD_DIR / "appworld" / "src"):
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

try:
    from opencode.bridge import AppWorldMcpBridge
    from fastmcp import Client
except Exception as exc:  # pragma: no cover - env-dependent
    pytest.skip(f"opencode bridge deps unavailable: {exc}", allow_module_level=True)


class _FakeTask:
    app_descriptions = {"spotify": "music", "supervisor": "creds"}


class _FakeWorld:
    """Minimal stand-in for AppWorld.world used by the bridge."""

    def __init__(self) -> None:
        self.task = _FakeTask()
        self.executed: list[str] = []

    def execute(self, code: str) -> str:
        self.executed.append(code)
        return f"OUTPUT<{code.strip()}>"


async def _exercise(url: str) -> dict:
    async with Client(url) as client:
        tools = [t.name for t in await client.list_tools()]
        r1 = await client.call_tool("execute_python", {"code": "apis.spotify.show()"})
        r2 = await client.call_tool(
            "execute_python", {"code": "apis.supervisor.complete_task(answer=42)"}
        )
        return {"tools": tools, "r1": r1, "r2": r2}


def test_repl_bridge_routes_and_captures_state():
    world = _FakeWorld()
    bridge = AppWorldMcpBridge(world, mode="repl")
    url = bridge.start()
    try:
        result = asyncio.run(_exercise(url))
    finally:
        bridge.stop()

    # The single repl tool is exposed.
    assert result["tools"] == ["execute_python"]

    # Both calls reached the (fake) world.execute, wrapped with the leading/trailing newlines.
    assert any("apis.spotify.show()" in c for c in world.executed)
    assert any("complete_task(answer=42)" in c for c in world.executed)

    # State captured: two tool calls, completion detected, answer extracted.
    assert len(bridge.state.tool_calls) == 2
    assert bridge.state.completed is True
    assert bridge.state.final_answer == "42"


def test_bridge_rejects_unknown_mode():
    with pytest.raises(ValueError):
        AppWorldMcpBridge(_FakeWorld(), mode="bogus")
