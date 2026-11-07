# Audit of itsm/e2891a7b98/skill_v1

Made on 2026-11-05 by `rule_audit.py report`. Package version `892a7fed28f1f90e+54bac94f7e8b`; made by skill / claude-code / claude-opus. 68 rules, 8 procedures, 17 obligations, 347 decision tests in the package.

## Which numbers these are

**tuning**: tuning sets itsm-pilot, itsm-tune; the pipeline was repaired on it in changes 105, 107, 112, 113, 114, 115, 116, 117, 118, 131; held-out sets itsm-unseen (run by aws/gpt-oss-120b, azure/DeepSeek-V4-Pro), itsm-unseen2 (run by azure/DeepSeek-V4-Pro), itsm-unseen3 (run by azure/DeepSeek-V4-Pro); the held-out tasks of this policy are not independent of its tuning.

The checks use no model unless a line names one. Back-translation and verifier numbers are read from saved results.

## Part 1: fidelity to the text

| Check | Result | Note |
|---|---|---|
| Coverage | 0 of 75 must or must-not statements have no outcome (96 statements) | coverage items: none; policy questions: 52 |
| Values grounded in the source | 0 of 68 rules have a value not found in their source text | source text: the package's own; 0 rules have no source text and are not counted |
| Rules that can never fire | 0 (no trigger tool) |  |
| Unknown tool | 0 |  |
| `validate_package` | 0 errors, 5 warnings | mode: strict; rule_conflict (warning) 4, schema_conflict (warning) 1 |
| `rule_conflict` | 4 (errors 0, warnings 4) | r_sla_pause_duty and r_manager_grant: the duty requires update_incident_sla_details, which r_manager_grant forbids for the roles ['manager']; r_sla_pause_duty and r_agent_grant: the duty requires update_incident_sla_details, which r_agent_grant forbids for the roles ['agent'] (Showing 2 of 4 conflicts.) |
| Cedar validator | passed | 4 role rules |
| Cedar against the rule JSON | 0 of 372 requests differ | 4 roles x 93 tools |
| Back-translation | 27 of 54 equivalent; broader 3, different 13, narrower 11 | source text of the judged rules: statements 54; writer aws/gpt-oss-120b, judge azure/DeepSeek-V4-Pro (another model family); not reviewed by a person; backtrans__itsm_e2891a7b98__skill_v1__azure-DeepSeek-V4-Pro.json |

### Decision tests, through all layers

347 tests from the package: 182 should be denied, 165 should be allowed. Caught = deny or remind by a rule, plus the calls the tool's own schema rejects.

| Run | Caught | of which tool schema | of which only the schema | False denies | False reminders | Errors | Failed verifier calls |
|---|---|---|---|---|---|---|---|
| code and Cedar, no model | 106 of 182 | 20 | 11 | 0 of 165 | 6 of 165 | 0 | - |

By layer, code-only run (a case can be caught by more than one layer; the verifier layer is empty without `--verifier`). 18 allow tests are rejected by the tool schema itself; they are not counted as false denies.

| Layer | Caught (deny or remind) | of which deny | False denies | False reminders |
|---|---|---|---|---|
| schema | 20 | 20 | - | - |
| code | 84 | 66 | 0 | 1 |
| cedar | 13 | 1 | 0 | 5 |
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
| r_manager_grant | role_permission |  | 0 | 0 | 26 | 11 |
| r_incident_required | required_args |  | 2 | 6 | 0 | 0 |
| r_incident_priority_matrix | derived_value |  | 0 | 3 | 0 | 0 |
| r_incident_transition | transition |  | 0 | 2 | 0 | 0 |

### Conflicts with graders (rules that denied on a passed run)

| Rule | Type | Source | Denies on passed runs | From | Tasks |
|---|---|---|---|---|---|
| r_incident_required | required_args |  | 2 | replayed | task_20251218_121722_423_1d219d93_8218da6c |
