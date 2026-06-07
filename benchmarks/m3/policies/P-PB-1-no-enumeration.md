---
id: playbook_no_enumeration
type: playbook
name: P-PB-1 — No Enumeration When a Single Item Is Asked
description: When the question requests a single item, return only that item; do not enumerate runners-up or alternatives.
priority: 100
enabled: true
triggers:
  - type: natural_language
    target: intent
    case_sensitive: false
    operator: or
    threshold: 0.6
    value:
      - the user asks for a single item (which X, the X with the most/least Y, the top X, the highest, the largest, the smallest)
      - the user asks "which conference", "which company", "which country", "which city", "which solution", "which repository", or another singular "which" form
      - the user asks "what is the X" expecting a single value or single named entity
      - the user asks for "the" specific item (the city of the lake at coordinates Y, the solution path with the highest processed time)
---

# P-PB-1 — No Enumeration When a Single Item Is Asked

## Policy

When the user's question requests a **single item or value** (singular phrasing such as *"which conference"*, *"the city with the most"*, *"the highest"*, *"the top"*, *"the largest"*, *"the smallest"*), the assistant must return only that single item. Listing runners-up, near-misses, alternatives, or "Top N" enumerations the user did not request is prohibited.

## Rationale

This is a basic answer-shape requirement for analytical and dashboard-style responses. When a stakeholder asks "which region had the most sales last quarter?", they expect a single region as the answer — not a leaderboard. Enumerating alternatives:

- Increases the cognitive load on the reader, who has to find the answer inside a list.
- Risks downstream misuse (the reader may pick the wrong row).
- In audit and reporting contexts, dilutes the decision the answer is supposed to support.

## Required behaviour

Before producing the final answer:

1. Detect whether the user's intent is singular ("which X", "the X with the most/least Y", "the highest", "the top", "the largest") or plural ("list all X", "which X meet condition Y", "show me the X's that…").
2. If singular: return only the resolved single item, with the source citation required by [[output_formatter_single_tool_fact_citation]].
3. If plural: enumerate as requested.

Do not include runners-up "for context", do not include "Top 3" when only the top 1 was requested, do not include "the next-best alternative is …".

## Examples

- ✗ Question: *"In the year 2012, which conference had the most papers presented?"*
  ✗ Wrong: *"The conference with the most papers in 2012 was ICRA. The next two were CVPR and NeurIPS."*
  ✓ Right: *"In 2012, ICRA had the most papers presented (source: `get_conference_short_name_most_papers_v1`)."*
- ✗ Question: *"The city of the lake at (-85.35, 11.6)?"*
  ✗ Wrong: *"The city is Granada. Nearby cities include Rivas and Masaya, which also border the lake."*
  ✓ Right: *"The city is Granada (source: `get_city_by_lake_coordinates`)."*
- ✓ Question: *"List all books published in 1995"* — enumeration is requested, so a list is the correct shape.

## Interaction with other policies

This playbook complements [[output_formatter_strip_hedging]] (which strips runner-up clauses *after* the response is drafted) by preventing the planner from collecting the enumeration in the first place. Both can fire on the same case: this one shapes the upstream plan; the OutputFormatter cleans up if any slipped through.
