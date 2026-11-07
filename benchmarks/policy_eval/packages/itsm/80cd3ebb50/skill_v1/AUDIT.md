# Audit of itsm/80cd3ebb50/skill_v1

Made on 2026-11-05 by `rule_audit.py report`. Package version `f5d6166d1667d622+e3dd9d1bb0be`; made by skill / claude-code / claude-sonnet. 68 rules, 8 procedures, 18 obligations, 0 decision tests in the package.

## Which numbers these are

**unseen, no run**: no task set and no change names this policy in the `policies` section of the registry.

The checks use no model unless a line names one. Back-translation and verifier numbers are read from saved results.

## Part 1: fidelity to the text

| Check | Result | Note |
|---|---|---|
| Coverage | 0 of 60 must or must-not statements have no outcome (84 statements) | coverage items: none; policy questions: 62 |
| Values grounded in the source | 0 of 68 rules have a value not found in their source text | source text: the package's own; 0 rules have no source text and are not counted |
| Rules that can never fire | 0 (no trigger tool) |  |
| Unknown tool | 0 |  |
| `validate_package` | 0 errors, 9 warnings | mode: strict; rule_conflict (warning) 5, schema_conflict (warning) 4 |
| `rule_conflict` | 5 (errors 0, warnings 5) | r_sla_pause_duty and r_manager_grant: the duty requires update_incident_sla_details, which r_manager_grant forbids for the roles ['manager']; r_sla_pause_duty and r_agent_grant: the duty requires update_incident_sla_details, which r_agent_grant forbids for the roles ['agent'] (Showing 2 of 5 conflicts.) |
| Cedar validator | passed | 4 role rules |
| Cedar against the rule JSON | 0 of 279 requests differ | 3 roles x 93 tools |
| Back-translation | 24 of 54 equivalent; broader 4, different 16, narrower 10 | source text of the judged rules: statements 54; writer aws/gpt-oss-120b, judge azure/DeepSeek-V4-Pro (another model family); not reviewed by a person; backtrans__itsm_80cd3ebb50__skill_v1__azure-DeepSeek-V4-Pro.json |

### Decision tests, through all layers

No data: the package has no `tests`.

## Part 2: fidelity to use

No data: none of the files given is a run of this policy (other policy (933219af01) 76, other policy (e2891a7b98) 183, other policy (d5ab75ff0f) 13, other policy (2e555b5177) 20, other policy (a5e328395b) 14, other policy (7bb25d850c) 31, other policy (c47f8ceef3) 21, other policy (cb2d4ee021) 3).
