# Gold policy builds (tuning policies only)

Reference builds used to measure the policy intake methods (Task 13) and the offline generators (Task 14).
Unseen-set policies have no gold build and were not opened.

| Gold | Built by | Reviewed by | Result |
|---|---|---|---|
| `itsm-e2891a7b98.build.json` (also valid for versions 933219af01 and 7bb25d850c: same statements) | Claude agent following `skill/SKILL.md`, from a gpt-oss-120b pipeline draft | A second, fresh Claude agent; open judgment calls decided by Claude (main session) | 96 rules; 0 errors, 2 `schema_conflict` warnings |
| `ab/<task>/build.json` (10 AutomationBench tuning tasks) | Claude agent following `skill/SKILL.md` | A second, fresh Claude agent; decisions accepted by Claude (main session) | 0 errors, 0 warnings each |

**Review status:** the user asked Claude to do the review (2026-11-01). The builds were **not reviewed by a
person**. Errors that the builder and the reviewer share would not have been found.

Pre-review copies (`*.prereview.json`) are kept. They are the "skill run by Claude Code" generator in the
comparison of generators.

## Review decisions (main session, 2026-11-01)

| Item | Decision | Why |
|---|---|---|
| ITSM reviewer changes (2:2 type → `role_permission`; links 1:12 → 1:11 and 4.1:4 → 9:8) | Accepted | The text supports them |
| ITSM 9:7 `resolution_code` rules (`g_996958cb41`, `g_d6f08d716e`) | Remind only | Policy values and the tool enum share no value; the rule can never be followed |
| ITSM 3.3:8 72-hour closure (`g_77c9cc41a7`) | Remind only | Describes system behavior; a deny could block a manual resolved → closed |
| ITSM 8.1:4 work-log fields (`g_a6d9ba8c32`) | Remind only | No tool has those arguments |
| ITSM role rules from grant lists (2:5–2:7), scope limited to the tables the role table names | Kept as built | Narrow scope gives fewer false denies; extending needs a person |
| ITSM 8.1:2 "user passed to update_user_details must be active" | Kept as built (literal) | The text says it; the runtime may still choose remind-only by measurement |
| ITSM section headings typed `definition` | Kept; scorers skip heading-like statements in type accuracy | Convention, not a policy reading |
| AutomationBench reviewer fixes (xero CC rule remind-only; linkedin record_condition tools; helpcrunch type) | Accepted | Clear errors, checked against the task data |
| AutomationBench six flagged judgment calls (trending_topic, prepaid_amortization, xero, hr, helpcrunch, zendesk) | Builder's readings kept | The reviewer agreed independently |

Problems found in the policy layer itself during the review are in `../changes.md` (items 6–9).
