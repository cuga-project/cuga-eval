# Audit of tau2_airline/airline/skill_v1

Made on 2026-11-05 by `rule_audit.py report`. Package version `3989a8d8c6e3c97f+d977fbd787a8`; made by skill / claude-code / claude-opus. 29 rules, 5 procedures, 19 obligations, 106 decision tests in the package.

## Which numbers these are

**seen, not tuned**: held-out sets tau2-airline-test (run by aws/gpt-oss-120b, azure/DeepSeek-V4-Pro) (no tuning set and no change names it). Note: the official test split (20 tasks) was run before this package existed: the headroom checks `a20_ds` and `a20_oss`, and the no-harm check of the SOP tracker `air1` (arms A and T, 5 trials, change 87). The runs and the agent writes were reviewed (change 87, `tau2/labels.md`). The result of `air1` (tracker 17/20 against 11/20) is the evidence for design decision 1 of the design spec (route by the shape of the policy source), and Task 5.3 (rule-list route) implements that decision and is checked on this package. The package was made from the policy text only and no rule, test or setting was changed from these runs, but the tasks, the runs and the failures are seen: numbers on this split are not a clean bar.

The checks use no model unless a line names one. Back-translation and verifier numbers are read from saved results.

## Part 1: fidelity to the text

| Check | Result | Note |
|---|---|---|
| Coverage | 0 of 59 must or must-not statements have no outcome (117 statements) | coverage items: none; policy questions: 11 |
| Values grounded in the source | 0 of 29 rules have a value not found in their source text | source text: the package's own; 0 rules have no source text and are not counted |
| Rules that can never fire | 0 (no trigger tool) |  |
| Unknown tool | 0 |  |
| `validate_package` | 0 errors, 1 warnings | mode: strict; unbound_value (warning) 1 |
| `rule_conflict` | 0 (errors 0, warnings 0) |  |
| Cedar validator and batch check | no data | the package has no role_permission rule, so no Cedar policy is generated |
| Back-translation | 19 of 23 equivalent; broader 2, different 1, narrower 1 | source text of the judged rules: statements 23; writer aws/gpt-oss-120b, judge azure/DeepSeek-V4-Pro (another model family); not reviewed by a person; backtrans__tau2_airline_airline__skill_v1__azure-DeepSeek-V4-Pro.json |

### Decision tests, through all layers

106 tests from the package: 57 should be denied, 49 should be allowed. Caught = deny or remind by a rule, plus the calls the tool's own schema rejects.

| Run | Caught | of which tool schema | of which only the schema | False denies | False reminders | Errors | Failed verifier calls |
|---|---|---|---|---|---|---|---|
| code and Cedar, no model | 2 of 57 | 0 | 0 | 0 of 49 | 0 of 49 | 0 | - |

By layer, code-only run (a case can be caught by more than one layer; the verifier layer is empty without `--verifier`). 0 allow tests are rejected by the tool schema itself; they are not counted as false denies.

| Layer | Caught (deny or remind) | of which deny | False denies | False reminders |
|---|---|---|---|---|
| schema | 0 | 0 | - | - |
| code | 2 | 2 | 0 | 0 |
| cedar | 0 | 0 | 0 | 0 |
| verifier | 0 | 0 | 0 | 0 |

## Part 2: fidelity to use

60 runs read; skipped: none. `replayed`: the tool calls of the run go through this package's code and Cedar checks. `live`: the decisions that a harness run met, from its `audit.jsonl`, when its result names this package version.

Role of the logged-in user, runs by source: default admin 60.

| Source | Runs | Passed runs with a deny | Passed runs with a reminder (false reminders) | Failed runs with a deny | Denies on passed / failed | Reminders on passed / failed |
|---|---|---|---|---|---|---|
| replayed | 60 (43 passed) | 0 of 43 | 0 of 43 | 0 of 17 | 0 / 0 | 0 / 0 |
| live | no data |  |  |  |  |  |

### Conflicts with graders (rules that denied on a passed run)

None.
