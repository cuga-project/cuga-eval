# Verbatim Definitions and Dates

For definition and timeframe questions, prefer faithful phrasing from the API response over generic paraphrases.

## Definitions

When asked for a metric definition:

1. Use `candidate_source_definitions_and_methodology`.
2. Return the definition text with key terms preserved.

Do not replace key wording with broad generic text if exact terminology is available.

For SLA-definition questions, return the verbatim `definitions.sla` field from the API response, preserving key terms such as:
- `reviewed`
- `SLA window`
- any example window timing the API provides (e.g., `48 hours`)

Include the word `Percentage` (capital P) exactly as it appears in the API response — do not replace it with vague synonyms.

Preferred SLA definition format:
- `SLA is defined as '<definitions.sla>'.`

Avoid paraphrasing: return the definition text as the API provides it.
Do not output placeholders such as `<sla_definition>` or `<verbatim sla_definition from API>`.

### SLA definition field mapping

The API returns SLA wording at `definitions.sla`, not at a top-level `sla_definition` field.

For SLA-definition prompts:

1. Call `candidate_source_definitions_and_methodology`.
2. Read `definitions.sla`.
3. Return: `SLA is defined as '<definitions.sla>'.`
4. If `definitions.sla` exists, never say the SLA definition was not found.

Example when the API returns `Percentage of candidates reviewed within the defined SLA window (e.g., 48 hours)`:
- `SLA is defined as 'Percentage of candidates reviewed within the defined SLA window (e.g., 48 hours)'.`

### Definition-only guard for direct SLA-definition prompts

When the prompt asks only for the SLA definition:

1. Use `candidate_source_definitions_and_methodology` only.
2. Return only the SLA definition sentence from `definitions.sla`.
3. Do not append per-source SLA percentages or any other metrics unless explicitly requested.

## Timeframes and update dates

When asked for timeframe coverage and update recency:

1. Use `candidate_source_metadata_and_timeframe`.
2. Include:
- `time_frame_start`
- `time_frame_end`
- `data_last_updated`
- `total_requisitions_analysed` (when asked)

Prefer explicit, absolute dates in the final answer.

For timeframe questions like "What's the data timeframe ... and how many similar requisitions were analysed?":

1. Use `candidate_source_metadata_and_timeframe` only.
2. Include all four fields when available:
   - `time_frame_start`
   - `time_frame_end`
   - `data_last_updated`
   - `total_requisitions_analysed`
3. Render dates in explicit human-readable form (e.g., `1 Jan 2024`, `31 Dec 2024`).
4. Do not substitute different date ranges or requisition counts.

For `data_last_updated`, preserve the returned date and also render it in day-month-year form when possible.
For example, if the API returns `2024-08-15`, include `15 Aug 2024` in the final answer.
