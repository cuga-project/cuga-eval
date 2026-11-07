# ITSM failure taxonomy (DeepSeek-V4-Pro, arm A)

Source: `benchmarks/enterpriseops_gym/results/*/A_*.json` with model DeepSeek (90 runs, 32 tasks, 47 failing runs).
Each distinct (task, verifier index) that failed at least once was read by hand: verifier SQL, user prompt, the task's policy text, and the agent's tool calls. Labels are in `itsm_labels.json`. Several tasks repeat the same verifier (for example 3e736be9 V0 = V5), so check counts overweight those tasks.

## Totals

| Feature | Distinct pairs | Failed checks (by run) |
|---|---|---|
| F1 SOP next-step | 7 | 17 |
| F2 end-state check | 1 | 3 |
| F3 policy table / default | 5 | 12 |
| F4 deliverables checklist (from the request) | 18 | 45 |
| NONE (capability or upstream) | 11 | 27 |
| Total | 42 | 104 |

Failing runs that would pass if every failure of the feature set were fixed (upper bound; 47 failing runs):

| Feature set | Failing runs fully recovered |
|---|---|
| F1 only | 4 |
| F4 only | 19 |
| F1 + F2 + F3 | 9 |
| F1 + F2 + F3 + F4 | 28 |

With all four, 43 + 28 = 71 of 90 runs would pass (upper bound: it assumes the agent fixes every flagged item).

## All failing pairs

| Task:verifier | Verifier | Failed / runs | Feature | What the agent did | Policy quote |
|---|---|---|---|---|---|
| 03a04c19:0 | Verify if the SLA is paused if the incident is on hold. | 1/3 | F1 | on_hold 'Awaiting Caller' without pausing the SLA (1 of 3 runs) | The SLA timer must be paused (stage = paused) when the Incident is in stage = on_hold |
| 0e601eac:0 | Verify SLA Paused | 1/2 | F1 | on_hold 'Awaiting Caller' without pausing the SLA (1 of 2 runs) | The SLA timer must be paused (stage = paused) when the Incident is in stage = on_hold |
| 27934d6b:1 | New KB | 3/9 | F1 | policy: create a knowledge draft at closure; agent created state published or left the default (published) | the Agent must be prompted to create and link a new knowledge draft before final closure |
| 27934d6b:3 | New KB | 3/9 | F1 | duplicate of V1 | the Agent must be prompted to create and link a new knowledge draft before final closure |
| 27934d6b:4 | New KB | 3/9 | F1 | duplicate of V1 | the Agent must be prompted to create and link a new knowledge draft before final closure |
| 3e736be9:3 | SLA paused | 3/3 | F1 | incident put on_hold 'Awaiting Change'; SLA never paused | The SLA timer must be paused (stage = paused) when the Incident is in stage = on_hold |
| 3e736be9:8 | SLA paused | 3/3 | F1 | duplicate of V3 | The SLA timer must be paused (stage = paused) when the Incident is in stage = on_hold |
| dd00cc8f:1 | user_added_to_group | 3/3 | F2 | policy: assigned_to must be a member of the assignment_group; Cheryl was assigned incidents but never added to the group | assigned_to must be an active user with the Agent or Manager role and must be a member of the specified assignment_group |
| 3e736be9:0 | Verify Change | 3/3 | F3 | change defaults in policy (impact default low, risk default low, category default other, priority from Impact x Risk matrix); agent set impact high, priority moderate | impact ('high','medium','low') [not null, default: 'low'] ... category [... default: 'other'] ... matrix of Impact x Risk |
| 3e736be9:5 | Verify Change | 3/3 | F3 | duplicate of V0 | impact ('high','medium','low') [not null, default: 'low'] ... category [... default: 'other'] ... matrix of Impact x Risk |
| c23d76df:2 | Record Incident | 2/2 | F3 | policy default 'channel (if not provided -> default = chat)'; agent inferred email from 'wrote to us' | channel (if not provided → default = chat) |
| c23d76df:5 | Record Incident | 2/2 | F3 | duplicate of V2 | channel (if not provided → default = chat) |
| c23d76df:8 | Record Incident | 2/2 | F3 | duplicate of V2 | channel (if not provided → default = chat) |
| 00dab62f:0 | Verify Change Assignment Update | 2/3 | F4 | no writes: agent failed the user lookup (get_user with an email) and stopped; reassignment named in request |  |
| 00dab62f:1 | Verify Change-Problem Mapping Exists | 2/3 | F4 | no writes; change-problem mapping named in request |  |
| 00dab62f:2 | Verify Change-Incident Mapping Exists | 2/3 | F4 | no writes; change-incident mapping named in request |  |
| 00dab62f:3 | Verify Complete Traceability Chain | 2/3 | F4 | no writes; traceability mappings named in request |  |
| 2dc8b3ce:1 | validate_reporter_notification_escalated | 2/2 | F4 | request says 'sending reports'; agent used no type or update; one run also missed 'top priority'/'expectation' from the request |  |
| 2dc8b3ce:2 | validate_assignee_notification_urgent | 2/2 | F4 | request says 'reports'; type missing or alert |  |
| 55f848d3:1 | Open incidents moved to new service and service offering | 2/3 | F4 | request: move incidents to the new service AND offering; one incident got only the service |  |
| 55f848d3:2 | Old service is retired | 3/3 | F4 | implied: 'Enterprise Email is being decommissioned' -> retire old service; never done |  |
| 55f848d3:3 | Old service offering retired | 3/3 | F4 | implied: retire old offerings; never done |  |
| 6bb33392:1 | Verify Incident Link to SLA | 3/3 | F4 | weak: request says 'high-priority SLA' (SLA_002); agent linked the critical SLA, which matches the policy matrix; request and policy conflict |  |
| 7196ef19:2 | verify_notification_inc_016_sent | 3/3 | F4 | request says 'Send reports'; agent used type alert |  |
| 7196ef19:3 | verify_notification_inc_014_sent | 3/3 | F4 | same |  |
| 7196ef19:4 | verify_notification_inc_003_sent | 3/3 | F4 | same |  |
| 7196ef19:5 | verify_notification_inc_004_sent | 3/3 | F4 | same |  |
| 8218da6c:0 | Checking for creation of new user. | 2/2 | F4 | partial: request names location 'New York' (location_id not set); user_name 'sarah.connor' is a naming convention |  |
| 893f6b2c:2 | verify_notification_sent | 2/2 | F4 | request says 'send a report'; agent used type update |  |
| c088062a:2 | validate_notification_sent | 3/3 | F4 | request says 'Send a report'; agent used type alert |  |
| ccb66a9a:1 | Sending notification | 3/3 | F4 | notification message must equal the text quoted in the request; agent added a period or rewrote it |  |
| 0e601eac:2 | Verify Incident Update Child | 2/2 | NONE | upstream: verifier reads incident.parent_incident; agent used add_child_incident, which writes a mapping table (same tool passes in a4b1468a) |  |
| 55f848d3:0 | New service created | 1/3 | NONE | service_classification must be copied from the old service (business); one run used application |  |
| 6bb33392:0 | Verify Incident CI | 3/3 | NONE | upstream: expects channel 'phone' (request says an email was received) and priority 'high' (policy matrix gives critical for high x high), plus words device/shutdown in short_description |  |
| 6bb33392:2 | Verify notification | 3/3 | NONE | message must contain 'problem' and 'currently', not asked for in the request |  |
| a4b1468a:2 | incident_inc_101_creation | 3/3 | NONE | new incident category 'database' not stated in request or policy (agent used default inquiry-help); 1 run also set impact/urgency high |  |
| a4fb07a9:0 | Existing Change Updated with Additional CI | 3/3 | NONE | expects the CI serial in change short_description; agent wrote it in implementation_plan/close_notes |  |
| dd00cc8f:3 | incidents_assigned_correctly | 2/3 | NONE | agent read 'open' as status new only and skipped on_hold incidents |  |
| dd00cc8f:4 | notification_sent | 3/3 | NONE | expects notification status 'sent' (not stated) |  |
| e6e42358:3 | verify_notification_sent_to_previous_assignee | 3/3 | NONE | expects notification status 'sent'; tool default is queued and another task expects queued |  |
| e6e42358:4 | verify_notification_sent_to_new_assignee | 3/3 | NONE | same as V3 |  |
| f8774fe4:1 | Verify Problem Update | 1/2 | NONE | problem must be closed; request only says 'residual risk has been accepted' (inference) |  |

## Examples per feature

**F1 SOP next-step** (7 pairs, 17 checks)
- 3e736be9 V3/V8: incident set `on_hold`, reason `Awaiting Change`; `update_incident_sla_details(stage=paused)` never called (3/3 runs).
- 0e601eac V0, 03a04c19 V0: same trigger with `Awaiting Caller`. The SLA was paused in the other runs, so the agent knows the step but forgets it 1 run in 2–3.
- 27934d6b V1/V3/V4: knowledge article created as `published`, or `state` left out (the tool defaults to published); the policy says draft (3/9 runs).

**F2 end-state check** (1 pair)
- dd00cc8f V1: 5 incidents reassigned to Cheryl, but she was never added to the incidents' assignment group (3/3 runs). A write-time check on `update_incident.assigned_to` would also catch it.

**F3 policy table / default** (5 pairs, 12 checks)
- 3e736be9 V0/V5: the request gives no impact, so the policy defaults apply (impact low, risk low, category other, priority from the Impact x Risk matrix). The agent set impact high, priority moderate and category application_software.
- c23d76df V2/V5/V8: the policy default is `channel = chat`; the agent inferred `email` from 'wrote to us'.

**F4 deliverables checklist** (18 pairs, 45 checks)
- Notification type named in the request ('send a report' → `type=report`): 7196ef19 V2–V5 (12 checks), 2dc8b3ce V1/V2, 893f6b2c V2, c088062a V2. 8 pairs, 21 checks. A code check (request word = enum value of the argument) would catch all of them.
- Exact text quoted in the request: ccb66a9a V1 (the agent added a period).
- Actions named in the request but never done: 00dab62f V0–V3 (the agent stopped after a failed user lookup), 55f848d3 V2/V3 (retire the old service and offerings; only implied by 'being decommissioned').
- Values named in the request: 8218da6c V0 (location 'New York'), 55f848d3 V1 (the offering not set on one incident), 6bb33392 V1 ('high-priority SLA'; this conflicts with the policy matrix).

**NONE** (11 pairs, 27 checks)
- Upstream benchmark: 6bb33392 V0 (expects channel phone after 'an email was received', and priority high for high x high), 0e601eac V2 (checks `incident.parent_incident`, while the child-link tool writes a mapping table), e6e42358 V3/V4 and dd00cc8f V4 (expect status `sent`; the tool default is `queued` and another task expects queued).
- Agent inference: a4b1468a V2 (category database), f8774fe4 V1 (close the problem), dd00cc8f V3 ('open' read as `new` only), a4fb07a9 V0 (field choice), 55f848d3 V0, 6bb33392 V2 (hidden words).

## Which features to build, ranked by recoverable failures

1. **F4 deliverables checklist**: 45 checks, 19 failing runs on its own. The largest part is cheap and exact: an enum value of a write argument that the request names ('report', 'reminder', 'alert', 'draft'). Missing actions need the agent to find a way to do them; a reminder is the only help.
2. **F1 SOP next-step**: 17 checks. Two rules cover all of them: SLA pause on hold, and the knowledge draft at closure. Both are compiled already in some builds, but intake drops them in others (see the parent's 10:40 log).
3. **F3 policy defaults and tables**: 12 checks, all in 2 tasks. Policy defaults ('if not provided → default = X') and the Impact x Risk matrix. Code can check these once intake reads the defaults.
4. **F2 end-state checks**: 3 checks (1 pair). It can also be a write-time rule.

Not recoverable by any layer feature: 27 of 104 checks (11 of 42 pairs). About half are benchmark expectations that contradict the request or policy, or are stated nowhere.
The upper bound assumes every flagged item is then fixed. Run-level: F1–F4 together could recover at most 28 of 47 failing runs.
