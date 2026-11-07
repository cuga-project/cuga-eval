# Audit of automationbench/marketing.trending_topic/gold

Made on 2026-11-05 by `rule_audit.py report`. Package version `fae8e8658c01b78f+6fd004f966d1`; made by skill / claude-code / claude (gold, reviewed by a person later). 13 rules, 0 procedures, 0 obligations, 0 decision tests in the package.

## Which numbers these are

**gold, tuning**: this is the reference build of the policy. The policy: tuning sets ab-tune.

The checks use no model unless a line names one. Back-translation and verifier numbers are read from saved results.

## Part 1: fidelity to the text

| Check | Result | Note |
|---|---|---|
| Coverage | no data | the package holds no policy text (`documents` is empty), so statements cannot be counted |
| Values grounded in the source | no data | no policy text in the package or in any package of the same policy |
| Rules that can never fire | 0 (no trigger tool) |  |
| Unknown tool | 0 |  |
| `validate_package` | 0 errors, 0 warnings | mode: converted package (legacy coverage kinds count, gaps are warnings); no finding |
| `rule_conflict` | 0 (errors 0, warnings 0) |  |
| Cedar validator and batch check | no data | the package has no role_permission rule, so no Cedar policy is generated |
| Back-translation | no data | not run for this package version; it uses models: `rule_audit.py backtrans` |

### Decision tests, through all layers

No data: the package has no `tests`.

## Part 2: fidelity to use

15 runs read; skipped: no tool calls 1. `replayed`: the tool calls of the run go through this package's code and Cedar checks. `live`: the decisions that a harness run met, from its `audit.jsonl`, when its result names this package version.

Role of the logged-in user, runs by source: default admin 15.

| Source | Runs | Passed runs with a deny | Passed runs with a reminder (false reminders) | Failed runs with a deny | Denies on passed / failed | Reminders on passed / failed |
|---|---|---|---|---|---|---|
| replayed | 15 (0 passed) | 0 of 0 | 0 of 0 | 12 of 15 | 0 / 18 | 0 / 0 |
| live | no data |  |  |  |  |  |

### Denies and reminders per rule (replayed)

| Rule | Type | Source | Deny, passed runs | Deny, failed runs | Remind, passed runs | Remind, failed runs |
|---|---|---|---|---|---|---|
| g_58b95e52ad | format | slack_msg_vp_trend §preamble step 4 | 0 | 18 | 0 | 0 |

### Conflicts with graders (rules that denied on a passed run)

None.
