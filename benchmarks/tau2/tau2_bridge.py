"""ConversationBridge + decoy tools + CugaProxyAgent for tau2-bench.

Phase 2 implements ConversationBridge (below). Decoy tools (Phase 3) and
CugaProxyAgent (Phase 4) are still TODO — see TAU2_CUGA_EVAL_PLAN.md §4, §5.3,
§11.1, §11.1b.

Design summary (verified by the Phase-0 spikes):
  - Decoy tools are ASYNC coroutines registered via `coroutine=` on StructuredTool.
    CUGA awaits them on its event loop (no run_in_executor wrap; confirmed in
    Step B — CUGA's generated code was `await get_customer(...)`).
  - Each decoy registers an action on a queue.Queue (CUGA -> τ²) and awaits an
    asyncio.Future that τ²'s thread completes via loop.call_soon_threadsafe
    (confirmed in Step A).
  - Two kinds of decoy: domain-tool decoys (-> tool_calls -> env) and a message
    decoy (-> content message -> user sim). Prefer the re-invoke loop for user
    turns to stay under cuga's (configurable) code-block timeout (§11.1b).
  - The bridge is intentionally MINIMAL: one queue + one pending Future per turn.
    It does NOT itself guard against the timeout->retry->double-exec case — that is
    prevented upstream (mitigations 1/2/4 in §11.1b). See the "Why no coalescing?"
    note on ConversationBridge below.
"""

from __future__ import annotations

import asyncio
import queue
from dataclasses import dataclass
from typing import Any, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class _Done:
    """Sentinel pushed into the action queue to unblock wait_for_action on close."""


DONE = _Done()


# ── Actions CUGA emits through the bridge ─────────────────────────────────────
# The proxy (Phase 4) maps these onto τ² AssistantMessages:
#   ToolAction   -> AssistantMessage(tool_calls=[...])  -> environment
#   MessageAction-> AssistantMessage(content=...)       -> user simulator
#   FinalAnswer  -> AssistantMessage(content=...)       -> user simulator (turn end)
@dataclass
class ToolAction:
    name: str
    arguments: dict


@dataclass
class MessageAction:
    text: str


@dataclass
class FinalAnswer:
    text: str


class BridgeClosed(RuntimeError):
    """Raised when the CUGA side tries to use a bridge that has been closed."""


class ConversationBridge:
    """Two-thread rendezvous between CUGA (main/event-loop) and τ² (proxy thread).

    Transport:
      - actions queue (CUGA -> τ²): tool calls / messages / final answers.
      - observations queue (τ² -> CUGA): the FIRST user message only; every later
        observation (tool result, user reply) is delivered by completing the
        per-call asyncio.Future the decoy is awaiting.
      - one outstanding action at a time (max_concurrency=1), so a single
        `_pending` Future is sufficient.

    Thread ownership:
      - CUGA side calls: register_action / register_message / first_observation /
        emit_final / close.
      - τ² proxy side calls: wait_for_action / complete_pending / deliver_observation.
    """

    # ── Why no retry-aware coalescing? (removed 2026-06-29 — read before re-adding) ──
    # cuga caps each generated code block with a timeout; if a tool call exceeds it,
    # cuga cancels the block and RETRIES — re-emitting the tool call. Through a naive
    # bridge that makes τ²'s orchestrator run the tool TWICE (e.g. double-booking).
    #
    # We originally built a "retry-aware coalescing" layer here (an `_abandoned` map +
    # done-callbacks) so a retry was served from the original call's result instead of
    # being re-forwarded. It worked and was unit-tested. We REMOVED it on 2026-06-29
    # because the hazard's trigger went away:
    #   - cuga #365 made the code-block timeout CONFIGURABLE; tau2.env sets it to 120s
    #     (mitigation 4), far above any orchestrator-run tool's wait.
    #   - domain tools are in-memory DB ops (ms) — mitigation 1.
    #   - user-sim turns go through the re-invoke loop, OUTSIDE any code block, so a slow
    #     user reply never counts against the timeout — mitigation 2.
    # With 1+2+4 the timeout→retry path realistically never fires inside a code block, so
    # the coalescing guarded a case that no longer occurs — pure complexity. The FULL
    # design (and how to restore it) lives in TAU2_CUGA_EVAL_PLAN.md §11.1b, mitigation 3.
    #
    # ⚠️ If you ever observe a real tool exceeding the configured timeout (cuga logs
    # "Execution timed out") and a tool running twice, restore coalescing per §11.1b —
    # do NOT just lower the timeout reflexively. This bridge intentionally does the simple
    # thing: one queue, one pending Future per turn.

    def __init__(self, tau2_tools: Any = None, domain_policy: Any = None) -> None:
        self._actions: queue.Queue = queue.Queue()
        self._observations: queue.Queue = queue.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # The single in-flight Future (one outstanding action at a time;
        # max_concurrency=1 + strict ping-pong, so one slot is sufficient).
        self._pending: Optional[asyncio.Future] = None
        self._closed = False
        # Context the CUGA side reads when building decoys / the agent.
        self.tau2_tools = tau2_tools
        self.domain_policy = domain_policy

    # ── lifecycle ────────────────────────────────────────────────────────────
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record the CUGA event loop so the τ² thread can complete Futures on it.

        Optional: register_action also captures the running loop lazily. Call this
        explicitly at setup if a complete_pending could ever race the first action.
        """
        self._loop = loop

    def close(self) -> None:
        """Idempotent shutdown: unblock both sides. Safe to call from any thread."""
        if self._closed:
            return
        self._closed = True
        self._actions.put(DONE)
        self._observations.put(DONE)
        # Cancel an in-flight wait on the loop thread so the awaiting decoy unwinds.
        fut = self._pending
        if self._loop is not None and fut is not None and not fut.done():
            self._loop.call_soon_threadsafe(fut.cancel)

    # ── CUGA (event-loop) side ───────────────────────────────────────────────
    def register_action(self, action: Any) -> asyncio.Future:
        """Send an action to τ² and return a Future to await for its result.
        Runs on the loop thread (inside the decoy coroutine)."""
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        fut: asyncio.Future = self._loop.create_future()
        if self._closed:
            fut.cancel()
            return fut
        self._pending = fut
        self._actions.put(action)
        return fut

    def register_message(self, text: str) -> asyncio.Future:
        """Send a content message (to the user sim) and await the user's reply."""
        return self.register_action(MessageAction(text))

    def emit_final(self, text: str) -> None:
        """Emit this turn's final answer (routed to the user sim). No result awaited."""
        self._actions.put(FinalAnswer(text))

    def first_observation(self) -> Any:
        """Block for the initial user message (or None if the bridge is closed)."""
        item = self._observations.get()
        return None if isinstance(item, _Done) else item

    # ── τ² (proxy thread) side ───────────────────────────────────────────────
    def wait_for_action(self) -> Any:
        """Block for CUGA's next action. Returns None when the bridge is closed."""
        item = self._actions.get()
        return None if isinstance(item, _Done) else item

    def complete_pending(self, result: Any) -> None:
        """Hand `result` back to the decoy awaiting the current pending Future.
        Runs on the τ² thread, so it hops to the loop via call_soon_threadsafe."""
        fut = self._pending
        self._pending = None
        if fut is not None and not fut.done() and self._loop is not None:
            self._loop.call_soon_threadsafe(fut.set_result, result)

    def deliver_observation(self, observation: Any) -> None:
        """Deliver the initial observation (first user message) to the CUGA side."""
        self._observations.put(observation)


# ── Decoy tools (Phase 3) ─────────────────────────────────────────────────────
# A decoy has a real τ² tool's name + parameter schema but NO body: it forwards
# the call over the bridge and returns τ²'s result. Registered via `coroutine=`
# so CUGA awaits it on its event loop (verified in the Step B spike — CUGA's
# generated code was `await get_customer(...)`). These are the ONLY tools CUGA
# gets, so every tool call is forced through the bridge → τ²'s orchestrator.


def _tool_description(t: Any) -> str:
    """LLM-facing description, mirroring τ²'s Tool._get_description() (short desc,
    then long desc if present). Reads only public fields so it works for real τ²
    Tools and test doubles alike."""
    short = (getattr(t, "short_desc", "") or "").strip()
    long = (getattr(t, "long_desc", "") or "").strip()
    if not short:
        return getattr(t, "name", "tool")
    return f"{short}\n\n{long}" if long else short


def _make_domain_decoy(t: Any, bridge: "ConversationBridge") -> StructuredTool:
    """One decoy for a τ² domain tool: same name + params schema, but the body
    forwards the call through the bridge instead of executing it. A per-tool
    factory so each closure captures its own tool name (no loop-var late binding)."""
    name = t.name

    async def _forward(**kwargs: Any) -> Any:
        return await bridge.register_action(ToolAction(name=name, arguments=kwargs))

    return StructuredTool(
        name=name,
        description=_tool_description(t),
        args_schema=t.params,  # τ²'s own pydantic model — CUGA sees the real contract
        coroutine=_forward,
    )


class _MessageArgs(BaseModel):
    message: str = Field(description="The message to send to the customer.")


def _make_message_decoy(bridge: "ConversationBridge", name: str) -> StructuredTool:
    """The 'talk to the customer' decoy: emits a content message and blocks for the
    user simulator's reply. Prefer the re-invoke loop for user turns where a reply
    could exceed the code-block timeout (plan §11.1b)."""

    async def _forward(message: str) -> Any:
        return await bridge.register_message(message)

    return StructuredTool(
        name=name,
        description="Send a message to the customer and wait for their reply.",
        args_schema=_MessageArgs,
        coroutine=_forward,
    )


def make_decoy_tools(
    tau2_tools: list,
    bridge: "ConversationBridge",
    *,
    include_message_decoy: bool = True,
    message_decoy_name: str = "send_message_to_user",
) -> list[StructuredTool]:
    """Build the tools CUGA is handed: one decoy per τ² domain tool, plus (optionally)
    a message decoy. The bridge is closed over by every decoy."""
    decoys = [_make_domain_decoy(t, bridge) for t in tau2_tools]
    if include_message_decoy:
        decoys.append(_make_message_decoy(bridge, message_decoy_name))
    return decoys


# TODO(Phase 4): class CugaProxyAgent(HalfDuplexAgent) + make_cuga_factory(...)
