"""cap4 deterministic policy tool-scoping (ported from ``CugaV2Agent``).

A capability-4 policy ("additional instructions") may restrict the task to
document retrievers only, or forbid them. Obeying the restriction at the TOOL
level (not just in prose) keeps forbidden-tool data out of the grounding
window, which is what makes a clean refusal *grounded* for the judge.

Absolute rules prune directly; conditional rules ("If a user's query pertains
to <topic>...") classify the query topic first with one cheap LLM call.
"""

from __future__ import annotations

import re
from typing import Awaitable, Callable, Optional

from loguru import logger

#: async (prompt) -> reply text; injected so this module stays cuga-free.
LlmAinvoke = Callable[[str], Awaitable[str]]

_COND_RULE_RE = re.compile(
    r"if a user.s query pertains to (.+?), which is/are about (.+?)[,.]",
    re.IGNORECASE | re.DOTALL,
)


#: VAKRA document retrievers are the MCP tools named ``query_<domain>``. cuga's registry
#: exposes MCP tools as ``<app>_<tool>``, so in cuga-eval the marker usually follows an app
#: prefix (``hockey_query_hockey``). No VAKRA API tool name contains "query" (checked against
#: all 7,580 cap2/cap3 tools), so matching it after a prefix does not misfire.
_RETRIEVER_RE = re.compile(r"(?:^|_)query_[A-Za-z0-9_]+$")


def is_retriever(name: str) -> bool:
    return bool(_RETRIEVER_RE.search(name)) or "retriev" in name.lower()


async def _classify_topic_match(query: str, topic: str, desc: str, llm_ainvoke: Optional[LlmAinvoke]) -> bool:
    """Does the query pertain to the policy's topic? On any failure, assume a match
    (the conservative reading: the restriction applies)."""
    if llm_ainvoke is None:
        return True
    try:
        reply = await llm_ainvoke(
            f"Topic area: {topic}\nIt covers: {desc}\n\nQuestion: {query}\n\n"
            f"Does the question pertain to this topic area? Reply exactly YES or NO."
        )
        return reply.strip().upper().startswith("Y")
    except Exception as exc:  # noqa: BLE001  (classifier is best-effort)
        logger.warning("[m3-adapter scope] topic classify failed ({}); assuming match", exc)
        return True


async def resolve_scope(policy: str, query: str, llm_ainvoke: Optional[LlmAinvoke] = None) -> str:
    """Resolve a policy string to a tool scope: ``all`` | ``retriever_only`` | ``no_retriever``."""
    text = (policy or "").lower()
    if "document retriever" not in text:
        return "all"
    m = _COND_RULE_RE.search(policy or "")
    if m:  # conditional rule: apply only when the query is on-topic
        if not await _classify_topic_match(query, m.group(1).strip(), m.group(2).strip(), llm_ainvoke):
            return "all"
        return "no_retriever" if "do not use document retrievers" in text else "retriever_only"
    if text.startswith("do not use document retriever"):
        return "no_retriever"
    if "do not use any other" in text or "only" in text:
        return "retriever_only"
    return "all"
