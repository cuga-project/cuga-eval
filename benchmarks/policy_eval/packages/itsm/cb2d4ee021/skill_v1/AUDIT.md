# Audit of itsm/cb2d4ee021/skill_v1

Made on 2026-11-05 by `rule_audit.py report`. Package version `9c26594302897102+13cec0356a1f`; made by skill / claude-code / claude-sonnet. 69 rules, 8 procedures, 18 obligations, 0 decision tests in the package.

## Which numbers these are

**tuning**: tuning sets itsm-xref.

The checks use no model unless a line names one. Back-translation and verifier numbers are read from saved results.

## Part 1: fidelity to the text

| Check | Result | Note |
|---|---|---|
| Coverage | 0 of 76 must or must-not statements have no outcome (98 statements) | coverage items: none; policy questions: 54 |
| Values grounded in the source | 0 of 69 rules have a value not found in their source text | source text: the package's own; 0 rules have no source text and are not counted |
| Rules that can never fire | 0 (no trigger tool) |  |
| Unknown tool | 0 |  |
| `validate_package` | 0 errors, 5 warnings | mode: strict; rule_conflict (warning) 4, schema_conflict (warning) 1 |
| `rule_conflict` | 4 (errors 0, warnings 4) | r_sla_pause_duty and r_manager_grant: the duty requires update_incident_sla_details, which r_manager_grant forbids for the roles ['manager']; r_sla_pause_duty and r_agent_grant: the duty requires update_incident_sla_details, which r_agent_grant forbids for the roles ['agent'] (Showing 2 of 4 conflicts.) |
| Cedar validator | passed | 4 role rules |
| Cedar against the rule JSON | 0 of 279 requests differ | 3 roles x 93 tools |
| Back-translation | 28 of 55 equivalent; broader 3, different 13, narrower 11 | source text of the judged rules: statements 55; writer aws/gpt-oss-120b, judge azure/DeepSeek-V4-Pro (another model family); not reviewed by a person; backtrans__itsm_cb2d4ee021__skill_v1__azure-DeepSeek-V4-Pro.json |

### Decision tests, through all layers

No data: the package has no `tests`.

## Part 2: fidelity to use

3 runs read; skipped: other policy 358 (of 7 policies). `replayed`: the tool calls of the run go through this package's code and Cedar checks. `live`: the decisions that a harness run met, from its `audit.jsonl`, when its result names this package version.

Role of the logged-in user, runs by source: roles file 3.

| Source | Runs | Passed runs with a deny | Passed runs with a reminder (false reminders) | Failed runs with a deny | Denies on passed / failed | Reminders on passed / failed |
|---|---|---|---|---|---|---|
| replayed | 3 (2 passed) | 0 of 2 | 0 of 2 | 0 of 1 | 0 / 0 | 0 / 0 |
| live | no data |  |  |  |  |  |

### Conflicts with graders (rules that denied on a passed run)

None.
