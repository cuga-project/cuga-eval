---
id: tool_guide_mountain_count_most_populous_country
type: tool_guide
name: P-TG-1 — `get_mountain_count_most_populous_country` Disambiguation
description: Clarifies that `get_mountain_count_most_populous_country` is the right tool when the user asks for mountains in the country with the largest/greatest/most population.
priority: 100
enabled: true
prepend: true
target_tools:
  - get_mountain_count_most_populous_country
triggers: []
---

# P-TG-1 — `get_mountain_count_most_populous_country` Disambiguation

## Policy

This `ToolGuide` enriches CUGA's view of the `get_mountain_count_most_populous_country` tool description so the shortlister surfaces it for the right intents and so the planner does not compose it with unrelated geography tools.

## Rationale

When the user asks *"How many mountains are in the most populous country?"* (or a paraphrase such as *"the country with the largest population"*, *"the country with the most people"*, *"the country with the greatest population"*), the right tool is the single composite endpoint `get_mountain_count_most_populous_country`. The CUGA shortlister can miss this because the user's phrasing uses *"most populous"* / *"largest population"* while the tool name encodes the same concept differently.

When the shortlister misses the composite tool, CUGA tends to compose two unrelated tools (a population-ranking tool plus a mountain-counting tool keyed by country), which:

- Costs extra LLM calls and tool calls.
- Produces a brittle chain that can fail if the population-ranking tool's country naming does not match the mountain-counting tool's country naming.
- Risks a wrong answer if the population tool returns a list of "most populous" countries while the question asks for *the* single country.

## What this ToolGuide adds

The following content is prepended to the tool's stored description so that the shortlister's embedding match and the planner's prompt both see it:

**Use this tool when the user asks for:**
- The mountain count of the most populous country
- The number of mountains in the country with the largest, greatest, or highest population
- "How many mountains" combined with "most people", "biggest population", "most populated country"

**Do NOT compose with city-population, country-population-ranking, or per-country mountain-listing tools.** This single tool returns the answer directly.

**Returns:** a single integer — the count of mountains in the country with the largest population.

## Scope and limits

This `ToolGuide` only changes CUGA's internal view of the tool's description (per the `ToolGuide` policy mechanism). It does **not** modify the upstream MCP tool definition, which is part of the benchmark and remains untouched.

The policy is narrow on purpose: it targets exactly one tool (the one CUGA missed in the analyzed PF case). If the same disambiguation pattern recurs for other composite tools, additional `ToolGuide` policies should be added for each rather than broadening this one.
