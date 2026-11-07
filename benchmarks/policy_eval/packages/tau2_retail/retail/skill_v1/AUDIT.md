# Audit of tau2_retail/retail/skill_v1

Made on 2026-11-05 by `rule_audit.py report`. Package version `5e643e86b61954a4+e34d4dea1f2b`; made by skill / claude-code / claude-opus. 31 rules, 6 procedures, 14 obligations, 88 decision tests in the package.

## Which numbers these are

**unseen, no run**: no task set and no change names this policy in the `policies` section of the registry. Note: no run has used this policy (no task set, no change).

The checks use no model unless a line names one. Back-translation and verifier numbers are read from saved results.

## Part 1: fidelity to the text

| Check | Result | Note |
|---|---|---|
| Coverage | 0 of 43 must or must-not statements have no outcome (82 statements) | coverage items: none; policy questions: 7 |
| Values grounded in the source | 0 of 31 rules have a value not found in their source text | source text: the package's own; 0 rules have no source text and are not counted |
| Rules that can never fire | 0 (no trigger tool) |  |
| Unknown tool | 0 |  |
| `validate_package` | 0 errors, 1 warnings | mode: strict; unbound_value (warning) 1 |
| `rule_conflict` | 0 (errors 0, warnings 0) |  |
| Cedar validator and batch check | no data | the package has no role_permission rule, so no Cedar policy is generated |
| Back-translation | 21 of 25 equivalent; broader 3, narrower 1 | source text of the judged rules: statements 25; writer aws/gpt-oss-120b, judge azure/DeepSeek-V4-Pro (another model family); not reviewed by a person; backtrans__tau2_retail_retail__skill_v1__azure-DeepSeek-V4-Pro.json |

### Decision tests, through all layers

88 tests from the package: 47 should be denied, 41 should be allowed. Caught = deny or remind by a rule, plus the calls the tool's own schema rejects.

| Run | Caught | of which tool schema | of which only the schema | False denies | False reminders | Errors | Failed verifier calls |
|---|---|---|---|---|---|---|---|
| code and Cedar, no model | 17 of 47 | 0 | 0 | 0 of 41 | 0 of 41 | 0 | - |

By layer, code-only run (a case can be caught by more than one layer; the verifier layer is empty without `--verifier`). 0 allow tests are rejected by the tool schema itself; they are not counted as false denies.

| Layer | Caught (deny or remind) | of which deny | False denies | False reminders |
|---|---|---|---|---|
| schema | 0 | 0 | - | - |
| code | 17 | 17 | 0 | 0 |
| cedar | 0 | 0 | 0 | 0 |
| verifier | 0 | 0 | 0 | 0 |

## Part 2: fidelity to use

No data: no --runs given.
