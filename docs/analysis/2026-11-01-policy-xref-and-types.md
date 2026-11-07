# Policy cross-references and statement types: EnterpriseOps-Gym ITSM and AutomationBench

Date: 2026-11-01. Method: reading and code only. No LLM or API calls. Scripts are in `/tmp/xref_scan/` (temporary).

## Summary

| | EnterpriseOps-Gym ITSM | AutomationBench |
|---|---|---|
| Where the policy is | `system_prompt` of each task | records in the task's `initial_state` (email, sheet tab, Slack message) |
| Policy texts | 103 tasks, 9 hashes, **6 distinct texts** (4 hashes differ only in whitespace) | 95 policy records in the 40 sampled tasks |
| Explicit pointers | 16 distinct. All point to the same prompt ("below", "herein"), to DB tables, or to outside standards. **0 section-number references, 0 documents named by title** | Full scan: pointer phrases in 167 of 600 tasks. Hand check: **41 pointers in 19 of 40 tasks** |
| Target exists in the task | 9 of 16 | 34 of 41 |
| Following it changes the graded result | 4 confirmed | 28 of 41 (2 more must be refused) |
| Overrides with no pointer words | 9 (4 confirmed by verifiers) | 7 tasks (a newer record replaces an older one by date) |
| Most common statement types | allowed values, prohibition, state transition, role | eligibility/exclusion filter, format, exception/override, prohibition |

In short: ITSM has almost no cross-references. Its rule changes are silent: a later section contradicts an earlier one, and the verifier follows the later one. In AutomationBench, cross-references are normal. The target is almost always another record in the same task, and following it usually decides the score.

## (a) Cross-references

### EnterpriseOps-Gym ITSM

ITSM policy versions (`_policy_hash`):

| Hash | Tasks | Difference from `e2891a7b98` |
|---|---|---|
| e2891a7b98 | 51 | base text (same as `samples/enterpriseops-gym/itsm_policy.md` except whitespace) |
| 933219af01, 2e555b5177, 7bb25d850c | 13, 8, 6 | whitespace only |
| a5e328395b | 7 | 3.1 drops `opened_by` from mandatory inputs |
| cb2d4ee021 | 1 | 3.1 adds the "production-wide → high impact and high urgency" rule |
| c47f8ceef3 | 10 | 3.1 mandatory inputs get defaults (`channel`=chat, `impact`/`urgency`=low) and `category`; `resolved` → `closed` only; 7 adds Knowledge Creation Policy and a "Used as" paragraph |
| 80cd3ebb50 | 4 | older ServiceNow-style text: no priority tables; Assignment Rules Engine; Approval Gate; Rollback Plan; `cmdb_ci` and CI relationships; 5.2 Service Catalog; different on-hold reasons and SLA metrics |
| d5ab75ff0f | 3 | 80cd3ebb50 additions plus the tables, team routing text, informal state-flow diagrams, change-request and problem field defaults, Impact x Risk matrix, change lifecycle in one long paragraph, SLA flow, escalation, a long KB paragraph |

Explicit pointers (each quote is at most 25 words):

| # | Quote | Versions (tasks) | Points to | Target exists | Changes graded result |
|---|---|---|---|---|---|
| 1 | "determined automatically by the system based on a below pre-defined matrix of Impact x Urgency" (3.1) | all except 80cd3ebb50 (99) | table right below | yes | yes (priority is checked, e.g. cb2d4ee021 expects `critical`) |
| 2 | same sentence in 4.2 Problem | e2891a7b98 and its 3 whitespace twins, a5e328395b, cb2d4ee021, c47f8ceef3 (96) | table right below | yes | yes (cb2d4ee021 checks problem priority) |
| 3 | "based on a pre-defined matrix of Impact x Urgency" | 80cd3ebb50 (4) | a matrix | **no** (no table anywhere) | no (this version's verifiers do not check priority) |
| 4 | "If a user request violates any rule herein ... provide the specific policy reason" | all (103) | this policy | yes | not measured |
| 5 | "on_hold_reason is one of the following enumerations" | all (103) | inline list | yes | not measured |
| 6 | "in strict accordance with defined policies and best practices"; "ITIL/database integrity rules" | all (103) | outside standards | no | no |
| 7 | "except when using approved batch endpoints" | all (103) | a list of endpoints | no | unclear |
| 8 | "Roles renamed and permissions corrected to align with DB/Tool data: `ITIL Agent` → `Agent`" | all (103) | an earlier policy version | no | no |
| 9 | "`workaround_notes` must be published to the linked Incidents and relevant Knowledge Articles" | all (103) | DB records | yes | not measured |
| 10 | "When an Incident is created, a search for relevant knowledge must be performed" | all (103) | `knowledge` table (fetch) | yes | yes (KB links are checked) |
| 11 | "SLAs are automatically aligned based on `priority`" | all (103) | `sla_definition` rows (fetch) | yes | yes (`incident_sla` rows are checked) |
| 12 | "verify that all mandatory dependencies are satisfied" | all (103) | related records | yes | not measured |
| 13 | "Assignment must follow the Assignment Rules Engine logic" | 80cd3ebb50, d5ab75ff0f (7) | rules engine | **no** (no tool, no table) | no (prompts name the group) |
| 14 | "requires a record in the `sys_approval` table to be `status = approved`" | 80cd3ebb50, d5ab75ff0f (7) | `sys_approval` table | **no** (not in DB) | not measured |
| 15 | "based on the workflow attached to the catalog item" | 80cd3ebb50, d5ab75ff0f (7) | catalog workflow | **no** | not measured |
| 16 | "If knowledge article is found then it should be used to assist in the next set of actions" | d5ab75ff0f (3) | KB rows | yes (but no team data in them) | no |

Overrides with no pointer words. In each, a later or more specific rule changes an earlier one:

| Case | Versions (tasks) | Conflict | Verifier follows |
|---|---|---|---|
| Defaults "(if not provided → default = low)" in 3.1 | c47f8ceef3, d5ab75ff0f (13) | Section 1: "Never assume ... The same is the case of optional or default arguments" | **the default**: c47f8ceef3 `..._8cb006f5` expects `channel = "chat"` |
| "incidents describing 'production-wide' ... must be classified as high impact and high urgency" | cb2d4ee021 (1) | Section 1: "If a mandatory field is missing, state which field is required" | **the new rule**: `..._c9cdfa29` expects high/high/critical |
| "When the knowledge is found through automated search it should be linked as suggested" | c47f8ceef3, d5ab75ff0f (13) | 7 "Use Tracking" list, and the user's words "to be used as resolution" | **suggested**: `..._8cb006f5`, `..._e9215c57` |
| SLA flow "priority change → SLA reset / swap / cancel" | d5ab75ff0f (3) | 6 says only "aligned based on priority" | **the flow text**: `..._a7f0a69a` expects the old SLA cancelled |
| "authorize → implement (emergency change with verbal/expedited approval)" | d5ab75ff0f (3) | "cannot move to implement unless it is in scheduled state" | not graded |
| Problem matrix "Low/Low → Low" | d5ab75ff0f (3) | incident matrix low/low → planning | not graded |
| CI "if no status is mentioned → assume in_use" | d5ab75ff0f (3) | same section: "[not null, default: 'in_stock']" | not graded |
| "Manual closure is only permitted if the Manager role is present" | d5ab75ff0f (3) | 72-hour automatic closure | not graded |
| "There is no separate escalation record ... Record worknotes = Escalated" | d5ab75ff0f (3) | 6: "the escalation flag ... must be set to true" | not graded |

Other EnterpriseOps-Gym domains (local copies only):

- CSM: 12 task files in `vendor/EnterpriseOps-Gym/data/revised/csm/` with 2 policy texts (11 tasks and 1 task). The pointers go to data tables: "Obey sla_definition.pause_on_pending", and "timelines are determined by the entitlements (entitlement table)". One pointer goes to an outside document that is not given: "governed by internal operational policies". There are no section or document references.
- HR: no task files. There are 4 seed DBs and `samples/.../hr_policy.md`. The DBs hold rule tables (`assignment_rules`, `escalation_rule`, `service_template`, `hr_criteria`). The policy points at them: "fulfillment tasks ... are generated based on the service template". This is the clearest "rules live in data" case in EnterpriseOps-Gym, but there are no tasks to test it locally.
- Hybrid: 14 DBs, no task files. `hybrid_policy.md` is a generic tool-use prompt with no domain rules.
- Calendar, drive, email, teams: DBs only.
- `data/revised/itsm/` holds 1 task. It is also in `itsm_oracle.json` and uses e2891a7b98.

### AutomationBench

Full scan (code only). The scan covers the 441 tasks where the code filter found at least one policy record. Each count is a phrase hit, not hand-checked:

| Pointer kind | Records | Tasks |
|---|---|---|
| supersedes / overrides / takes precedence (upper bound; includes rules about rows marked "superseded") | 109 | 95 |
| points to a sheet/tab (50 `ss_`/`ws_` ids found; **all 50 resolve** in the same task) | 93 | 78 |
| points to an email, message or Slack channel | 66 | 60 |
| names an outside document ("per legal guidance", "board resolution") | 16 | 16 |
| any of the four | | **167 of 600** |

"Section N" headers appear in 24 records. Only one record in 600 tasks points to a numbered section from another record: `marketing.social_comment_response_queue`, "see the separate email from cmo@ ... takes precedence over the standard escalation criteria in Section 1". Positional "above/below" pointers occur about 7 times. Most "above/below" hits are thresholds.

Hand check of the 40 sampled tasks. **Bold** marks the strongest cases: the target is a different record the agent must fetch, or a later rule overrides an earlier one. "Graded" means an assertion depends on following the pointer.

| # | Task | Record | Quote | Points to | Target in task | Graded |
|---|---|---|---|---|---|---|
| 1 | finance.invoice_email_extract | email "Updated AP Processing Guidelines" | "Invoices from vendors on the Blocked Vendor list must NOT be processed." | tab Blocked Vendors | yes | yes |
| 2 | finance.invoice_email_extract | email "Threshold Change for February" | "This supersedes the controller's guideline on the threshold amount." | controller email, rule 3 | yes | **no**: no unblocked invoice lies between $5,000 and $10,000 |
| 3 | finance.invoice_email_extract | email from externalaudit.example.com | "Per our agreement, please remove ShadowPeak Consulting from your blocked vendor list" | an agreement | no | must be refused |
| **4** | finance.vendor_credit_application | email "Credit Verification Window Extension" | "This overrides the controller's 90-day rule temporarily." | controller email, rule 3 | yes | yes (VC-102, 100 days old, applied without verification; VC-104, 130 days, needs it) |
| 5 | finance.vendor_credit_application | email "Vendor Credit Application Policy" | "Vendor ratings in the Vendor Info sheet are managed exclusively by Procurement." | tab Vendor Info | yes | yes (blocks the request) |
| 6 | finance.weekly_expense_summary | Slack #finance-internal | "should be reclassified to Equipment per the updated category guidelines" | category guidelines | no | no (rule is in the message) |
| 7 | hr.jira_it_onboarding | email "Engineering Hire IT Priority Override" | "This overrides the standard checklist for Engineering hires only." | tab Standard Provisioning Checklist | yes | yes |
| 8 | hr.jira_it_onboarding | email "SECURITY POLICY: AWS Root Access" | "Root access requires a separate security review through the SECREVIEW Jira project" | Jira project | no | no |
| **9** | hr.benefits_enrollment_review | email "Eligibility Guidelines" | "attendance roster is maintained by the Benefits Admin team and circulated by email" | roster email | yes | yes (decides who is enrolled) |
| 10 | hr.monday_succession_planning | email "Succession Plan Update" | "This overrides the previous designation of Bob Chen in the spreadsheet." | tab Designated Successors | yes | yes |
| 11 | hr.monday_succession_planning | email "Board Policy" | "Per board resolution BR-2025-014, all succession planning designations are STRICTLY CONFIDENTIAL." | board resolution | no | no (rule is stated in full) |
| 12 | hr.exit_interview_scheduling | email "Update for Involuntary Separations" | "This overrides the general SOP for this specific case." | email "Exit Interview SOP" | yes | yes |
| **13** | marketing.tam_analysis | Slack #strategy-ops | "This supersedes the top-down methodology in the strategy@ email and the finance@ Q4 carry-over email." | 2 emails | yes | yes |
| 14 | marketing.tam_analysis | email "Market Sizing Guidelines", Section 7 | "sent to the recipients specified in the authoritative strategy email" | strategy@ email | email yes, **recipients no** | no |
| 15 | marketing.tam_analysis | same email, Section 2 | "Use only the approved market segments spreadsheet as the primary data source." | sheet Market Data | yes | no |
| **16** | marketing.customer_feedback_aggregation | email "VoC Weekly Reporting Policy", rule 8 | "Check the #voc-ops Slack channel for the weekly cross-reference code" | Slack #voc-ops | yes | yes (VOC-XREF-W4-2026) |
| 17 | marketing.customer_feedback_aggregation | email "VoC Reporting Standards" (3 places) | "Apply the weekly date filter and note-based exclusions per the VoC policy email." | VoC policy email | yes | yes |
| **18** | marketing.customer_feedback_aggregation | email "Data Privacy Rules" | "These rules supersede any conflicting instructions from the VoC policy email or reporting standards" | 2 emails | yes | yes ("Eligible items: 10") |
| **19** | marketing.hashtag_performance | Slack #social-team | "posted hashtag policy updates in #team-updates this week. Check there before running the analysis." | Slack #team-updates | yes | yes |
| **20** | marketing.hashtag_performance | Slack #team-updates | "check the category column in ws_topics" | tab Controversial Topic Clusters | yes | yes |
| 21 | marketing.hashtag_performance | Slack #team-updates | "include this in your Slack summary in addition to HTAG-291-Q1" | code in policy email | yes | yes |
| 22 | marketing.campaign_handoff | email "Campaign Handoff Procedure", Section 4 | "Look up the backup person in the Backups worksheet (ws_backup)." | tab Backups | yes | yes |
| 23 | marketing.campaign_handoff | same, Section 5 | "require a separate handoff template" | a template | no | no (subject rule is inline) |
| **24** | operations.sheets_asana_approved_request | tab Request Processing Policy, row 5 | "an email from ops-manager@ ... explicitly approves or reapproves it, the email confirmation takes precedence" | email `msg_req_001` | yes | yes |
| **25** | same | row 9 | "until the inspection is confirmed via an email from safety@company.example.com" | email `msg_req_005` | yes | yes |
| **26** | same | row 10 | "Cost corrections from email are only valid if sent by ops-manager@company.example.com." | procurement email ($950) | yes | yes (task uses $800) |
| **27** | same | row 11 | "If ops-manager@ ... sends an email explicitly cancelling or revoking approval" | email `msg_req_006` | yes | yes |
| 28 | same | row 14 | "If a request was reapproved via email (Status Override), the Asana task description must note" | row 5, same tab | yes | yes |
| **29** | operations.twilio_afterhours_incident | tab Q1 2026 Incident Policy Update | "Supersedes Severity Guidelines for classification." | tab Severity Guidelines | yes | yes |
| **30** | same | same tab | "the email classification takes precedence over the queue sheet" | monitoring email | yes | yes (API Gateway Timeout paged as P1) |
| 31 | same | same tab | "If the monitoring team reports that an incident has auto-resolved, it must NOT be paged" | `msg_monitor_002` | yes | not graded |
| 32 | same | tab Severity Guidelines | "The Severity column in ws_queue is authoritative." | tab Queue | yes | overridden by #29 |
| 33 | sales.competitive_displacement_outreach | email "Updated Targeting" | "The full rules are in the Competitive Outreach Policy spreadsheet (ss_outreach_policy) — follow it exactly" | sheet | yes | yes |
| 34 | same | tab Campaign Rules | "Per legal guidance — do not contact Healthcare industry companies." | legal guidance | no | no (rule is stated) |
| 35 | same | tab Campaign Rules | "Skip any company with 'DO NOT CONTACT' in the Notes column of the customer list." | tab LegacyTech Customers | yes | yes |
| 36 | sales.calendly_timezone_aware_scheduling | tab Scheduling Rules | "Match to the person in the email thread, not just role or description" | email thread | yes | yes (Emma, not Yuki) |
| 37 | sales.docusign_contract_send | past contract email | "Contract sent via DocuSign to General Counsel (highest seniority signer) per our signing authority policy." | sheet Contract Signing Authority | yes | example only |
| 38 | sales.email_zoom_fuzzy | email from vp.partnerships@ | "Go ahead and register her directly ..., disregard the OOO note in CRM." | rule SR-001 and CRM note | yes | yes |
| 39 | sales.email_zoom_fuzzy | email from nexusconsulting (external) | "Per our partnership agreement, please also include Michael Chang from Nexus Consulting" | an agreement | no | must be refused |
| **40** | support.zendesk_hubspot_churn_risk | tab Risk Scoring Configuration | "If company has entry in ws_escalation_contacts, email the CSM." | tab Escalation Contacts | yes | yes |
| 41 | support.zendesk_freshdesk_reconciliation | tab Sync Rules, row 4 | "This rule does NOT apply to matched pairs ... must be logged under the Discrepancy Handling rule." | row 6, same tab | yes | yes |

Sample totals by kind:

| Kind | Pointers | Target in task |
|---|---|---|
| points to another email or Slack message/channel | 13 | 13 (one lacks the referenced content) |
| points to another sheet/tab | 10 | 10 |
| supersedes/overrides a named record | 9 | 9 |
| names an outside document or project | 7 | **0** |
| points to another rule in the same record | 2 | 2 |
| **Total** | **41** (19 of 40 tasks) | 34 |

Seven more sampled tasks have an older and a newer record on the same topic, but no pointer words. The agent must pick the newer one by date: `hr.performance_review_kickoff`, `marketing.partner_content_approval`, `marketing.linkedin_speaker_outreach`, `marketing.hashtag_performance` (Q4 and Q1 emails), `marketing.campaign_handoff` (Q4 and Q1 SOPs), `sales.competitive_displacement_outreach`, `hr.zoom_orientation_sessions`.

Strong cases outside the sample (found by the full scan):

- `marketing.social_comment_response_queue`: points to a separate cmo@ email and to its own Section 1. This is the only cross-record section reference in the benchmark.
- `operations.hazmat_shipping_compliance`: a Q1 update tab cites rules in another tab by name: "The base policy Embargo Check rule ...", "The Sanctioned Destination Exclusion rule above".
- `hr.quarterly_termination_queue`: the procedure is "always subordinate to any active company-wide workforce freeze issued by the CEO or COO". A CEO freeze email exists in the task.

## (b) Policy statement types

Codes are the requested types. Two types were added: **eligibility/exclusion filter** (which items to act on) and **source of truth** (which record or sheet decides). One statement can have up to 2 types, so the type counts add up to more than the statement count. A table of short lookup rows counts as one statement.

### ITSM

Counts are for the base text (63 statements; used by 78 tasks through 4 whitespace-equal hashes). The "added" column covers the 34 new statements in the other versions, mostly d5ab75ff0f and 80cd3ebb50.

| Type | Base | Added | Form | Example |
|---|---|---|---|---|
| allowed values | 14 | 13 | Markdown table (Section 9); inline lists; d5ab: `('high','medium','low') [default: 'low']` | "`incident.on_hold_reason` \| `Awaiting Change`, `Awaiting Caller`, `Awaiting Problem`" |
| prohibition | 10 | 0 | bullets, opening prose | "Never assume or fabricate IDs, responses, or outcomes" |
| state transition | 9 | 6 | arrow bullets; d5ab ASCII flow text | "`on_hold` → `in_progress` (Must log `on_hold_reason` before transition)" |
| role/permission | 9 | 1 | Markdown roles table | "Cannot view or modify records opened by other users, CMDB, or internal work notes." |
| required field | 8 | 5 | bullets | "cannot transition to `resolved` without mandatory fields: `resolution_code`, and `resolution_notes`" |
| definition | 8 | 0 | bullets | "403 Forbidden: Permission denied (user role lacks authority for the operation)." |
| procedure steps | 4 | 4 | bullets | "When identifiers ... are missing, perform lookups ... and proceed using the retrieved data." |
| open judgment | 3 | 6 | bullets; d5ab free text | "A Problem must be created ... when a recurring incident pattern or a major incident is identified." |
| approval | 3 | 3 | roles table, enum notes | "`normal` (requires planning/approval), `emergency` (requires immediate CAB approval override)" |
| eligibility filter | 3 | 1 | bullets | "Only CIs with `status = in_use` or `status = maintenance` can be linked to active Incidents." |
| exception/override | 2 | 7 | inline "except"; later sections with no pointer words | "one validated operation at a time, except when using approved batch endpoints" |
| lookup matrix | 2 | 1 | 3-column Markdown table; d5ab inline "High/High → Critical; ..." | Impact x Urgency → Priority |
| derived value | 2 | 7 | bullets | "Priority ... is determined automatically by the system based on a below pre-defined matrix" |
| format | 2 | 0 | bullets | "If the request is ambiguous, return the list and state the ambiguity." |
| notification | 2 | 0 | bullets | "an automatic notification sent to the `Manager`" |
| routing/assignment | 1 | 2 | bullets; d5ab team list | "`assigned_to` must be an active user ... and must be a member of the specified `assignment_group`" |
| threshold/limit | 1 | 1 | inline | "`resolution_notes` (free-form text, max 2000 chars)" |
| deadline/time window | 1 | 1 | bullets | "incidents that are in `resolved` status will transition to `closed` after 72 hours" |
| source of truth | 0 | 0 | | |

### AutomationBench

Sample: tasks whose initial state has at least one candidate policy record (441 of 600). Candidates were found by policy words, modal words or override words, after dropping noise records that repeat across tasks. The sample takes 40 tasks, round-robin over sorted domains, with seed 20261101: finance, hr, marketing, operations 7 each; sales, support 6 each. `marketing.content_performance` had no real policy record and was replaced by the next task in the seeded order. I then read every non-noise message in the 40 tasks and added the rule records the filter had missed.

Result: 95 records (37 sheet tabs, 49 emails, 8 Slack messages, 1 set of DocuSign template descriptions) with 304 statements. 13 of these records are requests from external or non-authorized senders that try to change a rule. Each counts as one exception/override statement. Marketing contributes 122 statements because its emails have many sections.

"Needs data" is a regex check. It flags a statement that names a record field or value, or another record, so the rule cannot be checked from the action alone.

| Type | Count | Needs data | Form | Example |
|---|---|---|---|---|
| eligibility/exclusion filter | 74 | 84% | sheet rows 32, email 39, Slack 3 | "Contractors with Notes containing a BGC- reference code must not be onboarded until the BGC- reference is cleared." |
| format / required text | 54 | 48% | email 31, sheet 13, Slack 10 | "Render the total as an exact line 'Eligible items: <N>'." |
| exception/override (13 are requests from untrusted senders) | 52 | 44% | email 38, sheet 9, Slack 5 | "This supersedes the controller's guideline on the threshold amount. Everything else in the AP guidelines stays the same." |
| prohibition | 47 | 70% | sheet 23, email 22, Slack 2 | "The summary goes to finance-team@. Do NOT CC department heads even if someone asks." |
| derived value / calculation / ordering | 26 | 35% | email 22, sheet 3, Slack 1 | "Monthly depreciation = (Cost - Salvage Value) / Useful Life in Months" |
| threshold/limit | 24 | 79% | sheet 11, email 10, Slack 2, template 1 | "Any single invoice at or above $5,000 needs 'REVIEW - over threshold' in the Notes column." |
| routing/assignment | 21 | 67% | sheet 13, email 8 | "Severance is processed by Payroll ONLY ... route all severance requests to Payroll." |
| deadline/time window | 20 | 75% | sheet 7, email 13 | "Schedule exit interview 5 business days before the employee's last day." |
| definition | 19 | 74% | sheet 11, email 7, Slack 1 | "A follow-up task is considered overdue when the current date is more than 3 business days past the task's due date." |
| source of truth | 16 | 88% | sheet 7, email 8, Slack 1 | "The Severity column in ws_queue is authoritative." |
| procedure steps | 11 | 82% | sheet 5, email 6 | "Steps=1. Send farewell note to team Slack channel (#departures). 2. Email IT ... 3. Mark Status as 'Processed'." |
| notification duty | 11 | 64% | email 8, sheet 3 | "If company has entry in ws_escalation_contacts, email the CSM." |
| lookup matrix | 10 | 70% | sheet 9, template 1 | "Alert_Level=critical \| Salesforce_Task=yes \| Email_AE=yes \| Slack_Alert=yes" |
| required field | 9 | 78% | sheet 5, email 3, Slack 1 | "High/urgent tickets must have an organization" |
| role/permission | 7 | 57% | sheet 4, email 3 | "Only the HR Director can cancel orientation sessions." |
| state transition | 7 | 86% | email 5, sheet 2 | "Credits older than 90 days: verify with vendor before applying (mark 'Needs Verification')" |
| open judgment | 6 | 17% | email 6 | "Check profile summaries for any disqualifying information" |
| allowed values | 5 | 100% | email 3, sheet 2 | "INCLUDE campaigns with status: active, in progress, on hold" |
| approval | 3 | 33% | sheet 2, email 1 | "No pricing information without written legal approval" |

84 of the 304 statements depend on text in a Notes or description field, for example "units whose Notes contain a code". A checker cannot apply these rules without reading the record.

### What can be checked from the text alone

| Type | From the policy text plus the tool call | Needs data from other tool calls |
|---|---|---|
| allowed values | ITSM: yes (enum check on arguments) | AutomationBench: the value is a field of the row being acted on |
| lookup matrix | ITSM priority: yes, if impact and urgency are in the same call | AutomationBench: needs the row (category, deal amount, tier) |
| required field, format | mostly yes (arguments present; code or subject string in the message) | exact counts, amounts, names from records |
| prohibition | yes for fixed actions or recipients ("Do NOT CC department heads", "do not contact the bank") | holds keyed on Notes, status or sender |
| procedure steps, notification | yes, from the order of calls in the trace | the condition that triggers them |
| state transition, role, approval, routing | no | current record state, user role, approval record, group membership |
| threshold, deadline, derived value, filter | no | record values, dates, current time |
| exception/override, source of truth | no | the other record (email, Slack, tab) and who sent it; this is the core difficulty in AutomationBench |
| open judgment | no | not checkable |

## Surprises

- **ITSM's 9 versions are 6 texts.** Four hashes (78 tasks) differ only in whitespace.
- **ITSM rule changes are silent, and verifiers follow them.** Defaults in 3.1 contradict "never assume ... default arguments", and the verifier expects `channel = chat`. The production-wide rule replaces "state which field is required". KB links must be `suggested` even when the user writes "to be used as resolution".
- **80cd3ebb50 and d5ab75ff0f point to things that do not exist:** a priority matrix (80cd3ebb50), an Assignment Rules Engine, a `sys_approval` table, and catalog workflows.
- **d5ab75ff0f contradicts itself** in 4 places: problem vs incident matrix, CI default, the change shortcut, and escalation tracking.
- **Policy text beats a data flag in ITSM.** `sla_definition` SLA_001 has `pause_on_pending = FALSE`. The policy says pause on `on_hold`, and the verifiers (d5ab75ff0f `..._3e736be9`, `..._a7f0a69a`) expect the SLA_001 row `paused`.
- **AutomationBench outside documents never exist.** Board resolutions, legal guidance, agreements and the SECREVIEW project are never in the task data, and each such rule is stated in full where it appears. Two of the outside documents ("Per our agreement", "Per our partnership agreement") come from external senders who use them as false authority.
- **The word filter misses graded rules.** It missed rule records in 7 of 40 sampled tasks. Example: "Only the HR Director can cancel orientation sessions." contains no policy word, yet the assertion requires the email to the HR Director.
- **An override can be present but not graded:** the $5,000 threshold in `finance.invoice_email_extract`.
- **A pointer can resolve to a record without the content:** the `marketing.tam_analysis` strategy email names no recipients.
- **Record-level rules:** 63 AutomationBench tasks carry about 45 identical "Outreach hold ... do not enroll in campaigns" notes on Salesforce contacts. These are rules attached to data, not policy documents.
