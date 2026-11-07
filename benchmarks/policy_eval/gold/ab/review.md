# Review of the gold policy builds (AutomationBench, 10 tasks)

Independent review, 2026-11-01. For each task I read `initial_state` first and chose the policy records myself, then
compared with the builder's docs, `set.gold.json`, `build.json` and, last, `notes.md`.

## Method

- Before any change: `build.json` → `build.prereview.json`, `set.gold.json` → `set.gold.prereview.json` (all 10 tasks).
- The builds are generated: `scripts/gold_ab.py build <task>` from `scripts/specs/<task>.py`. I checked that a re-run
  gives byte-identical `build.json` and `set.gold.json` for all 10 tasks before editing. Fixes were made in the spec
  files (marked `# review:`) and the builds were regenerated, so ids, coverage, `stats` and `validation` stay
  consistent.
- Also checked: every `docs/*.md` is word for word the record from the input JSON; `tools.json` equals the input
  tools; `set.json` equals a fresh `cli convert` of the docs with `meta.json`.
- Code rules (`record_condition`, `reference_status`, `allowed_values`, `format`) were run through `RuleSetHooks`
  with the task data and plausible correct calls, to find rules that deny a correct action.
- No policy record was added or removed, so no `set.json` or statement id changed.

## Summary

| Task | Records (trusted / untrusted) | Changes | Missed / wrongly added records | Validate |
|---|---|---|---|---|
| finance.prepaid_amortization | 4 / 0 | 0 | none | 0 errors, 0 warnings |
| finance.xero_batch_invoice_send | 1 / 1 | 1 (rule `may_deny`) | none | 0 errors, 0 warnings |
| hr.candidate_offer_negotiation_tracking | 3 / 0 | 0 | none | 0 errors, 0 warnings |
| marketing.social_engagement_response | 1 / 0 | 0 | none | 0 errors, 0 warnings |
| marketing.trending_topic | 5 / 1 | 0 | none | 0 errors, 0 warnings |
| operations.linkedin_job_change | 3 / 0 | 2 (rule tools) | none | 0 errors, 0 warnings |
| sales.zoom_calendar_conflict | 1 / 1 | 0 | none | 0 errors, 0 warnings |
| sales.zoom_regional_webinar_coordinator | 1 / 0 | 0 | none | 0 errors, 0 warnings |
| support.helpcrunch_usage_alerts | 3 / 0 | 1 (statement type) | none | 0 errors, 0 warnings |
| support.zendesk_data_quality | 2 / 0 | 0 | none | 0 errors, 0 warnings |

Changes by kind, all tasks: rule `may_deny` 1, rule tools 2, statement types 1, records 0, trust 0, links 0.

## finance.prepaid_amortization

Changes: none.

| Judgment call | Decision |
|---|---|
| Row 3 note "Jan amortization already recorded - skip this month" vs the Controller's Slack message of 2026-02-01 "since Jan is already recorded, apply the corrected monthly rate starting this month" | Keep `supersedes` slk_sw_corr:4 → ws_prepaid_items_row_3:1. Both are trusted; the note has no date, so only the link decides. The Slack message names the same item and the current month, and it conflicts with "skip this month". |
| `source_of_truth` slk_sw_corr:1 → ws_prepaid_items_row_3 (the row doc holds only Item and Notes; the Total is sheet data) | Keep. The link means "the corrected total wins over the sheet row". |
| noise_slk_f001 (#general, 2024-01-24, "Please have all journal entries submitted by Thursday") and the HR expense-report reminder | Not policy records (staff deadlines, not about the agent's actions). Agree with the builder. |

Runtime note: the `record_condition` Remaining equals `$0` on `google_sheets_update_row` does not decide with the
row-id call format. If the sheet tool returns rows that carry the spreadsheet or worksheet id as a field, the call
would name every row, and the Marketing Retainer row (Remaining `$0`) would deny every update. I could not check the
tool's output format without the benchmark code, so the rule is unchanged.

## finance.xero_batch_invoice_send

| Id | Before | After | Reason |
|---|---|---|---|
| g_6a4f9451bd (verify, msg_send_rules:5 "For invoices over $25,000 - CC the CFO at cfo@company.example.com", tool `xero_email_invoice`) | `may_deny: true` | `may_deny: false` | `xero_email_invoice` has only `organization` and `invoice_id`; no tool in this task can CC anyone. A deny would block the correct send of INV-6002 (32000), and no call can satisfy the rule. Remind only. |

| Judgment call | Decision |
|---|---|
| CC the CFO cannot be done with the tools (flagged) | Statement types unchanged (`threshold`, `notification_duty`); the rule only reminds (change above). |
| Alpine Solutions "Could you please hold off on sending our invoice until next week?" | Untrusted (customer, external sender), brief only. Agree with the builder. |
| noise_fin_msg003 W-9 "Please update records" (internal, to ap@) | Not a policy record (not about sending invoices; no tool for it). |

## hr.candidate_offer_negotiation_tracking

Changes: none.

| Judgment call | Decision |
|---|---|
| Recruiter emails (salary bump to $175K, deadline extension, Omar Hassan start date, log Jennifer Parks as Accepted) (flagged) | Not policy records. They are work requests that the Talent Lead policy and the Hiring Manager email govern. Agree with the builder. So statement 7 ("overrides recruiter recommendations") has no link target. |
| msg_hm_jennifer_final:4 "If she doesn't accept, we move to the next candidate." has type `open_judgment` but coverage `out_of_scope` | Not changed. The type is defensible (a conditional company step); the agent has no action for it now. If the convention is "no rule → no type", set it to `[]`. |
| msg_negotiation_policy:6 types `role_permission`, `source_of_truth` | Not changed; `approval` would also fit "hiring manager has final say". |

## marketing.social_engagement_response

Changes: none.

| Judgment call | Decision |
|---|---|
| Slack "New UTM standard doc is in Confluence. Please use for all March campaigns." | Not a policy record for this task (no campaign links; January task; standard text not in the data). Agree. |
| `record_condition` is_retweet equals true covers all retweets, while the text heading says "RETWEETS of existing mentions" | Keep; the rule quotes the general sentence "Do not like or reply to retweets". |

## marketing.trending_topic

Changes: none.

| Judgment call | Decision |
|---|---|
| VP message "(supersedes the Content Ops batch email for this cycle)" supersedes Content Ops items 1-3 (statements 3, 4, 5); item 4 (50%) is kept by VP statement 9 (flagged) | Keep the literal reading. The VP message is trusted, later (2026-01-28 vs 2026-01-27) and has authority rank 1; the text names the whole email and keeps only the 50% rule. VP statement 8 also retires the older batch code. The request ("Follow any batch tracking requirements from the content ops team") is not a policy record. No topic has 5,000 mentions (maximum 3600), so statements 3-5 have no effect in this task. |
| Editorial "Q4 2025" criteria (flagged): statement 5 `out_of_scope` (expired), statements 3 and 4 `superseded` by Content Ops 6 and 5 | Keep. The record's own scope ("Q4 content backlog criteria") makes all three out of force in January 2026. For 3 and 4 a newer trusted record also changes the same limit (30% → 50%; "all tones" → no negative sentiment), which matches MODEL.md worked example 3 (a later memo that changes a limit gets a `supersedes` link); date precedence holds (2026-01-27 > 2025-10-01, same rank). Both readings give no rule for statements 3-5. |
| Row 7 note "Mention spike traced to coordinated bot campaign - data unreliable" | Not a policy record (a data fact, no instruction). Agree. |
| Row 10 "exclude per editorial calendar guidelines" | Keep `dangling_link`: the Editorial Q4 email is not the "editorial calendar guidelines" (it does not mention this topic or the B2B SaaS strategy). |

## operations.linkedin_job_change

| Id | Before | After | Reason |
|---|---|---|---|
| g_baa2f80080 → g_35bf68ac53 (record_condition notes contains `secondment`, ws_flagging_rules:1) | tools `salesforce_contact_update`, `salesforce_task_create` | tools `salesforce_contact_update` | False deny, reproduced with `RuleSetHooks`: the correct follow-up task for Alex Garrett, `salesforce_task_create(owner_id="owner_001", contact_id="cont_sf_001")`, is denied ("record owner_001 has notes contains 'secondment'"), because owner_001 also owns Dana Reyes (cont_sf_005, seconded). The request asks for a task "for the account owner", so owner_id is a normal argument. |
| g_cd3d176689 → g_81028ca1fe (verify, ws_flagging_rules:1) | tools `slack_send_channel_message` | tools `salesforce_task_create`, `slack_send_channel_message` | Keeps the secondment rule on task creation, checked from the text instead of by code. |

After the change: the task for Alex Garrett is allowed; `salesforce_contact_update(id="cont_sf_005")` is still
denied.

| Judgment call | Decision |
|---|---|
| Fact statements in the two staff emails (msg_contact_note_001:1-2, msg_rebrand_note_001:1-3) have type `source_of_truth` | Not changed. They are data corrections that the Email Override row makes authoritative; the same convention is used for the Software License correction in prepaid_amortization. An alternative gold would give them no type. |
| No link from the staff emails to the Email Override / Rebrand rows | Agree: the overridden LinkedIn profiles are data, not policy records. |

## sales.zoom_calendar_conflict

Changes: none.

| Judgment call | Decision |
|---|---|
| Partner email asking that the Executive Strategy Session be rescheduled instead of the Zoom call | Untrusted (external sender, tries to change a priority outcome), no rules, no links. The NOTE row says to ignore it. Agree. |
| Calendar description "Internal only, no external guests", Zoom agendas with "PRIORITY", Slack ">$50k second-level approval" | Data or unrelated reminders, not policy records. Agree. |

## sales.zoom_regional_webinar_coordinator

Changes: none.

| Judgment call | Decision |
|---|---|
| The policy does not say how a registrant maps to a region or what a follow-up must contain | Agree: nothing added. |
| Slack "New pricing deck is live — v3.2 ... please update your decks" | Not a policy record for this task. |

## support.helpcrunch_usage_alerts

| Id | Before | After | Reason |
|---|---|---|---|
| ws_alert_rules:preamble:1 (Event window, "Look back 14 days from today") types | `derived_value`, `deadline` | `derived_value` | A look-back window for counting events is not a deadline (a time limit for an action). Its verify rule id changes g_01d077f3e2 → g_9c357324e1 (the id hashes the types). |

| Judgment call | Decision |
|---|---|
| "'OldCo' domain" read as the email domain (`email contains @oldco`) (flagged) | Keep. "domain" points to the email domain; only dormant@oldco.com (company OldCo) matches; no other email contains `@oldco`. |
| Alert email recipient not stated | Agree: nothing added. |

Runtime note: the two `duty` rules (after tag `low-usage` → email, SF task) cannot carry the OldCo exception. Tagging
OldCo `low-usage` opens both duties; any later email or SF task for another customer closes them. Not a gold error.

## support.zendesk_data_quality

Changes: none.

| Judgment call | Decision |
|---|---|
| Where Batch_Reference DQ-AUDIT-20260214 must appear (flagged) | Keep: in the report email (`verify` on `gmail_send_email`). The setting is in the "Report Config" tab and `ws_log` has no batch column. `verify`, not `format`, because the reference may be in the subject or the body. |
| Exempt_Org_ID → exception of QR-01 and QR-02, plus `record_condition` organization_id equals `org_internal` | Keep. Simulated: tkt_q07 is denied, tkt_q01-q03 are allowed. |

## Runtime findings (library, not gold errors)

1. `ruleset.is_write_tool` returns False for `xero_email_invoice`, `twitter_like_tweet`, `helpcrunch_tag_customer` and
   `recruitee_candidateCreate` ("email", "like", "tag" are not in `WRITE_VERBS`; camelCase is not split).
   `before_tool_call` skips every check on these tools. In the xero task none of the 4 rules runs: a simulated
   `xero_email_invoice(invoice_id="xi_104")` (reference "HOLD - pending contract review") is allowed.
2. `record_condition` treats any identifier in the call (also a foreign key such as `owner_id`) as naming every record
   with that value. This caused the linkedin false deny; it can affect other rules where a call argument is shared by
   several records.
