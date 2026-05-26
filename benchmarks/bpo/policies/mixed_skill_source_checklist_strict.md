# Mixed Skill and Source Checklist Strict Execution

This policy applies to prompts that simultaneously ask:

- which listed skills negatively impact SLA,
- which listed sources should be avoided based on offer conversion or SLA,
- and which data sources were used to compute the insights.

## Hard first-response rule

Do not answer this prompt class from memory.
The first assistant response must execute the required APIs before any final natural-language answer.

Required APIs before final answer:

- `skills_skill_impact_sla` for every user-listed skill that can be queried directly
- `skills_skill_analysis`
- `skills_data_sources_used`
- `candidate_source_sla_per_source`
- `candidate_source_funnel_conversion_by_source`
- `candidate_source_source_recommendation_summary`

If these APIs have not succeeded in the same turn, do not output checklist verdicts.

## Skill verdict rules

Evaluate every user-listed skill in the order provided.

- If direct SLA impact returns `delta: 0`, answer `no negative impact` and include `0%`.
- If a skill is absent from `skills_skill_analysis`, answer `not present in analysis`.
- Do not infer negative impact for missing or unknown skills.
- Do not omit skills that are not found.

## Source verdict rules

Evaluate every user-listed source in the order provided.

- Use `candidate_source_sla_per_source` for SLA percentage.
- Use `candidate_source_source_recommendation_summary` for offer acceptance rate.
- Mark a listed source as `avoid` only when the returned metrics clearly underperform the other listed sources.

## Data sources rule

Use only `datasets_used` from `skills_data_sources_used`.

## Required final format

Use concise sections with the exact format shown below. Replace the example values with actual API results:

- `Skills: <Skill A>: no negative impact (0% SLA delta); <Skill B>: not present in analysis; <Skill C>: negative impact (-5% SLA delta).`
- `Sources: <Source A>: do not avoid (SLA 92%, offer acceptance 75%); <Source B>: do not avoid (SLA 88%, offer acceptance 71%); <Source C>: avoid (SLA 65%, offer acceptance 45%).`
- `Data sources used: <Dataset 1>, <Dataset 2>, <Dataset 3>, <Dataset 4>.`

Example with fictional data:
- `Skills: Java: no negative impact (0% SLA delta); Machine Learning: not present in analysis; COBOL: negative impact (-8% SLA delta).`
- `Sources: LinkedIn: do not avoid (SLA 92%, offer acceptance 75%); Indeed: do not avoid (SLA 88%, offer acceptance 71%); CareerBuilder: avoid (SLA 65%, offer acceptance 45%).`
- `Data sources used: Candidate performance metrics, Job posting analytics, Interview feedback data, Hiring outcome records.`

Do not output fabricated dataset names like `BPO Recruiting Dataset`, `Skill-Impact Model`, `Source-Performance Model`, or `Candidate Profile Model`.
