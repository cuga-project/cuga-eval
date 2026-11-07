# Audit of itsm/d5ab75ff0f/skill_v1

Made on 2026-11-05 by `rule_audit.py report`. Package version `63cb577df701cdab+7f9f7d977470`; made by skill / claude-code / claude-sonnet. 92 rules, 8 procedures, 22 obligations, 0 decision tests in the package.

## Which numbers these are

**tuning**: the pipeline was repaired on it in changes 131; held-out sets itsm-unseen (run by aws/gpt-oss-120b, azure/DeepSeek-V4-Pro); the held-out tasks of this policy are not independent of its tuning.

The checks use no model unless a line names one. Back-translation and verifier numbers are read from saved results.

## Part 1: fidelity to the text

| Check | Result | Note |
|---|---|---|
| Coverage | 0 of 98 must or must-not statements have no outcome (168 statements) | coverage items: none; policy questions: 69 |
| Values grounded in the source | 0 of 91 rules have a value not found in their source text | source text: the package's own; 1 rules have no source text and are not counted |
| Rules that can never fire | 0 (no trigger tool) |  |
| Unknown tool | 0 |  |
| `validate_package` | 0 errors, 11 warnings | mode: strict; not_in_text (warning) 1, rule_conflict (warning) 9, schema_conflict (warning) 1 |
| `rule_conflict` | 9 (errors 0, warnings 9) | r_sla_pause_duty and r_manager_grant: the duty requires update_incident_sla_details, which r_manager_grant forbids for the roles ['manager']; r_sla_pause_duty and r_agent_grant: the duty requires update_incident_sla_details, which r_agent_grant forbids for the roles ['agent'] (Showing 2 of 9 conflicts.) |
| Cedar validator | passed | 4 role rules |
| Cedar against the rule JSON | 0 of 279 requests differ | 3 roles x 93 tools |
| Back-translation | 35 of 75 equivalent; broader 6, different 22, narrower 12 | source text of the judged rules: statements 75; 1 rules with no source text not judged; writer aws/gpt-oss-120b, judge azure/DeepSeek-V4-Pro (another model family); not reviewed by a person; backtrans__itsm_d5ab75ff0f__skill_v1__azure-DeepSeek-V4-Pro.json |

### Decision tests, through all layers

No data: the package has no `tests`.

## Part 2: fidelity to use

13 runs read; skipped: other policy 348 (of 7 policies). `replayed`: the tool calls of the run go through this package's code and Cedar checks. `live`: the decisions that a harness run met, from its `audit.jsonl`, when its result names this package version.

Role of the logged-in user, runs by source: roles file 13.

| Source | Runs | Passed runs with a deny | Passed runs with a reminder (false reminders) | Failed runs with a deny | Denies on passed / failed | Reminders on passed / failed |
|---|---|---|---|---|---|---|
| replayed | 13 (0 passed) | 0 of 0 | 0 of 0 | 0 of 13 | 0 / 0 | 0 / 15 |
| live | no data |  |  |  |  |  |

### Denies and reminders per rule (replayed)

| Rule | Type | Source | Deny, passed runs | Deny, failed runs | Remind, passed runs | Remind, failed runs |
|---|---|---|---|---|---|---|
| r_manager_grant | role_permission |  | 0 | 0 | 0 | 15 |

### Conflicts with graders (rules that denied on a passed run)

None.
