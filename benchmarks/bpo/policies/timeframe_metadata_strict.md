# Timeframe Metadata Strict Execution

This policy applies when the user asks for the data timeframe, time frame, date coverage, last updated date, or how many similar requisitions were analysed for a requisition.

## Hard first-response rule

Do not answer timeframe or similar-requisition-count questions from memory.
The first assistant response must call `candidate_source_metadata_and_timeframe` before any final natural-language answer.

If `candidate_source_metadata_and_timeframe` has not succeeded in the same turn, do not provide dates or requisition counts.

## Required fields

Read these exact fields from the API response:

- `time_frame_start`
- `time_frame_end`
- `data_last_updated`
- `total_requisitions_analysed`

Do not substitute other date ranges, old benchmark defaults, or guessed counts.

## Required final format

For prompts like "What's the data timeframe for <ID> and how many similar requisitions were analysed?", answer in one sentence:

`The metrics cover <start date> - <end date> and were last updated on <last updated date>. A total of <total_requisitions_analysed> similar requisitions were analysed.`

Render dates in day-month-year form, for example:

- `2022-01-15` -> `15 Jan 2022`
- `2024-06-30` -> `30 Jun 2024`
- `2024-11-20` -> `20 Nov 2024`

Example: If the API returns `2022-01-15`, `2024-06-30`, `2024-11-20`, and `35`, the final answer should include all of:

- `15 Jan 2022`
- `30 Jun 2024`
- `20 Nov 2024`
- `35`
- `requisitions`
