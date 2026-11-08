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

## Result: gpt-oss (written after the run, 2026-11-08)

105 runs per arm (35 tasks x 3 trials). SE from arm R; 2 x SE = 4.67 (strict), 4.11 (partial), 0.23 (guardrail breaks).

| Arm | Strict | Partial | Guardrail breaks per task |
|---|---|---|---|
| R: no policy system | 9.5% | 40.0% | 0.76 |
| P: keyword discovery | 12.4% | 52.8% | 0.67 |
| L: listing | 23.8% | 58.0% | 0.33 |

| Paired, per task | Diff | 95% CI | Tasks up / down | p |
|---|---|---|---|---|
| L - P strict | +11.4 | +2.9 .. +21.9 | 9 / 2 | 0.036 |
| L - P partial | +5.2 | -2.3 .. +12.7 | 18 / 16 | 0.182 |
| L - P guardrail breaks | -0.33 | -0.8 .. +0.1 | 5 / 15 | 0.150 |
| L - R strict | +14.3 | +5.7 .. +24.8 | 9 / 0 | 0.004 |
| L - R partial | +18.0 | +9.8 .. +26.6 | 21 / 7 | <0.001 |
| L - R guardrail breaks | -0.43 | -0.7 .. -0.2 | 4 / 16 | 0.002 |

Decision rule: 1 mechanism 105/105 L runs: pass. 2 gain: partial +5.2 >= +2.0 and strict +11.4 >= -4.67: pass (the
partial gain alone is not significant; the strict gain is). 3 no-harm vs R: pass on strict, partial and guardrail
breaks. Listing goes into the fresh4 frozen run for gpt-oss; Haiku 5.5 runs the same three arms. fresh3 is a tuning set,
so these numbers are in-sample. Cost $14.05.

## Result: Haiku 5.5 (written after the run, 2026-11-08)

105 runs per arm. 2 x SE = 6.02 (strict), 4.33 (partial), 0.13 (guardrail breaks).

| Arm | Strict | Partial | Guardrail breaks per task |
|---|---|---|---|
| R: no policy system | 44.8% | 76.9% | 0.26 |
| P: keyword discovery | 38.1% | 75.2% | 0.19 |
| L: listing | 41.0% | 74.7% | 0.11 |

| Paired, per task | Diff | 95% CI | Tasks up / down | p |
|---|---|---|---|---|
| L - P strict | +2.9 | -6.7 .. +12.4 | 7 / 4 | 0.706 |
| L - P partial | -0.5 | -6.6 .. +5.5 | 13 / 9 | 0.882 |
| L - R strict | -3.8 | -13.3 .. +4.8 | 3 / 5 | 0.548 |
| L - R partial | -2.2 | -11.9 .. +7.1 | 10 / 10 | 0.670 |
| L - R guardrail breaks | -0.14 | -0.3 .. +0.0 | 4 / 7 | 0.143 |
| P - R strict | -6.7 | -14.3 .. -0.0 | 1 / 5 | 0.126 |

Decision rule: 1 mechanism 105/105: pass. 2 gain: partial -0.5 < +2.0: fail. 3 no-harm vs R: pass (strict -3.8 >=
-6.02, partial -2.2 >= -4.33, fewer guardrail breaks). Rule 4: listing stays off for Haiku 5.5; result reported.
Side finding, not part of this pre-registration: arm P (today's B4T-F) is -6.7 strict against R, below -2 x SE, so P
fails the no-harm check on Haiku 5.5 for strict on this tuning set. Cost $11.41.

## Check after the run: did the extracted policies contain the rules? (2026-11-08)

Not part of the decision rule. For every L and P run, a judge (Opus 5.5) compared the statements the layer extracted
with the gold rule records (quote copied into a statement counts without the judge; the judge must cite statement
numbers, checked by code). 10 judge decisions were checked by hand: 10 correct. The live listing read the same number of
records as the offline dump in 210 of 210 runs.

| Arm | Gold rule records found (pooled) | Mean per task | Found before the first write | Runs with every rule found |
|---|---|---|---|---|
| L gpt-oss | 93.7% | 92.5% | 92.1% | 79 / 99 |
| L Haiku 5.5 | 92.3% | 90.3% | 92.3% | 75 / 99 |
| P gpt-oss | 28.6% | 44.0% | 26.7% | 25 / 99 |
| P Haiku 5.5 | 36.2% | 61.6% | 35.7% | 37 / 99 |

17 gold records were missed in at least one L run: 7 are notes in table rows (holds, exclusions; tables always reach the
extraction, so the extraction drops them); 4 are one-off corrections in email (a new time, a deal to include); 3 are
probably not rules (2 status updates, 1 recommendation from an outside agency). Finding the rules is not enough: L
gpt-oss runs with every rule found pass strict in 25.3%. Not checked: gold records labelled data that state rules.
Scripts: /tmp/aud/cov/livecov.py, summ.py.
