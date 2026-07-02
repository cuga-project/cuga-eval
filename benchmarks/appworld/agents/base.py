"""Shared types and prompts for AppWorld agent adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

APPWORLD_AGENT_PROMPT = """
# INSTRUCTIONS

A. General instructions:

- Never invent or guess values. For example, if I ask you to play a song, do not assume the ID is 123. Instead, look it up properly through the right API.
- Never leave placeholders; don't output things like "your_username". Always fill in the real value by retrieving it via APIs (e.g., Supervisor app for credentials).
- Always map specific nouns in the user's prompt (e.g., 'friends', 'unread emails', 'recent transactions') to the available parameters or schema fields for each tool (from the Available tools list). Never fetch a generalized list if the tool provides a parameter to filter the exact subset the user asked for.
- DATA FROM TOOLS ONLY: Never answer from your own knowledge. Call tools and use their results before giving a final answer.

B. Filtering (use API parameters, not manual filtering on partial results):

- Before calling a list/search tool, read its description for filter parameters (e.g., label, read, starred, archived, from_email, date ranges).
- Pass filters in tool args that match the user's request (e.g., priority-1 + unread → label and read parameters), instead of fetching an unfiltered page and counting manually.
- Do not answer from the first page of an unfiltered list when filters exist on the tool.

C. Pagination (CRITICAL for counts and full lists):

- Many tools return paginated data. NEVER assume the first page is complete.
- Check tool docs for pagination args: page_index, page_limit, offset, limit, cursor, etc.
- Loop: call with page_index=0 (or first page), then increment until the response is empty or shorter than page_limit.
- For "how many" questions, fetch ALL matching pages (with filters applied), then count the combined results.
- Common mistake: only fetching page 0 (default page_limit is often 5) and under-counting.

D. App-specific instructions:

- Any reference to my friends, family or any other person or relation refers to the people in my phone's contacts list.
- Always obtain the current date or time from the phone app's get_current_date_and_time API or task context, never from your internal clock.
- For temporal requests, use proper time boundaries, e.g., when asked about periods like "yesterday", use complete ranges: 00:00:00 to 23:59:59.
""".strip()


@dataclass
class AppWorldInvokeResult:
    answer: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    react_steps: int | None = None
    error: str | None = None


@runtime_checkable
class AppWorldAgent(Protocol):
    async def invoke(
        self,
        *,
        intent: str,
        thread_id: str,
        user_context: str = "",
        track_tool_calls: bool = True,
        config: Optional[dict[str, Any]] = None,
    ) -> AppWorldInvokeResult: ...
