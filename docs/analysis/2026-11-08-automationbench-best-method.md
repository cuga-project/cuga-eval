# Workstream "AutomationBench best method" (2026-11-08, plan written before the run)

Goal: the best general method for Haiku 5.5 on AutomationBench, from up to 10 approaches. Companion workstream: "HANDBOOK best
method" (`2026-11-08-handbook-haiku-approaches.md`).

Tasks: 10 of `ab-policy-types-fresh3` (a tuning set: its failures were traced), chosen before any run as the 10 with 0 of 3
strict passes and the lowest partial score for Haiku with the general agent rules (runs `lx_R_haiku55_t1..3`):
sales.linkedin_profile_enrichment, hr.employee_transfer_approval_workflow, finance.cash_sweep, hr.asana_compliance_tasks,
sales.calendly_discovery_call, finance.intercompany_transfer, hr.zoom_all_hands_setup, sales.form_to_crm_qualification,
marketing.utm_audit_and_fix, support.freshdesk_zoho_migration. Picked by low score, so a gain partly regresses to the mean:
every arm is compared with the base run at the same time, never with the old runs.

Setup: Haiku 5.5 agent, `AB_AGENT_RULES=1` in every arm, snapshot `polisys-cde232a`, 3 trials, cache off, all arms at the same
time. Failure analysis behind the arms: 161 traced fresh3 failures (rule never read 65, stopped early 29, rule misapplied 17,
benchmark check 21, polisys caused 8 primary and 17 secondary).

| Arm | Profile | Targets |
|---|---|---|
| ab-base | baseline | |
| ab-listing | experiments/ab-best-listing (listing + online intake, rules in the brief, no checks) | rule never read |
| ab-readback | experiments/ab-best-readback | stopped early, missing outputs |
| ab-listing-readback | experiments/ab-best-listing-readback | both |
| ab-scope | experiments/ab-best-scope (request_scope, cells) | stopping before writes |
| ab-actors | experiments/ab-best-actors | approvals misapplied |
| ab-b4tf-list | experiments/ab-best-b4tf-list (B4T-F + listing, checks by gpt-oss) | reference polisys arm |
| ab-b4tf-notracker | experiments/ab-best-b4tf-list-notracker | wrong checklist items (polisys caused) |
| ab-b4tf-remind | experiments/ab-best-b4tf-list-remind | blocks for a later step (polisys caused) |
| ab-rules-all | experiments/ab-best-rules-all (actors, request_scope, cells, idempotent, readback) | combined |

Decision rule: mean over 10 tasks x 3 trials, paired per task with ab-base. An arm is a candidate if partial is at least
ab-base + 3 points and strict is not below ab-base, and it passes the no-harm check (arm - base >= -2 x SE on strict and
partial, SE from ab-base). The best candidate then needs a run on fresh tasks before any claim.

## Result (300 runs, Haiku 5.5, 10 tasks x 3 trials; paired per task with ab-base, 95% bootstrap interval, sign-flip p)

2 x SE from ab-base: strict 7.7, partial 7.7 points, guardrail breaks 0.11 per run.

| Arm | Strict diff | Partial diff | Guardrail breaks diff | No-harm | Candidate |
|---|---|---|---|---|---|
| ab-b4tf-remind | +6.7 [-6.7, +23.3] | +24.5 [+7.5, +44.1], p = 0.027 | +0.03 | pass | yes |
| ab-listing-readback | +6.7 [0.0, +16.7] | +21.2 [+5.5, +36.6], p = 0.035 | -0.03 | pass | yes |
| ab-b4tf-notracker | +3.3 [-6.7, +13.3] | +17.6 [+1.3, +36.0], p = 0.082 | 0.00 | pass | yes |
| ab-listing | 0.0 [-10, +10] | +16.2 [+2.6, +30.8], p = 0.078 | -0.07 | pass | yes |
| ab-b4tf-list | 0.0 | +14.4 [-1.4, +31.2] | +0.13 | fail (guards) | no |
| ab-readback | -3.3 | +6.7 | +0.30 | fail (guards) | no |
| ab-rules-all | +3.3 | +4.8 | +0.23 | fail (guards) | no |
| ab-scope | -3.3 | +4.7 | +0.23 | fail (guards) | no |
| ab-actors | -3.3 | +1.6 | +0.33 | fail (guards) | no |

Absolute: base strict 3%, partial 42.5%; listing-readback 10% / 63.7%; b4tf-remind 10% / 67.0% (approx.). In-sample (tuning
tasks chosen for low base scores); a candidate needs a run on fresh tasks before any claim. Every arm with listing is a
candidate; the work-method rule texts break guardrails on AutomationBench and fail the no-harm check.

## Strict fixes round (plan, written before the run)

From the strict analysis (`2026-11-08-automationbench-strict-analysis.md`). polisys main with PR #5 (rules replaced one by
one; the agent's own writes never read as rules) plus `7dc68b0` (snapshot `polisys-7dc68b0`): `notes.read_first` (until the
first message to people, a reminder of sources the request names that were not read; never a block) and
`sources.listing_data` (the listing also keeps corrections and examples and shows them to the agent as data). Same 10 tasks,
Haiku 5.5, `AB_AGENT_RULES=1`, 3 trials, all arms at the same time:

| Arm | Profile |
|---|---|
| sf-base | baseline |
| sf-lr | experiments/ab-best-listing-readback (now with PR #5) |
| sf-readfirst | experiments/ab-sf-readfirst |
| sf-data | experiments/ab-sf-data |
| sf-both | experiments/ab-sf-both |

Reported: strict as measured and strict without the frozen upstream-flagged checks
(`benchmarks/automationbench/upstream_flagged_checks_2026-11-08.json`), partial, guardrail breaks; paired per task with sf-lr
and with sf-base. A fix is kept if strict (without flagged checks) is at least sf-lr + 1 run of 30, partial is not below
sf-lr by more than 2 x SE, and it passes the no-harm check against sf-base. In-sample (tuning tasks).
