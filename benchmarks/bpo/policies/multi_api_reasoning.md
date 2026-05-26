# Multi-API Reasoning

When a question asks about multiple dimensions of performance, call the individual specific APIs rather than relying on a single summary endpoint. Summary tools give a quick overview but often lack the granular detail needed for a complete answer.

## Hard Execution Gate

For requisition-scoped source-prioritization questions (for example prompts asking which sources to prioritize), do not provide any ranked sources or numeric source metrics before successful API calls in the same turn.

First-response rule for this prompt class:
- The first assistant response must execute tool-calling code for required source APIs.
- Do not send a direct natural-language recommendation as the first response.
- Only finalize recommendation text after required API results are available in this turn.

Required successful calls before final answer:
- `candidate_source_sla_per_source`
- `candidate_source_candidate_volume_by_source` (or an explicit volume-unavailable fallback statement if this call fails)
- `candidate_source_funnel_conversion_by_source`
- `candidate_source_source_recommendation_summary`

If these calls were not completed successfully in this turn, return an explicit limitation for ranking in this turn instead of a direct recommendation.
If only `candidate_source_candidate_volume_by_source` fails with an endpoint/schema error, continue with the volume-unavailable fallback ranking rather than returning a blanket limitation.

## Source Performance Questions

When comparing or recommending sources across multiple metrics (SLA, volume, conversion, hires), call the specific tools:

- **SLA performance** → `candidate_source_sla_per_source`
- **Candidate volume and share** → `candidate_source_candidate_volume_by_source`
- **Funnel conversion rates** (review %, interview %, offer acceptance %) → `candidate_source_funnel_conversion_by_source`
- **Total hires by source** → `candidate_source_total_hires_by_source`

Do NOT rely solely on `candidate_source_source_recommendation_summary` when the question asks for specific metrics like SLA percentages, offer acceptance rates, or conversion rates. The summary tool is useful for a quick recommendation but does not contain all granular metrics.
Use `candidate_source_source_recommendation_summary` as supplemental benchmark-aligned evidence when the prompt asks for source recommendation, source effectiveness, or sources to avoid; never use it as the only evidence for granular metric questions.

### Fallback when candidate-volume tool is unavailable

If `candidate_source_candidate_volume_by_source` fails or returns invalid payloads:

1. Do not invent candidate counts/shares.
2. Continue with reliable tools:
   - `candidate_source_sla_per_source`
   - `candidate_source_funnel_conversion_by_source`
   - `candidate_source_total_hires_by_source`
   - `candidate_source_source_recommendation_summary`
3. State explicitly that volume counts could not be retrieved from current APIs in this turn.
4. Still provide evidence-backed SLA/conversion/hires conclusions.

## Multi-Source Join Output (Required for "most candidates + effectiveness")

When the user asks which sources provided the most candidates and how effective they were:

1. Fetch candidate volume/share, hires by source, funnel conversion rates, and source recommendation summary.
2. Join results by `source_name`.
3. Rank strictly by candidate volume descending and report exactly the top 3 sources unless fewer than 3 sources are returned.

Required content per reported source:
- source name
- candidate count (and share if available)
- total hires
- offer acceptance rate

Canonical source for each field:
- candidate count and share: `candidate_source_candidate_volume_by_source`
- total hires: prefer `candidate_source_source_recommendation_summary`; use `candidate_source_total_hires_by_source` only if the summary does not provide hires
- offer acceptance rate: prefer `candidate_source_source_recommendation_summary`; use `candidate_source_funnel_conversion_by_source` only if the summary does not provide offer acceptance

Required answer format:
- `<Source>: <count> candidates (<share>%), <hires> hires. Offer acceptance rate: <rate>%.`

Do not respond with only one source or one percentage.
Do not omit `candidate_source_source_recommendation_summary` for this prompt class; it is required as supplemental evidence even when granular APIs also succeed.
Do not rank by hires, SLA, conversion, or recommendation score for this prompt class.

If candidate-volume data is unavailable, do not fabricate "most candidates" rankings; provide only the effectiveness portion from successful tools and clearly mark the missing volume component.

## Recommendation Output (Required for "best sources to prioritize")

When recommending sources to prioritize:

1. Compare SLA, volume, and conversion across sources.
2. Name the recommended sources explicitly.
3. Explicitly mention at least one source to avoid when data supports it (for example low SLA and low conversion).

Answer must explicitly reference SLA and conversion tradeoff; avoid generic rankings without metrics.

When volume is unavailable due tool failure, base recommendation on SLA + conversion + hires, and disclose that volume weighting was omitted because volume data could not be retrieved.
For this fallback, `candidate_source_source_recommendation_summary` is required because it provides benchmark-aligned offer acceptance and hires.

When volume is unavailable, use a normalized weighted fallback ranking:

1. Exclude sources with clearly poor outcomes (`sla_percentage == 0` or `offer_acceptance_rate == 0.0`) from the priority set.
2. Compute a score per remaining source using normalized metrics:
   - `0.5 * SLA_norm + 0.3 * hires_norm + 0.2 * offer_acceptance_norm`
3. Rank by this score and recommend the top 3 sources.
4. Explicitly name at least one excluded low-performing source as "avoid" when such a source exists.

Do not use ad-hoc ranking formulas outside this fallback.

When building the "avoid" set, evaluate low performers from available SLA and offer-acceptance signals even if hires rows are missing for those sources.
Do not restrict avoid detection to only sources present in all joined metric tables.
If any source has `sla_percentage == 0` or `offer_acceptance_rate == 0.0`, do not output `Avoid: None`; explicitly name those sources as avoid candidates.

### Deterministic fallback ranking rule

When using the volume-unavailable fallback scoring formula, keep recommendations aligned to computed rank order.

Selection rule:
1. Sort by computed fallback score descending.
2. Use deterministic tie-breaks only when scores are equal (or near-equal after rounding):
   - higher SLA first
   - then higher offer acceptance
   - then higher hires
3. Select the top 3 after tie-breaks.

Do not forcibly replace a top-scoring source with another source purely for "diversity".

### Recommendation response template (when APIs succeed)

Use this structure:

- `Prioritize: <Source A>, <Source B>, <Source C>.`
- `Evidence: <Source A> (SLA <x>%, offer acceptance <y>%, hires <z>) ...`
- `Avoid: <Source D> (<reason based on returned SLA/conversion metrics>).`

Do not include a source or metric that was not returned by successful APIs in this turn.
If required recommendation APIs fail, do not output a fallback ranking from memory; return an explicit limitation for this turn.

### Recommendation response template (when only volume fails)

Use this structure:

- `Candidate volume could not be retrieved, so this ranking uses SLA, offer acceptance, and hires.`
- `Prioritize: <Source A>, <Source B>, <Source C>.`
- `Evidence: <Source A> (SLA <x>%, offer acceptance <y>%, hires <z>) ...`
- `Avoid: <Source D> (<reason based on returned SLA/conversion metrics>).`

Do not include candidate counts or shares in this fallback.

## Requisition Count and Sample Size Questions

There are two different "counts" in the system — do not confuse them:

- **"How many requisitions were used to compute these metrics"** or **"sample size"** → use `candidate_source_definitions_and_methodology`, which returns the total number of requisitions used for computation across the system
- **"How many similar requisitions were analysed"** → use `candidate_source_metadata_and_timeframe`, which returns the count of requisitions similar to the given one

These return different numbers. Read the question carefully to determine which one is being asked for.

## Top Metrics List Questions

For prompts like "What are the top metrics considered ...":

1. Call `candidate_source_definitions_and_methodology`.
2. Read `top_metrics_considered`.
3. Return the list in canonical order and naming:
   - `SLA %`
   - `First round review %`
   - `Offer acceptance rate`
   - `Candidate volume`
   - `Total hires`

Do not replace these with internal field names such as `jobs_filled_percentage` or `first_round_review_percentage`.

## Skill Analysis Questions

When a question asks about skill impact across multiple dimensions (SLA, fill rate, relevance):

- **SLA impact** → `skills_skill_impact_sla`
- **Fill rate impact** → `skills_skill_impact_fill_rate`
- **Historical effectiveness and statistical analysis** → `skills_skill_analysis`
- **Relevance justification** → `skills_skill_relevance_justification`

If a skill is not found in the analysis results, say so explicitly rather than guessing or inferring a negative impact.

For prompts asking whether a skill was historically effective, use `skills_skill_analysis` as the primary signal for effectiveness.
Do not use `is_relevant` from relevance-justification as the final effectiveness verdict.
If skill-analysis indicates negative SLA impact (including slight negative), answer that the skill was not historically effective.
If skill-analysis indicates positive SLA impact, answer that the skill was historically effective.
If skill-analysis uses a phrase like `highly negative impact on SLA`, preserve that exact phrase in the final answer.
Always include data sources from `skills_data_sources_used` when the user asks what informed the analysis.

For prompts asking which listed sources should be avoided based on low offer conversion or SLA:

1. Evaluate only the user-listed sources.
2. Compare listed sources on returned SLA and offer-conversion metrics.
3. Mark a listed source as "avoid" only when there is clear evidence of underperformance relative to the listed peers.
4. If no listed source is clearly underperforming, state that none of the listed sources should be avoided.

## Multi-Clause Skill + Source Questions

When a question asks for multiple things in one prompt (for example skills impact + sources to avoid + datasets used), answer in fixed sections:

- `Skills:` evaluate each listed skill explicitly:
  - report SLA delta when available
  - if skill is absent from analysis, state "not present in analysis"
- `Sources:` evaluate each listed source explicitly against SLA/conversion criteria before marking "avoid"
- `Data sources used:` list datasets used from `skills_data_sources_used`

Do not infer negative impact for missing skills.
Do not mark a source as "avoid" without evidence from returned metrics.

### Required execution gate for mixed checklist prompts

For prompts that combine all three elements:
- a listed set of skills,
- a listed set of sources,
- and a request for which data sources were used,

you must execute the following APIs in the same turn before finalizing:

- `skills_skill_impact_sla`
- `skills_skill_analysis`
- `skills_data_sources_used`
- `candidate_source_sla_per_source`
- `candidate_source_funnel_conversion_by_source`
- `candidate_source_source_recommendation_summary`

Output requirements for this prompt class:
- enumerate every listed skill and every listed source explicitly
- include numeric evidence when available (for example skill SLA deltas; source SLA and offer-conversion values)
- if one or more required APIs fail, do not answer from memory and do not produce complete checklist verdicts from partial evidence; clearly state which section is unavailable

Completion rules for this prompt class:
- do not collapse output to only negative items; report every user-listed skill and source even when the verdict is "no negative impact" or "do not avoid"
- if `skills_skill_analysis` has not been called successfully in this turn, call it before finalizing the answer
- for source-level offer-acceptance values in this prompt class, prefer `candidate_source_source_recommendation_summary` as the canonical benchmark-aligned signal; call it before final answer and use its percentages when reporting listed-source comparisons
- when `skills_skill_impact_sla` and `skills_skill_analysis` disagree for a listed skill, prefer the `skills_skill_analysis` presence/correlation signal for whether the skill should be treated as "not present in analysis" vs explicitly negative in final wording
- if a listed skill has SLA delta `0`, `0.0`, or `0.0%`, treat it as `no negative impact`, not as negative
- if a listed skill is absent from `skills_skill_analysis`, treat it as `not present in analysis` even if other generic relevance policies would classify it
- for listed-source prompts, ignore the generic recommendation rule that says to name an avoid candidate whenever any source has `sla_percentage == 0` or `offer_acceptance_rate == 0.0`; only evaluate the sources explicitly listed by the user
- do not mark a listed source as `avoid` merely because it is not in the top recommendations; mark `avoid` only when its returned SLA or offer-acceptance clearly underperforms the other listed sources
- preserve user-listed item order for both the skills list and the sources list
- include one explicit verdict per listed item (no grouped shorthand)
  - skills verdicts: `negative impact`, `no negative impact`, or `not present in analysis`
  - source verdicts: `avoid` or `do not avoid`
- include numeric evidence for every listed source verdict using available SLA and offer-acceptance values

### Strict phrase rule for historical effectiveness

For questions that ask whether a skill is historically effective:

- If `skills_skill_analysis` indicates negative SLA impact, answer explicitly with:
  - "not considered effective"
  - "highly negative impact on SLA"

Do not soften this to generic "effective/not effective" without the SLA-impact wording.
For negative-correlation cases, final text must include the exact substring: `highly negative impact on SLA`.

### Historical effectiveness response template

When `skills_skill_analysis` shows negative correlation:

- `<Skill name> was not considered effective and showed a negative impact on SLA (<correlation text>).`
- `Data sources used: <datasets_used list>.`

When `skills_skill_analysis` shows positive correlation:

- `<Skill name> was considered historically effective with a positive impact on SLA (<correlation text>).`
- `Data sources used: <datasets_used list>.`
