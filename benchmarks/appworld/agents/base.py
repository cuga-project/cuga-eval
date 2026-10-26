"""Shared types and prompts for AppWorld agent adapters.

Two prompts live here, side by side and on purpose.

``APPWORLD_SDK_PROMPT`` is what ``eval_appworld_sdk.py`` passes to the CUGA SDK.
``APPWORLD_AGENT_PROMPT`` is what the external adapters pass to their agent.
They are not identical, and they cannot be: CUGA has ``find_tools`` and a Python
sandbox, so its prompt can refer to both, while the external adapters run a
plain tool loop over a fixed tool list and need explicit filtering and
pagination rules that CUGA's graph already handles in code.

Keeping them in one file makes that gap visible in a diff. When you change one,
read the other and decide deliberately whether the change applies to it too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

# Passed to CugaAgent as `special_instructions`. Kept verbatim in sync with the
# SDK eval path — it is the prompt every published CUGA AppWorld number was
# produced with, so it is not a place to try adapter-friendly wording.
APPWORLD_SDK_PROMPT = """
# INSTRUCTIONS

A. General instructions:

- Never invent or guess values. For example, if I ask you to play a song, do not assume the ID is 123. Instead, look it up properly through the right API.
- Never leave placeholders; don't output things like "your_username". Always fill in the real value by retrieving it via APIs (e.g., Supervisor app for credentials).
- Always map specific nouns in the user's prompt (e.g., 'friends', 'unread emails', 'recent transactions') to the available parameters or schema fields for each tool (from **Current Available Tools** or from **`find_tools`** output). Never fetch a generalized list if the tool provides a parameter to filter the exact subset the user asked for.

B. App-specific instructions:

- Any reference to my friends, family or any other person or relation refers to the people in my phone's contacts list.
- Always obtain the current date or time, from Python function calls like `datetime.now()`, or from the phone app's get_current_date_and_time API, never from your internal clock.
- For temporal requests, use proper time boundaries, e.g., when asked about periods like "yesterday", use complete ranges: 00:00:00 to 23:59:59.
        """

# Passed to the external adapters (deepagents / openclaw / hermes). Derived from
# APPWORLD_SDK_PROMPT, with sections B and C added: those agents have no
# equivalent of CUGA's pagination and filter handling, so the rules have to be
# stated in the prompt instead.
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
