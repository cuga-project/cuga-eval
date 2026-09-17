"""CugaProxyAgent — the τ²-side shim (Phase 4).

This is the object τ²'s orchestrator thinks is "the agent". It implements τ²'s
HalfDuplexAgent interface, but instead of running an LLM it forwards each turn to
CUGA over the ConversationBridge and translates CUGA's actions into τ² messages.

It imports τ², so it lives in its OWN module (not tau2_bridge.py) — that keeps the
bridge + decoy unit tests runnable without the optional `tau2` dependency group.

API verified against tau2 @ pin 5ebebbe:
  - HalfDuplexAgent(tools, domain_policy); implement get_init_state + generate_next_message
    (base_agent.py). is_stop(cls, AssistantMessage) -> bool (llm_agent.py:427).
  - generate_next_message(message, state) -> (AssistantMessage, state); the incoming
    `message` is a UserMessage / ToolMessage / MultiToolMessage carrying `.content` (str).
  - AssistantMessage(role='assistant', content=..., tool_calls=[ToolCall(...)]);
    ToolCall(id, name, arguments, requestor='assistant')  (data_model/message.py).
  - registry factory signature: factory(tools, domain_policy, **kwargs) -> agent (registry.py:117).
"""

from __future__ import annotations

import json
from typing import Any, Optional
from uuid import uuid4

from tau2.agent.base_agent import HalfDuplexAgent
from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolCall, ToolMessage

from benchmarks.tau2.tau2_bridge import (
    ConversationBridge,
    FinalAnswer,
    MessageAction,
    ToolAction,
)


def _incoming_content(message: Any) -> Optional[str]:
    """Pull the text the CUGA side needs out of a τ² input message.

    UserMessage (user reply) and ToolMessage (tool output) both carry `.content` (str).
    MultiToolMessage bundles several ToolMessages — shouldn't occur in our one-tool-at-a-
    time flow, but we join them defensively rather than drop data.
    """
    if isinstance(message, MultiToolMessage):
        return "\n".join((m.content or "") for m in message.tool_messages)
    return getattr(message, "content", None)


def _maybe_json(text: Optional[str]) -> Any:
    """Parse a τ² tool result string back into structured data when it's JSON.

    τ² serializes every tool's return into ToolMessage.content as a JSON string. If we hand
    that raw string to CUGA, its generated code does result["field"] / result.get(...) on a
    str and dies ('str' object has no attribute 'get'; string indices must be integers) —
    this is what sank the whole retail domain. Parsing it back to a dict/list lets CUGA index
    the result as intended. Non-JSON content (plain-text tool messages) passes through as-is.
    """
    if not isinstance(text, str):
        return text
    s = text.strip()
    if not s or s[0] not in "[{":  # cheap guard: only attempt on JSON-looking payloads
        return text
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return text


def _incoming_result(message: Any) -> Any:
    """The value to resolve CUGA's awaiting Future with.

    Tool outputs (ToolMessage/MultiToolMessage) are parsed to structured data so CUGA can
    index them; a customer reply (UserMessage) stays a plain string.
    """
    if isinstance(message, MultiToolMessage):
        return [_maybe_json(m.content) for m in message.tool_messages]
    if isinstance(message, ToolMessage):
        return _maybe_json(getattr(message, "content", None))
    return _incoming_content(message)


class CugaProxyAgent(HalfDuplexAgent):
    """Forwards each τ² turn to CUGA over the bridge; translates CUGA's actions back.

    Subclasses HalfDuplexAgent (NOT LLMAgent) so τ² never runs its own LLM — CUGA is
    the model. State is just a flag for whether the opening message has been delivered.
    """

    DONE = "__CUGA_DONE__"

    def __init__(self, bridge: ConversationBridge, tools: list, domain_policy: str) -> None:
        super().__init__(tools=tools, domain_policy=domain_policy)
        self.bridge = bridge

    def get_init_state(self, message_history: Optional[list] = None) -> dict:
        # We keep no real conversation state (CUGA holds it); just track the opening turn.
        return {"started": False}

    def generate_next_message(self, message: Any, state: dict) -> tuple[AssistantMessage, dict]:
        if not state.get("started"):
            # The opening customer message: hand it to CUGA's loop so it starts invoke().
            self.bridge.deliver_observation(_incoming_content(message))
            state["started"] = True
        elif message is not None:
            # The RESULT of CUGA's last action (a tool result OR a customer reply):
            # resolve the Future the awaiting decoy holds. Tool results are parsed to
            # structured data so CUGA can index them; customer replies stay text.
            self.bridge.complete_pending(_incoming_result(message))
        action = self.bridge.wait_for_action()  # block for CUGA's next move
        return self._to_message(action), state

    def _to_message(self, action: Any) -> AssistantMessage:
        """Translate a bridge action into the τ² message the orchestrator expects."""
        if action is None:  # bridge closed / CUGA is done
            return AssistantMessage(role="assistant", content=self.DONE)
        if isinstance(action, ToolAction):
            # tool_calls set -> is_tool_call() True -> orchestrator runs it on the env
            return AssistantMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    ToolCall(
                        id=uuid4().hex,
                        name=action.name,
                        arguments=action.arguments,
                        requestor="assistant",
                    )
                ],
            )
        if isinstance(action, (MessageAction, FinalAnswer)):
            # plain content -> orchestrator routes it to the user simulator
            return AssistantMessage(role="assistant", content=action.text)
        raise TypeError(f"CugaProxyAgent received an unexpected action: {action!r}")

    @classmethod
    def is_stop(cls, message: AssistantMessage) -> bool:
        return message.content is not None and cls.DONE in message.content


# ── factory + module-level "current bridge" (for registry.register_agent_factory) ──
# With max_concurrency=1 there is exactly one active task at a time, so a single
# module-level bridge (set before launching run_domain, read by the factory) suffices —
# no pairing handshake needed.
_current_bridge: Optional[ConversationBridge] = None


def set_current_bridge(bridge: Optional[ConversationBridge]) -> None:
    global _current_bridge
    _current_bridge = bridge


def get_current_bridge() -> Optional[ConversationBridge]:
    return _current_bridge


def make_cuga_factory(get_bridge=get_current_bridge):
    """Return a τ² agent factory: factory(tools, domain_policy, **kwargs) -> CugaProxyAgent,
    closing over the current task's bridge."""

    def factory(tools: list, domain_policy: str, **kwargs: Any) -> CugaProxyAgent:
        bridge = get_bridge()
        if bridge is None:
            raise RuntimeError("No current bridge set — call set_current_bridge() before run_domain")
        return CugaProxyAgent(bridge, tools, domain_policy)

    return factory
