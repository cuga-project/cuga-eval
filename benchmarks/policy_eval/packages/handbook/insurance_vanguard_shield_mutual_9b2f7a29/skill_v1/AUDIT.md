# Audit of handbook/insurance_vanguard_shield_mutual_9b2f7a29/skill_v1

Made on 2026-11-05 by `rule_audit.py report`. Package version `612138ae04d49c94+9ea93c302570`; made by skill / claude-code / claude-opus. 15 rules, 17 procedures, 118 obligations, 331 decision tests in the package.

## Which numbers these are

**tuning**: tuning sets handbook-public3.

The checks use no model unless a line names one. Back-translation and verifier numbers are read from saved results.

## Part 1: fidelity to the text

| Check | Result | Note |
|---|---|---|
| Coverage | 0 of 137 must or must-not statements have no outcome (337 statements) | coverage items: none; policy questions: 14 |
| Values grounded in the source | 0 of 15 rules have a value not found in their source text | source text: the package's own; 0 rules have no source text and are not counted |
| Rules that can never fire | 0 (no trigger tool) |  |
| Unknown tool | 0 |  |
| `validate_package` | 0 errors, 12 warnings | mode: strict; unbound_value (warning) 12 |
| `rule_conflict` | 0 (errors 0, warnings 0) |  |
| Cedar validator and batch check | no data | the package has no role_permission rule, so no Cedar policy is generated |
| Back-translation | 0 of 5 equivalent; broader 3, different 1, narrower 1 | source text of the judged rules: statements 5; writer aws/gpt-oss-120b, judge azure/DeepSeek-V4-Pro (another model family); not reviewed by a person; backtrans__handbook_insurance_vanguard_shield_mutual_9b2f7a29__skill_v1__azure-DeepSeek-V4-Pro.json |

### Decision tests, through all layers

331 tests from the package: 179 should be denied, 152 should be allowed. Caught = deny or remind by a rule, plus the calls the tool's own schema rejects.

| Run | Caught | of which tool schema | of which only the schema | False denies | False reminders | Errors | Failed verifier calls |
|---|---|---|---|---|---|---|---|
| code and Cedar, no model | 108 of 179 | 107 | 107 | 0 of 152 | 0 of 152 | 0 | - |

By layer, code-only run (a case can be caught by more than one layer; the verifier layer is empty without `--verifier`). 94 allow tests are rejected by the tool schema itself; they are not counted as false denies.

| Layer | Caught (deny or remind) | of which deny | False denies | False reminders |
|---|---|---|---|---|
| schema | 107 | 107 | - | - |
| code | 1 | 1 | 0 | 0 |
| cedar | 0 | 0 | 0 | 0 |
| verifier | 0 | 0 | 0 | 0 |

## Part 2: fidelity to use

51 runs read; skipped: none. `replayed`: the tool calls of the run go through this package's code and Cedar checks. `live`: the decisions that a harness run met, from its `audit.jsonl`, when its result names this package version.

Role of the logged-in user, runs by source: default admin 51.

| Source | Runs | Passed runs with a deny | Passed runs with a reminder (false reminders) | Failed runs with a deny | Denies on passed / failed | Reminders on passed / failed |
|---|---|---|---|---|---|---|
| replayed | 51 (2 passed) | 0 of 2 | 0 of 2 | 0 of 49 | 0 / 0 | 0 / 0 |
| live | no data |  |  |  |  |  |

### Conflicts with graders (rules that denied on a passed run)

None.
