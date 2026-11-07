# Audit of itsm/e2891a7b98/builds_v4_remind

Made on 2026-11-05 by `rule_audit.py report`. Package version `3f8382b04c91277c+2df0fd1fc1e3`; made by pipeline / builder / aws/gpt-oss-120b. 65 rules, 0 procedures, 0 obligations, 347 decision tests in the package.

## Which numbers these are

**tuning**: tuning sets itsm-pilot, itsm-tune; the pipeline was repaired on it in changes 105, 107, 112, 113, 114, 115, 116, 117, 118, 131; held-out sets itsm-unseen (run by aws/gpt-oss-120b, azure/DeepSeek-V4-Pro), itsm-unseen2 (run by azure/DeepSeek-V4-Pro), itsm-unseen3 (run by azure/DeepSeek-V4-Pro); the held-out tasks of this policy are not independent of its tuning.

The checks use no model unless a line names one. Back-translation and verifier numbers are read from saved results.

## Part 1: fidelity to the text

| Check | Result | Note |
|---|---|---|
| Coverage | 0 of 54 must or must-not statements have no outcome (101 statements) | coverage items: definition 14, guidance 21, out_of_scope 6, rule 49, verify 11; policy questions: 0 |
| Values grounded in the source | 1 of 65 rules have a value not found in their source text | source text: the package's own; 0 rules have no source text and are not counted |
| Rules that can never fire | 2 (no trigger tool) |  |
| Unknown tool | 0 |  |
| `validate_package` | 1 errors, 8 warnings | mode: converted package (legacy coverage kinds count, gaps are warnings); invalid_slots (error) 1, rule_conflict (warning) 3, rule_no_trigger (warning) 2, schema_conflict (warning) 2, unknown_field (warning) 1 |
| `rule_conflict` | 3 (errors 0, warnings 3) | 303d3040d9f5 and grant_manager: the duty requires update_incident_sla_details, which grant_manager forbids for the roles ['manager']; 303d3040d9f5 and grant_agent: the duty requires update_incident_sla_details, which grant_agent forbids for the roles ['agent'] (Showing 2 of 3 conflicts.) |
| Cedar validator | passed | 3 role rules |
| Cedar against the rule JSON | 0 of 372 requests differ | 4 roles x 93 tools |
| Back-translation | no data | not run for this package version; it uses models: `rule_audit.py backtrans` |

### Decision tests, through all layers

347 tests from the package: 182 should be denied, 165 should be allowed. Caught = deny or remind by a rule, plus the calls the tool's own schema rejects.

| Run | Caught | of which tool schema | of which only the schema | False denies | False reminders | Errors | Failed verifier calls |
|---|---|---|---|---|---|---|---|
| code and Cedar, no model | 99 of 182 | 20 | 16 | 1 of 165 | 6 of 165 | 0 | - |
| + verifier aws/gpt-oss-120b (2026-11-05T07:59 UTC) | 112 of 182 | 20 | 16 | 1 of 165 | 22 of 165 | 0 | 0 |
| + verifier aws/gpt-oss-120b (2026-11-05T07:59 UTC) | 112 of 182 | 20 | 16 | 1 of 165 | 22 of 165 | 0 | 0 |

Verifier spread over 2 runs: caught 112 to 112; false reminders 22 to 22; false denies 1 to 1. Rows that differ from the first run: 1 of 347. A run made right after another is answered partly from the gateway's cache (it takes a fraction of the time), so this spread is a lower bound; it is one sample, not a range.

By layer, code-only run (a case can be caught by more than one layer; the verifier layer is empty without `--verifier`). 18 allow tests are rejected by the tool schema itself; they are not counted as false denies.

| Layer | Caught (deny or remind) | of which deny | False denies | False reminders |
|---|---|---|---|---|
| schema | 20 | 20 | - | - |
| code | 71 | 61 | 1 | 0 |
| cedar | 14 | 0 | 0 | 6 |
| verifier | 0 | 0 | 0 | 0 |

## Part 2: fidelity to use

182 runs read; skipped: other policy 178 (of 7 policies), no tool calls 1. `replayed`: the tool calls of the run go through this package's code and Cedar checks. `live`: the decisions that a harness run met, from its `audit.jsonl`, when its result names this package version.

Role of the logged-in user, runs by source: roles file 182.

| Source | Runs | Passed runs with a deny | Passed runs with a reminder (false reminders) | Failed runs with a deny | Denies on passed / failed | Reminders on passed / failed |
|---|---|---|---|---|---|---|
| replayed | 182 (93 passed) | 2 of 93 | 18 of 93 | 10 of 89 | 2 / 11 | 26 / 11 |
| live | no data |  |  |  |  |  |

### Denies and reminders per rule (replayed)

| Rule | Type | Source | Deny, passed runs | Deny, failed runs | Remind, passed runs | Remind, failed runs |
|---|---|---|---|---|---|---|
| grant_manager | role_permission | §2 L45 | 0 | 0 | 26 | 11 |
| 686e27675c93 | required_args | §3.1 | 2 | 6 | 0 | 0 |
| r_d17e6233 | derived_value | §4.2 L65 | 0 | 3 | 0 | 0 |
| r_5b90ba65 | transition | §3.3 L47 | 0 | 2 | 0 | 0 |

### Conflicts with graders (rules that denied on a passed run)

| Rule | Type | Source | Denies on passed runs | From | Tasks |
|---|---|---|---|---|---|
| 686e27675c93 | required_args | §3.1 | 2 | replayed | task_20251218_121722_423_1d219d93_8218da6c |
