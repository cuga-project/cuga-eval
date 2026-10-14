"""eval_m3 for VAKRA capability 4 with the campaign's multi-turn protocol.

The evaluator scores only the LAST turn of a cap4 dialogue and asserts exactly one predicted
turn. The campaign ran each item as ONE agent call on a fresh thread, with the earlier turns
as history taken from the data — the user's questions and the GOLD answers
(vakra-main benchmark/runner_helpers.py ``BenchmarkItem.from_dict``). eval_m3 instead runs
the agent on every turn and feeds back its own answers. This wrapper makes eval_m3 do what the
campaign did: the multi-turn helper runs only the last turn, through an agent proxy that
prepends ``[user q_1, assistant a_1, ..., user q_{n-1}, assistant a_{n-1}]`` to that call,
and the predicted turn keeps the last turn's id.

usage: python -m benchmarks.m3.parity.eval_m3_cap4 <eval_m3 arguments>
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List

from langchain_core.messages import AIMessage, HumanMessage

import benchmarks.m3.eval_m3 as em

_original_multiturn = em.evaluate_multiturn_task_with_langfuse


def campaign_history(turns: List[Dict[str, Any]]) -> List[Any]:
    """User question and gold answer of every turn before the last."""
    history: List[Any] = []
    for turn in turns[:-1]:
        history.append(HumanMessage(content=str(turn.get("query", ""))))
        if turn.get("answer"):
            history.append(AIMessage(content=str(turn["answer"])))
    return history


class HistoryAgent:
    """Agent proxy: every ``invoke`` gets the campaign history in front of its messages."""

    def __init__(self, agent: Any, history: List[Any]):
        self._agent = agent
        self._history = history

    def __getattr__(self, name: str) -> Any:
        return getattr(self._agent, name)

    async def invoke(self, message: Any = None, *args: Any, **kwargs: Any) -> Any:
        messages = message if isinstance(message, list) else [HumanMessage(content=str(message))]
        return await self._agent.invoke(list(self._history) + list(messages), *args, **kwargs)


async def last_turn_with_campaign_history(agent: Any, turns: List[Dict[str, Any]], *args: Any, **kwargs: Any):
    """Drop-in for ``evaluate_multiturn_task_with_langfuse``: one call, for the last turn."""
    if len(turns) <= 1:
        return await _original_multiturn(agent, turns, *args, **kwargs)
    result = await _original_multiturn(
        HistoryAgent(agent, campaign_history(turns)), turns[-1:], *args, **kwargs
    )
    for response in result.get("all_responses") or []:
        response["turn"] = len(turns)  # eval_m3 writes turn_id = turn - 1: the last turn's id
    return result


def install() -> None:
    em.evaluate_multiturn_task_with_langfuse = last_turn_with_campaign_history


if __name__ == "__main__":
    install()
    sys.exit(em._run_main())
