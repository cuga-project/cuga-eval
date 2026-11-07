# Audit of itsm/c47f8ceef3/skill_v1

Made on 2026-11-05 by `rule_audit.py report`. Package version `07eebaa5b7383398+64cefefcb299`; made by skill / claude-code / claude-sonnet. 72 rules, 8 procedures, 21 obligations, 0 decision tests in the package.

## Which numbers these are

**tuning**: tuning sets itsm-pilot, itsm-xref; held-out sets itsm-unseen2 (run by azure/DeepSeek-V4-Pro), itsm-unseen3 (run by azure/DeepSeek-V4-Pro); the held-out tasks of this policy are not independent of its tuning.

The checks use no model unless a line names one. Back-translation and verifier numbers are read from saved results.

## Part 1: fidelity to the text

| Check | Result | Note |
|---|---|---|
| Coverage | 0 of 76 must or must-not statements have no outcome (99 statements) | coverage items: none; policy questions: 57 |
| Values grounded in the source | 0 of 72 rules have a value not found in their source text | source text: the package's own; 0 rules have no source text and are not counted |
| Rules that can never fire | 0 (no trigger tool) |  |
| Unknown tool | 0 |  |
| `validate_package` | 0 errors, 7 warnings | mode: strict; rule_conflict (warning) 6, schema_conflict (warning) 1 |
| `rule_conflict` | 6 (errors 0, warnings 6) | r_sla_pause_duty and r_manager_grant: the duty requires update_incident_sla_details, which r_manager_grant forbids for the roles ['manager']; r_sla_pause_duty and r_agent_grant: the duty requires update_incident_sla_details, which r_agent_grant forbids for the roles ['agent'] (Showing 2 of 6 conflicts.) |
| Cedar validator | passed | 4 role rules |
| Cedar against the rule JSON | 0 of 279 requests differ | 3 roles x 93 tools |
| Back-translation | 24 of 57 equivalent; broader 4, different 17, narrower 12 | source text of the judged rules: statements 57; writer aws/gpt-oss-120b, judge azure/DeepSeek-V4-Pro (another model family); not reviewed by a person; backtrans__itsm_c47f8ceef3__skill_v1__azure-DeepSeek-V4-Pro.json |

### Decision tests, through all layers

No data: the package has no `tests`.

## Part 2: fidelity to use

21 runs read; skipped: other policy 340 (of 7 policies). `replayed`: the tool calls of the run go through this package's code and Cedar checks. `live`: the decisions that a harness run met, from its `audit.jsonl`, when its result names this package version.

Role of the logged-in user, runs by source: roles file 13, default admin 8. The default is `admin`, which no role rule forbids: with role rules in the package, the reminders and denies of those rules are undercounted for every run on the default.

| Source | Runs | Passed runs with a deny | Passed runs with a reminder (false reminders) | Failed runs with a deny | Denies on passed / failed | Reminders on passed / failed |
|---|---|---|---|---|---|---|
| replayed | 21 (10 passed) | 0 of 10 | 0 of 10 | 0 of 11 | 0 / 0 | 0 / 6 |
| live | no data |  |  |  |  |  |

### Denies and reminders per rule (replayed)

| Rule | Type | Source | Deny, passed runs | Deny, failed runs | Remind, passed runs | Remind, failed runs |
|---|---|---|---|---|---|---|
| r_manager_grant | role_permission |  | 0 | 0 | 0 | 6 |

### Conflicts with graders (rules that denied on a passed run)

None.
