# CUGA Policies for BPO Benchmark

This document tracks all policies and their measured impact on evaluation scores.

## Measured Results (5 runs each, clean Milvus DB)

### Per-run scores

```text
Config          Run1 Run2 Run3 Run4 Run5   Mean   pass@5  pass^5
──────────────────────────────────────────────────────────────────
No policies       12   13   14   13   12   12.8    15/26   10/26
5 policies        21   23   22   21   20   21.4    23/26   19/26
```

### Aggregate metrics

| Metric | No Policies | 5 Policies | Delta |
|---|---|---|---|
| Mean score | 12.8/26 (49.2%) | 21.4/26 (82.3%) | +33.1pp |
| pass@5 | 15/26 (57.7%) | 23/26 (88.5%) | +30.8pp |
| pass^5 | 10/26 (38.5%) | 19/26 (73.1%) | +34.6pp |

### Per-task breakdown

```text
Task     NoPol  @5 ^5  |  Pol   @5 ^5  Delta  Category
────     ─────  ── ──  |  ───   ── ──  ─────  ────────
   1      5/5   Y  Y   |  4/5   Y  -     -1   regression (flaky)
   2      5/5   Y  Y   |  5/5   Y  Y      =   stable pass
   3      1/5   Y  -   |  0/5   -  -     -1   regression
   4      5/5   Y  Y   |  5/5   Y  Y      =   stable pass
   5      5/5   Y  Y   |  5/5   Y  Y      =   stable pass
   6      0/5   -  -   |  3/5   Y  -     +3   IMPROVED (flaky)
   7      0/5   -  -   |  0/5   -  -      =   stable fail
   8      5/5   Y  Y   |  5/5   Y  Y      =   stable pass
   9      0/5   -  -   |  5/5   Y  Y     +5   IMPROVED (Policy #3)
  10      5/5   Y  Y   |  5/5   Y  Y      =   stable pass
  11      4/5   Y  -   |  5/5   Y  Y     +1   IMPROVED (stabilized)
  12      3/5   Y  -   |  5/5   Y  Y     +2   IMPROVED (Policy #2)
  13      5/5   Y  Y   |  5/5   Y  Y      =   stable pass
  14      4/5   Y  -   |  5/5   Y  Y     +1   IMPROVED (Policy #2)
  15      0/5   -  -   |  1/5   Y  -     +1   IMPROVED (flaky)
  16      0/5   -  -   |  5/5   Y  Y     +5   IMPROVED (Policy #1)
  17      5/5   Y  Y   |  5/5   Y  Y      =   stable pass
  18      5/5   Y  Y   |  5/5   Y  Y      =   stable pass
  19      0/5   -  -   |  5/5   Y  Y     +5   IMPROVED (Policy #1)
  20      5/5   Y  Y   |  5/5   Y  Y      =   stable pass
  21      0/5   -  -   |  4/5   Y  -     +4   IMPROVED (Policy #1, flaky)
  22      0/5   -  -   |  5/5   Y  Y     +5   IMPROVED (Policy #1)
  23      0/5   -  -   |  5/5   Y  Y     +5   IMPROVED (Policy #1)
  24      2/5   Y  -   |  5/5   Y  Y     +3   IMPROVED (Policy #1/#2)
  25      0/5   -  -   |  0/5   -  -      =   stable fail
  26      0/5   -  -   |  5/5   Y  Y     +5   IMPROVED (Policy #4)
────     ─────  ── ──  |  ───   ── ──
TOTALS         15  10  |       23  19
```

---

## Policy #1: API Capability Boundaries [IMPLEMENTED]

**Type:** Playbook
**File:** `api_capability_boundaries.md`
**Triggers:** Keywords + natural language (threshold 0.65, priority 90)

Teaches the agent to recognize when the available APIs cannot answer a question.
Lists what the APIs can and cannot do, and instructs the agent to decline
out-of-scope requests directly instead of asking for a requisition ID or calling
irrelevant tools.

**Failure pattern addressed:** The agent would ask for a requisition ID or call
random APIs for queries about job descriptions, time-to-fill, geography
filtering, SLA deadlines, funnel timing, and job-card details — none of which
are supported by any API.

**Tasks fixed:** 16, 19, 21, 22, 23 (all 0/5 → 4-5/5)

---

## Policy #2: Error-Prone Tool Warnings [IMPLEMENTED]

**Type:** Tool Guide
**File:** `error_tool_warnings.md`
**Target:** 19 error-prone tools (prepended to their descriptions)

Prepends a warning to the descriptions of the 19 known-unreliable tools (those
that return 503s, schema violations, type mismatches). Steers the agent toward
the 13 reliable core tools and teaches it to recover gracefully when an error
tool is called.

**Failure pattern addressed:** The agent would call tools like `funnel_status`
(503 error), `model_registry` (wrong data), or `source_recommendation_summary`
(incomplete shortcut) instead of using the correct granular APIs.

**Tasks fixed:** 12 (3/5 → 5/5), 14 (4/5 → 5/5), 24 (2/5 → 5/5)

---

## Policy #3: Multi-API Reasoning [IMPLEMENTED]

**Type:** Playbook
**File:** `multi_api_reasoning.md`
**Triggers:** Keywords + natural language (threshold 0.65, priority 80)

Instructs the agent on when to call multiple specific APIs instead of relying on
a single summary endpoint. Provides a mapping from question type to the correct
specific tool, and clarifies the difference between "total requisitions used for
computation" (`definitions-and-methodology`) vs "similar requisitions analysed"
(`metadata-and-timeframe`).

**Failure pattern addressed:** The agent would use the summary shortcut tool for
multi-metric questions, or confuse which API returns the requisition count.

**Tasks fixed:** 9 (0/5 → 5/5 — now correctly returns 1047 from
`definitions-and-methodology` instead of 40 from `metadata-and-timeframe`)

---

## Policy #4: Average vs Total Calculations [IMPLEMENTED]

**Type:** Playbook
**File:** `average_vs_total.md`
**Triggers:** Keywords + natural language (threshold 0.65, priority 70)

Teaches the agent that when the user asks for "average" or "typical" values, it
must compute a per-requisition average by dividing the total by the count of
similar requisitions, rather than returning the raw total.

**Failure pattern addressed:** The agent would return the total candidate count
(2913) when asked "how many candidates do we usually get" instead of computing
the average (2913 / 40 = ~73).

**Tasks fixed:** 26 (0/5 → 5/5)

---

## Policy #5: Missing Requisition ID vs Unsupported Query [IMPLEMENTED]

**Type:** Playbook
**File:** `missing_req_id_vs_unsupported.md`
**Triggers:** Keywords + natural language (threshold 0.60, priority 85)

Helps the agent distinguish between "I need a requisition ID to answer this"
(answerable but missing context) vs "This can't be answered regardless of
requisition ID" (unsupported by any API). Reinforces Policy #1 for edge cases.

**Failure pattern addressed:** The agent would ask for a requisition ID even
when the question was about something no API supports.

**Tasks fixed:** Overlaps with Policy #1; provides reinforcement for edge cases.

---

## Remaining Failing Tasks

| Task | Pass rate (no pol) | Pass rate (5 pol) | Issue | Notes |
|---|---|---|---|---|
| 1 | 5/5 | 4/5 | Flaky regression | May be LLM non-determinism |
| 3 | 1/5 | 0/5 | Agent provides incomplete source data | Regression — policies may over-constrain |
| 7 | 0/5 | 0/5 | LLM judge scores correct behavior as 0 | Judge issue, not agent issue |
| 15 | 0/5 | 1/5 | Calls too few APIs, misidentifies negative-SLA skills | Complex multi-part question |
| 25 | 0/5 | 0/5 | Calls error tool for invalid requisition ID instead of declining | Edge case not caught by Policy #1 triggers |
