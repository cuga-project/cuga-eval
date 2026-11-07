# Audit of itsm/2e555b5177/skill_v1

Made on 2026-11-05 by `rule_audit.py report`. Package version `892a7fed28f1f90e+2846d10c9d57`; made by skill / claude-code / claude-sonnet. 68 rules, 8 procedures, 17 obligations, 0 decision tests in the package.

## Which numbers these are

**tuning**: tuning sets itsm-pilot; held-out sets itsm-unseen (run by aws/gpt-oss-120b, azure/DeepSeek-V4-Pro), itsm-unseen2 (run by azure/DeepSeek-V4-Pro), itsm-unseen3 (run by azure/DeepSeek-V4-Pro); the held-out tasks of this policy are not independent of its tuning.

The checks use no model unless a line names one. Back-translation and verifier numbers are read from saved results.

## Part 1: fidelity to the text

| Check | Result | Note |
|---|---|---|
| Coverage | 0 of 75 must or must-not statements have no outcome (96 statements) | coverage items: none; policy questions: 52 |
| Values grounded in the source | 0 of 68 rules have a value not found in their source text | source text: the package's own; 0 rules have no source text and are not counted |
| Rules that can never fire | 0 (no trigger tool) |  |
| Unknown tool | 0 |  |
| `validate_package` | 0 errors, 5 warnings | mode: strict; rule_conflict (warning) 4, schema_conflict (warning) 1 |
| `rule_conflict` | 4 (errors 0, warnings 4) | r_sla_pause_duty and r_manager_grant: the duty requires update_incident_sla_details, which r_manager_grant forbids for the roles ['manager']; r_sla_pause_duty and r_agent_grant: the duty requires update_incident_sla_details, which r_agent_grant forbids for the roles ['agent'] (Showing 2 of 4 conflicts.) |
| Cedar validator | passed | 4 role rules |
| Cedar against the rule JSON | 0 of 279 requests differ | 3 roles x 93 tools |
| Back-translation | 27 of 54 equivalent; broader 3, different 13, narrower 11 | source text of the judged rules: statements 54; writer aws/gpt-oss-120b, judge azure/DeepSeek-V4-Pro (another model family); not reviewed by a person; backtrans__itsm_2e555b5177__skill_v1__azure-DeepSeek-V4-Pro.json |

### Decision tests, through all layers

No data: the package has no `tests`.

## Part 2: fidelity to use

20 runs read; skipped: other policy 341 (of 7 policies). `replayed`: the tool calls of the run go through this package's code and Cedar checks. `live`: the decisions that a harness run met, from its `audit.jsonl`, when its result names this package version.

Role of the logged-in user, runs by source: roles file 17, default admin 3. The default is `admin`, which no role rule forbids: with role rules in the package, the reminders and denies of those rules are undercounted for every run on the default.

| Source | Runs | Passed runs with a deny | Passed runs with a reminder (false reminders) | Failed runs with a deny | Denies on passed / failed | Reminders on passed / failed |
|---|---|---|---|---|---|---|
| replayed | 20 (4 passed) | 1 of 4 | 1 of 4 | 0 of 16 | 3 / 0 | 1 / 0 |
| live | no data |  |  |  |  |  |

### Denies and reminders per rule (replayed)

| Rule | Type | Source | Deny, passed runs | Deny, failed runs | Remind, passed runs | Remind, failed runs |
|---|---|---|---|---|---|---|
| r_incident_transition | transition |  | 1 | 0 | 1 | 0 |
| r_resolution_fields | required_args |  | 2 | 0 | 0 | 0 |

### Conflicts with graders (rules that denied on a passed run)

| Rule | Type | Source | Denies on passed runs | From | Tasks |
|---|---|---|---|---|---|
| r_resolution_fields | required_args |  | 2 | replayed | task_20251223_153021_454_66392a82_0d6d8897 |
| r_incident_transition | transition |  | 1 | replayed | task_20251223_153021_454_66392a82_0d6d8897 |
