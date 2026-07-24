---
id: output_formatter_groundedness_claim_verification
type: output_formatter
name: P-OF-3 — Groundedness Claim Verification
description: Caveat claims not literally supported by the tool response — unverified attributes, possibly-partial lists, and facts not present in any tool output.
priority: 100
enabled: true
format_type: markdown
triggers:
  - type: natural_language
    target: agent_response
    case_sensitive: false
    operator: or
    value:
      - the response lists multiple items, names, or categories derived from a tool result
      - the response asserts an attribute, category, or property such as origin, type, era, or classification about something retrieved from a tool
      - the response claims to list all, every, or the complete set of something
---

# P-OF-3 — Groundedness Claim Verification

## Policy

When the assistant's answer (a) lists items derived from a tool result, (b) asserts an
attribute/category/property about a retrieved item, or (c) claims completeness
("all", "every", "the full list"), the answer must not claim more than the tool
response actually supports. Three specific failure patterns motivate this policy,
mined from real judge explanations on cap4-300:

1. **Unverified attribute/category claim** — the tool response has no such field,
   but the answer asserts it anyway (e.g. asserting "USA-origin" for a list of car
   names when the tool never returned a country/origin field).
2. **False completeness claim** — the tool result was a partial or paginated list
   (a `top_k`/`n_results`/limit parameter was used, or nothing confirms the result
   is exhaustive), but the answer states it as the complete set, omitting items the
   tool didn't happen to surface.
3. **Fabrication** — the answer states a name, value, or fact that did not appear
   in any tool response for this task, drawn instead from general/prior knowledge.

## Reformatting instruction (LLM-facing)

Important constraint on this reformatting pass: do not delete or change any
factual value from the original response, and do not remove content — only
annotate it. Given that constraint, apply these checks to the agent's draft
response and add an explicit caveat wherever a check fails (do not silently
drop the flagged content; mark it):

1. For each attribute, category, or property asserted about a retrieved item
   (country, origin, type, era, classification, or similar), verify that
   attribute is a literal field in the tool response for that item. If it is
   not, append a caveat immediately after the claim, e.g. `(not confirmed by
   the retrieved data — the tool response did not include this field)`.

2. If the response describes a list as complete, exhaustive, "all", or "every"
   member of a set, and the originating tool call used a result-count limit,
   `top_k`/`n_results` parameter, or pagination, append a caveat, e.g. `(these
   are the items returned by the tool; the result may not be exhaustive)`.

3. For any specific name, value, or fact in the response, check whether it
   appears in the tool responses from this conversation. If it does not, mark
   it clearly, e.g. `(not found in the retrieved tool data)`. Do not remove
   it — flag it so it is visibly distinguished from tool-supported content.

4. If every claim in the response is already directly supported by a literal
   tool response field, and the list is confirmed non-partial, return the
   response unchanged — do not add unnecessary caveats to already-grounded
   answers.
