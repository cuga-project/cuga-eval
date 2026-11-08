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
