# Audit of handbook/medical_careig_specialty_pharmacy_f5947c33/skill_v1

Made on 2026-11-05 by `rule_audit.py report`. Package version `77e01a1a98bdda75+3caffd465afd`; made by skill / claude-code / claude-opus. 42 rules, 26 procedures, 166 obligations, 647 decision tests in the package.

## Which numbers these are

**tuning**: tuning sets handbook-public3.

The checks use no model unless a line names one. Back-translation and verifier numbers are read from saved results.

## Part 1: fidelity to the text

| Check | Result | Note |
|---|---|---|
| Coverage | 0 of 305 must or must-not statements have no outcome (489 statements) | coverage items: none; policy questions: 25 |
| Values grounded in the source | 0 of 42 rules have a value not found in their source text | source text: the package's own; 0 rules have no source text and are not counted |
| Rules that can never fire | 0 (no trigger tool) |  |
| Unknown tool | 0 |  |
| `validate_package` | 0 errors, 0 warnings | mode: strict; no finding |
| `rule_conflict` | 0 (errors 0, warnings 0) |  |
| Cedar validator | passed | 7 role rules |
| Cedar against the rule JSON | 0 of 820 requests differ | 10 roles x 82 tools |
| Back-translation | 5 of 26 equivalent; broader 5, different 11, narrower 5 | source text of the judged rules: statements 26; writer aws/gpt-oss-120b, judge azure/DeepSeek-V4-Pro (another model family); not reviewed by a person; backtrans__handbook_medical_careig_specialty_pharmacy_f5947c33__skill_v1__azure-DeepSeek-V4-Pro.json |

### Decision tests, through all layers

647 tests from the package: 345 should be denied, 302 should be allowed. Caught = deny or remind by a rule, plus the calls the tool's own schema rejects.

| Run | Caught | of which tool schema | of which only the schema | False denies | False reminders | Errors | Failed verifier calls |
|---|---|---|---|---|---|---|---|
| code and Cedar, no model | 2 of 345 | 0 | 0 | 0 of 302 | 0 of 302 | 0 | - |

By layer, code-only run (a case can be caught by more than one layer; the verifier layer is empty without `--verifier`). 0 allow tests are rejected by the tool schema itself; they are not counted as false denies.

| Layer | Caught (deny or remind) | of which deny | False denies | False reminders |
|---|---|---|---|---|
| schema | 0 | 0 | - | - |
| code | 2 | 2 | 0 | 0 |
| cedar | 0 | 0 | 0 | 0 |
| verifier | 0 | 0 | 0 | 0 |

## Part 2: fidelity to use

54 runs read; skipped: none. `replayed`: the tool calls of the run go through this package's code and Cedar checks. `live`: the decisions that a harness run met, from its `audit.jsonl`, when its result names this package version.

Role of the logged-in user, runs by source: default admin 54. The default is `admin`, which no role rule forbids: with role rules in the package, the reminders and denies of those rules are undercounted for every run on the default.

| Source | Runs | Passed runs with a deny | Passed runs with a reminder (false reminders) | Failed runs with a deny | Denies on passed / failed | Reminders on passed / failed |
|---|---|---|---|---|---|---|
| replayed | 54 (0 passed) | 0 of 0 | 0 of 0 | 0 of 54 | 0 / 0 | 0 / 0 |
| live | no data |  |  |  |  |  |

### Conflicts with graders (rules that denied on a passed run)

None.
