# Pre-registration: read every record at the start (`sources.listing`), 2026-11-08

Written before the live run.

## Why

The fresh3 failure analysis found the largest cause for both models: the agent never read the procedure (65 of 161
traced failures). The policy layer's discovery runs 8 keyword searches on Gmail and Slack only and never reads
Google Sheets, which hold data in 33 of the 35 tasks.

## Change

- `polisys` branch `feat/list-all-sources`: `sources.listing`. At the request the layer reads every record the host
  lists. A model (the intake model) labels each record rule, data or unsure. Rule records, unsure records, records
  without a label, and every table (worksheet) go to the normal extraction. Records the listing read are not sent
  again when the agent reads them.
- cuga-eval: `adapters/automationbench_listing.py` lists every record through the agent's own read tools, on a copy of
  the world. The run's world and score do not change (tested).
- Profile `experiments/automationbench-gptoss-b4tf-list`: B4T-F with `discovery: false, listing: true`.

## Offline check (fresh3, 35 tasks; done before this file)

Gold labels: Opus 5.5 labelled which listed records state rules, from the request and the records only (no grader).
128 rule records; every quote was checked as copied. Labels were not checked by hand.

| Method at task start | Recall, mean over 33 tasks with rules | Tasks with every rule found | Records sent to extraction |
|---|---|---|---|
| Today: keyword searches, then policy words or Kev | 29.1% | 5/33 | 30 |
| Listing + Kev | 65.7% | 14/33 | 56 |
| Listing + gpt-oss labels | 88.0% | 22/33 | 211 |
| Listing + gpt-oss labels + every worksheet (this change) | 95.4% | 28/33 | 251 |
| Listing, send everything | 100% | 33/33 | 1562 |

Listing coverage (text of 4+ words reached through the read tools): 100% for Gmail, Sheets, Salesforce, Calendar and
most helpdesk apps over all 600 tasks; Slack 98.1%. DocuSign templates, Twilio, Buffer, Mailchimp and Airtable need
IDs that no listing tool gives; the agent cannot list them either.

## Live run

- Set: `ab-policy-types-fresh3` (35 tasks). It is a tuning set (its failures were traced), so this run informs the
  design; the claim needs the fresh4 frozen run.
- Agent `aws/gpt-oss-120b`, 3 trials, cache off (proxy 8801), cuga-eval `policy-eval` with the clock fix on, snapshot
  `polisys-969bf8f` (polisys `feat/list-all-sources`) for all arms.
- Arms, all with `AB_AGENT_RULES=1`:
  - R: profile `baseline` (no policy system)
  - P: `automationbench-gptoss-b4tf` (keyword discovery)
  - L: `experiments/automationbench-gptoss-b4tf-list` (listing)
- Haiku 5.5 runs the same three arms only if gpt-oss passes rules 1-3.

## Decision rule

SE = `sqrt(2 * mean per-task variance / trials / tasks)` from arm R; paired per task.

1. Mechanism: a `listing` audit record in at least 95% of L runs. Otherwise the run is void.
2. Gain: L - P partial >= +2.0 points, and L - P strict >= -2 x SE.
3. No-harm (AGENTS.md): L - R >= -2 x SE for strict and for partial; guardrail breaks of L may not exceed R by more than
   2 x their SE.
4. If 1-3 hold, listing goes into the fresh4 frozen run. If 2 fails and 3 holds, listing stays off and the result is
   reported. If 3 fails, listing is not supported for that model.

Report the paired difference with a 95% bootstrap interval and the sign-flip p-value next to the no-harm check.
