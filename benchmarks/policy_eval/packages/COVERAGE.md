# Coverage matrix of the policy packages

Stabilization task 3.4, 2026-11-05 (change 134). One row per package: what it holds, both parts of its audit, its tests and its
label. No experiment was run: the numbers come from the packages, their own decision tests and saved runs.

- 15 packages `skill_v1`: made by fresh agents with the skill (`skill/SKILL.md`) from the policy text and the tool schemas only.
  They did not read `claude_v1`, a gold build, a grader or a run. HANDBOOK 3 tasks, ITSM `e2891a7b98` (base), the other 8 ITSM
  versions (one agent, from the base package and the text differences), τ² Telecom, airline and retail.
- 10 AutomationBench gold builds: audit only. The AutomationBench runtime stays online intake. A gold build is made by hand, holds
  no policy text, no tests and no policy questions (so its coverage and grounding checks have no data), and is labelled `gold, tuning`.
- Each package folder has `package.json`, `draft.json` (what the author wrote), `set.json` (the converted policy text it was packed with) and `AUDIT.md` (`rule_audit.py report`). `import_skill_packages.py --check` makes every package again from these files and the tool specs, and finds no difference (15 of 15).
- Measured packages (`builds*`, `v3`, `v4`, `claude_v1`, `gold`) were not changed. `convert_all.py` has no source for `skill_v1`;
  it hashes the `skill_v1` files before and after and fails on a difference (60 files: package, draft, set and `AUDIT.md` of 15 packages; 0 changed).

Regenerate: `~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/tools/coverage_matrix.py --md benchmarks/policy_eval/packages/COVERAGE.md`
(the measured numbers also go to `coverage_matrix.json`). Counts alone: `python -m cuga.policy_layer.cli counts package.json`.

<!-- tables:start (tools/coverage_matrix.py) -->
## 1. What each package holds

| Package | Label | Statements (must, must-not) | Must or must-not statements with no outcome | Deny tests on a statement with no outcome (statements) | Outcomes (statements) | Rules hard / judgment / guidance | Verify | Procedures (steps, must-nots) | Obligations | Policy questions | Tests |
|---|---|---|---|---|---|---|---|---|---|---|---|
| handbook/hr_crestwood_university_79786c46 | tuning | 733 (232) | 0 | 95 (88) | hard_rule 11, judgment_rule 9, obligation 125, procedure_step 195, guidance 24, definition 68, out_of_scope 1, question 55 | 13 / 9 / 14 | 9 | 26 (191, 22) | 146 | 25 | 654 |
| handbook/insurance_vanguard_shield_mutual_9b2f7a29 | tuning | 337 (137) | 0 | 19 (19) | hard_rule 2, judgment_rule 5, obligation 73, procedure_step 130, guidance 8, definition 17, question 44 | 3 / 4 / 8 | 4 | 17 (127, 30) | 118 | 14 | 331 |
| handbook/medical_careig_specialty_pharmacy_f5947c33 | tuning | 489 (305) | 0 | 12 (12) | hard_rule 11, judgment_rule 28, obligation 141, procedure_step 244, guidance 14, definition 71, question 76 | 12 / 16 / 14 | 16 | 26 (241, 27) | 166 | 25 | 647 |
| itsm/2e555b5177 | tuning | 96 (75) | 0 | - | hard_rule 55, judgment_rule 7, obligation 13, procedure_step 28, guidance 13, definition 4, question 41 | 50 / 6 / 12 | 6 | 8 (28, 3) | 17 | 52 | no tests |
| itsm/7bb25d850c | tuning | 96 (75) | 0 | - | hard_rule 55, judgment_rule 7, obligation 13, procedure_step 28, guidance 13, definition 4, question 41 | 50 / 6 / 12 | 6 | 8 (28, 3) | 17 | 52 | no tests |
| itsm/80cd3ebb50 | unseen, no run | 84 (60) | 0 | - | hard_rule 34, judgment_rule 10, obligation 14, procedure_step 30, guidance 13, definition 4, question 52 | 47 / 9 / 12 | 9 | 8 (30, 4) | 18 | 62 | no tests |
| itsm/933219af01 | tuning | 96 (75) | 0 | - | hard_rule 55, judgment_rule 7, obligation 13, procedure_step 28, guidance 13, definition 4, question 41 | 50 / 6 / 12 | 6 | 8 (28, 3) | 17 | 52 | no tests |
| itsm/a5e328395b | tuning | 96 (75) | 0 | - | hard_rule 55, judgment_rule 7, obligation 13, procedure_step 28, guidance 13, definition 4, question 40 | 50 / 6 / 12 | 6 | 8 (28, 3) | 17 | 51 | no tests |
| itsm/c47f8ceef3 | tuning | 99 (76) | 0 | - | hard_rule 57, judgment_rule 7, obligation 15, procedure_step 29, guidance 15, definition 4, question 50 | 53 / 6 / 13 | 6 | 8 (29, 3) | 21 | 57 | no tests |
| itsm/cb2d4ee021 | tuning | 98 (76) | 0 | - | hard_rule 55, judgment_rule 9, obligation 14, procedure_step 29, guidance 13, definition 4, question 43 | 50 / 7 / 12 | 7 | 8 (29, 3) | 18 | 54 | no tests |
| itsm/d5ab75ff0f | tuning | 168 (98) | 0 | - | hard_rule 76, judgment_rule 10, obligation 17, procedure_step 39, guidance 23, definition 4, question 78 | 69 / 9 / 14 | 9 | 8 (38, 5) | 22 | 69 | no tests |
| itsm/e2891a7b98 | tuning | 96 (75) | 0 | ids not in the package | hard_rule 55, judgment_rule 7, obligation 13, procedure_step 28, guidance 13, definition 4, question 41 | 50 / 6 / 12 | 6 | 8 (28, 3) | 17 | 52 | 347 (0 with a statement id that exists) |
| tau2_telecom/telecom | tuning | 267 (63) | 0 | 3 (3) | hard_rule 10, judgment_rule 7, obligation 25, procedure_step 62, guidance 5, definition 6, question 22 | 9 / 6 / 4 | 6 | 9 (59, 6) | 29 | 14 | 95 |
| tau2_airline/airline | seen, not tuned | 117 (59) | 0 | 1 (1) | hard_rule 2, judgment_rule 37, obligation 16, procedure_step 54, guidance 4, definition 8, question 20 | 3 / 22 / 4 | 22 | 5 (55, 15) | 19 | 11 | 106 |
| tau2_retail/retail | unseen, no run | 82 (43) | 0 | 3 (3) | hard_rule 13, judgment_rule 19, obligation 13, procedure_step 29, guidance 5, definition 5, question 13 | 12 / 15 / 4 | 15 | 6 (29, 21) | 14 | 7 | 88 |
| automationbench/finance.prepaid_amortization (gold) | gold, tuning | none | - | - | no text in the package | 1 / 8 / 0 | 8 | 0 (0, 0) | 0 | 0 | no tests |
| automationbench/finance.xero_batch_invoice_send (gold) | gold, tuning | none | - | - | no text in the package | 3 / 1 / 0 | 1 | 0 (0, 0) | 0 | 0 | no tests |
| automationbench/hr.candidate_offer_negotiation_tracking (gold) | gold, tuning | none | - | - | no text in the package | 2 / 4 / 0 | 4 | 0 (0, 0) | 0 | 0 | no tests |
| automationbench/marketing.social_engagement_response (gold) | gold, tuning | none | - | - | no text in the package | 1 / 6 / 0 | 6 | 0 (0, 0) | 0 | 0 | no tests |
| automationbench/marketing.trending_topic (gold) | gold, tuning | none | - | - | no text in the package | 6 / 7 / 0 | 7 | 0 (0, 0) | 0 | 0 | no tests |
| automationbench/operations.linkedin_job_change (gold) | gold, tuning | none | - | - | no text in the package | 1 / 6 / 0 | 6 | 0 (0, 0) | 0 | 0 | no tests |
| automationbench/sales.zoom_calendar_conflict (gold) | gold, tuning | none | - | - | no text in the package | 0 / 2 / 0 | 2 | 0 (0, 0) | 0 | 0 | no tests |
| automationbench/sales.zoom_regional_webinar_coordinator (gold) | gold, tuning | none | - | - | no text in the package | 0 / 1 / 0 | 1 | 0 (0, 0) | 0 | 0 | no tests |
| automationbench/support.helpcrunch_usage_alerts (gold) | gold, tuning | none | - | - | no text in the package | 4 / 9 / 0 | 9 | 0 (0, 0) | 0 | 0 | no tests |
| automationbench/support.zendesk_data_quality (gold) | gold, tuning | none | - | - | no text in the package | 1 / 3 / 0 | 3 | 0 (0, 0) | 0 | 0 | no tests |

## 2. Audit part 1: do the rules say what the text says

| Package | Label | Validator errors / warnings | Values not in the cited text | Rules that never fire | Unknown tool | Cedar vs rule JSON | Back-translation (judge reads the cited statements only) |
|---|---|---|---|---|---|---|---|
| handbook/hr_crestwood_university_79786c46 | tuning | 0 / 6 | 4 | 0 | 0 | 0 differ | 6 of 20 equivalent (broader 6, narrower 0, different 8) |
| handbook/insurance_vanguard_shield_mutual_9b2f7a29 | tuning | 0 / 12 | 0 | 0 | 0 | no role rules | 0 of 5 equivalent (broader 3, narrower 1, different 1) |
| handbook/medical_careig_specialty_pharmacy_f5947c33 | tuning | 0 / 0 | 0 | 0 | 0 | 0 differ | 5 of 26 equivalent (broader 5, narrower 5, different 11) |
| itsm/2e555b5177 | tuning | 0 / 5 | 0 | 0 | 0 | 0 differ | 27 of 54 equivalent (broader 3, narrower 11, different 13) |
| itsm/7bb25d850c | tuning | 0 / 5 | 0 | 0 | 0 | 0 differ | 27 of 54 equivalent (broader 3, narrower 11, different 13) |
| itsm/80cd3ebb50 | unseen, no run | 0 / 9 | 0 | 0 | 0 | 0 differ | 24 of 54 equivalent (broader 4, narrower 10, different 16) |
| itsm/933219af01 | tuning | 0 / 5 | 0 | 0 | 0 | 0 differ | 27 of 54 equivalent (broader 3, narrower 11, different 13) |
| itsm/a5e328395b | tuning | 0 / 5 | 0 | 0 | 0 | 0 differ | 27 of 54 equivalent (broader 3, narrower 11, different 13) |
| itsm/c47f8ceef3 | tuning | 0 / 7 | 0 | 0 | 0 | 0 differ | 24 of 57 equivalent (broader 4, narrower 12, different 17) |
| itsm/cb2d4ee021 | tuning | 0 / 5 | 0 | 0 | 0 | 0 differ | 28 of 55 equivalent (broader 3, narrower 11, different 13) |
| itsm/d5ab75ff0f | tuning | 0 / 11 | 0 | 0 | 0 | 0 differ | 35 of 75 equivalent (broader 6, narrower 12, different 22) |
| itsm/e2891a7b98 | tuning | 0 / 5 | 0 | 0 | 0 | 0 differ | 27 of 54 equivalent (broader 3, narrower 11, different 13) |
| tau2_telecom/telecom | tuning | 0 / 1 | 0 | 0 | 0 | no role rules | 8 of 13 equivalent (broader 2, narrower 0, different 3) |
| tau2_airline/airline | seen, not tuned | 0 / 1 | 0 | 0 | 0 | no role rules | 19 of 23 equivalent (broader 2, narrower 1, different 1) |
| tau2_retail/retail | unseen, no run | 0 / 1 | 0 | 0 | 0 | no role rules | 21 of 25 equivalent (broader 3, narrower 1, different 0) |
| automationbench/finance.prepaid_amortization (gold) | gold, tuning | 0 / 0 | no text in the package | 0 | 0 | no role rules | not run |
| automationbench/finance.xero_batch_invoice_send (gold) | gold, tuning | 0 / 0 | no text in the package | 0 | 0 | no role rules | not run |
| automationbench/hr.candidate_offer_negotiation_tracking (gold) | gold, tuning | 0 / 0 | no text in the package | 0 | 0 | no role rules | not run |
| automationbench/marketing.social_engagement_response (gold) | gold, tuning | 0 / 0 | no text in the package | 0 | 0 | no role rules | not run |
| automationbench/marketing.trending_topic (gold) | gold, tuning | 0 / 0 | no text in the package | 0 | 0 | no role rules | not run |
| automationbench/operations.linkedin_job_change (gold) | gold, tuning | 0 / 0 | no text in the package | 0 | 0 | no role rules | not run |
| automationbench/sales.zoom_calendar_conflict (gold) | gold, tuning | 0 / 0 | no text in the package | 0 | 0 | no role rules | not run |
| automationbench/sales.zoom_regional_webinar_coordinator (gold) | gold, tuning | 0 / 0 | no text in the package | 0 | 0 | no role rules | not run |
| automationbench/support.helpcrunch_usage_alerts (gold) | gold, tuning | 0 / 0 | no text in the package | 0 | 0 | no role rules | not run |
| automationbench/support.zendesk_data_quality (gold) | gold, tuning | 0 / 0 | no text in the package | 0 | 0 | no role rules | not run |

## 3. Audit part 2: do the rules hold on real data

Decision tests are the package's own, written from the text without the rules. A test whose call the tool schema rejects is counted in the schema columns and left out of the rule columns. Replay: saved arm-A runs of the policy (CUGA alone) through the package's code and Cedar checks; a deny on a passed run is a conflict with the grader.

| Package | Label | Tests | Deny tests caught by rules (schema-accepted) | False denies (allow tests) | False reminders | Rejected by the tool schema | Replay |
|---|---|---|---|---|---|---|---|
| handbook/hr_crestwood_university_79786c46 | tuning | 654 | 10 of 345 (4 deny) | 0 of 309 | 1 | 0 deny, 0 allow | 60 runs, no passed runs, so no deny on a passed run can be counted; on failed runs 6 denies and 135 reminders |
| handbook/insurance_vanguard_shield_mutual_9b2f7a29 | tuning | 331 | 1 of 72 (1 deny) | 0 of 58 | 0 | 107 deny, 94 allow | 51 runs, 2 passed; 0 passed runs denied (0 denies), 0 reminded (0); on failed runs 0 denies and 0 reminders |
| handbook/medical_careig_specialty_pharmacy_f5947c33 | tuning | 647 | 2 of 345 (2 deny) | 0 of 302 | 0 | 0 deny, 0 allow | 54 runs, no passed runs, so no deny on a passed run can be counted; on failed runs 0 denies and 0 reminders |
| itsm/2e555b5177 | tuning | no tests | - | - | - | - | 20 runs, 4 passed; 1 passed runs denied (3 denies), 1 reminded (1); on failed runs 0 denies and 0 reminders |
| itsm/7bb25d850c | tuning | no tests | - | - | - | - | 30 runs, 15 passed; 0 passed runs denied (0 denies), 0 reminded (0); on failed runs 0 denies and 0 reminders |
| itsm/80cd3ebb50 | unseen, no run | no tests | - | - | - | - | no runs |
| itsm/933219af01 | tuning | no tests | - | - | - | - | 76 runs, 40 passed; 0 passed runs denied (0 denies), 0 reminded (0); on failed runs 2 denies and 0 reminders |
| itsm/a5e328395b | tuning | no tests | - | - | - | - | 14 runs, 2 passed; 0 passed runs denied (0 denies), 0 reminded (0); on failed runs 0 denies and 0 reminders |
| itsm/c47f8ceef3 | tuning | no tests | - | - | - | - | 21 runs, 10 passed; 0 passed runs denied (0 denies), 0 reminded (0); on failed runs 0 denies and 6 reminders |
| itsm/cb2d4ee021 | tuning | no tests | - | - | - | - | 3 runs, 2 passed; 0 passed runs denied (0 denies), 0 reminded (0); on failed runs 0 denies and 0 reminders |
| itsm/d5ab75ff0f | tuning | no tests | - | - | - | - | 13 runs, no passed runs, so no deny on a passed run can be counted; on failed runs 0 denies and 15 reminders |
| itsm/e2891a7b98 | tuning | 347 | 86 of 162 (58 deny) | 0 of 147 | 6 | 20 deny, 18 allow | 182 runs, 93 passed; 2 passed runs denied (2 denies), 18 reminded (26); on failed runs 11 denies and 11 reminders |
| tau2_telecom/telecom | tuning | 95 | 7 of 51 (7 deny) | 0 of 44 | 0 | 0 deny, 0 allow | 140 runs, 95 passed; 1 passed runs denied (1 denies), 0 reminded (0); on failed runs 20 denies and 0 reminders |
| tau2_airline/airline | seen, not tuned | 106 | 2 of 57 (2 deny) | 0 of 49 | 0 | 0 deny, 0 allow | 60 runs, 43 passed; 0 passed runs denied (0 denies), 0 reminded (0); on failed runs 0 denies and 0 reminders |
| tau2_retail/retail | unseen, no run | 88 | 17 of 47 (17 deny) | 0 of 41 | 0 | 0 deny, 0 allow | no runs |
| automationbench/finance.prepaid_amortization (gold) | gold, tuning | no tests | - | - | - | - | 13 runs, no passed runs, so no deny on a passed run can be counted; on failed runs 0 denies and 0 reminders |
| automationbench/finance.xero_batch_invoice_send (gold) | gold, tuning | no tests | - | - | - | - | 13 runs, 1 passed; 0 passed runs denied (0 denies), 0 reminded (0); on failed runs 0 denies and 0 reminders |
| automationbench/hr.candidate_offer_negotiation_tracking (gold) | gold, tuning | no tests | - | - | - | - | 13 runs, 1 passed; 0 passed runs denied (0 denies), 0 reminded (0); on failed runs 0 denies and 0 reminders |
| automationbench/marketing.social_engagement_response (gold) | gold, tuning | no tests | - | - | - | - | 15 runs, 2 passed; 0 passed runs denied (0 denies), 0 reminded (0); on failed runs 0 denies and 0 reminders |
| automationbench/marketing.trending_topic (gold) | gold, tuning | no tests | - | - | - | - | 15 runs, no passed runs, so no deny on a passed run can be counted; on failed runs 18 denies and 0 reminders |
| automationbench/operations.linkedin_job_change (gold) | gold, tuning | no tests | - | - | - | - | 15 runs, 5 passed; 0 passed runs denied (0 denies), 0 reminded (0); on failed runs 0 denies and 0 reminders |
| automationbench/sales.zoom_calendar_conflict (gold) | gold, tuning | no tests | - | - | - | - | 14 runs, 13 passed; 0 passed runs denied (0 denies), 0 reminded (0); on failed runs 0 denies and 0 reminders |
| automationbench/sales.zoom_regional_webinar_coordinator (gold) | gold, tuning | no tests | - | - | - | - | 15 runs, no passed runs, so no deny on a passed run can be counted; on failed runs 0 denies and 0 reminders |
| automationbench/support.helpcrunch_usage_alerts (gold) | gold, tuning | no tests | - | - | - | - | 14 runs, 3 passed; 0 passed runs denied (0 denies), 0 reminded (0); on failed runs 0 denies and 0 reminders |
| automationbench/support.zendesk_data_quality (gold) | gold, tuning | no tests | - | - | - | - | 13 runs, no passed runs, so no deny on a passed run can be counted; on failed runs 0 denies and 0 reminders |

### Why deny tests are not caught: the outcome of the tested statement

Deny tests that the tool schema accepts, by what the tested statement became in the package (the strongest outcome first). Each cell is caught of tests. Obligations and procedures have no test yet (Task 4.1 and 4.3 read them), so a deny test on an obligation or a step is caught only by a rule that happens to apply to the same tool. A `verify` rule never denies without a verifier model. The stored ITSM tests carry statement ids of an older split, so they cannot be placed.

| Package | Deny tests | Code rule | Verify | Obligation or step | Guidance, duty or global rule | Definition | Question only | No outcome | Statement id not in the package |
|---|---|---|---|---|---|---|---|---|---|
| handbook/hr_crestwood_university_79786c46 | 345 | 7 of 9 | 0 of 13 | 1 of 184 | 2 of 21 | 0 of 19 | 0 of 4 | 0 of 95 | - |
| handbook/insurance_vanguard_shield_mutual_9b2f7a29 | 72 | 1 of 1 | 0 of 2 | 0 of 53 | 0 of 3 | 0 of 1 | 0 of 1 | 0 of 11 | - |
| handbook/medical_careig_specialty_pharmacy_f5947c33 | 345 | 2 of 9 | 0 of 29 | 0 of 256 | 0 of 7 | 0 of 31 | 0 of 1 | 0 of 12 | - |
| itsm/e2891a7b98 | 162 | - | - | - | - | - | - | - | 86 of 162 |
| tau2_telecom/telecom | 51 | 5 of 10 | 0 of 8 | 2 of 28 | - | - | 0 of 2 | 0 of 3 | - |
| tau2_airline/airline | 57 | 2 of 2 | 0 of 46 | 0 of 7 | - | 0 of 1 | - | 0 of 1 | - |
| tau2_retail/retail | 47 | 16 of 20 | 1 of 19 | 0 of 2 | 0 of 3 | - | - | 0 of 3 | - |

### itsm/e2891a7b98: the builds on one set of tests and runs

All numbers from one run now, on the same tests (same test hash) and the same saved runs. The tests are the tuning version: the 347 stored blind tests of this policy, and its runs were used to tune the earlier builds, so this is no held-out number. The count of hard denies differs a lot between the builds: a build that reminds where another denies gets the same `caught`.

| Build | Rules, of 162 | Deny / remind | With schema, of 182 | Rules alone, of 182 | False deny, of 147 | False remind, of 147 | Passed runs denied, of 93 |
|---|---|---|---|---|---|---|---|
| skill_v1 | 86 | 58 / 28 | 106 | 95 | 0 | 6 | 2 |
| builds_v4_v4A | 84 | 62 / 22 | 104 | 88 | 1 | 6 | 2 |
| builds_v5 | 82 | 60 / 22 | 102 | 85 | 1 | 6 | 2 |
| gold | 77 | 76 / 1 | 97 | 92 | 1 | 5 | 9 |

## 4. Verify rules per package (input for Task 3.5)

A `verify` rule has no code check: it needs the verifier model, and with none it never denies. Share = verify rules of all rules.

| Package | Rules | Verify | Share | Rules with a code check (not verify, guidance, duty or global) |
|---|---|---|---|---|
| handbook/hr_crestwood_university_79786c46 | 36 | 9 | 25% | 8 |
| handbook/insurance_vanguard_shield_mutual_9b2f7a29 | 15 | 4 | 27% | 1 |
| handbook/medical_careig_specialty_pharmacy_f5947c33 | 42 | 16 | 38% | 10 |
| itsm/2e555b5177 | 68 | 6 | 9% | 43 |
| itsm/7bb25d850c | 68 | 6 | 9% | 43 |
| itsm/80cd3ebb50 | 68 | 9 | 13% | 39 |
| itsm/933219af01 | 68 | 6 | 9% | 43 |
| itsm/a5e328395b | 68 | 6 | 9% | 43 |
| itsm/c47f8ceef3 | 72 | 6 | 8% | 44 |
| itsm/cb2d4ee021 | 69 | 7 | 10% | 43 |
| itsm/d5ab75ff0f | 92 | 9 | 10% | 58 |
| itsm/e2891a7b98 | 68 | 6 | 9% | 43 |
| tau2_telecom/telecom | 19 | 6 | 32% | 5 |
| tau2_airline/airline | 29 | 22 | 76% | 1 |
| tau2_retail/retail | 31 | 15 | 48% | 10 |

<!-- tables:end -->

## Reading the tables

- Outcomes count statements, not objects: a statement can have more than one. `Must or must-not statements with no outcome` is the
  `coverage_incomplete` check of `validate`, and it is 0 for all 15 packages. **That 0 trusts the author's choice of modality** (a
  statement with no modality needs no outcome). The blind tests show the limit: 133 deny tests are on 126 statements that have no
  outcome at all (Crestwood 95 tests on 88 statements, Vanguard 19 on 19, CareIG 12 on 12, Telecom 3 on 3, airline 1 on 1, retail 3 on 3;
  121 of the 126 statements have no modality, 5 are marked `may`). Each is a statement that a writer who did not see the rules
  thought a call could break and the author left unmarked. The column `Deny tests on a statement with no outcome` in table 1 gives it per package
  (it counts the tests the tool schema accepts as well as those it rejects). The coverage check cannot find this gap; the blind tests are the
  only check for it. Not counted for ITSM `e2891a7b98`: its test ids are from an older split.
- Part 1 says whether the rules say what the text says. `Values not in the cited text` is a check of the literals of a rule against the
  statements it cites. The back-translation judge (DeepSeek-V4-Pro, a model family other than the writer, gpt-oss-120b) reads the
  rule restated in words and only the cited statements; it is not reviewed by a person. A rule that cites one statement of a
  table or list gets `different` or `broader` when the missing words are in the next statement (Crestwood `r_duty_er` cites "Reply using
  Template 2.", and the address is in `policy:8:6`; the 4 values that the grounding check misses on Crestwood are the same case). So a
  `different` verdict mixes real rule defects with citations that are too narrow, and it is not a count of wrong rules.
- Part 2 is decision tests and replay. The tests were written from the text by another agent, without the rules. The code-only run
  answers each test through the package's rules and Cedar. Replay sends the tool calls of saved arm-A runs of the policy (CUGA alone)
  through the code and Cedar checks. A deny on a passed run is a conflict with the grader; a deny can still be right by the text. Where a
  policy has no passed run (Crestwood 60 runs, CareIG 54, ITSM `d5ab75ff0f` 13, four of the AutomationBench gold builds), a deny on a passed run
  cannot be counted and the table says so; the denies and reminders on failed runs are given instead.
- The tool schema is a layer of its own. A test whose call the tool's own schema rejects (a value outside an enum, or a string that does
  not match the argument's `pattern`) says nothing about a rule, so it is counted apart (`Rejected by the tool schema`) and the rule
  columns use the tests that the schema accepts.

### Why so few deny tests are caught

The cause differs by package. The table `Why deny tests are not caught` above puts each schema-accepted deny test under the outcome of
the statement it tests. Obligations and procedures have no test yet (Task 4.1 and 4.3 read them), so a deny test on an obligation or a step is
caught only by a rule that happens to apply to the same tool.

| Package | Deny tests | Main cause |
|---|---|---|
| Crestwood | 345 | 184 on obligations or steps, 95 on statements with no outcome, 19 definitions: these 298 have no rule a single call can answer. 4 question only. 21 on guidance, duty or global rules (2 caught), 13 on `verify` (0 caught), 9 on code rules (7 caught) |
| Vanguard | 72 | 53 on obligations or steps, 11 with no outcome; 1 code rule (caught) |
| CareIG | 345 | 256 on obligations or steps, 31 definitions, 29 `verify`, 9 code rules (2 caught), 12 with no outcome |
| Telecom | 51 | 28 on obligations or steps, 10 code rules (5 caught), 8 `verify` |
| **Airline** | 57 | **`verify`: 46 of 57** (0 caught: it never denies without a verifier model). 2 code rules, both caught. Only 3 of 29 rules are not `verify` or guidance |
| **Retail** | 47 | **Code rules: 20 of 47** (16 caught), `verify` 19 (1 caught), 3 with no outcome. The 4 uncaught code-rule tests ask for a read first (the `reference_status` rule is silent when the order was never read, as designed) |
| ITSM `e2891a7b98` | 162 | not attributable: the statement ids of the stored tests are from an older split. 86 of 162 are caught by rules |

Crestwood has 23 deny tests, not caught, on statements that a rule other than `verify` cites. 18 are guidance rules (text for the brief, no
check by design). The other 5 show limits of the rule types, not of the author:
`r_no_placeholders_send` and `_reply` are `format` rules with the pattern `[^\[\]]*`, which matches any text including the empty text, so they
never deny (there is no rule type "must not contain"); `r_folder_move` is an `allowed_values` rule, which compares without case, while the text says
"match exactly"; `r_duty_er` and `r_duty_payroll` are duties, which watch later calls and cannot answer a single call; `r_grounded` and `r_ids`
do not read a number quoted in the body of a reply.

## Findings

### Numbers by benchmark

| Benchmark | Deny tests caught by rules (schema-accepted) | Schema-only catches | False denies | Passed runs denied | Label |
|---|---|---|---|---|---|
| HANDBOOK Crestwood | 10 of 345 | 0 | 0 of 309 | no passed runs (60 runs) | tuning |
| HANDBOOK Vanguard | 1 of 72 | 107 deny tests (not rule results) | 0 of 58 | 0 of 2 passed (51 runs) | tuning |
| HANDBOOK CareIG | 2 of 345 | 0 | 0 of 302 | no passed runs (54 runs) | tuning |
| ITSM `e2891a7b98` | 86 of 162 (106 of 182 with the schema) | 11 | 0 of 147 (6 false reminders) | 2 of 93 passed (182 runs), one task | tuning |
| ITSM other 8 | no tests | - | - | 1 of 4 passed on `2e555b5177`; 0 of 69 passed on 5 other versions with passed runs; `d5ab75ff0f` has no passed run (13 runs); `80cd3ebb50` has no runs | `unseen, no run` for `80cd3ebb50`, `tuning` for the 7 others |
| τ² Telecom | 7 of 51 | 0 | 0 of 44 | 1 of 95 passed (140 runs) | tuning |
| τ² airline | 2 of 57 | 0 | 0 of 49 | 0 of 43 passed (60 runs) | seen, not tuned |
| τ² retail | 17 of 47 | 0 | 0 of 41 | no runs | unseen, no run |
| AutomationBench gold (10) | no tests | - | - | 0 of 25 passed (140 runs); 4 builds have no passed run; 18 denies on failed runs, all one rule of `marketing.trending_topic` | gold, tuning |

Telecom was 6 of 51 before the date fix of fix round 1 and is 7 now: the blind test that has a contract end date of `2025-02-24` is caught by
`r_no_resume_contract_ended` (nothing in the package or the test changed).

**No package is `held-out`.** Every held-out set that has any `seen_n` above 0 is `seen` (`sets/registry.json`, field `label`), and a policy
whose only sets are `seen` is `seen, not tuned`.

### ITSM `e2891a7b98`: the builds on one denominator

The third table block above (`itsm/e2891a7b98: the builds on one set of tests and runs`) is the reading to use. It is the **tuning version**: the 347
stored blind tests and the 182 saved runs of this policy were used to tune the earlier builds (changes 105 to 118), so it is no held-out number.
Same tests (one test hash for all four builds), 162 deny tests and 147 allow tests that the schema accepts (20 deny and 18 allow tests are rejected
by the schema):

| Build | Caught by rules | Hard denies | Reminders | With schema, of 182 | False deny | False remind | Passed runs denied |
|---|---|---|---|---|---|---|---|
| `skill_v1` (from text alone) | 86 | 58 | 28 | 106 | 0 | 6 | 2 of 93 |
| `builds_v4_v4A` | 84 | 62 | 22 | 104 | 1 | 6 | 2 of 93 |
| `builds_v5` | 82 | 60 | 22 | 102 | 1 | 6 | 2 of 93 |
| `gold` | 77 | 76 | 1 | 97 | 1 | 5 | 9 of 93 |

106 against 97 does not mean that the text-only package is better than gold. `caught` counts a reminder as a catch: `skill_v1` denies in 58 cases and
reminds in 28, gold denies in 76 and reminds in 1. By hard denies gold is ahead (76 against 58), and gold also denies on 9 passed runs against 2.
The four builds are close; what the table shows is that a package made from the text by an agent that did not see the rules is in the same range as the
measured builds, with no false deny and 2 passed runs denied, the same as v4A and v5.

### The 347 stored ITSM tests

They were written from the text by DeepSeek-V4-Pro without the rules (changes 107 and 114) and are copied as they are. Their `statement_id`
values come from an older split: 0 of 347 exist in the new package. With the document prefix mapped (`itsm-e2891a7b98:` to `policy:`), 328
exist, and 252 of those have the same text (folded). The 100 distinct ids are kept as they are; a per-statement reading of these tests is
not valid, the decision outcomes are. The other tests have all their ids in the package: HANDBOOK Crestwood 654 of 654 (the 733 statement ids of the test
writer and of the author are the same, the text is equal after folding dashes: 654 are equal as they are, 79 differ by a dash), the other
packages 100%.

### The tool schema layer (Vanguard, and the effect on ITSM)

201 of 331 Vanguard tests (107 deny, 94 allow) use a value that the tool schema `pattern` rejects: Jira `issue_key` 121, `project_key` 61, Slack
`channel_id` 17, `inward_issue_key` 2 (names such as `OPS-FIN-SUSPENSE-2025-05`, `IT-Support`, `ar-collections`). The author reported 206; the
check here finds 201, all of them `pattern`. These names come from the policy text: the policy writes project and channel names the tool does not
accept. So this is a **policy-tool conflict**, not only a weak test: an agent that follows the policy literally meets a tool error. `validate` now warns
(`schema_conflict`) on a rule literal that a tool `pattern` rejects (it found one in the older Vanguard builds `v3` and `v4`, value `OPS-AP-INV`; none in `skill_v1`).
`rule_audit._schema_reject` knew enums only, so before this task these tests would have counted as rule results. It now checks `pattern` too (a string
is matched as JSON Schema does, by search). Result: Vanguard caught 1 of 72, with 107 deny tests rejected by the schema alone and 94 allow tests rejected
by the schema. The Crestwood and CareIG tests use the same tools and none of them breaks a pattern.

**Effect on ITSM, which was not said in the first report.** The same change moved ITSM numbers a little. The ITSM tool file has 2 patterns (`phone` of
`add_new_user` and of `update_user_details`), and 2 allow tests of the 347 call `add_new_user` with a phone number that breaks it. So `schema_on_allow` is
**18 instead of 16 on every ITSM build**, and the schema-accepted allow count is 147 instead of 149 (165 allow tests in all). `caught`, the false denies and
the false reminders did not move. Before the change the 20 deny tests and 16 allow tests were rejected by the enum alone; after it the 20 deny tests and 18
allow tests. The `AUDIT.md` of the 7 older `e2891a7b98` builds that have one (`builds_v2`, `builds_v4`, `builds_v4_remind`, `builds_v4_v4A`, `builds_v4_v4B`, `builds_v5`,
`gold`) were made again and say 18 as `skill_v1` does (before, they said 16 and `skill_v1` said 18). The saved result files in `rule_audit/` were not changed:
the saved verifier results (`tests_run__...__verifier*.json`) were made before the pattern check and hold the old split of allow tests (they count 165 allow
tests and no schema-accepted subset), so their false-reminder rows stay valid and are not compared with the 147.

### Rules flagged as unverified, checked against saved runs

Offline, on the record shapes in the saved runs (the results of `get_details_by_id`, `get_bills_for_customer`, `get_reservation_details` and
the ITSM reads). Nothing in a package was changed.

| Rule | What the saved runs show | Verdict |
|---|---|---|
| Telecom `r_request_only_overdue` (`reference_status`, `bill_id`, field `status`, allowed `Overdue`) | Bill records come from `get_bills_for_customer`, field `status`, values `Draft`, `Issued`, `Paid`, `Overdue`. Of 44 `send_payment_request` calls, 23 are for an `Overdue` bill (allowed) and 21 for an `Issued` bill (denied: 20 on failed runs, 1 on a passed run). No call names a bill that was not read. | Right. The stored value `Overdue` is confirmed. The one deny on a passed run is a call for an `Issued` bill, which the text forbids ("check that the bill is overdue"), so the grader and the text disagree, and the rule follows the text. |
| Telecom `r_no_resume_contract_ended` (`record_condition`, `contract_end_date lt 2025-02-25`) | The date is in the text ("The current time is 2025-02-25 12:08:00 EST"), the field is `contract_end_date` on line records (ISO text). No line read before a `resume_line` call has an ended contract, so the rule never fires in the 140 runs. | **Was wrong, now right.** `ruleset._condition` compared `gt`, `ge`, `lt`, `le` by the first number of each side, i.e. the year: `2025-02-24 ge 2025-02-25` and `2025-12-31 le 2025-02-25` were both true. Fixed in fix round 1: two ISO dates (with or without a time and an offset) are compared as dates; numbers and other forms keep the old reading. A probe with records now gives deny for `2024-12-31` and `2025-02-24`, allow for `2025-02-25` and `2026-06-30`, and the blind test with the end date `2025-02-24` is caught (Telecom 6 to 7 of 51). The package is unchanged. |
| τ² airline `r_basic_economy_flights` (`record_condition`, `cabin equals basic_economy`, `when cabin = basic_economy` on `update_reservation_flights`) | `get_reservation_details` has the field `cabin`, values `basic_economy` 65, `economy` 55, `business` 48. The `when` makes the rule apply to a call that keeps `cabin=basic_economy`; none of the 25 `update_reservation_flights` calls does (cabin arguments `economy` or `business`), so it never fires. The record can be stale after a cabin change in the same run. | Field name and value confirmed. Correct for the call it describes; it never fires on these runs and cannot be tested further without a run that keeps the cabin. |
| ITSM `reference_status` (12 rules: `assigned_to` active/role, `user_id` active, `configuration_item` status) | Fields `active` (values `True`), `role` (`manager`), `status` (`in_use`) exist in the records of 182 runs: 70 checks resolved, all allowed. Calls with `assigned_to` as an e-mail address (4 calls of `update_change`) find no record, so the rule says nothing. `assigned_to` is absent in all 50 `create_incident` calls. | Shapes confirmed. The limit the authors reported is real: where the argument is not the record's own id, the rule cannot decide. 0 denies in replay. |
| τ² retail `reference_status` (6 rules, `status` `pending` / `delivered`) | No saved run uses the retail policy. | Unverified: there is no run. |

### False-deny outliers

No rule has 5 or more false denies: every package has 0 false denies on its allow tests. Denies on passed runs can only be counted where there are
passed runs (ITSM 7 versions with runs, Vanguard 2, Telecom 95, airline 43, AutomationBench 25); in those, no rule has 5 or more (the most is 3, on one
passed run of `2e555b5177`). Crestwood, CareIG and `d5ab75ff0f` have no passed run, so nothing can be said there; on their failed runs Crestwood
has 6 denies and 135 reminders (`r_comment_format` 96, `r_subject_format` 39: the comment and subject formats of the SOP).

Rules with 5 or more reminders on passed runs: `r_manager_grant` on `e2891a7b98`, 26 reminders on 18 passed runs (and 11 on failed runs): it reminds a manager
who calls `send_notification` (11), `update_configuration_item` (8) or `update_service` (7). The text gives the Manager full access to four operational
tables and read access to the others, and it names no write on notifications, CIs or services, so the reminder follows the text, and a policy question asks
the same ("Is the Manager forbidden on every other write tool"). The rule stays at `remind`. The measured pipeline build v4A has the same rule with the same 26
and 11. **What a later live run must watch for this rule:** the pass rate of these tasks by arm (the arm with the reminder against the arm without it), and
what the agent does after the reminder on `send_notification`, `update_configuration_item` and `update_service`: whether it stops, asks, changes the call
or goes on, and whether the task then passes. The grader passed 18 of these runs without the reminder, so a drop of the pass rate would be the cost of the rule.
Denies on passed runs by rule: `r_incident_required` (2 denies, 1 task of `e2891a7b98`: `create_incident` with no `impact` and `urgency`, which the text makes
mandatory), `r_request_only_overdue` (above).

### Labels

The label of each policy comes from the `policies` and `sets` sections of `sets/registry.json` (`audit_report.basis_of`) and nothing else. Rule: a held-out set
that some agent model has run (`seen_n` above 0 for any model) is `seen`, never `held-out`; a policy whose only sets are `seen` is `seen, not tuned`. No
package is `held-out` now.

| Policy | Label |
|---|---|
| τ² airline | `seen, not tuned` (set `tau2-airline-test`: `seen`) |
| τ² retail, ITSM `80cd3ebb50` | `unseen, no run` |
| Other 8 ITSM, Telecom, 3 HANDBOOK | `tuning` |
| 10 AutomationBench gold | `gold, tuning` |

τ² airline: the official test split (20 tasks) was run before this package existed: the headroom checks `a20_ds` and `a20_oss`, and the no-harm check of the SOP
tracker `air1` (arms A and T, 5 trials, change 87). The runs and the agent writes were reviewed (change 87, `tau2/labels.md`). The result of `air1` (17 of 20
against 11 of 20) is the evidence for design decision 1 of the design spec (route by the shape of the policy source), and Task 5.3 (rule-list route) implements
that decision and is checked on this package. The package was made from the policy text only and no rule, test or setting was changed from these runs, but the
tasks, the runs and the failures are seen, so numbers on this split are not a clean bar.

### Open ambiguities are in `policy_questions`

- Every must or must-not statement has an outcome (`coverage_incomplete` 0 for all 15), but see the limit above: the author's modality decides what must have one.
  Every `rule_conflict` and `schema_conflict` warning (the 83 `rule_conflict` warnings are 44 of the new packages) names a rule that a policy question lists. The
  15 `unbound_value` warnings are not ambiguities: a value that no match pattern names, so it is shown and never compared.
- ITSM roles: 18 to 23 questions per version on the role grants (which tools the grants cover, what the Administrator row lacks,
  what a Reporter may read or update, who pauses the SLA). ITSM priority: 6 to 8 per version (the matrix and the default `planning`,
  an override, a change of impact, the priority of a change, an SLA for `planning`). `80cd3ebb50` has no priority matrix in its text, no
  `derived_value` rule, and a question that says so ("this text has no matrix. Which matrix applies? The package derives no priority").
  `opened_by` is mandatory in the text and `create_incident` has no such argument: a question on it, and the rule requires the other 4.
- Not checkable by a tool: an ambiguity the author did not notice. The back-translation and the tests are the checks for that (see the 126 statements above).

### Runtime check

`tools/runtime_check.py`: each package built with `build_runtime` and `RecordingModels` (no agent, no model), on the gate profile
(`handbook-gemini-graph-gate`), a guide profile (`handbook-dsv4-loop-guide`) and the rules profile (`itsm-rules`): 45 builds, 0 raised, and each
build has the components of its profile (gate and procedure tools; guide and loop; rules and the procedure monitor). The rules profile ran
on every package, not only ITSM and τ². Known and not fixed (task 4.2): `ProcedureMonitor` ignores a step's `condition`. A probe with one tool
call per procedure gives a follow-up with 17 lines for Telecom, which has 17 required action steps that carry a condition and are listed as if
they had none, and 14 lines for ITSM `e2891a7b98`.

### Skill and tool problems (input for Task 3.5)

Reported by the authors:

- Array and integer arguments have no matching (`item_ids`, `passengers`, `amount`; 100 matches 1000), and typed rules do not fit comparisons
  with records: airline has 22 of 29 rules as `verify`.
- No source for record fields and stored values (`reference_status`, `record_condition`), and `validate` does not check them. This task
  checked the flagged ones against saved runs (above).
- `convert` gives every section parent `None`, so sub-sections do not inherit preconditions (retail, Telecom). Long paragraphs are merged into
  one statement (`d5ab75ff0f`), a version number in a header table makes false sections (Vanguard 5.0, 6.0), and a table row with no
  closing `|` makes the next row a header (`d5ab75ff0f`).
- The tool patterns reject names (Vanguard Jira names): `schema_conflict` covered enums only (now patterns too). Policy fields that no tool has (ITSM `opened_by`).
- Grant lists have no tool-to-table map, and collide with duties (`rule_conflict` warnings that cannot be cleared); they do not fit a policy
  that grants files, not tools (CareIG).
- A write spread over a code tool: several obligations per field, `match` has no "or" across tools, one pattern per argument; fixed reply text
  cannot get to 0 warnings.
- Section headings are not policy text for `not_in_text`; `validate` checks a rule's quote only for role rules.
- A statement that needs two calls cannot have a step action; a shared fallback table has no pattern (Vanguard 1.3). System-effect
  statements are the only text for a write (retail). Another actor's action on a `user__` tool (Telecom).

Found by this audit:

- The date compare (fixed in the runtime in fix round 1, see the table above; `validate` warns on the forms that stay unreliable).
- A rule cites only one statement of a list or table while its values come from the next statement (Crestwood 4 rules). `rule_audit static`
  finds it (`Values not in the cited text`); `validate` does not. A check in `validate` is the general fix.
- No rule type says "must not contain": a `format` rule with a pattern that matches any text never denies (Crestwood `r_no_placeholders_*`),
  and `validate` does not warn about it. `allowed_values` compares without case. Blind tests are the only check for these.
- The blind tests find 126 statements with no outcome that the author left without a modality (above); `validate` cannot.
- The schema `pattern` was not an audit layer (fixed in `rule_audit`, above, with the effect on ITSM). `rule_audit._literals` raised on a `threshold` rule
  (`then` is a word): fixed, with a test.
- `ruleset._check_format` folds dashes in the pattern before matching, so a class such as `[-]` with an en dash and an em dash becomes `[---]` and Python
  warns (`FutureWarning: Possible set difference`) on Crestwood. It still matches.
- `tau2/telecom_tools.json` keeps the schema under `parameters`, the authors' copy under `inputSchema`; the contents are the same.

### Verify counts

Table 4 above is the input of Task 3.5: 15 packages, 4 to 22 `verify` rules each. Airline is the extreme: 22 of 29 rules (76%) are `verify`,
because its rules are about arrays, counts and records the typed rules cannot express. ITSM has 6 to 9 of 68 to 92 (8 to 13%). A `verify`
rule never denies without a verifier model.
