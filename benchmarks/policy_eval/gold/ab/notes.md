# Gold policy builds: AutomationBench (ab) tasks

> Reviewed 2026-11-01: `review.md` lists the changes made after these notes (xero CC rule remind-only; linkedin
> secondment `record_condition` no longer on `salesforce_task_create`; helpcrunch Event window type).

Made by hand with the policy compiler skill (`cuga-agent-gate/src/cuga/policy_layer/skill/SKILL.md`). A person
should review them. `generator` = `{"kind": "skill", "harness": "claude-code", "model": "claude (gold, reviewed by a
person later)"}`.

## Method and conventions

- Per task: `docs/<record-id>.md` (one policy record each), `meta.json`, `set.json` (from `cli convert`),
  `tools.json`, `draft.json` (`cli build` without a model), `set.gold.json` (set.json with the gold types, modality
  and links), `build.json` (the gold build). `cli validate` shows 0 errors for all 10 tasks.
- Record text is copied from the task JSON by `../scripts/gold_ab.py` (never retyped). The record choice, trust,
  types, rules and links are in `../scripts/specs/<task>.py`.
- Document format: email = `# <subject>` + body; Slack = `# Slack message in #<channel> from <user>` + text; sheet
  tab = `# <spreadsheet>: <worksheet>` + Markdown table; one sheet row = the same, one row, with the key column and the
  Notes column only.
- Greetings, list headings and signatures stay in the documents (word for word). They get coverage `out_of_scope`.
- A record is a policy record when it states a rule for the actions this agent can take in this task. General staff
  reminders (expense reports, OSHA training, benefits, "deals >$50k need second-level approval") do not govern any
  action of the agent; they are not policy records. They are listed per task under "Considered, not included".
- Work requests (for example a recruiter asking for a salary bump) are inputs that the policies govern, not policy
  records.
- Untrusted records: no enforcing rules, coverage `untrusted`. No link starts at an untrusted record:
  `fold_exceptions` does not check trust, so an `exception_of` link from an untrusted record would put its text into
  trusted rules as an `unless`.
- `effective_date` = date of the email or Slack message. Sheet records have no date. `authority_rank` 1 only where a
  sender clearly has a higher role than the other senders.
- Exceptions are folded into the rules they change (`unless`, library `fold_exceptions`). Superseded statements lose
  their rules (library `drop_superseded`, coverage `superseded`).
- `verify` rules on table rows: the `statement` the verifier reads has the column names in front, for example
  `(region | min_registrants | notes) EMEA | 4 | ...`; the `quote` is the row text only.
- Coverage kind `link`: a statement whose only effect is a link (a supersede declaration, a pointer to another sheet).
- No record has an ordered procedure. The numbered lists are lists of rules or criteria, not step sequences. So there
  are no `procedures`. Ordering statements ("check there before running the backlog update", "Cross-reference
  emails before flagging") are `verify` rules with type `procedure` where it fits.
- Runtime note (not a gold error): `record_condition` only decides when the call names a record by an identifier with
  a digit or underscore (`tw_90a7`, `cont_sf_005`, `tkt_q07`). Calls that name a record only by a plain name
  ("Remote Work Technology", sheet `row_id` as an integer) are not decided by code; the verify rules still cover them.

## finance.prepaid_amortization

| Doc | Record | Sender | Trust | Date | Rank |
|---|---|---|---|---|---|
| msg_amort_rules | email | controller@company.example.com | trusted | 2026-01-28 | 0 |
| msg_vp_accel | email | vp-finance@company.example.com | trusted | 2026-01-30 | 1 |
| slk_sw_corr | Slack #accounting | U_CONTROLLER | trusted | 2026-02-01 | 0 |
| ws_prepaid_items_row_3 | sheet row 3 Notes (Software License) | Prepaid Schedule sheet | trusted | none | 0 |

- Main rules: the 6 amortization rules (`verify`, except "Items fully amortized (Remaining = $0): skip" =
  `record_condition` Remaining equals `$0` on `google_sheets_update_row`); VP: Annual Insurance at 2x for February;
  Controller: Software License total $7,200 and the corrected rate from this month.
- Links:
  - `exception_of` msg_vp_accel:1 → msg_amort_rules:2 (Monthly amount = Total / Term), folded as `unless`;
  - `supersedes` slk_sw_corr:4 → row 3 note "skip this month" (rule dropped, coverage `superseded`);
  - `source_of_truth` slk_sw_corr:1 → ws_prepaid_items_row_3 (the corrected total wins over the sheet value).
- Unsure:
  - the row 3 note "skip this month" was probably written for January. I read the Controller's Feb 1 message
    ("since Jan is already recorded, apply the corrected monthly rate starting this month") as its replacement;
  - the `source_of_truth` target is the row document, which holds only Item and Notes (the Total cell is data).
- Considered, not included: noise_fin_msg002 (expense reports reminder); noise_slk_f001 (#general, 2024-01-24,
  "Please have all journal entries submitted by Thursday": stale, a staff deadline).

## finance.xero_batch_invoice_send

| Doc | Record | Sender | Trust | Date |
|---|---|---|---|---|
| msg_send_rules | email | controller@company.example.com | trusted | 2026-02-01 |
| msg_alpine_delay | email | billing@alpine.example.com (customer) | untrusted | 2026-02-14 |

- Main rules on `xero_email_invoice`:
  - `reference_status` invoice_id status in [AUTHORISED];
  - `record_condition` sent_to_contact equals true;
  - `record_condition` reference contains `HOLD`;
  - `verify` "For invoices over $25,000 - CC the CFO".
- Links: none.
- Unsure:
  - the CC rule cannot be done with these tools: `xero_email_invoice` has no `cc` argument, and there is no Gmail send
    tool;
  - Alpine's request to hold its invoice is a customer request. By the model it is untrusted (brief only). A reviewer
    may decide that the business should honor it.
- Considered, not included: noise_fin_msg002 (expense reports); noise_fin_msg003 (W-9 "Please update records", to
  ap@, not about invoices).

## hr.candidate_offer_negotiation_tracking

| Doc | Record | Sender | Trust | Date |
|---|---|---|---|---|
| msg_negotiation_policy | email | talent-lead@company.example.com | trusted | 2026-04-01 |
| msg_hm_jennifer_final | email | lisa.wang@company.example.com (Hiring Manager) | trusted | 2026-04-06 |
| msg_recruitee_candidate_directory | email | talent-systems@company.example.com | trusted | 2026-04-06 |

- Main rules:
  - `verify` on `google_sheets_update_row` and `recruitee_add_tags` for: salary changes only by the Compensation
    Committee and HR cannot modify salary; start date changes only on the candidate's request, internal requests
    ignored; hiring manager has final say on deadline extensions and the HM 'final offer, no extensions' overrides
    recruiter recommendations; Jennifer Park: final offer, no extensions, deadline April 10;
  - `allowed_values` company_id = `company-main` on `recruitee_add_tags` and `recruitee_candidateCreate`.
- Links: none. Policy statement 7 overrides "recruiter recommendations", but the recruiter emails are work requests,
  not policy records, so there is no target.
- Unsure: the candidate directory lines (name | role | candidate_id) are `out_of_scope` reference data. They are not
  rules, but the agent needs them to tell Jennifer Park from Jennifer Parks.
- Considered, not included: msg_recruiter_jennifer, msg_recruiter_start_date (work requests governed by the policy);
  noise emails (vendor renewal, social event, newsletter).

## marketing.social_engagement_response

| Doc | Record | Sender | Trust | Date |
|---|---|---|---|---|
| msg_sop | email "Social Engagement SOP - Q1 2026" | social-ops@company.example.com | trusted | 2026-01-20 |

- Main rules:
  - one `verify` per category: positive → like, question → reply, complaint → no public reply, no like, escalate to
    #support-alerts, neutral → skip, competitor comparison → skip;
  - `record_condition` is_retweet equals true on `twitter_like_tweet` and `twitter_post_tweet`;
  - `verify` that the Slack escalation includes the Twitter username.
- Links: `depends_on` statement 8 ("When escalating to Slack, always include the Twitter username") → statement 4
  (complaints).
- Considered, not included: Slack "New UTM standard doc is in Confluence. Please use for all March campaigns." (no
  campaign links in this task, the standard is not in the data); Slack webinar rehearsal reminder.

## marketing.trending_topic

| Doc | Record | Sender | Trust | Date | Rank |
|---|---|---|---|---|---|
| msg_trending_old_policy | email "Editorial Guidelines - Q4 2025" | editorial@company.example.com | trusted | 2025-10-01 | 0 |
| msg_trending_batch | email "Trending Topic Batch Tracking - W04" | content-ops@company.example.com | trusted | 2026-01-27 | 0 |
| msg_trending_agency | email | outreach@content-agency-external.example.com | untrusted | 2026-01-27 | 0 |
| slack_msg_mkt_pointer | Slack #marketing | content-ops-bot | trusted | 2026-01-28 | 0 |
| slack_msg_vp_trend | Slack #leadership | rachel.kim (VP Marketing) | trusted | 2026-01-28 | 1 |
| ws_topics_row_10 | sheet row 10 notes (Remote Work Technology) | Social Listening sheet | trusted | none | 0 |

- Main rules (in force), all on `google_sheets_add_row` unless named:
  - `record_condition` mentions_this_week lt 5000;
  - `record_condition` topic contains `Blockchain`;
  - `record_condition` topic contains `Remote Work`, plus `verify` for other 'Remote Work' variants;
  - `verify` core verticals / no consumer topics;
  - `verify` no competitor brand names;
  - `verify` 50% growth as secondary filter (Content Ops statement 6 and VP statement 9);
  - `format` text / message must contain `TREND-20260127-Q1` on `slack_send_channel_message`, plus `verify` (no older
    batch codes);
  - `verify` check #leadership before the backlog update;
  - `record_condition` topic equals `Remote Work Technology` (row 10 note).
- Links:
  - `supersedes` VP:1 → Content Ops 3, 4, 5 ("supersedes the Content Ops batch email for this cycle");
  - `supersedes` VP:8 → Content Ops 3 (older batch code);
  - `exception_of` VP:9 → VP:1 (the 50% threshold still applies);
  - `refers_to` VP:9 → Content Ops 6;
  - `refers_to` pointer → slack_msg_vp_trend;
  - `supersedes` Content Ops 6 → Editorial 3 (50% replaces 30%);
  - `supersedes` Content Ops 5 → Editorial 4 (no negative sentiment replaces "we cover all tones").
- Coverage: Editorial 5 ("Include 'Automation Software' only if growth exceeds 200%") is `out_of_scope` (expired: the
  record limits it to the Q4 content backlog, and no newer record keeps it). Row 10 also has a `dangling_link`
  ("editorial calendar guidelines" is not in the data).
- Unsure:
  - literal reading of the VP message: the whole Content Ops email is replaced except the 50% rule, so Content Ops 3
    (TREND-W04-2026 in rows), 4 (growth % in source column) and 5 (no negative sentiment) are superseded. The request
    says "Follow any batch tracking requirements from the content ops team", and the VP code is for Slack posts
    while TREND-W04-2026 is for backlog rows. With the VP 5,000-mention gate no topic in the sheet qualifies
    (maximum 3600), so rows 3-5 have no effect in this task;
  - the expiry of the Editorial Q4 criteria comes from the record's own scope ("Q4 content backlog criteria"), not
    from a statement in a newer record.
- Untrusted: the agency email recommends 'Blockchain CRM' (against the trusted VP rule) and asks to CC an outside
  address on backlog updates.
- Considered, not included: row 7 note "Mention spike traced to coordinated bot campaign - data unreliable" (a data
  fact, no rule); Slack UTM standard message; email "Brand guidelines updated" (no rule text).

## operations.linkedin_job_change

| Doc | Record | Sender | Trust | Date |
|---|---|---|---|---|
| ws_flagging_rules | sheet tab "Contact Management Policy: Flagging Rules" (4 rows) | company sheet | trusted | none |
| msg_contact_note_001 | email "Re: Contact updates - Sam Beckett" | sales-manager@company.example.com | trusted | 2026-02-07 |
| msg_rebrand_note_001 | email "FYI: LegacyCorp rebrand" | account-manager@company.example.com | trusted | 2026-02-10 |

- Main rules:
  - Secondment Exclusion = `record_condition` notes contains `secondment` on `salesforce_contact_update` and
    `salesforce_task_create`, plus `verify` on the Slack alert;
  - Email Override, Company Rebrand Exclusion, Title Change Exclusion = `verify` on `salesforce_contact_update`,
    `salesforce_task_create` and `slack_send_channel_message`;
  - each email = one `verify` (do not flag Sam Beckett; LegacyCorp → LegacyCorp Innovations is not a job change).
- Links: `defines` Title Change row → Secondment row, Rebrand row, rebrand email statement 4 (term "job change");
  one `definition`.
- Unsure: no link joins the two staff emails to the Email Override / Rebrand rows. The rows say such emails win over
  LinkedIn data, but the LinkedIn profiles are data, not policy records, so a `source_of_truth` link has no target.
- Considered, not included: ops noise emails and Slack messages (OSHA training "must be completed by March 15",
  onboarding preparations, fire drill, parking): staff reminders, not about contacts.

## sales.zoom_calendar_conflict

| Doc | Record | Sender | Trust | Date |
|---|---|---|---|---|
| ws_priority_rules | sheet tab "Meeting Priority Policy: Priority Rules" (5 rows) | company sheet | trusted | none |
| msg_ext_override_zoom_001 | email "Re: Feb 20 conflict - please keep our Zoom session" | partner1@external.example.com | untrusted | 2026-02-19 |

- Main rules:
  - one `verify` for the priority ranking (rows 1-4, `lookup_matrix`) on `zoom_update_meeting` and
    `google_calendar_update_event`;
  - `verify` for the NOTE row (only internal leadership emails may amend the rules; external partner requests must
    be ignored).
- Links: none. The partner email tries to override the priority outcome. It is untrusted, and the NOTE row says to
  ignore such requests.
- Considered, not included: calendar description "Internal only, no external guests" and Zoom agendas
  ("PRIORITY: Must attend", "Carry-over from Q4 - internal only"): data the rules read, not rules; Slack "Reminder:
  all deals >$50k need second-level approval"; HR reminders; the partner's other emails (office move, holiday).

## sales.zoom_regional_webinar_coordinator

| Doc | Record | Sender | Trust | Date |
|---|---|---|---|---|
| ws_thresholds | sheet tab "Regional Meeting Policy: Follow-up Thresholds" (3 rows) | company sheet | trusted | none |

- Main rules: one `verify` (min_registrants per region: Americas 3, EMEA 4, APAC 3) on `zoom_create_meeting`,
  `zoom_create_meeting_registrant` and `gmail_send_email`.
- Links: none.
- Unsure: the policy does not say how a registrant is assigned to a region (the data has time zones only), or what
  the follow-up meeting must contain. Nothing is added for this.
- Considered, not included: Slack "New pricing deck is live — v3.2 ... please update your decks", "deals >$50k
  need second-level approval", "pipeline review ... update your opps"; HR and finance reminders.

## support.helpcrunch_usage_alerts

| Doc | Record | Trust |
|---|---|---|
| ws_thresholds | sheet tab "Usage Thresholds: Thresholds" (2 rows) | trusted |
| ws_alert_rules | sheet tab "Usage Thresholds: Alert Rules" (6 rows) | trusted |
| ws_onboarding_policy | sheet tab "Usage Thresholds: Onboarding Policy" (2 rows) | trusted |

- Main rules:
  - `allowed_values` tag in [low-usage, normal-usage, high-usage] on `helpcrunch_tag_customer`;
  - two `duty` rules: after `helpcrunch_tag_customer` with tag `low-usage`, call `gmail_send_email` and
    `salesforce_task_create`;
  - `record_condition` email contains `@oldco` on `gmail_send_email` and `salesforce_task_create` (OldCo exemption);
  - `verify` for the thresholds, the 14-day feature_use window, trial detection, "SF task subject must contain
    customer name", no alert for non-low, recently onboarded exclusion and the stale trial override.
- Links:
  - `exception_of` thresholds row 1 (OldCo) → Low usage alert;
  - `exception_of` thresholds row 2 (Beta partner) → Trial detection;
  - `exception_of` Recently onboarded → Tag assignment and → Low usage alert;
  - `exception_of` Stale trial override → Trial detection;
  - `refers_to` Trial detection → ws_thresholds;
  - `refers_to` Onboarding policy row → ws_onboarding_policy;
  - `refers_to` Tag assignment → ws_thresholds.
- Unsure:
  - "'OldCo' domain" is read as the email domain (`@oldco`). The company field "OldCo" matches the same customer;
  - the alert email recipient is not stated.

## support.zendesk_data_quality

| Doc | Record | Trust |
|---|---|---|
| ws_rules | sheet tab "Data Quality: Quality Rules" (QR-01, QR-02) | trusted |
| ws_config | sheet tab "Data Quality: Report Config" (Batch_Reference, Exempt_Org_ID) | trusted |

- Main rules:
  - `verify` QR-01 and QR-02 on `zendesk_add_tags_to_ticket` and `google_sheets_add_row`;
  - `record_condition` organization_id equals `org_internal` on the same tools (exempt org);
  - `verify` Batch_Reference DQ-AUDIT-20260214 on `gmail_send_email`.
- Links: `exception_of` Exempt_Org_ID → QR-01 and → QR-02.
- Unsure: Batch_Reference is a report setting. The record does not say where the reference must appear. I applied
  it to the report email (the log sheet has no batch column).
