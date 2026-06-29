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
    turns to stay under cuga's hardcoded 30s code-block timeout (§11.1b).
  - The bridge is RETRY-AWARE: cuga re-emits a tool call after a 30s timeout,
    which would otherwise make τ² execute the tool twice (§11.1b, mitigation 3).
    Coalescing is implemented (see register_action / _on_pending_done /
    _complete_on_loop) and covered by test_bridge.py.
"""

from __future__ import annotations

import asyncio
import json
import queue
from dataclasses import dataclass
from typing import Any, Optional


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

    def __init__(self, tau2_tools: Any = None, domain_policy: Any = None) -> None:
        self._actions: queue.Queue = queue.Queue()
        self._observations: queue.Queue = queue.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # (coalesce_key, future) for the in-flight action; touched only on the loop.
        self._pending: Optional[tuple[Optional[str], asyncio.Future]] = None
        # Retry-aware coalescing state (§11.1b), touched only on the loop:
        #   key -> {"has_result": bool, "result": Any, "waiter": Future|None}
        # Populated when an in-flight tool call is CANCELLED by cuga's 30s timeout,
        # so a retry of the same call is served from the late result instead of
        # being re-forwarded to τ² (which would run the tool twice).
        self._abandoned: dict[str, dict] = {}
        self._closed = False
        # Context the CUGA side reads when building decoys / the agent.
        self.tau2_tools = tau2_tools
        self.domain_policy = domain_policy

    @staticmethod
    def _coalesce_key(action: Any) -> Optional[str]:
        """Stable key for coalescing retries. Only ToolActions are coalesced —
        a duplicated message/final answer is handled by the re-invoke loop (§11.1b),
        not here."""
        if isinstance(action, ToolAction):
            return f"{action.name}:{json.dumps(action.arguments, sort_keys=True, default=str)}"
        return None

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
        # Cancel in-flight / waiting futures on the loop thread (where they live).
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._cancel_on_loop)

    def _cancel_on_loop(self) -> None:
        if self._pending is not None:
            _, fut = self._pending
            if not fut.done():
                fut.cancel()
        for entry in self._abandoned.values():
            waiter = entry.get("waiter")
            if waiter is not None and not waiter.done():
                waiter.cancel()
        self._abandoned.clear()

    # ── CUGA (event-loop) side ───────────────────────────────────────────────
    def register_action(self, action: Any) -> asyncio.Future:
        """Send an action to τ² and return a Future to await for its result.

        If `action` is a retry of a tool call that cuga's 30s timeout cancelled,
        the bridge serves it from the original call's (in-flight or already-arrived)
        result instead of forwarding it again — so τ² never runs the tool twice.
        Runs on the loop thread (inside the decoy coroutine).
        """
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        fut: asyncio.Future = self._loop.create_future()
        if self._closed:
            fut.cancel()
            return fut

        key = self._coalesce_key(action)
        if key is not None and key in self._abandoned:
            # Retry of a timed-out tool call → do NOT re-forward to τ².
            entry = self._abandoned[key]
            if entry["has_result"]:
                fut.set_result(entry["result"])  # late result already arrived
                del self._abandoned[key]
            else:
                entry["waiter"] = fut  # result still in-flight; hand it over on arrival
            return fut

        self._pending = (key, fut)
        if key is not None:
            fut.add_done_callback(self._on_pending_done)
        self._actions.put(action)
        return fut

    def _on_pending_done(self, fut: asyncio.Future) -> None:
        """Loop-thread callback: if the in-flight tool call was CANCELLED (cuga's
        30s timeout) rather than completed, mark it abandoned so the eventual late
        result is routed to a retry instead of dropped (§11.1b)."""
        if self._closed or not fut.cancelled():
            return
        pending = self._pending
        if pending is None:
            return
        key, pending_fut = pending
        if key is not None and pending_fut is fut:
            self._abandoned.setdefault(key, {"has_result": False, "result": None, "waiter": None})

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

        Runs on the τ² thread; hops to the loop so all _pending/_abandoned state is
        touched on a single thread (no lock needed).
        """
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._complete_on_loop, result)

    def _complete_on_loop(self, result: Any) -> None:
        pending = self._pending
        self._pending = None
        if pending is None:
            return
        key, fut = pending
        if not fut.done():
            fut.set_result(result)  # normal: the decoy is still awaiting
            return
        # fut was CANCELLED by cuga's 30s timeout. Route this late result so a retry
        # of the same tool call is served from it instead of re-forwarding (§11.1b).
        if key is None:
            return
        entry = self._abandoned.setdefault(key, {"has_result": False, "result": None, "waiter": None})
        waiter = entry["waiter"]
        if waiter is not None and not waiter.done():
            waiter.set_result(result)  # a retry is already waiting
            del self._abandoned[key]
        else:
            entry["has_result"] = True
            entry["result"] = result  # stash for a retry that hasn't arrived yet

    def deliver_observation(self, observation: Any) -> None:
        """Deliver the initial observation (first user message) to the CUGA side."""
        self._observations.put(observation)


# TODO(Phase 3): make_decoy_tools(tau2_tools, bridge) -> list[StructuredTool]  (coroutine=)
# TODO(Phase 4): class CugaProxyAgent(HalfDuplexAgent) + make_cuga_factory(...)
