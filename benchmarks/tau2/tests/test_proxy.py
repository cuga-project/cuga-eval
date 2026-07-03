"""Unit tests for CugaProxyAgent — the τ²-side shim (Phase 4).

Needs the `tau2` dependency group (the proxy subclasses τ²'s HalfDuplexAgent), so we
importorskip. No LLM, no threads, no real event loop: we drive the proxy with a FAKE
bridge that records what it was told and returns a canned "next action". That isolates
the proxy's real job — translating a bridge action into the right τ² AssistantMessage,
and routing incoming messages to deliver_observation (opening) vs complete_pending (result).
"""

import pytest

pytest.importorskip("tau2")

from tau2.data_model.message import AssistantMessage, ToolMessage, UserMessage  # noqa: E402

from benchmarks.tau2.tau2_bridge import FinalAnswer, MessageAction, ToolAction  # noqa: E402
from benchmarks.tau2.tau2_proxy import (  # noqa: E402
    CugaProxyAgent,
    get_current_bridge,
    make_cuga_factory,
    set_current_bridge,
)

pytestmark = pytest.mark.sanity


class FakeBridge:
    """Stand-in for ConversationBridge: records the CUGA-side calls and returns a
    pre-set action from wait_for_action (no queue, no Future, no loop needed)."""

    _SENTINEL = object()

    def __init__(self, next_action):
        self._next_action = next_action
        self.delivered = self._SENTINEL  # arg passed to deliver_observation
        self.completed = self._SENTINEL  # arg passed to complete_pending

    def deliver_observation(self, obs):
        self.delivered = obs

    def complete_pending(self, result):
        self.completed = result

    def wait_for_action(self):
        return self._next_action


def _proxy(next_action):
    bridge = FakeBridge(next_action)
    return CugaProxyAgent(bridge, tools=[], domain_policy="be helpful"), bridge


def test_tool_action_becomes_a_tool_calls_message():
    proxy, bridge = _proxy(ToolAction("get_customer", {"customer_id": "C1"}))
    state = proxy.get_init_state()

    msg, state = proxy.generate_next_message(UserMessage(role="user", content="Hi"), state)

    # opening message was handed to CUGA (not completed as a result)
    assert bridge.delivered == "Hi"
    assert bridge.completed is FakeBridge._SENTINEL
    assert state["started"] is True
    # the queued ToolAction became a real τ² tool_calls message
    assert msg.is_tool_call()
    assert msg.tool_calls[0].name == "get_customer"
    assert msg.tool_calls[0].arguments == {"customer_id": "C1"}
    assert msg.tool_calls[0].requestor == "assistant"


def test_message_action_becomes_a_content_message():
    proxy, _ = _proxy(MessageAction("Can you confirm your ID?"))
    state = proxy.get_init_state()

    msg, _ = proxy.generate_next_message(UserMessage(role="user", content="Hi"), state)

    assert not msg.is_tool_call()
    assert msg.content == "Can you confirm your ID?"


def test_subsequent_message_completes_pending_not_deliver():
    proxy, bridge = _proxy(FinalAnswer("Done, re-enabled your data"))
    state = proxy.get_init_state()
    state["started"] = True  # not the opening turn

    tool_result = ToolMessage(id="t1", role="tool", content="the tool output", requestor="assistant")
    msg, _ = proxy.generate_next_message(tool_result, state)

    # the result went back to CUGA via complete_pending, NOT deliver_observation
    assert bridge.completed == "the tool output"
    assert bridge.delivered is FakeBridge._SENTINEL
    # FinalAnswer -> content message routed to the user sim
    assert not msg.is_tool_call()
    assert msg.content == "Done, re-enabled your data"


def test_none_action_is_the_done_sentinel_and_is_stop():
    proxy, _ = _proxy(None)  # bridge closed -> wait_for_action returns None
    state = proxy.get_init_state()
    state["started"] = True

    msg, _ = proxy.generate_next_message(UserMessage(role="user", content="bye"), state)

    assert CugaProxyAgent.is_stop(msg) is True
    # a normal content message must NOT read as stop
    assert CugaProxyAgent.is_stop(AssistantMessage(role="assistant", content="hello")) is False


def test_factory_builds_proxy_from_the_current_bridge():
    bridge = FakeBridge(None)
    set_current_bridge(bridge)
    try:
        agent = make_cuga_factory()(tools=[], domain_policy="p")
        assert isinstance(agent, CugaProxyAgent)
        assert agent.bridge is bridge
        assert get_current_bridge() is bridge
    finally:
        set_current_bridge(None)
