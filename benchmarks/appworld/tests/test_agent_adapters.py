"""Tests for AppWorld external agent adapters."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from benchmarks.appworld.agents.base import APPWORLD_AGENT_PROMPT, AppWorldInvokeResult
from benchmarks.appworld.agents.factory import EXTERNAL_AGENT_NAMES, create_appworld_agent
from benchmarks.appworld.agents.final_answer import (
    format_appworld_final_answer,
    maybe_format_appworld_final_answer,
    skip_final_answer_format,
)
from benchmarks.appworld.agents.tool_loop import (
    extract_final_answer,
    extract_tool_request,
    run_tool_react_loop,
)

pytestmark = pytest.mark.sanity


class _MockTool:
    def __init__(self, name: str, result: Any = "ok"):
        self.name = name
        self.description = f"Mock {name}"
        self._result = result

    async def ainvoke(self, args: dict[str, Any]) -> Any:
        return {"tool": self.name, "args": args, "result": self._result}


@pytest.mark.parametrize("agent_name", sorted(EXTERNAL_AGENT_NAMES))
def test_factory_creates_agent(agent_name: str):
    tools = [_MockTool("supervisor_login")]
    agent = create_appworld_agent(agent_name, tools=tools, max_steps=3)
    assert agent is not None
    assert hasattr(agent, "invoke")


def test_appworld_invoke_result_shape():
    result = AppWorldInvokeResult(
        answer="done",
        tool_calls=[{"name": "t1", "arguments": {}, "result": "ok"}],
        react_steps=2,
    )
    assert result.answer == "done"
    assert len(result.tool_calls) == 1
    assert result.react_steps == 2
    assert result.error is None


def test_shared_prompt_not_empty():
    assert "Never invent or guess values" in APPWORLD_AGENT_PROMPT
    assert "Pagination" in APPWORLD_AGENT_PROMPT
    assert "page_index" in APPWORLD_AGENT_PROMPT
    assert "filter parameters" in APPWORLD_AGENT_PROMPT


def test_extract_tool_request():
    text = 'Thought\n```json\n{"action": "tool", "tool_name": "login", "args": {"x": 1}}\n```'
    parsed = extract_tool_request(text)
    assert parsed == ("login", {"x": 1})


def test_extract_final_answer():
    assert extract_final_answer("Reasoning\nFinal Answer: hello world") == "hello world"


@pytest.mark.asyncio
async def test_format_appworld_final_answer_strips_markdown_count():
    intent = "How many priority-1 unread email threads are in my Gmail inbox?"
    raw = "**1**"

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="answer: 1"))

    formatted = await format_appworld_final_answer(intent, raw, llm=mock_llm)
    assert formatted == "1"
    mock_llm.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_maybe_format_appworld_final_answer_skips_when_disabled(monkeypatch):
    monkeypatch.setenv("APPWORLD_SKIP_FINAL_ANSWER_FORMAT", "1")
    assert skip_final_answer_format() is True
    result = await maybe_format_appworld_final_answer("intent", "**1**")
    assert result == "**1**"


@pytest.mark.asyncio
async def test_run_tool_react_loop_returns_result_shape():
    tools = [_MockTool("fetch_data")]

    call_count = 0

    async def fake_llm_two_step(convo, invoke_callbacks=None):
        nonlocal call_count
        del convo, invoke_callbacks
        call_count += 1
        if call_count == 1:
            return '```json\n{"action": "tool", "tool_name": "fetch_data", "args": {}}\n```'
        return "Final Answer: completed"

    result = await run_tool_react_loop(
        tools=tools,
        system_prompt="test",
        intent="do task",
        user_context="ctx",
        call_llm=fake_llm_two_step,
        max_steps=3,
    )
    assert isinstance(result, AppWorldInvokeResult)
    assert result.answer == "completed"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["name"] == "fetch_data"


@pytest.mark.asyncio
async def test_deepagents_adapter_invoke():
    import sys

    from langchain_core.messages import AIMessage

    tools = [_MockTool("t1")]

    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={"messages": [AIMessage(content="Final answer here")]})

    mock_deepagents = MagicMock()
    mock_deepagents.create_deep_agent = MagicMock(return_value=mock_agent)

    with patch.dict(sys.modules, {"deepagents": mock_deepagents}):
        with patch("benchmarks.appworld.agents.deepagents.create_eval_llm", return_value=MagicMock()):
            from benchmarks.appworld.agents.deepagents import DeepAgentsAppWorldAgent

            agent = DeepAgentsAppWorldAgent(tools=tools)
            agent._agent = None
            result = await agent.invoke(
                intent="test task",
                thread_id="thread-1",
                user_context="supervisor info",
            )

    assert isinstance(result, AppWorldInvokeResult)
    assert result.answer == "Final answer here"


@pytest.mark.asyncio
async def test_hermes_adapter_uses_tool_loop():
    tools = [_MockTool("t1")]

    with patch(
        "benchmarks.appworld.agents.hermes.run_tool_react_loop",
        new_callable=AsyncMock,
        return_value=AppWorldInvokeResult(answer="hermes done", react_steps=2),
    ) as mock_loop:
        from benchmarks.appworld.agents.hermes import HermesAppWorldAgent

        agent = HermesAppWorldAgent(tools=tools)
        result = await agent.invoke(intent="task", thread_id="t1", user_context="ctx")

    mock_loop.assert_awaited_once()
    assert result.answer == "hermes done"


def test_factory_unknown_agent_raises():
    with pytest.raises(ValueError, match="Unknown external agent"):
        create_appworld_agent("unknown", tools=[])
