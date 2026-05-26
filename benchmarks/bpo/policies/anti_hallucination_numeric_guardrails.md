# Anti-Hallucination Numeric Guardrails

For requisition analytics questions, do not output concrete numbers unless they come from APIs called in the current turn.

## Rules

1. If the question is supported and requires requisition-scoped metrics, call the relevant APIs first.
2. If no successful relevant API call is available, do not guess or synthesize plausible values.
3. If a required API call fails and no reliable fallback endpoint exists, state that the data cannot be retrieved from current APIs.

## Applies strongly to

- source comparison metrics (counts, conversion rates, hires)
- timeframe and requisition counts
- skill impact deltas
- averages derived from totals/counts

## Prohibited behavior

- invented percentages, counts, or date ranges
- replacing missing API data with generic benchmark-like numbers
- confidently returning full numeric answers without any data retrieval step
