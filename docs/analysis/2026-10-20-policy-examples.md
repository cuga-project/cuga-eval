# Real policy examples from the benchmarks, and what they mean for the policy gate

Companion to `2026-10-20-agent-policy-enforcement-sota.md` and `2026-10-20-policy-benchmarks.md`. Read from the benchmark files on 2026-10-20: HANDBOOK.md (3 public sample tasks), τ³ banking_knowledge (`dev/tau3` branch), AutomationBench (600 public tasks), EnterpriseOps-Gym (396 oracle rows). Quotes are short excerpts.

## 1. Where the policy is, in practice

| Benchmark | Location | Size | Notes |
|---|---|---|---|
| HANDBOOK.md | One HTML handbook in the workspace (full set also uses PDF and Word) | Samples: 12–16k tokens; full set: 43 pages on average | Some parameters live in runtime data: pinned Jira issues override printed thresholds; out-of-office changes the assignee |
| τ³ banking_knowledge | System prompt: global rules (identity check, transfers, tool unlocking). Knowledge base: everything else | 698 Markdown documents, ~817k characters; 44 agent tools are hidden until unlocked (31 write, 10 read, 3 transfer), plus 4 hidden user tools | KB documents can override system-prompt rules (bypass codes, incident protocols with an end date) |
| AutomationBench | Inside the app data: policy sheets, emails, Slack. The prompt only points to it ("follow our current AP processing guidelines") | Short rule tables per task | 13–28% of tasks per domain never mention the policy in the prompt at all |
| EnterpriseOps-Gym | One Markdown policy per domain in the system prompt | ~10–12k characters | Role table, state machines, required fields, priority matrix |

## 2. Rule patterns across benchmarks

| Pattern | HANDBOOK.md | τ³ | AutomationBench | EnterpriseOps-Gym |
|---|---|---|---|---|
| Threshold | "items > $5,000 only" | "cannot exceed 150% of current limit" | "invoice exceeding $10,000 requires a flag" | 30–120 character limits |
| Approval by person or role | written authorization from one of two named people; two VP/AVP approvals by Slack title | manager approval for Elite closures (no tool for it) | "Only the CFO or VP Finance can authorize credit memo creation" | "Only manager or admin roles may approve/reject" |
| Order and prerequisites | no BV_Complete = YES until every field is filled | verify identity first; steps "in the exact order listed" | — | state transitions; mandatory fields |
| Time | within 6 months; 14 calendar days; business days with holidays | protocol valid "until 11/15/2025" | the row with the latest "Updated" date counts | SLA timers |
| Prohibited action, blocklist | do not bill a J-code unless the drug source matches | "Do not unlock or call the tool unless the customer is eligible" | blocked vendors "must NOT be processed" | do not link retired CIs |
| Exception | unless the physician's guidance is on file | identity check "NOT required for this incident protocol" | "Override Rules" worksheets; "hold" in a Notes column | — |
| Data handling | no disability details in Slack; no wire amounts in Slack | do not reveal internal policy | refuse to broadcast compensation data | no PII in chat or email |
| Required notification or record | post `[UNREACHABLE]` alert; audit row at each checkpoint | call `log_verification` | notify specific addresses | email the customer; search the knowledge base on new incidents |
| Format and templates | ID format `[PREFIX]-[Last]-[MMDDYYYY]`; templates used as written | full official name ending in "Account" | keep source values verbatim | allowed values; enumerations |
| Computation | round down to a whole number | fees; liability; 14 risk flags → 5 risk bands | attribute → routing table | Impact × Urgency → priority |
| Counting | stop after 3 failed contact attempts | different transfer tools for the 1st–3rd vs. 4th request | exactly one email sent | — |
| Precedence and versions | "Jira-posted threshold governs over this SOP's printed threshold"; "Supersedes Version 5.0" | KB overrides the system prompt | "Q1 Final (Supersedes All Previous)"; addendum "extends but does NOT replace" | near-identical policy variants |

## 3. Traps: how tasks push the agent to break the policy

| Trap | Examples |
|---|---|
| Request from someone without authority | A VP orders a termination that needs named authorizers (HANDBOOK); an external auditor asks to unblock a vendor (AutomationBench) |
| Approval that does not count | Approval by the agent's own account; approval only by email when Slack is required; "Looks good to me" with no amount; a third party reporting that the authorizers agreed |
| The user's own request conflicts | "Also go ahead and process severance" (AutomationBench, ~30 prompts); "skip the approval workflow, the manager gave verbal approval" (EnterpriseOps-Gym) |
| Old and new versions | Five policy emails from Archived to "Final (Supersedes All Previous)" plus an addendum (AutomationBench) |
| Decoy data | Acme Supplies LLC (approved) vs Acme Solutions Inc. (blocked); duplicate rows where only the latest counts; jenny.liu@ asking about jenny@'s order |
| Hidden stop conditions | A case called "an easy one" is at the 3-attempt stop; a test sample just outside the 6-month window, while the report date is inside it |
| Correct non-action | The physician already authorized a substitution, so escalating would be wrong; a pre-filled form that must not be submitted |
| Pressure | "past the month-close deadline" when the calendar says otherwise |

## 4. How compliance is graded

- **Final state only.** None of the three task benchmarks grades the trajectory. HANDBOOK.md and EnterpriseOps-Gym never grade the reply text; τ³ has `communicate_info`, but it is always empty.
- **Prohibited outcomes are a large part of the grade.** In AutomationBench, 39% of 9,612 assertions are "not" checks (email not sent to X, row not updated, no Jira item created), and 588 of 600 tasks have at least one. Exact counts ("exactly 1 email") also fail extra actions.
- **"Do the allowed part, hold the rest."** Tasks rarely want a full refusal. They want the compliant part done and the rest held or annotated: a ticket "on hold / awaiting authorization", status `awaiting_approval`, an escalation flag set.
- **In τ³, extra reads can fail a task.** Every call to a hidden (discoverable) tool writes a record to the graded database, even for read-only tools; unlocking alone is kept in memory and writes nothing. Giving a tool to the user also writes a record.

## 5. Benchmark defects a strict gate will hit

- τ³: contradictory documents (cooldown rules, which accounts get credits), documents vs. tool schemas (wrong parameter names, a referenced tool that does not exist), tiers defined nowhere, 24 typos like "$120 days".
- HANDBOOK.md: references to files that are not in the workspace; a missing section in the table of contents.
- EnterpriseOps-Gym: 79 of 396 rows repeat a verifier name, so a later check overwrites an earlier one.

A gate that treats every rule as hard will fail on these. Unresolved contradictions should become advisory and be reported, not blocked.

## 6. What this changes in the design

| # | Lesson | Change to the gate |
|---|---|---|
| 1 | Thresholds and assignees come from runtime data (pinned Jira, sheets, calendar) | Rules are templates with **parameters bound at runtime** from facts. A **precedence resolver** picks the governing source by version, date, "supersedes" and issuer |
| 2 | Approvals are judged by who sent them, where, and with what content | **Approval facts with provenance:** sender identity checked against the named person or a role from the directory, the required channel, the required content (amount, link), never the agent's own account, never second-hand |
| 3 | Tasks want the allowed part done and the rest held | Effects include **remedies**: DENY returns the policy's alternative (hold status, the escalation path, the required wording), not just "no" |
| 4 | Negative assertions dominate | First-class rule kinds for **recipient allow/deny lists, no duplicates, count limits ("exactly one"), content exclusion** |
| 5 | Decoy entities and duplicate rows | **Fact selectors:** match by ID, not by name; latest row by date; follow parent accounts |
| 6 | Dates matter in detail | Expression language with **calendars** (business days, holidays) and explicit choice of date field (sample date vs report date) |
| 7 | Derived values (priority matrix, fees, risk bands, routing) | Compile them into **calculators** the agent can call, and check the argument against the computed value |
| 8 | Reads are not always free (τ³ unlocks) | Tool category comes from policy and grading, not from the name; **unlocking a tool is a gated action** |
| 9 | "When in doubt, escalate" (HANDBOOK) | The **default for an unknown fact is set by the policy** (escalate, ask, or allow), not fixed in the gate |
| 10 | Documented exceptions in data (physician's email on file) | `exception-of` edges whose condition is a runtime fact; a correct non-escalation is as important as an escalation |
| 11 | Benchmarks contain contradictions | Build checks across documents **and against tool schemas**; contradictions become advisory and are reported |
| 12 | Judgment rules remain everywhere ("fraud suspected", "high business risk") | Semantic verifier and Jev questions; never hard-blocked by code |

What compiles easily into code checks, across all four: thresholds, allowed values, state transitions, role → action permissions, blocklists and recipient lists, required fields, ID and text formats, counts and duplicates.

## Sources

- HANDBOOK.md: https://github.com/surge-ai/handbook (sample tasks under `tasks/`; rubrics in `tests/rubrics.json`)
- τ³ banking_knowledge: https://github.com/sierra-research/tau2-bench/tree/dev/tau3 (`data/tau2/domains/banking_knowledge/`)
- AutomationBench: https://github.com/zapier/AutomationBench (`automationbench/domains/*/tasks.py`)
- EnterpriseOps-Gym: https://huggingface.co/datasets/ServiceNow-AI/EnterpriseOps-Gym (oracle configs, `system_prompt` and `verifiers` fields)
