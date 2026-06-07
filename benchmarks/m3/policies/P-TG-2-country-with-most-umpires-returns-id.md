---
id: tool_guide_country_with_most_umpires_returns_id
type: tool_guide
name: P-TG-2 — `get_country_with_most_umpires` Returns an ID, Not a Name
description: Clarifies that `get_country_with_most_umpires` returns a numeric country ID and must be chained with a name-lookup tool before the country can be reported by name.
priority: 100
enabled: true
prepend: true
triggers: []
target_tools:
  - get_country_with_most_umpires
---

# P-TG-2 — `get_country_with_most_umpires` Returns an ID, Not a Name

## Policy

This `ToolGuide` enriches CUGA's view of `get_country_with_most_umpires` so the planner knows the response is a country **ID** (an integer key into the country table) and not a country **name**. The planner is instructed to chain the result through `get_country_name_by_id` when the user has asked for a country by name.

## Rationale

When the user asks *"From which country are the most umpires?"*, they expect a country name in the answer (e.g., "England", "Australia"). The composite tool `get_country_with_most_umpires` is the correct entry point — it returns the answer directly — but its response shape is `{country_id: <int>, umpire_count: <int>}`. Without this disambiguation, CUGA tends to either:

- Emit the raw ID as the answer ("The country with the most umpires has ID 1, with 27 umpires."), which is technically true but useless to the reader.
- Conclude that the dataset "does not provide a tool to translate ID 1 into a name" and refuse — wrong, because `get_country_name_by_id` exists and is the obvious next call.

Both behaviours fail an analytics-style reader's basic expectation that a "which country" question is answered with a country name.

## What this ToolGuide adds

The following content is prepended to the tool's stored description so the planner sees it before it sends the response back to the user:

**Return shape:** `{country_id: <int>, umpire_count: <int>}` — the `country_id` is a numeric primary key, NOT a country name.

**Required follow-up when the user asked for a country by name:** chain with `get_country_name_by_id(country_id=<id>)` to translate the ID into a name before producing the final answer.

**Do NOT report the raw `country_id` to the user when they asked for the country itself.** Reporting "ID = 1" to a user who asked "which country" is a policy violation: see [[output_formatter_strip_hedging]] for the answer-shape requirement and [[output_formatter_single_tool_fact_citation]] for the citation requirement.

**Do NOT refuse with "the dataset does not provide a name lookup tool"** — `get_country_name_by_id` exists in the same capability and is the canonical name lookup.

## Scope and limits

This `ToolGuide` only changes CUGA's internal view of the tool description (per the `ToolGuide` policy mechanism). It does **not** modify the upstream MCP tool definition, which is part of the benchmark and remains untouched.

The same pattern (composite tool returns an ID, name lookup lives in a separate tool) likely recurs across the `capability_2_dashboard_apis` and `capability_3_multihop_reasoning` domains. If new "X with most Y returns an ID" cases turn up, add a focused `ToolGuide` per tool rather than broadening this one — narrow, tool-specific guides are easier to debug than a single sprawling rule.
