---
id: output_formatter_single_tool_fact_citation
type: output_formatter
name: P-OF-1 — Single-Tool-Fact Citation
description: Single-fact answers must cite the originating API/tool as the source of the value.
priority: 100
enabled: true
format_type: markdown
triggers:
  - type: natural_language
    target: agent_response
    case_sensitive: false
    operator: or
    value:
      - the response answers a single-fact question (number, name, date, identifier, percentage, ratio, or single-row attribute) that was retrieved from a tool or API call
      - the response cites a value taken directly from a tool result
      - the answer reports a single value retrieved from one or more data-fetching tools
---

# P-OF-1 — Single-Tool-Fact Citation

## Policy

When the assistant answers a question whose answer is a **single fact** — a number, name, date, identifier, percentage, ratio, or single-row attribute — and that fact was obtained from a tool/API call, the assistant must cite the originating tool/API as the source of the value in the final answer.

## Rationale

This policy enforces the standard data-provenance requirement that all analytical or dashboard-style answers carry an audit trail. Across the regulated and reporting-driven contexts this assistant is deployed in — financial dashboards, healthcare analytics, sports statistics, public-development indicators, academic citation, e-commerce reporting — every numeric or factual claim in a response must be traceable to its system of record. Without source attribution, downstream consumers cannot verify the figure, replicate the query, or assess the freshness of the data.

The policy applies uniformly across all dashboard-API and multi-hop-reasoning workflows, regardless of the underlying domain (publications, sports, geography, education, e-commerce, etc.).

## Format requirement

The final answer to a single-fact question must include source attribution in one of the following equivalent forms (the assistant may choose the most natural style for the answer):

1. **Inline citation** — `"<answer>. Source: <tool name>."`
   Example: *"The Adjusted net enrolment rate for Algeria from 1975 to 1980 averages 77.0. Source: `get_adjusted_net_enrolment_avg`."*
2. **Natural-language attribution** — `"Per <data-system name>, <answer>."`
   Example: *"Per the World Development Indicators API, the average is 77.0."*
3. **Parenthetical citation** — `"<answer> (from <tool name>)."`

The cited tool name should be the actual API/tool the assistant invoked to retrieve the value. If multiple tools contributed, cite the tool whose response directly produced the cited value.

## Scope

- **Applies** when the answer's value originates from a single tool/API call.
- **Applies** to single-fact answers in `capability_2_dashboard_apis` and `capability_3_multihop_reasoning` workflows, across all 16 covered domains (authors, books, codebase_comments, hockey, mondial_geo, movie_platform, professional_basketball, soccer_2016, student_loan, talkingdata, beer_factory, college_completion, computer_student, disney, trains, university, world_development_indicators).
- **Does not apply** to general explanations or definitional answers not tied to a specific data retrieval.
- **Does not apply** to aggregated values whose provenance spans multiple tools (those are governed by a separate citation policy if and when one is added).

## Examples

- ✓ "Per the books API, *Hyperion* was published in 1989."
- ✓ "There are 3 ICRA papers from 2012 (source: `get_conference_short_name_most_papers_v1`)."
- ✗ "There are 3 ICRA papers from 2012." (no source attribution — fails policy)
- ✗ "The most popular conference in 2012 was ICRA, based on the available data." (vague — fails policy)

## Reformatting instruction (LLM-facing)

If the agent's draft final answer reports a single fact retrieved from a tool, rewrite it so that the originating tool name (and, where applicable, the result field or data system) is cited in the answer. Use the most natural of the three formats above. Do **not** invent tool names that were not actually called in the current conversation; if the originating tool name is unavailable, cite the data system or capability instead (e.g., "the dashboard API" or "the world development indicators dataset"). Do not change the factual value itself.
