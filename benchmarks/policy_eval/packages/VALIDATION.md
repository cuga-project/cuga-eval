# Validation of the converted packages (45 at change 126; 55 after change 131; 70 after change 134, see the last sections)

Change 126 (stabilization task 1.3), run on 2026-11-05, again after fix round 1, and again after change 127 (task 2.1, fix
round 1), which added the 8 filtered ITSM builds as source `builds`. No LLM calls.

```
~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/tools/validate_all.py --findings out.json
```

Validator: `validate_package(pkg, tool_specs, legacy=True)` in the gate repo (`policy/stable`, commit `38326b202`; first
version `9b480b557`). The run never changes a package. All 45 packages were read and checked with no crash.

`legacy=True` means: the legacy coverage kinds count as outcomes, and the two completeness codes (`coverage_incomplete`,
`rule_no_trigger`) are warnings, not errors. Every other code keeps its severity.

## Tool specs

All 45 packages have a spec file, so no package skipped the tool checks.

| Benchmark | Spec file |
|---|---|
| ITSM (25 packages) | `benchmarks/enterpriseops_gym/tasks/itsm_tools.json` |
| AutomationBench (10) | `gold/ab/<id>/tools.json` |
| HANDBOOK (9) | `benchmarks/handbook/tools/<id>.json` |
| τ² Telecom (1) | `tau2/telecom_tools.json` (schema under `parameters`; the validator reads it) |

## Findings

| Code | Severity | Findings | Packages | Correct by hand |
|---|---|---:|---:|---|
| `invalid_slots` | error | 16 | 14 | 16 of 16 |
| `rule_conflict` | error | 12 (6 distinct pairs) | 4 | 6 of 6 as rule defects; 0 of 6 as contradictions in the policy text |
| `rule_conflict` (a duty against a role rule) | warning | 15 (3 distinct pairs) | 5 | 3 of 3 are a real tension; see below |
| `rule_no_trigger` | warning | 963 | 30 | 963 of 963 (all are `verify` rules with `tools: []`); see below for how many should be rules |
| `schema_conflict` | warning | 54 | 25 | 54 of 54 (52 carry the builder's `schema_conflict: true`; the 2 in ITSM `gold` have `may_deny: false` instead) |
| `unknown_field` | warning | 8 | 5 | 8 of 8 (`extra.repair` 5, `extra.repair2` 3) |
| `empty_value` | warning | 2 | 2 | 2 of 2 are right as written; see below |
| `coverage_incomplete` | | 0 | 0 | |
| `unfilled_slot`, `unknown_tool`, `unknown_arg`, `value_not_in_enum`, `quote_not_verbatim`, `unknown_level`, `unknown_class`, `invalid_field`, `duplicate_rule_id`, `coverage_conflict`, `cedar_invalid`, `link_target_missing` | | 0 | 0 | |

What changed since the first run (`9b480b557`): nothing was removed and no error was added. Errors are the same 16 and 12.

What changed with Task 5.3 (change 141): a new warning, `exception_without_rule`, for an `exception_of` link whose source or target statement is held by no rule and is no step of a procedure (a rule list cannot show that exception under its rule). 18 findings on 10 of the 84 packages (HANDBOOK Crestwood `skill_v1`, Vanguard and CareIG `v3`, `v4`, `pipeline_dsv4`, `pipeline_gptoss`, and one AutomationBench gold build); the τ² airline and retail packages have none. Every other finding of every package is the same before and after (compared by package).

What changed with the 8 `itsm/<id>/builds` packages (change 127): 28 `rule_no_trigger` and 18 `schema_conflict` warnings, nothing else.
The 8 files are what the IT service runner reads by default (`policy_eval/builds/<id>.json`, after the tuning filters). Errors are
still the same 16 and 12, and no new code appears.
Added: 15 `rule_conflict` warnings (a duty against a role rule, new in fix round 1) and 2 `empty_value` warnings (an empty string
among `values`, new). One thing that the new checks first flagged is not a finding: the Telecom definition `<main_policy>` is the
policy's own tag, so definition terms, sentences and questions are text slots with no placeholder check.

Per package: the table at the end.

### Expected items

| Expected | Result |
|---|---|
| The two `resolution_code` schema conflicts on ITSM | Present: `create_incident.resolution_code` and `update_incident.resolution_code` in all 25 ITSM packages (50 findings). `d5ab75ff0f` has two more in each of its two packages (`builds`, `builds_v2`), on `on_hold_reason` (the value `Awaiting Caller" (something pending from caller)` is a parse slip in the rule). |
| Verify rules with no tool in `builds_v2` | Present: 95 in the 8 `builds_v2` packages (11 each, 12 in `c47f8ceef3`, 17 in `d5ab75ff0f`). |

### `invalid_slots`: bare values in `then.when` of a duty

14 strings (12 ITSM, 2 HANDBOOK) and 2 booleans. Three distinct rules; the same rule recurs in several builds.

| Rule | Slot | Packages |
|---|---|---|
| `ec984baa2dd4` (trigger: `update_incident` with status closed; then: `list_child_incidents`) | `then.when.parent_incident` is the string `"<incident_id>"` | 12 ITSM: `builds_v2` x7, `builds_v4`, `builds_v4_remind`, `builds_v4_v4A`, `v4AB`, `v4B` |
| `5effb7056c1b` (then: `google_mail__move_emails`) | `then.when.target_folder` is the string `"General"` | Crestwood `v3`, `v4` |
| `0befc04daf49` (then: `google_mail__mark_emails`) | `then.when.is_read` is the boolean `true` | Crestwood `v3`, `v4` |

Runtime effect, checked with `ruleset._when`: a string is read as its characters, so `{"target_folder": "General"}` does not
match a call with `target_folder="General"` (`False`). The duty then never counts as done and `before_reply` lists it as open.
The boolean works (`True`), because task 1.2 made `_values` wrap a bare value. Nothing was changed: not the runtime, not the
packages. Task 3.1 normalizes at compile. The ITSM string is also a placeholder for the id of the incident that was closed,
which a literal list in `when` cannot express.

### `rule_conflict`: read by hand

12 findings are 6 distinct pairs (5 on Crestwood, identical in `v3` and `v4`; 1 on ITSM, identical in `v4A` and `v4AB`).
All of them are `allowed_values` rules on the same tool and argument with nothing in common and no `when`.

| Pair | What I read | Verdict |
|---|---|---|
| `send_email.to`: `hr@crestwood.edu` (11.2:7) vs `Patricia Huang`, `Nicole Ashford` (13.2:10) | Two procedures, each with its own recipients. Neither rule kept its procedure. | Rule defect: every send is denied by one of them. Policy is consistent. |
| `forward_email.to`: `n.ashford@` (11.2:16) vs `hr-escalations@` (16:9) | Different sections, different cases. | Rule defect, policy consistent. |
| `forward_email.to`: `n.ashford@`, `j.whitfield@` (11.2:17) vs `hr-escalations@` (16:9) | Same. | Rule defect, policy consistent. |
| `forward_email.to`: `n.ashford@` (14.2:8) vs `hr-escalations@` (16:9) | Same. | Rule defect, policy consistent. |
| `send_email.cc`: `Nicole Ashford` (14.1:10) vs `n.ashford@crestwood.edu` (14.2:6) | The same person, written once as a name and once as an address. The rules deny each other's form. | Rule defect (no alias): a false conflict in meaning, a real one in effect. |
| ITSM `create_problem.status`: `new` (4.2:4) vs `fix_in_progress` when `workaround` is given (4.2:5) | The second sentence is an exception to the first. No `exception_of` link joins them, and the second rule has no `statement_ids` (flat rule `c67e64e86324_t0`), so nothing decides. | Rule defect: an exception that was not folded in. |

Consequence for `resolve_conflicts`: all 6 would be a tie. It would set both rules to `remind` and ask the policy owner. The
question now offers "each holds in a different case (which one)", which is the true answer on all 6 pairs. The better fix is
upstream: a rule that holds only inside one procedure is a must-not on that procedure (Task 3.3), and a name and an address
need an alias. I did not add a `scope` slot.

Not covered by the check, and counted so the denominator is known: the packages have 52 pairs of `allowed_values` rules on
the same tool and argument. 2 are identical, 12 have nothing in common (the 12 findings), 38 overlap in part, so only the
shared values pass both rules. The spec asks for disjoint values, so those 38 are not reported.

### `rule_conflict`, a duty against a role rule: read by hand

A warning, because it depends on the role. 15 findings = 3 distinct pairs in each of the 5 `builds_v4*` packages (`gold` has
none: its reporter rule also forbids the duty's trigger, so that role never owes the duty, and the check skips it).

The duty is `303d3040d9f5` ("The SLA timer must be paused (stage = paused) when the Incident is on hold ..."). It is
triggered by `update_incident` and needs `update_incident_sla_details`. The grant rules `grant_manager`, `grant_agent` and
`grant_reporter` (from the grant table) forbid that tool for their role, and do not forbid `update_incident`. So a manager, an
agent or a reporter can put an incident on hold and then owes a call that the grant table forbids. The tension is real. The
sentence is in the passive ("must be paused"), so the system may do it; that is a question for the owner, not a defect. Not
changed by `resolve_conflicts`.

### `empty_value`

2 findings, Crestwood `v3` and `v4`, rule `9a9f6c9beded`: `values: [""]` for `jira__create_issue.description`, from "When
creating a Jira ticket, the ticket description starts empty." The rule is right: the value must be empty. An empty string among
`values` or `allowed` is a warning for this reason; anywhere else (names, `when`, `edges`) it is an `unfilled_slot` error.

### `rule_no_trigger`: read by hand

All 963 are `verify` rules with an empty `tools` list (804 HANDBOOK, 141 ITSM, 18 Telecom). At run time each one is a global
verifier on every write, so the finding is correct. I read 12 at random (4 each from ITSM `e2891a7b98/builds_v2`, Telecom,
HANDBOOK Careig `v3`):

- 2 are rules that need a tool: "A Problem must be created (create_problem) when a recurring incident pattern ...", "You must
  first identify the customer."
- 10 are not rules for a write: a fact ("Priority is determined automatically by the system"), a definition ("Change Types
  (Enumeration)"), a table row ("Education_Provided | ..."), a note ("Team communications use defined Slack channels"), or a
  leftover word ("model").

So most of these need `definition` or `guidance`, not a tool. Under `legacy=False` all 963 are errors.

The 28 findings of the new `builds` packages, all read: 18 are rules for a write ("assigned_to must be an active user with the Agent
or Manager role ..." in 8 packages, "SLA Pause: the SLA timer must be paused ..." in 6, an assignment rule, and in `d5ab75ff0f` the
change rules "all changes must originate from a Change Request", "Approval Gate" and "Rollback Plan"), 6 are role-table rows (they
need `role_permission` rules, not a verifier), and 4 are error-handling statements ("403 Forbidden", "409 Conflict", "Rate
Limiting", "Error Handling"), which are not rules for a write.

### `coverage_incomplete`

0 with `legacy=True`: every `must` and `must_not` statement of the 31 packages that hold statements has an outcome. The check
does fire: removing the coverage items of Crestwood `v3` gives 187 gaps.

14 packages hold no statements, so coverage cannot be shown for them: 10 AutomationBench gold packages, ITSM `e2891a7b98/gold`,
and the 3 HANDBOOK `claude_v1` graphs. Under `legacy=False` each is one `coverage_incomplete` error.

Under `legacy=False` the result is different, because a coverage item is a claim and counts only for `out_of_scope`. Every
other outcome must be an object of the package that names the statement. The 45 packages then give 426 `coverage_incomplete`
errors (the first version of the validator gave 20, because it still took the claims `definition`, `procedure_step`, ... as written):

| Cause | Count |
|---|---:|
| 14 packages with no statements | 14 |
| `must` statement that legacy coverage calls `definition` and no definition record names (HANDBOOK 204, ITSM 164, Telecom 38; a term defined twice is kept once; the 8 `builds` packages add 96 of the ITSM ones) | 406 |
| `must` statements that the coverage calls `verify`, in ITSM `builds_v4_v4A` and `v4AB` (3 each): their rules exist but have no `statement_ids` in the package, because the conversion could not find their wrapper (tool-split copies, ids `96d374e7fa9b_t0` ..., `c67e64e86324_t0`, `28236de885df_t0`) | 6 |

Under `legacy=False` there are also 79 `coverage_conflict` warnings (a statement that is `out_of_scope` and also has an outcome:
78 are quoted by a procedure's precondition, exception, template or escalation, 1 has a rule); I did not read these by hand.
Under `legacy=True` none of this is reported: the legacy coverage items count as written.

### `unknown_field`

`extra.repair` (5 packages) and `extra.repair2` (3): logs that `rule_repair` wrote into the artifact. The model has no field for
them, so they stay in `extra`. Harmless; listed so a typo in a new package is not confused with them.

## Per package

| package | invalid_slots | rule_conflict error | rule_conflict role warning | rule_no_trigger | schema_conflict | empty_value | unknown_field |
|---|---:|---:|---:|---:|---:|---:|---:|
| `automationbench/finance.prepaid_amortization/gold` |  |  |  |  |  |  |  |
| `automationbench/finance.xero_batch_invoice_send/gold` |  |  |  |  |  |  |  |
| `automationbench/hr.candidate_offer_negotiation_tracking/gold` |  |  |  |  |  |  |  |
| `automationbench/marketing.social_engagement_response/gold` |  |  |  |  |  |  |  |
| `automationbench/marketing.trending_topic/gold` |  |  |  |  |  |  |  |
| `automationbench/operations.linkedin_job_change/gold` |  |  |  |  |  |  |  |
| `automationbench/sales.zoom_calendar_conflict/gold` |  |  |  |  |  |  |  |
| `automationbench/sales.zoom_regional_webinar_coordinator/gold` |  |  |  |  |  |  |  |
| `automationbench/support.helpcrunch_usage_alerts/gold` |  |  |  |  |  |  |  |
| `automationbench/support.zendesk_data_quality/gold` |  |  |  |  |  |  |  |
| `handbook/hr_crestwood_university_79786c46/claude_v1` |  |  |  |  |  |  |  |
| `handbook/hr_crestwood_university_79786c46/v3` | 2 | 5 |  | 150 |  | 1 |  |
| `handbook/hr_crestwood_university_79786c46/v4` | 2 | 5 |  | 150 |  | 1 |  |
| `handbook/insurance_vanguard_shield_mutual_9b2f7a29/claude_v1` |  |  |  |  |  |  |  |
| `handbook/insurance_vanguard_shield_mutual_9b2f7a29/v3` |  |  |  | 47 |  |  |  |
| `handbook/insurance_vanguard_shield_mutual_9b2f7a29/v4` |  |  |  | 47 |  |  |  |
| `handbook/medical_careig_specialty_pharmacy_f5947c33/claude_v1` |  |  |  |  |  |  |  |
| `handbook/medical_careig_specialty_pharmacy_f5947c33/v3` |  |  |  | 205 |  |  |  |
| `handbook/medical_careig_specialty_pharmacy_f5947c33/v4` |  |  |  | 205 |  |  |  |
| `itsm/2e555b5177/builds` |  |  |  | 2 | 2 |  |  |
| `itsm/2e555b5177/builds_v2` | 1 |  |  | 11 | 2 |  |  |
| `itsm/7bb25d850c/builds` |  |  |  | 2 | 2 |  |  |
| `itsm/7bb25d850c/builds_before_filters` |  |  |  | 2 | 2 |  |  |
| `itsm/7bb25d850c/builds_v2` | 1 |  |  | 11 | 2 |  |  |
| `itsm/933219af01/builds` |  |  |  | 2 | 2 |  |  |
| `itsm/933219af01/builds_before_filters` |  |  |  | 2 | 2 |  |  |
| `itsm/933219af01/builds_v2` | 1 |  |  | 11 | 2 |  |  |
| `itsm/a5e328395b/builds` |  |  |  | 2 | 2 |  |  |
| `itsm/a5e328395b/builds_v2` | 1 |  |  | 11 | 2 |  |  |
| `itsm/c47f8ceef3/builds` |  |  |  | 9 | 2 |  |  |
| `itsm/c47f8ceef3/builds_v2` | 1 |  |  | 12 | 2 |  |  |
| `itsm/cb2d4ee021/builds` |  |  |  | 2 | 2 |  |  |
| `itsm/cb2d4ee021/builds_v2` | 1 |  |  | 11 | 2 |  |  |
| `itsm/d5ab75ff0f/builds` |  |  |  | 7 | 4 |  |  |
| `itsm/d5ab75ff0f/builds_v2` |  |  |  | 17 | 4 |  |  |
| `itsm/e2891a7b98/builds` |  |  |  | 2 | 2 |  |  |
| `itsm/e2891a7b98/builds_before_filters` |  |  |  | 2 | 2 |  |  |
| `itsm/e2891a7b98/builds_v2` | 1 |  |  | 11 | 2 |  |  |
| `itsm/e2891a7b98/builds_v4` | 1 |  | 3 | 2 | 2 |  | 1 |
| `itsm/e2891a7b98/builds_v4_remind` | 1 |  | 3 | 2 | 2 |  | 1 |
| `itsm/e2891a7b98/builds_v4_v4A` | 1 | 1 | 3 | 1 | 2 |  | 2 |
| `itsm/e2891a7b98/builds_v4_v4AB` | 1 | 1 | 3 |  | 2 |  | 2 |
| `itsm/e2891a7b98/builds_v4_v4B` | 1 |  | 3 |  | 2 |  | 2 |
| `itsm/e2891a7b98/gold` |  |  |  | 7 | 2 |  |  |
| `tau2_telecom/telecom/builds` |  |  |  | 18 |  |  |  |

## After change 131 (task 3.1): 55 packages

10 packages were added: the 9 ITSM rebuilds `itsm/<id>/builds_v5` (the pipeline with the repairs inside, `legacy=False`
counts below) and `itsm/e2891a7b98/builds_v5_norepair` (the same compile with `repair=False`). Everything above, the 45
packages and their findings, is as it was on 2026-11-05.

New code `identifier_values` (error): an `allowed_values` rule on an argument that has no enum and holds a record
identifier (the name ends in `_id`, or the argument's description says `id` or `identifier`), when the statement does not
write the argument's name. No real identifier is one of a few words, so the rule denies every call. The first `builds_v5`
had one such rule (`6f3b07ad3b99`: status words for the CI identifier argument of the tool that links a CI to an
incident); on the 55 packages of that day the check gave 8 hits (7 versions and the `norepair` variant), all this rule, and
none on any other package, gold ones included. The pipeline (`handlers/prose.py`, `rule_repair.py`) now rejects such a rule,
and the prose step sends the reason back to the model ("use reference_status").

`validate_all.py` (legacy mode) on the 55 packages after the rebuild: `invalid_slots` 16 and `rule_conflict` error 12 as before,
`rule_conflict` warning 39 (the 15 of before, and 3 in each of 8 `builds_v5` that have grant rules; all a duty against a role rule),
`schema_conflict` 78, `rule_no_trigger` 979 (16 of them in the `norepair` variant), `identifier_values` 0, `empty_value` 2,
`unknown_field` 8.

`validate_package(legacy=False)` on the 9 `builds_v5` (the new standard): 9 of 9 have 0 errors. Warnings: `schema_conflict` 2
(4 on `80cd3ebb50`, `d5ab75ff0f`), `coverage_conflict` 1-2, `rule_conflict` of a duty against a role rule 3 (7 versions and
`d5ab75ff0f`). `coverage_incomplete` 0 and `rule_no_trigger` 0: a `verify` rule that no write tool can trigger is guidance, and
a must or must-not statement that ends so also has a policy question (4 to 10 per version).

## After change 134 (task 3.4): 70 packages, and a correction for the 9 `builds_v5`

15 packages were added, all source `skill_v1`: made with the skill by fresh agents from the policy text and the tool schemas only
(HANDBOOK 3, ITSM 9 versions, τ² Telecom, airline, retail). Everything above is as it was. `validate_all.py` has the tool specs of
`tau2_airline` and `tau2_retail` (`tau2/airline_tools.json`, `tau2/retail_tools.json`), and it checks the `skill_v1` source as a new
package (`legacy=False`: a coverage gap or a rule with no trigger tool is an error). A new flag, `--strict`, checks every package that way.

Default run on the 70 packages: `invalid_slots` 16 and `rule_conflict` error 12, as before (none in a `skill_v1` package). The 15 new
packages have **0 errors** with the tool checks on. Their warnings: `rule_conflict` 44 (a duty against a role rule, 4 to 9 for each of the 9 ITSM
versions), `schema_conflict` 12 (`resolution_code`, and 3 more on `80cd3ebb50`), `unbound_value` 15 (Vanguard 12, Telecom, airline, retail 1 each),
`not_in_text` 7 (Crestwood 6 template names that are only in headings, `d5ab75ff0f` 1). Each `rule_conflict` and `schema_conflict` warning names a
rule that a policy question lists. The totals of the default run: `schema_conflict` 92, `rule_conflict` warning 83, `rule_no_trigger` 979,
`unbound_value` 15, `not_in_text` 7, `unknown_field` 8, `empty_value` 2.

New code `date_compare` (warning), changed in fix round 1. First it warned on any date in a `gt`, `ge`, `lt` or `le`, because
`ruleset._condition` read the first number of each side (a date was compared by its year). The runtime now compares two ISO dates
(`2025-02-25`, with or without a time) as dates, so Telecom's `r_no_resume_contract_ended` (`lt 2025-02-25`) is right and has no warning. The code
now warns on what is still read by its first number: a date that is not in ISO form in a `record_condition` comparison, and any date in a `threshold`
(it reads its argument as a number). 0 hits on the 70 packages. No measured package has a date in a comparison.

`schema_conflict` also covers a literal that the tool's argument `pattern` rejects (the values of an `allowed_values` rule, and the values of a
`when`), as for a value outside an enum. It hits 2 packages that were already there: `handbook/insurance_vanguard_shield_mutual_9b2f7a29/v3` and `/v4`,
rule `4139a4d572cc`, `jira__add_comment.issue_key` with the value `OPS-AP-INV`, which the Jira key pattern `^[A-Z][A-Z0-9_]*-\d+$` does not accept (so
`schema_conflict` is 90 to 92 in the default run). None in a `skill_v1` package.

### Correction: `quote_not_verbatim` on the `builds_v5` packages

Change 131 said that 9 of 9 `builds_v5` packages validate with 0 errors. That was before the text checks of task 3.3 (`quote_not_verbatim`
and the other checks that read a quote against the policy). `validate_all.py --strict` on the 70 packages (the same `validate_package`,
`legacy=False`) gives **10 `quote_not_verbatim` errors in the 9 `builds_v5` packages: one in each, two in `d5ab75ff0f`**. All are in the
procedure `itsm-<id>:general`: `preconditions[0].quote` is `"You are strictly prohibited from ... by"`, and on `d5ab75ff0f` also `preconditions[4].quote`
(`"Agent ... Cannot bypass approvals, or c..."`). The pipeline model elided words of the statement with `...`. No rule is affected: the finding is in
procedure parts that carry a quote. The `builds_v5_norepair` variant has one more. Changes 126 and 127 packages are as they were; their older
procedure quotes were not checked then (`--strict` also gives `quote_not_verbatim` for `handbook/v3` 39 and `handbook/v4` 60). For task 3.5: the
pipeline's procedure handler must quote whole text, or repair the quote (an elision with `...` is not text).

`--strict` on the 70 packages, all codes: `coverage_incomplete` 404 and `rule_no_trigger` 955 (errors only for converted packages by design,
none for `skill_v1`), `quote_not_verbatim` 110, `invalid_slots` 16, `rule_conflict` 12 (error), `invalid_field` 2, and the warnings
`coverage_conflict` 89, `schema_conflict` 84, `rule_conflict` 83, `unbound_value` 15, `not_in_text` 7, `unknown_field` 8, `empty_value` 2.

Per package (`skill_v1`):

| Package | Rules | Errors | Warnings |
|---|---:|---:|---|
| `handbook/hr_crestwood_university_79786c46` | 36 | 0 | `not_in_text` 6 |
| `handbook/insurance_vanguard_shield_mutual_9b2f7a29` | 15 | 0 | `unbound_value` 12 |
| `handbook/medical_careig_specialty_pharmacy_f5947c33` | 42 | 0 | none |
| `itsm/e2891a7b98`, `2e555b5177`, `7bb25d850c`, `933219af01`, `a5e328395b`, `cb2d4ee021` | 68 to 69 | 0 | `rule_conflict` 4, `schema_conflict` 1 each |
| `itsm/80cd3ebb50` | 68 | 0 | `rule_conflict` 5, `schema_conflict` 4 |
| `itsm/c47f8ceef3` | 72 | 0 | `rule_conflict` 6, `schema_conflict` 1 |
| `itsm/d5ab75ff0f` | 92 | 0 | `rule_conflict` 9, `schema_conflict` 1, `not_in_text` 1 |
| `tau2_telecom/telecom` | 19 | 0 | `unbound_value` 1 |
| `tau2_airline/airline` | 29 | 0 | `unbound_value` 1 |
| `tau2_retail/retail` | 31 | 0 | `unbound_value` 1 |
