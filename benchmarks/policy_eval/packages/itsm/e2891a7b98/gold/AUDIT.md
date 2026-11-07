# Audit of itsm/e2891a7b98/gold

Made on 2026-11-05 by `rule_audit.py report`. Package version `b070b1ebff10dc96+af2afae52e51`; made by skill / claude-code / claude (gold, reviewed by a person later). 96 rules, 0 procedures, 0 obligations, 347 decision tests in the package.

## Which numbers these are

**gold, tuning**: this is the reference build of the policy. The policy: tuning sets itsm-pilot, itsm-tune; the pipeline was repaired on it in changes 105, 107, 112, 113, 114, 115, 116, 117, 118, 131; held-out sets itsm-unseen (run by aws/gpt-oss-120b, azure/DeepSeek-V4-Pro), itsm-unseen2 (run by azure/DeepSeek-V4-Pro), itsm-unseen3 (run by azure/DeepSeek-V4-Pro); the held-out tasks of this policy are not independent of its tuning.

The checks use no model unless a line names one. Back-translation and verifier numbers are read from saved results.

Note: Earlier verifier runs on these tests, from before the package format (research note section 3, change 118): caught 148, false reminders 65 to 71.

## Part 1: fidelity to the text

| Check | Result | Note |
|---|---|---|
| Coverage | no data | the package holds no policy text (`documents` is empty), so statements cannot be counted |
| Values grounded in the source | 4 of 96 rules have a value not found in their source text | source text: the statements of package `builds` of the same policy; 0 rules have no source text and are not counted |
| Rules that can never fire | 7 (no trigger tool) |  |
| Unknown tool | 0 |  |
| `validate_package` | 0 errors, 9 warnings | mode: converted package (legacy coverage kinds count, gaps are warnings); rule_no_trigger (warning) 7, schema_conflict (warning) 2 |
| `rule_conflict` | 0 (errors 0, warnings 0) |  |
| Cedar validator | passed | 3 role rules |
| Cedar against the rule JSON | 0 of 372 requests differ | 4 roles x 93 tools |
| Back-translation | 50 of 79 equivalent; broader 4, different 19, narrower 6 | source text of the judged rules: statements 79, from package `builds` of the same policy; writer aws/gpt-oss-120b, judge azure/DeepSeek-V4-Pro (another model family); not reviewed by a person; backtrans__itsm_e2891a7b98__gold__azure-DeepSeek-V4-Pro__2.json |

### Decision tests, through all layers

347 tests from the package: 182 should be denied, 165 should be allowed. Caught = deny or remind by a rule, plus the calls the tool's own schema rejects.

| Run | Caught | of which tool schema | of which only the schema | False denies | False reminders | Errors | Failed verifier calls |
|---|---|---|---|---|---|---|---|
| code and Cedar, no model | 97 of 182 | 20 | 5 | 1 of 165 | 5 of 165 | 0 | - |
| + verifier aws/gpt-oss-120b (2026-11-05T07:57 UTC) | 150 of 182 | 20 | 5 | 1 of 165 | 71 of 165 | 0 | 0 |
| + verifier aws/gpt-oss-120b (2026-11-05T07:57 UTC) | 152 of 182 | 20 | 5 | 1 of 165 | 72 of 165 | 0 | 0 |

Verifier spread over 2 runs: caught 150 to 152; false reminders 71 to 72; false denies 1 to 1. Rows that differ from the first run: 7 of 347. A run made right after another is answered partly from the gateway's cache (it takes a fraction of the time), so this spread is a lower bound; it is one sample, not a range.

By layer, code-only run (a case can be caught by more than one layer; the verifier layer is empty without `--verifier`). 18 allow tests are rejected by the tool schema itself; they are not counted as false denies.

| Layer | Caught (deny or remind) | of which deny | False denies | False reminders |
|---|---|---|---|---|
| schema | 20 | 20 | - | - |
| code | 89 | 88 | 1 | 5 |
| cedar | 3 | 3 | 0 | 0 |
| verifier | 0 | 0 | 0 | 0 |

## Part 2: fidelity to use

182 runs read; skipped: other policy 178 (of 7 policies), no tool calls 1. `replayed`: the tool calls of the run go through this package's code and Cedar checks. `live`: the decisions that a harness run met, from its `audit.jsonl`, when its result names this package version.

Role of the logged-in user, runs by source: roles file 182.

| Source | Runs | Passed runs with a deny | Passed runs with a reminder (false reminders) | Failed runs with a deny | Denies on passed / failed | Reminders on passed / failed |
|---|---|---|---|---|---|---|
| replayed | 182 (93 passed) | 9 of 93 | 0 of 93 | 13 of 89 | 10 / 16 | 0 / 0 |
| live | no data |  |  |  |  |  |

### Denies and reminders per rule (replayed)

| Rule | Type | Source | Deny, passed runs | Deny, failed runs | Remind, passed runs | Remind, failed runs |
|---|---|---|---|---|---|---|
| g_6225b57a3e | role_permission | §2 L45 | 8 | 5 | 0 | 0 |
| g_54288cf650 | required_args | §3.1 L59 | 2 | 6 | 0 | 0 |
| g_971b9a9e6c | derived_value | §3.1 L61 | 0 | 3 | 0 | 0 |
| g_3bfa687538 | transition | §3.3 L93 | 0 | 2 | 0 | 0 |

### Conflicts with graders (rules that denied on a passed run)

| Rule | Type | Source | Denies on passed runs | From | Tasks |
|---|---|---|---|---|---|
| g_6225b57a3e | role_permission | §2 L45 | 8 | replayed | task_20260114_174427_042_99ba2325_7915481a |
| g_54288cf650 | required_args | §3.1 L59 | 2 | replayed | task_20251218_121722_423_1d219d93_8218da6c |
