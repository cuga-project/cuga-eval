# Missing Requisition ID vs Unsupported Query

When a question does not include a requisition ID, determine whether providing one would actually help before asking for it.

## Ask for a requisition ID when:

The question is about something the APIs support but needs a specific requisition to look up:
- SLA performance by source
- Candidate volume or hires by source
- Skill analysis or skill impact
- Funnel conversion rates
- Data sources or methodology used
- Metadata and timeframe
- Invalid-ID checks for analytics endpoints (for example candidate funnel by requisition ID)

These all require a requisition ID to return useful results.

## Do NOT ask for a requisition ID when:

The question is about something no API supports regardless of requisition ID:
- Job description text (reading, optimizing, rewriting)
- Time-to-fill metrics (overall or by source)
- Geographic or location-based filtering
- Live requisition status or SLA deadline countdowns
- Stage-by-stage funnel timing (days in each stage)
- Full job-card details (title, location, hiring-manager info)
- Listing or searching across all open requisitions
- Requests phrased as "show me the details of <ID>" when "details" means full job-card fields

For these, explain directly that the current APIs do not support the request. Asking for a requisition ID would be misleading because providing one would not help.

## Decision order

1. Determine whether the requested data type is supported at all.
2. If unsupported, respond with capability boundary immediately.
3. Only if supported, decide whether requisition ID is missing or invalid.

Do not route unsupported "full details" requests into "ID not found" responses.
