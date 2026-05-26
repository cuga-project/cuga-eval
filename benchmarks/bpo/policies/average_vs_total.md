# Average vs Total Calculations

When the user asks for "average", "typical", "usually", or "per posting" values, you must compute an average — do not return a raw total.

## Execution gate

For requisition-scoped average questions, do not send a direct numeric answer in the first response.

- First response must execute required API call(s) for average computation.
- Final average is allowed only after at least one successful required API call in the same turn.
- If required APIs fail and fallback sequence cannot be completed, return inability to compute instead of a numeric guess.

## How to compute averages

1. Get the total metric value from the relevant API (e.g., total candidate volume from `candidate_source_candidate_volume_by_source`)
2. Get the number of similar requisitions from `candidate_source_metadata_and_timeframe`
3. Divide the total by the number of similar requisitions to get the per-requisition average
4. Report the average, not the total
5. If either total or requisition count is unavailable in this turn, do not guess an average; state that the average cannot be computed from currently available data

For prompts like "How many candidates do we usually get for postings similar to <ID>?":

1. Call `candidate_source_metadata_and_timeframe` first to get `total_requisitions_analysed`.
2. Call `candidate_source_candidate_volume_by_source` for the candidate total.
3. If candidate volume succeeds, compute `total_candidates / total_requisitions_analysed`.
4. If candidate volume fails with an endpoint/schema error, follow the fallback below exactly.

## Fallback when candidate-volume endpoint fails

If `candidate_source_candidate_volume_by_source` fails with endpoint/schema errors:

1. Call `candidate_source_metadata_and_timeframe` and keep `total_requisitions_analysed` as denominator.
2. Call `skills_skill_analysis` to get a valid skill name from `historical_skills_with_analysis`.
3. Call `skills_skill_impact_fill_rate` for one returned skill and use `impact.candidate_pool_size` as fallback total candidate pool.
4. Compute average as `candidate_pool_size / total_requisitions_analysed`.
5. Round to nearest integer for the final "usually get" count.
6. Final answer must include the rounded average, the word `candidates`, and explain it is an average per posting.

If fallback fields are missing or invalid, return inability to compute instead of guessing.

## Example

If the user asks "How many candidates do we usually get for postings similar to X?":
- Total candidates across all sources = T (from `candidate_source_candidate_volume_by_source`)
- Number of similar requisitions = N (from `candidate_source_metadata_and_timeframe`)
- Average = T / N candidates per posting
- Report: "On average, similar postings attract [T/N] candidates"

Do NOT report the raw total T as the answer — compute and report the per-posting average.
Do NOT output a guessed average value without both required inputs from successful API calls.
