---
id: playbook_no_idempotent_retries
type: playbook
name: P-PB-3 — No Idempotent Retries
description: Do not re-invoke a tool that returned a deterministic value with the same arguments during the same turn.
priority: 100
enabled: true
triggers:
  - type: natural_language
    target: intent
    case_sensitive: false
    operator: or
    threshold: 0.5
    value:
      - any question whose answer is retrieved by a deterministic data-fetching tool (lookup, count, average, sum, ratio, attribute fetch)
      - a single-fact or single-list question that resolves via one tool call
---

# P-PB-3 — No Idempotent Retries

## Policy

Once a tool has returned a non-error value for a given set of arguments during a turn, the assistant must not re-invoke that same tool with the same arguments to re-fetch, verify, or "double-check" the value.

## Rationale

The data-fetching tools in this benchmark and in the standard analytics/dashboard contexts are **deterministic**: calling `get_repo_stars(solution_id=83855)` twice in the same minute returns the same value. Re-invoking such a tool:

- Adds latency to the final answer with zero information gain.
- Costs LLM tokens (the agent has to parse the duplicate response and explain why it called the tool a second time).
- For paid APIs, costs money.
- Creates a misleading audit trail in which the system-of-record appears to have been queried multiple times for a single decision.

This policy is the runtime guard. The planner-level [[playbook_one_composite_tool_no_corroboration]] addresses a related but distinct anti-pattern (calling *different* tools to corroborate); P-PB-3 specifically addresses calling the *same* tool repeatedly.

## Required behaviour

For each turn, the assistant must:

1. Maintain awareness of the (tool_name, arguments) pairs already called in this turn.
2. If the planner or reflection step proposes a tool call with the same (tool_name, arguments) as one already executed and the prior result was not an error, **skip the call** and re-use the prior result.
3. If the planner proposes the same tool with **different arguments**, that is allowed (it is not the same call).
4. Once the answer is derivable from the calls already made, emit the final answer and end the turn.

## Exceptions

This policy does **not** apply when:
- The prior call returned an error or a transport-level failure (HTTP 5xx, timeout, schema-validation error). Retrying after an error is allowed.
- The prior call was made with materially different arguments (different filter, different time window, different ID).
- The user explicitly asks for a re-fetch ("re-query the API and confirm the current value").
- The tool is documented as non-deterministic (e.g., a tool that returns a sampled or time-of-day-dependent value). None of the M3 capability_2_dashboard_apis or capability_3_multihop_reasoning tools meet this criterion.

## Examples

- ✗ Question: *"What are the solution ids for repositories with 238 forks?"*
  ✗ Wrong: *Call `get_solution_ids_by_repo_forks(forks=238)` → ["62258", "258160"]. Then, "to verify", call `get_repo_forks(solution_id=62258)`, `get_repo_forks(solution_id=258160)`, then again `get_solution_ids_by_repo_forks(forks=238)`.*
  ✓ Right: *Call `get_solution_ids_by_repo_forks(forks=238)` → ["62258", "258160"]. Report: *"The solution ids are 62258 and 258160 (source: `get_solution_ids_by_repo_forks`)."**
- ✗ Wrong: *Calling `get_average_processed_time(url=X)` twice in the same turn to "confirm" the average.*
  ✓ Right: *Single call; emit result.*

## Interaction with other policies

- [[playbook_one_composite_tool_no_corroboration]] forbids calling redundant **different** tools to corroborate; this policy forbids calling the **same** tool twice with the same arguments.
- [[output_formatter_strip_hedging]] cleans up "to verify, I also ran the call again" prose if any slips through.
