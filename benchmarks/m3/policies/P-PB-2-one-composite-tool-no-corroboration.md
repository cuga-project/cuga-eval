---
id: playbook_one_composite_tool_no_corroboration
type: playbook
name: P-PB-2 — One Composite Tool, No Corroboration
description: For percentage, ratio, and proportion questions, use the single endpoint that returns the composite value directly; do not also call the raw component tools to corroborate it.
priority: 100
enabled: true
triggers:
  - type: natural_language
    target: intent
    case_sensitive: false
    operator: or
    threshold: 0.6
    value:
      - the user asks for a percentage (forks-to-stars %, conversion rate, success rate, ratio, proportion, share)
      - the user asks for a ratio of two quantities (X-to-Y ratio, X per Y, X over Y)
      - the user asks for an aggregate metric (average, mean, total) that a single endpoint returns directly
      - the user asks for a "percentage difference" or "% change" or "% of total" or similar composite metric
  - type: keyword
    target: intent
    case_sensitive: false
    operator: or
    value:
      - percentage
      - "%"
      - ratio
      - proportion
      - share of
      - per cent
      - rate of
      - conversion rate
---

# P-PB-2 — One Composite Tool, No Corroboration

## Policy

When a single endpoint returns the composite metric the user asked for (percentage, ratio, proportion, share, aggregate), the assistant must:

1. Call only that endpoint.
2. Report the returned value (subject to [[output_formatter_single_tool_fact_citation]] for source attribution).

The assistant must **not** also call the raw component endpoints (the numerator and denominator tools) to re-derive or "double-check" the composite value.

## Rationale

This policy enforces two related principles from analytical and dashboard reporting:

1. **Source-of-truth discipline.** When the data system exposes a tool that returns the composite metric directly, that tool is the source of truth. Re-deriving the value from component tools introduces consistency risk (numerator and denominator may be computed over different time windows, populations, or filters than the composite tool uses) and produces an answer that is *less trustworthy*, not more.
2. **Tool-call frugality.** Each extra tool call costs LLM tokens, latency, and (for paid APIs) money. When the answer is already in hand from the composite tool, additional calls add no value.

## Required behaviour

For percentage / ratio / proportion / aggregate questions:

1. **Identify the composite tool first** — the tool whose name and description directly match the requested metric (e.g., `get_forks_to_stars_percentage`, `get_conversion_rate`, `get_average_X`, `get_X_per_Y`).
2. **Call only that tool** with the appropriate parameters.
3. **Report the returned value** with the source citation required by P-OF-1.

Explicitly forbidden:
- Calling `get_repo_forks` and `get_repo_stars` separately, then dividing, **when** `get_forks_to_stars_percentage` exists.
- Calling `get_total_X` and `get_count_X` separately to compute an average, **when** `get_average_X` exists.
- Re-running the composite tool with the same arguments to "verify" the value.

## Exceptions

This policy does **not** apply when:
- No composite tool exists for the requested metric (then the assistant must compute it from components — that is the only path).
- The user explicitly asks for the component values *as well as* the composite ("give me the forks count, stars count, and forks-to-stars percentage").
- The composite tool returned a clearly invalid value (HTTP error, type-validation failure) — then the assistant may fall back to components and must say so.

## Examples

- ✗ Question: *"What is the forks-to-stars percentage for solution 104086?"*
  ✗ Wrong: *Call `get_forks_to_stars_percentage(solution=104086)` → 0.00%. Then also call `get_repo_forks` and `get_repo_stars` to "double-check". Then report `0 forks / 1 star = 0.00%, confirmed by `get_forks_to_stars_percentage`.*
  ✓ Right: *Call `get_forks_to_stars_percentage(solution=104086)` → 0.00%. Report: *"The forks-to-stars percentage for solution 104086 is 0.00% (source: `get_forks_to_stars_percentage`)."**
- ✗ Question: *"Average net enrolment rate for Algeria 1975–1980?"*
  ✗ Wrong: *Call `get_average_enrolment_rate(country=Algeria, start=1975, end=1980)` → 77.0. Then also call `get_enrolment_rate(year=1975)`, …, `get_enrolment_rate(year=1980)` and average them yourself.*
  ✓ Right: *Call `get_average_enrolment_rate(country=Algeria, start=1975, end=1980)` → 77.0. Report once with citation.*

## Interaction with other policies

- [[playbook_no_idempotent_retries]] forbids calling the same tool with the same arguments twice; this policy forbids calling **redundant** tools after a composite tool has already answered.
- [[output_formatter_single_tool_fact_citation]] handles the source-citation requirement for the single composite tool's value.
