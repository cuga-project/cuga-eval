"""_invoke_agent_for_eval uses the correct keyword per agent type."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from benchmarks.helpers.react_agent import GenericReactAgent
from benchmarks.helpers.sdk_eval_helpers import _invoke_agent_for_eval

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_invoke_agent_for_eval_cuga_uses_message_kwarg():
    agent = MagicMock()
    agent.invoke = AsyncMock(return_value=MagicMock(answer="ok", tool_calls=[]))

    await _invoke_agent_for_eval(
        agent,
        [HumanMessage(content="hi")],
        thread_id="t1",
        lf_config={"callbacks": ["cb"]},
    )

    agent.invoke.assert_awaited_once()
    kwargs = agent.invoke.call_args.kwargs
    assert "message" in kwargs
    assert "messages" not in kwargs
    assert kwargs["config"] == {"callbacks": ["cb"]}


@pytest.mark.asyncio
async def test_invoke_agent_for_eval_react_uses_messages_kwarg():
    agent = MagicMock(spec=GenericReactAgent)
    agent.invoke = AsyncMock(return_value=MagicMock(answer="ok", tool_calls=[], react_steps=1))

    await _invoke_agent_for_eval(
        agent,
        [HumanMessage(content="hi")],
        thread_id="t1",
        lf_config={"callbacks": ["cb"]},
    )

    kwargs = agent.invoke.call_args.kwargs
    assert "messages" in kwargs
    assert kwargs["invoke_callbacks"] == ["cb"]
