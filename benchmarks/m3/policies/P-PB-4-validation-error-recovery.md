---
id: playbook_validation_error_recovery
type: playbook
name: P-PB-4 — Validation-Error Recovery
description: When a tool returns a parameter-validation error, diagnose from the tool's schema, recover the missing or wrong-typed argument from prior responses, and retry once — instead of abandoning, randomly retrying, or pivoting to a worse tool.
priority: 110
enabled: true
triggers:
  - type: keyword
    target: chat_messages
    case_sensitive: false
    operator: or
    value:
      - Input validation error
      - is a required property
      - is not of type 'integer'
      - is not of type 'string'
      - is not of type 'number'
      - is not of type 'array'
      - validation error
  - type: natural_language
    target: chat_messages
    case_sensitive: false
    operator: or
    threshold: 0.65
    value:
      - a previous tool call returned an input-validation error about a required property being missing
      - a previous tool call returned a type-mismatch error such as "X is not of type 'integer'" or "X is not of type 'string'"
      - a recent tool call failed because of missing or wrong-typed arguments, not because the underlying data is unavailable
---

# P-PB-4 — Validation-Error Recovery

## Policy

When a tool call returns a parameter-validation error — most commonly `"Input validation error: 'X' is a required property"` or `"'Y' is not of type 'integer'"` — the planner must perform a one-time **structured recovery** rather than abandoning the call, randomly retrying, or pivoting to a different (and usually worse) tool.

## Rationale

In analytical and dashboard workflows, the difference between a successful run and a failed run is often a single misformed argument: the right tool was selected, but the planner passed `path=[]` instead of `path="x.sln"`, or omitted a parameter that the API requires. **The data is reachable. The agent just needs to fix the call.**

The typical observed behaviours when CUGA receives a validation error are:

1. Try the same tool with a permuted but still-wrong set of arguments (wastes calls).
2. Pivot to a different tool that looks similar by name (often a worse match for the question).
3. Conclude the data is unavailable and emit a refusal.

All three pollute the trajectory with failed calls without retrieving the data the next step needs — and (importantly for downstream consumers and audit logs) without producing the successful tool responses that establish the answer's provenance. A clean recovery puts the right value back on the table.

## Required behaviour

When a tool result contains a parameter-validation error:

1. **Identify the failing parameter.** Parse the error message to extract:
   - The parameter name (e.g., `'path'`, `'summary'`, `'processed_time'`, `'solution_id'`).
   - The failure kind: *missing required property*, *wrong type* (`is not of type 'integer'`, `is not of type 'string'`, etc.), or *invalid value*.
2. **Recover the value.** Search prior tool responses in the conversation for a field whose key or content matches the failing parameter. Typical sources:
   - A list-returning tool whose single element is the value (e.g., a previous call returned `{"solution_paths": ["x.sln"]}` and the failing parameter is `path` — pass `"x.sln"`).
   - A scalar field with a matching name (e.g., a previous call returned `{"solution_id": 45997}` and the failing parameter is `solution_id`).
   - A typed value that needs coercion (e.g., a string `"636449700980488000"` when the schema requires an integer — coerce to `int(636449700980488000)`).
3. **Retry, once.** Re-invoke the same tool with the recovered value substituted into the failing parameter. Keep the rest of the arguments unchanged.
4. **If the retry also fails**, do **not** retry a third time and do **not** pivot to a generic detail tool to "discover" the value indirectly. Emit a final answer based on the data already in hand, or a clear refusal if no answer is supportable. See [[playbook_no_idempotent_retries]] for the same-call-twice rule (this policy is the explicit exception, because the arguments change).

## Common parameter-recovery patterns

These cover the validation errors seen most often in `capability_2_dashboard_apis` and `capability_3_multihop_reasoning`:

| Validation error | Where to look for the value | What to pass |
| --- | --- | --- |
| `'path' is a required property` | Prior responses with `paths`, `solution_paths`, or `solution_path` field | The single element / first element |
| `'summary' is a required property` | Prior responses with `summary`, `description`, or `body` field | Pass it through |
| `'X_id' is a required property` | Prior `X_id`, `id` (in an object containing X), or a "by name → id" lookup tool's response | The integer ID |
| `X is not of type 'integer'` | Same value is in hand; it's just typed as a string | Coerce to integer |
| `X is not of type 'string'` | Same value is in hand; it's typed as a list or number | First element of list, or `str(number)` |
| `X is not of type 'array'` | A scalar is in hand and the API wants a list | Wrap in a single-element list |

## What this playbook does NOT permit

- Calling the failing tool a third time after the first retry also fails.
- **Manufacturing** a parameter value not present in any prior tool response (do not invent IDs, paths, or timestamps to satisfy the schema).
- Treating "tool not found", "404", "500", or timeout errors as validation errors — those are different recovery scenarios and this policy does not apply.
- Suppressing the validation error from the final answer if no recovery succeeded — be honest about what was retrieved and what wasn't.

## Interaction with other policies

- [[playbook_no_idempotent_retries]] (P-PB-3) forbids a second identical call; this policy is explicitly the *one* permitted retry, because the arguments change between attempts.
- [[playbook_one_composite_tool_no_corroboration]] (P-PB-2) takes precedence in *choosing* the right tool; this policy operates **after** the right tool has been chosen and only needs argument repair.
- [[output_formatter_single_tool_fact_citation]] (P-OF-1) applies normally to the final answer; the recovered (now-successful) call is the citable source.
- This policy has higher priority (110) than the default planning playbooks (100) because it is a corrective action that should pre-empt re-exploration.
