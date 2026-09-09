"""Threading + termination test for run_cuga_loop (Phase 5). No LLM, no τ².

Drives the REAL ConversationBridge + run_cuga_loop with a FAKE CugaAgent (injected) and a
fake τ² thread that plays proxy + orchestrator + user simulator. This validates the risky
part the other unit tests can't reach: the multi-turn re-invoke loop and — crucially — that
the CUGA loop TERMINATES cleanly (no hang) when τ² ends the conversation and closes the bridge.
"""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from benchmarks.tau2.cuga_runner import run_cuga_loop
from benchmarks.tau2.tau2_bridge import ConversationBridge, MessageAction

pytestmark = pytest.mark.sanity


class FakeAgent:
    """Stands in for CugaAgent: returns a canned final answer per invoke(), no LLM."""

    def __init__(self, answers):
        self._answers = list(answers)
        self.prompts = []

    async def invoke(self, prompt, thread_id=None, track_tool_calls=False):
        self.prompts.append(prompt)
        answer = self._answers.pop(0) if self._answers else None
        return SimpleNamespace(answer=answer)


@pytest.mark.asyncio
async def test_run_loop_multi_turn_then_terminates_on_close():
    bridge = ConversationBridge(tau2_tools=[], domain_policy="p")
    agent = FakeAgent(answers=["turn-1 answer", "turn-2 answer", "turn-3 answer"])
    seen_from_cuga = []

    def fake_tau2():
        # τ² speaks first: the opening customer message.
        bridge.deliver_observation("Hi, my data is down")
        # Respond to two of CUGA's messages, then the user simulator ends the chat.
        for i in range(2):
            action = bridge.wait_for_action()
            if action is None:
                return
            assert isinstance(action, MessageAction)
            seen_from_cuga.append(action.text)
            bridge.complete_pending(f"user reply {i}")
        bridge.close()  # conversation over → must unblock + end the CUGA loop

    t = threading.Thread(target=fake_tau2, name="fake-tau2", daemon=True)
    t.start()

    # The whole point: this must return, not hang. Bound it so a bug fails fast.
    await asyncio.wait_for(run_cuga_loop(bridge, agent=agent, max_turns=10), timeout=5)
    t.join(timeout=5)

    assert not t.is_alive()
    # CUGA got the opening message, then was re-invoked with each user reply (same loop).
    assert agent.prompts[0] == "Hi, my data is down"
    assert "user reply 0" in agent.prompts and "user reply 1" in agent.prompts
    # τ² received CUGA's two answers before it closed the chat.
    assert seen_from_cuga == ["turn-1 answer", "turn-2 answer"]


@pytest.mark.asyncio
async def test_run_loop_exits_if_cuga_returns_no_answer():
    """If CUGA finishes with no answer, the loop ends and closes the bridge (no hang)."""
    bridge = ConversationBridge(tau2_tools=[], domain_policy="p")
    agent = FakeAgent(answers=[None])  # invoke returns answer=None

    def fake_tau2():
        bridge.deliver_observation("opening")

    t = threading.Thread(target=fake_tau2, daemon=True)
    t.start()

    await asyncio.wait_for(run_cuga_loop(bridge, agent=agent, max_turns=10), timeout=5)
    t.join(timeout=5)

    assert agent.prompts == ["opening"]
