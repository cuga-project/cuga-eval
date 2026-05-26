# Mandatory API Evidence Before Answer

For benchmark questions that require computed values, list membership checks, or source/skill recommendations, do not produce the final answer until the required APIs have been called successfully in the same turn.

## Core rule

If the question is answerable with current APIs, the final answer must be grounded in successful tool outputs from this turn.

- Do not answer from memory.
- Do not return plausible benchmark-looking numbers without tool evidence.
- If a required tool fails and no reliable fallback exists, say the data could not be retrieved.
- For matched computed/list-membership prompts, do not send a direct plain-text final answer before executing required tool calls in this turn.
- For supported requisition-scoped analytics prompts (valid ID present), execute at least one relevant API before any final answer text.
- If zero required APIs succeeded in this turn, do not output numeric claims or yes/no checklist judgments; return a capability/availability limitation instead.

## Precedence across policies

Use this policy to arbitrate supported benchmark questions when another policy gives a looser fallback.

1. If the requested data type is unsupported by the APIs, `API Capability Boundaries` wins.
2. If the request is supported and has the needed requisition context, this evidence gate wins.
3. If a task-specific policy requires a stricter API set than a general policy, use the stricter API set.
4. If a required API fails, follow the required pattern for that prompt class; do not switch to a conflicting looser fallback from another policy.
5. If zero required APIs succeeded for a supported prompt, return only an API-evidence availability limitation and do not answer the business question.

## Required API patterns

Use these minimum API sets before finalizing:

- **Most candidates + effectiveness**:
  - `candidate_source_candidate_volume_by_source`
  - `candidate_source_funnel_conversion_by_source`
  - `candidate_source_total_hires_by_source`
  - `candidate_source_source_recommendation_summary`
  - use `candidate_source_source_recommendation_summary` as supplemental benchmark-aligned evidence, not as the sole source when granular metrics are requested
  - rank strictly by candidate count from `candidate_source_candidate_volume_by_source`
  - report exactly the top 3 sources when at least 3 are returned
  - use `candidate_source_source_recommendation_summary` as the preferred source for hires and offer acceptance rate
  - use this final pattern per source: `<Source>: <count> candidates (<share>%), <hires> hires. Offer acceptance rate: <rate>%.`

- **Best sources to prioritize**:
  - `candidate_source_sla_per_source`
  - `candidate_source_candidate_volume_by_source`
  - `candidate_source_funnel_conversion_by_source`
  - `candidate_source_source_recommendation_summary`
  - final answer must explicitly mention `SLA`; include at least one source to avoid when returned metrics support it
  - if required APIs above were not successfully called in this turn, do not provide a ranked recommendation or numeric source metrics
  - if `candidate_source_candidate_volume_by_source` fails with an endpoint/schema error, do not fail the whole recommendation; use SLA + offer-acceptance + hires from successful source APIs and disclose that candidate volume was unavailable
  - when volume is unavailable, still recommend sources from successful SLA/conversion/summary evidence and name avoid candidates from returned metrics
  - if all source-performance APIs except candidate volume fail, return a capability limitation for ranking in this turn instead of a guessed recommendation

- **Models used / datasets used**:
  - `skills_data_sources_used`
  - final membership decisions must be derived only from `models_involved` / `datasets_used` in that response
  - do not mark unreturned items as used

- **Historically effective skill + data sources used**:
  - `skills_skill_analysis`
  - `skills_data_sources_used`
  - do not answer historical-effectiveness verdicts unless `skills_skill_analysis` succeeded in this turn
  - if the skill correlation is negative, answer that the skill is **not considered effective** and state it had a **negative impact on SLA**
  - include the returned correlation wording; if it is `highly negative impact on SLA`, keep that exact phrase in final text
  - include the data sources from `skills_data_sources_used` when the user asks what informed the analysis

- **Mixed skill-impact + source-avoidance + data-sources prompts**:
  - `skills_skill_impact_sla`
  - `skills_skill_analysis`
  - `skills_data_sources_used`
  - `candidate_source_sla_per_source`
  - `candidate_source_funnel_conversion_by_source`
  - `candidate_source_source_recommendation_summary`
  - do not answer this prompt class unless the required APIs above succeeded in this turn
  - if one required API fails, return an availability limitation for the missing section instead of producing complete checklist verdicts from partial evidence
  - evaluate only user-listed skills and sources
  - `0.0%` SLA delta means no negative impact
  - absent skills are `not present in analysis`, not negative
  - listed sources are `avoid` only when returned metrics show clear underperformance among the listed sources

- **SLA impact + models used + SLA definition**:
  - `skills_skill_impact_sla`
  - `skills_data_sources_used`
  - `candidate_source_definitions_and_methodology`
  - do not answer this prompt class unless all three required APIs above succeeded in this turn
  - if one required API fails, return an availability limitation instead of model names/deltas/definitions

- **SLA definition only**:
  - `candidate_source_definitions_and_methodology`
  - read `definitions.sla`
  - final answer must include the exact returned definition text and must not contain placeholders like `<sla_definition>`

- **Average candidates for similar postings**:
  - `candidate_source_metadata_and_timeframe`
  - `candidate_source_candidate_volume_by_source`
  - if `candidate_source_candidate_volume_by_source` fails with an endpoint/schema error, use the fallback in `Average vs Total Calculations`

- **Data timeframe + similar requisitions analysed**:
  - `candidate_source_metadata_and_timeframe`
  - include `time_frame_start`, `time_frame_end`, `data_last_updated`, and `total_requisitions_analysed` from that response

## Final answer gate

Before sending the final answer, verify:

1. Required APIs were called successfully.
2. Every claimed number/list membership is directly supported by returned payloads.
3. If evidence is missing, return a capability/availability limitation instead of a fabricated answer.
4. Model/dataset names in the answer appear in the corresponding returned arrays unless explicitly marked as not used/not listed.
5. For source-prioritization prompts, every ranked source and numeric metric is backed by successful calls in this turn; otherwise return a limitation.
6. For historical-effectiveness prompts, wording matches `skills_skill_analysis` correlation direction and explicitly mentions SLA impact.
7. For prompts combining models + SLA delta + SLA definition, every model name, delta value, and definition phrase must come from successful APIs in this turn (no placeholders).
8. If no required API succeeded for a supported benchmark prompt, do not output a direct answer. Return only: `I could not retrieve the required API evidence for this request.`
9. Never output placeholder template variables such as `<sla_definition>`, `<models from models_involved>`, or `<Source A>`.

## Combined answer template (for SLA-impact + models + definition prompts)

When the user asks all three in one question, answer in this order:

1. List the models returned in `models_involved` from `skills_data_sources_used` as used.
2. SLA delta with explicit percent format (for example `0.0%`, not just `0`).
3. SLA definition text from `definitions.sla` preserving `Percentage`, `reviewed`, and `SLA window`.

For benchmark-stability on this prompt class, prefer the canonical sentence pattern:

- `'<models from models_involved>' were used. The SLA delta for <skill_name> was <delta_percent>. SLA is defined as '<sla_definition from API>'.`

Formatting requirements:
- keep single quotes around model name(s)
- keep single quotes around the SLA definition text
- keep the explicit wording `The SLA delta for <skill_name> was ...`
- do not invent placeholder model names; use only models returned by `skills_data_sources_used`
- do not use generic fallback placeholders like `ModelA` or `ModelB`

## Timeframe output template (for timeframe + requisition-count prompts)

For prompts like "What's the data timeframe ... and how many similar requisitions were analysed?":

1. Call `candidate_source_metadata_and_timeframe` in the same turn.
2. Do not substitute or infer date ranges/requisition counts.
3. Use this final format:
   - `Timeframe: <time_frame_start> to <time_frame_end>. Data last updated: <data_last_updated>. Total requisitions analysed: <total_requisitions_analysed>.`
