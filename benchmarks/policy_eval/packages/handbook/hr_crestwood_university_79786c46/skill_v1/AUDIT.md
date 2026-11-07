# Audit of handbook/hr_crestwood_university_79786c46/skill_v1

Made on 2026-11-05 by `rule_audit.py report`. Package version `1b6339f83fc78944+61a6514f00da`; made by skill / claude-code / claude-opus. 36 rules, 26 procedures, 146 obligations, 654 decision tests in the package.

## Which numbers these are

**tuning**: tuning sets handbook-public3.

The checks use no model unless a line names one. Back-translation and verifier numbers are read from saved results.

## Part 1: fidelity to the text

| Check | Result | Note |
|---|---|---|
| Coverage | 0 of 232 must or must-not statements have no outcome (733 statements) | coverage items: out_of_scope 1; policy questions: 25 |
| Values grounded in the source | 4 of 36 rules have a value not found in their source text | source text: the package's own; 0 rules have no source text and are not counted |
| Rules that can never fire | 0 (no trigger tool) |  |
| Unknown tool | 0 |  |
| `validate_package` | 0 errors, 6 warnings | mode: strict; not_in_text (warning) 6 |
| `rule_conflict` | 0 (errors 0, warnings 0) |  |
| Cedar validator | passed | 1 role rules |
| Cedar against the rule JSON | 0 of 82 requests differ | 1 roles x 82 tools |
| Back-translation | 6 of 20 equivalent; broader 6, different 8 | source text of the judged rules: statements 20; writer aws/gpt-oss-120b, judge azure/DeepSeek-V4-Pro (another model family); not reviewed by a person; backtrans__handbook_hr_crestwood_university_79786c46__skill_v1__azure-DeepSeek-V4-Pro.json |

### Decision tests, through all layers

654 tests from the package: 345 should be denied, 309 should be allowed. Caught = deny or remind by a rule, plus the calls the tool's own schema rejects.

| Run | Caught | of which tool schema | of which only the schema | False denies | False reminders | Errors | Failed verifier calls |
|---|---|---|---|---|---|---|---|
| code and Cedar, no model | 10 of 345 | 0 | 0 | 0 of 309 | 1 of 309 | 0 | - |

By layer, code-only run (a case can be caught by more than one layer; the verifier layer is empty without `--verifier`). 0 allow tests are rejected by the tool schema itself; they are not counted as false denies.

| Layer | Caught (deny or remind) | of which deny | False denies | False reminders |
|---|---|---|---|---|
| schema | 0 | 0 | - | - |
| code | 9 | 4 | 0 | 1 |
| cedar | 1 | 0 | 0 | 0 |
| verifier | 0 | 0 | 0 | 0 |

## Part 2: fidelity to use

60 runs read; skipped: none. `replayed`: the tool calls of the run go through this package's code and Cedar checks. `live`: the decisions that a harness run met, from its `audit.jsonl`, when its result names this package version.

Role of the logged-in user, runs by source: default admin 60. The default is `admin`, which no role rule forbids: with role rules in the package, the reminders and denies of those rules are undercounted for every run on the default.

| Source | Runs | Passed runs with a deny | Passed runs with a reminder (false reminders) | Failed runs with a deny | Denies on passed / failed | Reminders on passed / failed |
|---|---|---|---|---|---|---|
| replayed | 60 (0 passed) | 0 of 0 | 0 of 0 | 5 of 60 | 0 / 6 | 0 / 135 |
| live | no data |  |  |  |  |  |

### Denies and reminders per rule (replayed)

| Rule | Type | Source | Deny, passed runs | Deny, failed runs | Remind, passed runs | Remind, failed runs |
|---|---|---|---|---|---|---|
| r_comment_format | format |  | 0 | 0 | 0 | 96 |
| r_subject_format | format |  | 0 | 0 | 0 | 39 |
| r_ticket_name | format |  | 0 | 6 | 0 | 0 |

### Conflicts with graders (rules that denied on a passed run)

None.
