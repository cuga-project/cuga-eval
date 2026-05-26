# Invalid ID and Unsupported Details

This policy separates two different failure modes:

- invalid requisition ID for a supported analytics endpoint
- unsupported request for full job-card details

## Invalid ID (supported endpoint)

If the endpoint type is supported (for example funnel metrics by requisition ID) but the provided ID is invalid:

1. clearly state that no job can be found with the provided ID
2. do not silently substitute another ID unless user asks for alternatives

Preferred wording pattern:
- `No job can be found with the ID <ID>.`

## Unsupported full-details request

If the user asks for full requisition details (title, location, hiring manager, job-card details):

1. state that current APIs do not provide full job-card details
2. do not fabricate details
3. do not return source analytics as a replacement for job-card details

## Precedence rule

Check request type first:

- if unsupported data type -> respond unsupported
- else, if supported data type with invalid ID -> respond not found
