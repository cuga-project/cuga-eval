# Enumerated Checklist Answers

When a question lists multiple items (models, datasets, skills, sources), answer each listed item explicitly.

## Missing ID guard (apply first)

Before enumerating items, first check whether the question requires a requisition ID.

If requisition-scoped analytics are required and the ID is missing:
- ask for the requisition ID
- do not invent values
- do not output per-item judgments from memory

Only enumerate item-by-item after the requisition context is available (or when the request is clearly unsupported by API capability).

## Execution gate for requisition-scoped checklists

For requisition-scoped checklist prompts (models/datasets/skills/sources), do not send a direct natural-language final answer as the first response.

- First response must execute required API call(s) for that checklist class.
- Final checklist judgments are allowed only after at least one successful required API call in the same turn.
- If required APIs fail, return an availability limitation instead of inferred checklist judgments.

## Required format behavior

For each listed item:

- state whether it is present/used/effective
- do not omit any item from the user list
- avoid collapsing to a partial summary

For model/dataset checklist questions, verify membership against API-returned arrays in the same turn:

- models: `models_involved`
- datasets: `datasets_used`

Do not infer "not present" unless the item is actually absent from the returned list.

For model-checklist prompts, call `skills_data_sources_used` first and map each listed model to:
- `used` if present in `models_involved`
- `not used` if absent from `models_involved`

Do not return bulk shortcuts like "all present" or "all absent" without explicit per-item checks.
Do not finalize model membership answers unless `skills_data_sources_used` succeeded in the same turn.
Do not infer model usage from model-name similarity alone; require exact membership in returned `models_involved`.

For benchmark stability on model-checklist prompts, use this delimiter format, listing items in the order the user asked them:
- `<Item A>: used; <Item B>: not used; <Item C>: used`

For dataset-checklist prompts, call `skills_data_sources_used` first and map each listed dataset to:
- `used` if present in `datasets_used`
- `not listed` if absent from `datasets_used`

Do not convert unknown datasets into `present/used` by default.
Do not finalize dataset membership answers unless `skills_data_sources_used` succeeded in the same turn.

## Examples of applicable question types

- "Were these models used: A, B, C?"
- "Were these datasets used: X, Y, Z?"
- "Which of these skills negatively impact SLA: ...?"
- "Which of these sources should be avoided: ...?"

If an item is absent in returned analysis, say so explicitly (for example "not listed" or "not present in analysis").

## Source/skill mixed checklist guard

For prompts that list both skills and sources:

1. Evaluate each listed skill explicitly from `skills_skill_impact_sla` / `skills_skill_analysis`.
2. Evaluate each listed source explicitly from `candidate_source_sla_per_source` and `candidate_source_funnel_conversion_by_source`.
3. Use `candidate_source_source_recommendation_summary` as supplemental benchmark-aligned source evidence when reporting offer-conversion comparisons.
4. Only mark a source as "avoid" when returned metrics support it.
5. If one required API fails, do not fabricate missing numbers or produce complete checklist verdicts from partial evidence; state the unavailable section instead.
6. If all required APIs succeed, include every listed item in the final answer, even when the result is "no negative impact" or "do not avoid".
7. When metrics are available, include the relevant numeric evidence for each listed item (for example SLA delta for skills; SLA and offer-conversion values for sources).
8. Preserve the user-provided item order in output for both skill and source lists.
9. Use exactly one verdict per listed item; do not compress multiple items into a single combined verdict sentence.

Conflict rules for mixed skill/source prompts:

- Evaluate only the items explicitly listed by the user.
- A skill with SLA delta `0`, `0.0`, or `0.0%` has `no negative impact`.
- A skill missing from `skills_skill_analysis` is `not present in analysis`, not negative.
- A source missing from recommendation summaries is not automatically `avoid`; use returned SLA/conversion evidence if available, otherwise state that evidence is unavailable.
- Do not apply generic source-prioritization rules that require naming an avoid candidate unless the listed-source evidence supports it.
- Do not mark a listed source as `avoid` merely because another unlisted source performs better.
