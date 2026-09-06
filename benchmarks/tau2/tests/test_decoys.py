"""Unit tests for make_decoy_tools — the tools CUGA is handed.

No LLM, no τ², no cuga. Uses *fake* τ² tool doubles (duck-typed: name, short_desc,
long_desc, params) + the real ConversationBridge with a fake orchestrator thread.

We exercise each decoy's `coroutine` directly because that is exactly how CUGA
calls it — its generated code does `await get_customer(...)`, hitting the coroutine,
not LangChain's invoke wrapper.
"""

import asyncio
import threading

import pytest
from pydantic import BaseModel, Field

from benchmarks.tau2.tau2_bridge import (
    ConversationBridge,
    MessageAction,
    ToolAction,
    make_decoy_tools,
)

pytestmark = pytest.mark.sanity


# ── a fake τ² Tool: same attributes make_decoy_tools reads off the real one ──
class _GetCustomerParams(BaseModel):
    customer_id: str = Field(description="ID of the customer to look up")


class _FakeTool:
    def __init__(self, name, short, long, params):
        self.name = name
        self.short_desc = short
        self.long_desc = long
        self.params = params


def _fake_tools():
    return [_FakeTool("get_customer", "Look up a customer.", "Returns the full record.", _GetCustomerParams)]


def test_decoy_mirrors_the_tau2_tool_contract():
    """name, description and args_schema come straight from the τ² tool; it's async-only."""
    bridge = ConversationBridge()
    tools = make_decoy_tools(_fake_tools(), bridge, include_message_decoy=False)

    assert len(tools) == 1
    d = tools[0]
    assert d.name == "get_customer"
    assert "Look up a customer." in d.description
    assert "Returns the full record." in d.description
    # CUGA sees τ²'s own parameter schema (same field names + descriptions).
    assert "customer_id" in d.args_schema.model_fields
    # Async path: coroutine set, no sync func (so cuga takes the coroutine branch).
    assert d.coroutine is not None
    assert d.func is None


@pytest.mark.asyncio
async def test_domain_decoy_forwards_through_bridge_and_returns_result():
    bridge = ConversationBridge()
    bridge.bind_loop(asyncio.get_running_loop())
    [decoy] = make_decoy_tools(_fake_tools(), bridge, include_message_decoy=False)

    seen = {}

    def orchestrator():
        seen["action"] = bridge.wait_for_action()  # τ² receives the forwarded call
        bridge.complete_pending({"customer_id": "C1", "name": "Ada", "plan": "gold"})

    t = threading.Thread(target=orchestrator, daemon=True)
    t.start()

    # How CUGA calls it: await the coroutine with the tool's args.
    result = await decoy.coroutine(customer_id="C1")
    t.join(timeout=5)

    # The call arrived at τ² as a ToolAction with the right name + args...
    assert isinstance(seen["action"], ToolAction)
    assert seen["action"].name == "get_customer"
    assert seen["action"].arguments == {"customer_id": "C1"}
    # ...and τ²'s result flowed back to the decoy unchanged.
    assert result == {"customer_id": "C1", "name": "Ada", "plan": "gold"}


@pytest.mark.asyncio
async def test_domain_decoy_accepts_positional_args():
    """CUGA's code executor calls tools positionally — e.g. get_customer("C1") — not just
    by keyword. The decoy must map positional args onto the schema fields by order.
    (Regression: previously `_forward(**kwargs)` raised TypeError on positional calls,
    which failed real airline/retail tool calls mid-run.)"""
    bridge = ConversationBridge()
    bridge.bind_loop(asyncio.get_running_loop())
    [decoy] = make_decoy_tools(_fake_tools(), bridge, include_message_decoy=False)

    seen = {}

    def orchestrator():
        seen["action"] = bridge.wait_for_action()
        bridge.complete_pending({"customer_id": "C1"})

    t = threading.Thread(target=orchestrator, daemon=True)
    t.start()

    result = await decoy.coroutine("C1")  # positional, as CUGA's generated code calls it
    t.join(timeout=5)

    assert seen["action"].arguments == {"customer_id": "C1"}  # mapped to the field name
    assert result == {"customer_id": "C1"}


@pytest.mark.asyncio
async def test_message_decoy_forwards_text_and_returns_user_reply():
    bridge = ConversationBridge()
    bridge.bind_loop(asyncio.get_running_loop())
    tools = make_decoy_tools(
        [], bridge, include_message_decoy=True, message_decoy_name="send_message_to_user"
    )

    assert len(tools) == 1
    msg_decoy = tools[0]
    assert msg_decoy.name == "send_message_to_user"
    assert "message" in msg_decoy.args_schema.model_fields

    seen = {}

    def orchestrator():
        seen["action"] = bridge.wait_for_action()  # routed to the user simulator
        bridge.complete_pending("Yes, my data is down.")

    t = threading.Thread(target=orchestrator, daemon=True)
    t.start()

    reply = await msg_decoy.coroutine(message="Hi, how can I help?")
    t.join(timeout=5)

    assert isinstance(seen["action"], MessageAction)
    assert seen["action"].text == "Hi, how can I help?"
    assert reply == "Yes, my data is down."


def test_make_decoy_tools_count_and_message_toggle():
    """One decoy per domain tool; the message decoy is opt-out."""
    bridge = ConversationBridge()
    two = [
        _FakeTool("get_customer", "Look up a customer.", "", _GetCustomerParams),
        _FakeTool("get_order", "Look up an order.", "", _GetCustomerParams),
    ]
    with_msg = make_decoy_tools(two, bridge)  # default includes message decoy
    without_msg = make_decoy_tools(two, bridge, include_message_decoy=False)
    assert [t.name for t in with_msg] == ["get_customer", "get_order", "send_message_to_user"]
    assert [t.name for t in without_msg] == ["get_customer", "get_order"]
