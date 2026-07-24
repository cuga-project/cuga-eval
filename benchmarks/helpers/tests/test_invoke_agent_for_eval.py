"""_invoke_agent_for_eval uses the correct keyword per agent type, and
retries a transient failure before giving up."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from cuga.backend.cuga_graph.nodes.cuga_lite.tracking.policy_guard import RetrieverPolicyGuard
from langchain_core.messages import HumanMessage

from benchmarks.helpers.react_agent import GenericReactAgent
from benchmarks.helpers.sdk_eval_helpers import (
    _INVOKE_MAX_ATTEMPTS,
    _invoke_agent_for_eval,
    _retry_thread_id,
)

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


@pytest.mark.asyncio
async def test_invoke_agent_for_eval_retries_transient_failure(monkeypatch):
    monkeypatch.setattr("benchmarks.helpers.sdk_eval_helpers.asyncio.sleep", AsyncMock(return_value=None))
    agent = MagicMock()
    ok_result = MagicMock(answer="ok", tool_calls=[])
    agent.invoke = AsyncMock(side_effect=[ConnectionError("boom"), ok_result])

    result = await _invoke_agent_for_eval(
        agent,
        [HumanMessage(content="hi")],
        thread_id="t1",
    )

    assert result is ok_result
    assert agent.invoke.await_count == 2


@pytest.mark.asyncio
async def test_invoke_agent_for_eval_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr("benchmarks.helpers.sdk_eval_helpers.asyncio.sleep", AsyncMock(return_value=None))
    agent = MagicMock()
    agent.invoke = AsyncMock(side_effect=ConnectionError("still down"))

    with pytest.raises(ConnectionError, match="still down"):
        await _invoke_agent_for_eval(
            agent,
            [HumanMessage(content="hi")],
            thread_id="t1",
        )

    assert agent.invoke.await_count == _INVOKE_MAX_ATTEMPTS


def test_retry_thread_id_unchanged_for_first_attempt():
    assert _retry_thread_id("t1", 1) == "t1"


def test_retry_thread_id_distinct_per_retry():
    ids = {_retry_thread_id("t1", attempt) for attempt in range(1, _INVOKE_MAX_ATTEMPTS + 1)}
    assert len(ids) == _INVOKE_MAX_ATTEMPTS, "each attempt must get its own thread_id"


@pytest.mark.asyncio
async def test_invoke_agent_for_eval_retries_use_distinct_thread_ids(monkeypatch):
    monkeypatch.setattr("benchmarks.helpers.sdk_eval_helpers.asyncio.sleep", AsyncMock(return_value=None))
    agent = MagicMock()
    ok_result = MagicMock(answer="ok", tool_calls=[])
    agent.invoke = AsyncMock(side_effect=[ConnectionError("boom"), ok_result])

    await _invoke_agent_for_eval(
        agent,
        [HumanMessage(content="hi")],
        thread_id="base",
    )

    thread_ids_used = [call.kwargs["thread_id"] for call in agent.invoke.await_args_list]
    assert thread_ids_used[0] == "base"
    assert thread_ids_used[1] != "base", "retry must not reuse the failed attempt's thread_id"


@pytest.mark.asyncio
async def test_invoke_agent_for_eval_retry_inherits_and_cleans_up_policy(monkeypatch):
    monkeypatch.setattr("benchmarks.helpers.sdk_eval_helpers.asyncio.sleep", AsyncMock(return_value=None))
    RetrieverPolicyGuard.register("base_policy_thread", "Do not use document retrievers.")

    agent = MagicMock()
    ok_result = MagicMock(answer="ok", tool_calls=[])
    captured_retry_thread_id = {}

    async def fake_invoke(**kwargs):
        if "retry" in kwargs["thread_id"]:
            captured_retry_thread_id["value"] = kwargs["thread_id"]
            RetrieverPolicyGuard.bind(kwargs["thread_id"])
            assert RetrieverPolicyGuard.check_call("some_query_tool") is not None, (
                "retry thread_id must still enforce the original task's policy"
            )
            return ok_result
        raise ConnectionError("boom")

    agent.invoke = AsyncMock(side_effect=fake_invoke)

    try:
        await _invoke_agent_for_eval(
            agent,
            [HumanMessage(content="hi")],
            thread_id="base_policy_thread",
        )
    finally:
        RetrieverPolicyGuard.unregister("base_policy_thread")

    retry_thread_id = captured_retry_thread_id["value"]
    RetrieverPolicyGuard.bind(retry_thread_id)
    assert RetrieverPolicyGuard.check_call("some_query_tool") is None, (
        "retry thread_id's policy alias must be cleaned up after the call resolves"
    )
