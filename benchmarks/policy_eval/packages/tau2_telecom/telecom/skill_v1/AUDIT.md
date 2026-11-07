# Audit of tau2_telecom/telecom/skill_v1

Made on 2026-11-05 by `rule_audit.py report`. Package version `e282f27bd1893c22+db1a81b39165`; made by skill / claude-code / claude-opus. 19 rules, 9 procedures, 29 obligations, 95 decision tests in the package.

## Which numbers these are

**tuning**: tuning sets tau2-telecom-dev20; held-out sets tau2-telecom-fresh40 (run by azure/DeepSeek-V4-Pro), tau2-telecom-test (run by aws/gpt-oss-120b, azure/DeepSeek-V4-Pro); the held-out tasks of this policy are not independent of its tuning.

The checks use no model unless a line names one. Back-translation and verifier numbers are read from saved results.

## Part 1: fidelity to the text

| Check | Result | Note |
|---|---|---|
| Coverage | 0 of 63 must or must-not statements have no outcome (267 statements) | coverage items: none; policy questions: 14 |
| Values grounded in the source | 0 of 19 rules have a value not found in their source text | source text: the package's own; 0 rules have no source text and are not counted |
| Rules that can never fire | 0 (no trigger tool) |  |
| Unknown tool | 0 |  |
| `validate_package` | 0 errors, 1 warnings | mode: strict; unbound_value (warning) 1 |
| `rule_conflict` | 0 (errors 0, warnings 0) |  |
| Cedar validator and batch check | no data | the package has no role_permission rule, so no Cedar policy is generated |
| Back-translation | 8 of 13 equivalent; broader 2, different 3 | source text of the judged rules: statements 13; writer aws/gpt-oss-120b, judge azure/DeepSeek-V4-Pro (another model family); not reviewed by a person; backtrans__tau2_telecom_telecom__skill_v1__azure-DeepSeek-V4-Pro.json |

### Decision tests, through all layers

95 tests from the package: 51 should be denied, 44 should be allowed. Caught = deny or remind by a rule, plus the calls the tool's own schema rejects.

| Run | Caught | of which tool schema | of which only the schema | False denies | False reminders | Errors | Failed verifier calls |
|---|---|---|---|---|---|---|---|
| code and Cedar, no model | 7 of 51 | 0 | 0 | 0 of 44 | 0 of 44 | 0 | - |

By layer, code-only run (a case can be caught by more than one layer; the verifier layer is empty without `--verifier`). 0 allow tests are rejected by the tool schema itself; they are not counted as false denies.

| Layer | Caught (deny or remind) | of which deny | False denies | False reminders |
|---|---|---|---|---|
| schema | 0 | 0 | - | - |
| code | 7 | 7 | 0 | 0 |
| cedar | 0 | 0 | 0 | 0 |
| verifier | 0 | 0 | 0 | 0 |

## Part 2: fidelity to use

140 runs read; skipped: none. `replayed`: the tool calls of the run go through this package's code and Cedar checks. `live`: the decisions that a harness run met, from its `audit.jsonl`, when its result names this package version.

Role of the logged-in user, runs by source: default admin 140.

| Source | Runs | Passed runs with a deny | Passed runs with a reminder (false reminders) | Failed runs with a deny | Denies on passed / failed | Reminders on passed / failed |
|---|---|---|---|---|---|---|
| replayed | 140 (95 passed) | 1 of 95 | 0 of 95 | 20 of 45 | 1 / 20 | 0 / 0 |
| live | no data |  |  |  |  |  |

### Denies and reminders per rule (replayed)

| Rule | Type | Source | Deny, passed runs | Deny, failed runs | Remind, passed runs | Remind, failed runs |
|---|---|---|---|---|---|---|
| r_request_only_overdue | reference_status |  | 1 | 20 | 0 | 0 |

### Conflicts with graders (rules that denied on a passed run)

| Rule | Type | Source | Denies on passed runs | From | Tasks |
|---|---|---|---|---|---|
| r_request_only_overdue | reference_status |  | 1 | replayed | [service_issue]airplane_mode_on|break_apn_settings[PERSONA:Hard] |
