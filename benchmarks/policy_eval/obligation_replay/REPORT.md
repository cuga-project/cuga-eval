# Obligation replay: may the ledger send follow-ups? (task 4.3)

**Result.** No producer passes the rule on any benchmark: all stay at level 1. Every number is on tuning policies or on sets that are held-out only in status (`audit_report.basis_of`, and the table of runs by set): none is a held-out result, and the replay gives no score gain. **The ledger cannot send on `package` today**: see the section on why.

**ITSM `request`, on gate `fcb15283d`:** false-open 0 of 95 (0.0%), recall 37 of 134 (27.6%), 13 of 57 runs get a follow-up, level 1. On the gate before the change that gives request items no keys, it passed: false-open 3 of 95 (3.2%), recall 57 of 134 (42.5%), level 2, not firm: one count per task gave 7.7% false-open and 26.1% recall, the mean of task rates 10.2% and 27.9%; by set, `itsm-tune` 0 of 74 (0.0%) false-open, 53 of 96 (55.2%) recall; `itsm-unseen` 2 of 19 (10.5%) false-open, 1 of 27 (3.7%) recall. 24 of its 58 sends were made while a successful call of the item's tool existed: the follow-up then said that no successful call did the work, which is false. The section on that change shows it.

## What was replayed

No agent ran. Finished arm-A runs were read, their tool calls were given to the real ledger (`ObligationLedger`, gate commit `fcb15283d`, a clean copy of that commit) through `build_runtime`, and the final answer went to `before_reply`. The binding call and the request producer's call use the real prompts with `aws/gpt-oss-120b` (`max_tokens` 16000 for the binding), on the data that run read. Every item is at level `follow_up`: the tables show what level 2 would send. One ledger per producer, so producers do not mix.

| Benchmark | Runs | Distinct tasks | Agent models | Basis (`basis_of`, runs) | Runs by set |
|---|---:|---:|---|---|---|
| HANDBOOK | 18 | 3 | aws/gpt-oss-120b 9, gcp/gemini-3.8-flash 9 | tuning 18 | handbook-public3 18 |
| ITSM | 57 | 22 | aws/gpt-oss-120b 57 | tuning 57 | itsm-tune 45, itsm-unseen 10, itsm-xref 2 |
| τ² Telecom † | 93 | 52 | azure/DeepSeek-V4-Pro 93 | tuning 93 | tau2-telecom-dev20 29, tau2-telecom-test 64 |

The runs are every saved arm-A run in these folders, with no choice by outcome: HANDBOOK `hba_*_A` and `hbq_*_A`; ITSM every `A_*.json` of the gpt-oss-120b runs; τ² Telecom `dev1_A`, `dev2_A`, `test1_A`, `test2_A` with environment assertions. A failed binding counts as a failure and is in the tables. `obligation_replay/sample.json` lists the run ids. "tuning" in `basis_of` hides what the sets are: `itsm-unseen` and `tau2-telecom-test` have status heldout, and an agent model has run them, so they are "status heldout, label seen" (see the table by set). HANDBOOK is in-sample: the packages were written from the same documents that the tasks use.

**The level for ITSM applies to the gpt-oss-120b agent only.** Only that agent's runs were replayed, and it is the weakest of the three that have saved ITSM arm-A runs (runs, passed): aws/gpt-oss-120b 6 of 57; azure/DeepSeek-V4-Pro 145 of 280; gcp/gemini-3.8-flash 15 of 24. A stronger agent passes more checks, so more passed checks can be given an item (false-open) and fewer failed ones can be recovered. No saved binding exists for the other two, and none was paid for.

## Result and level

Rule (spec section 5): false-open <= 10% of the checks the run passed, and recall >= 30% of the failed checks, per benchmark and producer. **The replay narrows the second denominator**: it counts only the failed checks that a write of the agent could have met (the brief's rule), and the table gives recall over all failed checks beside it. The denominators were fixed before the numbers were seen. A rate with no denominator does not pass, and recall over fewer than 5 failed checks a write could meet is "not known". The intervals are 95% Wilson on the pooled count; runs of one task are not independent, so read them as too narrow. The level uses the pooled count, as the spec states the rule. A level 2 is marked **not firm** when the counts by task disagree.

### Result and level, per benchmark and producer

| Benchmark | Basis of the runs (`basis_of`, runs) | Producer | Runs | False-open: passed checks given an item | Recall: failed checks a write could meet, given an item | Failed checks of any kind, given an item | Sent items that break a passed check | Level by the pooled rule |
|---|---|---|---:|---|---|---|---:|---|
| HANDBOOK | tuning 18 | package | 18 | 9 of 158 (5.7%) [3-10%] | 18 of 127 (14.2%) [9-21%] | 18 of 148 (12.2%) | 4 | 1: recall below 30% |
| HANDBOOK | tuning 18 | request | 18 | 0 of 158 (0.0%) [0-2%] | 0 of 127 (0.0%) [0-3%] | 0 of 148 (0.0%) | 0 | 1: recall below 30% |
| HANDBOOK | tuning 18 | duty | 18 | 0 of 158 (0.0%) [0-2%] | 0 of 127 (0.0%) [0-3%] | 0 of 148 (0.0%) | 0 | 1: recall below 30% |
| ITSM | tuning 57 | package | 57 | 4 of 95 (4.2%) [2-10%] | 4 of 134 (3.0%) [1-7%] | 4 of 134 (3.0%) | 0 | 1: recall below 30% |
| ITSM | tuning 57 | request | 57 | 0 of 95 (0.0%) [0-4%] | 37 of 134 (27.6%) [21-36%] | 37 of 134 (27.6%) | 0 | 1: recall below 30% |
| ITSM | tuning 57 | duty | 57 | 3 of 95 (3.2%) [1-9%] | 6 of 134 (4.5%) [2-9%] | 6 of 134 (4.5%) | 0 | 1: recall below 30% |
| τ² Telecom † | tuning 93 | package | 93 | 0 of 128 (0.0%) [0-3%] | 0 of 2 (0.0%) [0-66%] | 0 of 24 (0.0%) | 0 | 1: recall is not known: only 2 failed checks that a write could have met |
| τ² Telecom † | tuning 93 | request | 93 | 1 of 128 (0.8%) [0-4%] | 0 of 2 (0.0%) [0-66%] | 0 of 24 (0.0%) | 1 | 1: recall is not known: only 2 failed checks that a write could have met |
| τ² Telecom † | tuning 93 | duty | 93 | 0 of 128 (0.0%) [0-3%] | 0 of 2 (0.0%) [0-66%] | 0 of 24 (0.0%) | 0 | 1: recall is not known: only 2 failed checks that a write could have met |

† τ² Telecom is a conversation, and a conversation cannot run these configurations live: `build_runtime` refuses the producer `request` in a conversation, and the one `package` item that would be sent asks for the hand-off tool itself, which the ledger never asks for before a hand-off. These rows are what the saved runs give when the end of the conversation is taken as the final reply. They are not a measure of a live run.

### What the sent items would tell the agent

| Benchmark | Producer | Items sent | on a failed check (meets) | on a passed check | of those, break a passed check | sent while a successful call of the item's tool exists | name no check | name no check, on a passed run |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| HANDBOOK | package | 97 | 37 | 9 | 4 | 56 | 50 | 0 |
| HANDBOOK | request | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| HANDBOOK | duty | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ITSM | package | 8 | 4 | 3 | 0 | 3 | 1 | 0 |
| ITSM | request | 34 | 34 | 0 | 0 | 0 | 0 | 0 |
| ITSM | duty | 10 | 6 | 3 | 0 | 4 | 1 | 0 |
| τ² Telecom † | package | 1 | 0 | 0 | 0 | 1 | 1 | 1 |
| τ² Telecom † | request | 1 | 0 | 1 | 1 | 0 | 0 | 0 |
| τ² Telecom † | duty | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

An item sent while a successful call of its tool exists says that no successful call did the work, and that is false for the call that exists (it may have another target or value). The columns count items, not checks. A passed check is given an item if the item meets or breaks it; a failed check counts for recall only through `meets`.

### Run level

| Benchmark | Producer | Runs (passed) | Runs with a follow-up | Passed runs with a follow-up | Follow-ups that name work of a failed check | Follow-ups that name work of a passed check |
|---|---|---|---:|---|---|---|
| HANDBOOK | package | 18 (1) | 4 | 0 of 1 (0.0%) | 3 of 4 (75.0%) | 3 of 4 (75.0%) |
| HANDBOOK | request | 18 (1) | 0 | 0 of 1 (0.0%) | 0 of 0 (n/a) | 0 of 0 (n/a) |
| HANDBOOK | duty | 18 (1) | 0 | 0 of 1 (0.0%) | 0 of 0 (n/a) | 0 of 0 (n/a) |
| ITSM | package | 57 (6) | 7 | 0 of 6 (0.0%) | 4 of 7 (57.1%) | 3 of 7 (42.9%) |
| ITSM | request | 57 (6) | 13 | 0 of 6 (0.0%) | 13 of 13 (100.0%) | 0 of 13 (0.0%) |
| ITSM | duty | 57 (6) | 9 | 1 of 6 (16.7%) | 6 of 9 (66.7%) | 3 of 9 (33.3%) |
| τ² Telecom † | package | 93 (77) | 1 | 1 of 77 (1.3%) | 0 of 1 (0.0%) | 0 of 1 (0.0%) |
| τ² Telecom † | request | 93 (77) | 1 | 1 of 77 (1.3%) | 0 of 1 (0.0%) | 1 of 1 (100.0%) |
| τ² Telecom † | duty | 93 (77) | 0 | 0 of 77 (0.0%) | 0 of 0 (n/a) | 0 of 0 (n/a) |

"Names work of a failed check" means the item names the work that the check tests. It does not mean the work can be recovered: see the section on recall.

### Status of the items after the final reply

| Benchmark | Producer | Items | met | open | held | unknown | wrong | unbound | not_applicable |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| HANDBOOK | package | 586 | 173 | 97 | 32 | 277 | 5 | 2199 | 2 |
| HANDBOOK | request | 6 | 3 | 0 | 0 | 3 | 0 | 0 | 0 |
| HANDBOOK | duty | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ITSM | package | 682 | 12 | 8 | 64 | 597 | 1 | 711 | 0 |
| ITSM | request | 156 | 98 | 34 | 0 | 15 | 9 | 0 | 0 |
| ITSM | duty | 39 | 3 | 10 | 0 | 26 | 0 | 0 | 0 |
| τ² Telecom † | package | 880 | 103 | 1 | 16 | 750 | 0 | 1898 | 10 |
| τ² Telecom † | request | 46 | 45 | 1 | 0 | 0 | 0 | 0 | 0 |
| τ² Telecom † | duty | 18 | 0 | 0 | 0 | 18 | 0 | 0 | 0 |

### Value origin

| Benchmark | Producer | Items | Items that name values | with a known value | with every value known | Items with a value shown | Items sent | Sent with a value shown |
|---|---|---:|---:|---|---|---|---:|---|
| HANDBOOK | package | 586 | 512 | 435 of 512 (85.0%) | 338 of 512 (66.0%) | 478 of 586 (81.6%) | 97 | 97 of 97 (100.0%) |
| HANDBOOK | request | 6 | 0 | 0 of 0 (n/a) | 0 of 0 (n/a) | 0 of 6 (0.0%) | 0 | 0 of 0 (n/a) |
| HANDBOOK | duty | 0 | 0 | 0 of 0 (n/a) | 0 of 0 (n/a) | 0 of 0 (n/a) | 0 | 0 of 0 (n/a) |
| ITSM | package | 682 | 89 | 53 of 89 (59.6%) | 24 of 89 (27.0%) | 53 of 682 (7.8%) | 8 | 7 of 8 (87.5%) |
| ITSM | request | 156 | 98 | 98 of 98 (100.0%) | 98 of 98 (100.0%) | 98 of 156 (62.8%) | 34 | 27 of 34 (79.4%) |
| ITSM | duty | 39 | 21 | 21 of 21 (100.0%) | 21 of 21 (100.0%) | 21 of 39 (53.8%) | 10 | 6 of 10 (60.0%) |
| τ² Telecom † | package | 880 | 159 | 159 of 159 (100.0%) | 159 of 159 (100.0%) | 159 of 880 (18.1%) | 1 | 0 of 1 (0.0%) |
| τ² Telecom † | request | 46 | 0 | 0 of 0 (n/a) | 0 of 0 (n/a) | 0 of 46 (0.0%) | 1 | 0 of 1 (0.0%) |
| τ² Telecom † | duty | 18 | 0 | 0 of 0 (n/a) | 0 of 0 (n/a) | 0 of 18 (0.0%) | 0 | 0 of 0 (n/a) |

### Cost, with the model `aws/gpt-oss-120b`

| Benchmark | Producer | Runs | Cost | Per run | Failed bindings or request calls | Runs with no obligation |
|---|---|---:|---:|---:|---:|---:|
| HANDBOOK | package | 18 | $0.101 | $0.0056 | 1 hit the 16000-token output limit | 0 |
| HANDBOOK | request | 18 | $0.006 | $0.0003 | 0 | 0 |
| HANDBOOK | duty | 18 | $0.000 | $0.0000 | 0 | 12 |
| ITSM | package | 57 | $0.111 | $0.0019 | 1 answer is not a JSON list of cases (malformed or empty) | 0 |
| ITSM | request | 57 | $0.042 | $0.0007 | 0 | 0 |
| ITSM | duty | 57 | $0.000 | $0.0000 | 0 | 0 |
| τ² Telecom † | package | 93 | $0.180 | $0.0019 | 0 | 0 |
| τ² Telecom † | request | 93 | $0.036 | $0.0004 | 0 | 0 |
| τ² Telecom † | duty | 93 | $0.000 | $0.0000 | 0 | 0 |

### Why failed checks that a write could meet got no item

| Benchmark | Producer | Failed checks (writable) | binding failed | covered, held | covered, held/met | covered, met | covered, met/unknown | covered, open | covered, open/unknown | covered, unknown | covered, wrong | no binding | no item |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| HANDBOOK | package | 127 | 7 | 1 | 1 | 8 | 2 | 2 | 2 | 7 | 0 | 0 | 79 |
| HANDBOOK | request | 127 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 127 |
| HANDBOOK | duty | 127 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 77 | 50 |
| ITSM | package | 134 | 3 | 1 | 0 | 0 | 0 | 1 | 0 | 20 | 0 | 0 | 105 |
| ITSM | request | 134 | 0 | 0 | 0 | 33 | 0 | 0 | 0 | 9 | 8 | 0 | 47 |
| ITSM | duty | 134 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 128 |
| τ² Telecom † | package | 2 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| τ² Telecom † | request | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |
| τ² Telecom † | duty | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |

### Items of the producer `package` by the tools they name, and the status they ended in

| Benchmark | Shape | Items | met | open | held | unknown | wrong | unbound | not_applicable |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| HANDBOOK | code_only | 129 | 32 | 1 | 13 | 82 | 0 | 0 | 1 |
| HANDBOOK | no_tool:file | 14 | 0 | 0 | 1 | 13 | 0 | 0 | 0 |
| HANDBOOK | tool | 443 | 141 | 96 | 18 | 182 | 5 | 0 | 1 |
| ITSM | no_tool:reply | 579 | 0 | 0 | 57 | 522 | 0 | 0 | 0 |
| ITSM | tool | 43 | 12 | 8 | 5 | 17 | 1 | 0 | 0 |
| ITSM | tool_not_in_task_list | 60 | 0 | 0 | 2 | 58 | 0 | 0 | 0 |
| τ² Telecom † | no_tool:reply | 84 | 1 | 0 | 8 | 75 | 0 | 0 | 0 |
| τ² Telecom † | tool | 173 | 102 | 1 | 4 | 66 | 0 | 0 | 0 |
| τ² Telecom † | user_only | 623 | 0 | 0 | 4 | 609 | 0 | 0 | 10 |

### The rule on four counts, per benchmark and producer

Pooled over runs is the count of the rule. One count per task: a task weighs 1 and its runs share the weight (the counts are weighted). Mean of task rates: the rate of each task, then the mean. Bootstrap: tasks drawn with replacement, 2000 draws, 95% range. "Firm": the pooled count, one count per task and the mean of task rates all pass the rule.

| Benchmark | Producer | Tasks | Pooled: false-open / recall | One count per task: false-open / recall | Mean of task rates: false-open / recall | Task bootstrap: false-open / recall | Firm |
|---|---|---:|---|---|---|---|---|
| HANDBOOK | package | 3 | 5.7% / 14.2% | 5.7% / 14.2% | 4.1% / 12.6% | 0-12% / 0-26% | no |
| HANDBOOK | request | 3 | 0.0% / 0.0% | 0.0% / 0.0% | 0.0% / 0.0% | 0-0% / 0-0% | no |
| HANDBOOK | duty | 3 | 0.0% / 0.0% | 0.0% / 0.0% | 0.0% / 0.0% | 0-0% / 0-0% | no |
| ITSM | package | 22 | 4.2% / 3.0% | 8.4% / 1.7% | 7.0% / 2.9% | 0-11% / 0-11% | no |
| ITSM | request | 22 | 0.0% / 27.6% | 0.0% / 14.9% | 0.0% / 17.3% | 0-0% / 5-51% | no |
| ITSM | duty | 22 | 3.2% / 4.5% | 3.9% / 2.5% | 2.5% / 3.8% | 0-7% / 0-12% | no |
| τ² Telecom † | package | 52 | 0.0% / 0.0% | 0.0% / 0.0% | 0.0% / 0.0% | 0-0% / 0-0% | no |
| τ² Telecom † | request | 52 | 0.8% / 0.0% | 0.7% / 0.0% | 1.1% / 0.0% | 0-3% / 0-0% | no |
| τ² Telecom † | duty | 52 | 0.0% / 0.0% | 0.0% / 0.0% | 0.0% / 0.0% | 0-0% / 0-0% | no |

### Runs and counts by task set

A set is named by `sets/registry.json`. "Status" is the role it was made for. A set with status `heldout` that an agent model has run (`seen`) is "status heldout, label seen": it is no held-out set for this replay. A task can be in two sets, and a run of the sample in none.

| Benchmark | Producer | Set | Status and label | Runs | Tasks | False-open | Recall |
|---|---|---|---|---:|---:|---|---|
| HANDBOOK | package | handbook-public3 | tuning | 18 | 3 | 9 of 158 (5.7%) | 18 of 127 (14.2%) |
| HANDBOOK | request | handbook-public3 | tuning | 18 | 3 | 0 of 158 (0.0%) | 0 of 127 (0.0%) |
| HANDBOOK | duty | handbook-public3 | tuning | 18 | 3 | 0 of 158 (0.0%) | 0 of 127 (0.0%) |
| ITSM | package | itsm-tune | tuning | 45 | 10 | 1 of 74 (1.4%) | 4 of 96 (4.2%) |
| ITSM | package | itsm-unseen | status heldout, label seen | 10 | 10 | 1 of 19 (5.3%) | 0 of 27 (0.0%) |
| ITSM | package | itsm-xref | tuning | 2 | 2 | 2 of 2 (100.0%) | 0 of 11 (0.0%) |
| ITSM | request | itsm-tune | tuning | 45 | 10 | 0 of 74 (0.0%) | 36 of 96 (37.5%) |
| ITSM | request | itsm-unseen | status heldout, label seen | 10 | 10 | 0 of 19 (0.0%) | 1 of 27 (3.7%) |
| ITSM | request | itsm-xref | tuning | 2 | 2 | 0 of 2 (0.0%) | 0 of 11 (0.0%) |
| ITSM | duty | itsm-tune | tuning | 45 | 10 | 2 of 74 (2.7%) | 6 of 96 (6.2%) |
| ITSM | duty | itsm-unseen | status heldout, label seen | 10 | 10 | 1 of 19 (5.3%) | 0 of 27 (0.0%) |
| ITSM | duty | itsm-xref | tuning | 2 | 2 | 0 of 2 (0.0%) | 0 of 11 (0.0%) |
| τ² Telecom † | package | tau2-telecom-dev20 | tuning | 29 | 16 | 0 of 50 (0.0%) | 0 of 0 (n/a) |
| τ² Telecom † | package | tau2-telecom-test | status heldout, label seen | 64 | 36 | 0 of 78 (0.0%) | 0 of 2 (0.0%) |
| τ² Telecom † | request | tau2-telecom-dev20 | tuning | 29 | 16 | 0 of 50 (0.0%) | 0 of 0 (n/a) |
| τ² Telecom † | request | tau2-telecom-test | status heldout, label seen | 64 | 36 | 1 of 78 (1.3%) | 0 of 2 (0.0%) |
| τ² Telecom † | duty | tau2-telecom-dev20 | tuning | 29 | 16 | 0 of 50 (0.0%) | 0 of 0 (n/a) |
| τ² Telecom † | duty | tau2-telecom-test | status heldout, label seen | 64 | 36 | 0 of 78 (0.0%) | 0 of 2 (0.0%) |

### The mapping of items to checks, against a hand check

| Items checked | Distinct items | Pairs the judge made | of which right | Pairs missed by the judge | Items with the same set |
|---:|---:|---:|---|---:|---|
| 36 | 22 | 32 | 31 of 32 (96.9%) | 4 | 31 of 36 (86.1%) |

## What recall means here

Recall is the share of the failed checks that the sent items *name*: an item for the work that the check tests. It is not the share of failed work that a follow-up would get done. For ITSM `request`: 37 of the 37 recalled checks are named by an item sent when the run has no successful call of the item's tool (the agent never tried, or gave up), and 0 by an item sent while such a call exists (the agent wrote to another target or with other values, or stopped short). A recalled check on a run where the agent gave up is not work that one more turn would finish. The reading of runs by hand (the controller counted 31 of 57 pairs on runs where the agent gave up or wrote to another incident) is not reproduced by this table: the split above is the one that the data gives by code.

## The change that gives request items no keys

On gate `61699250e` a request item had the keys of its case (an empty list), so a call of its tool with another target or with the value left out did not count as the item's work, and the item stayed open. 24 of 58 sends were of that kind, 20 of the 57 recall hits rest on one, and all 3 false opens are among them. The follow-up said that no successful call did the work. The three false opens, as that gate would have told the agent:

- `- update_incident: "Please ensure that any open incidents related to this service are closed" Values: status = "closed".` against the passed check "No open incidents remain for Enterprise Email: the database holds this (2 expected): SELECT COUNT(*) AS cnt FR". A successful call existed: `update_incident({"incident_id": "INC_004", "status": "resolved", "resolution_code": "Solution Provided", "resolution_notes": "Service de)`.
- `- create_incident or update_incident: "Please create an incident for Barbara" Values: priority = "moderate".` against the passed check "Verify Incident Record: the database holds this (1 expected): SELECT COUNT(*) FROM incident where incident_id=". A successful call existed: `create_incident({"short_description": "Barbara Perry cannot access the new HR portal and needs UI walkthrough", "caller_id": "USER_025",)`.
- `- create_incident: "Please log today's outage for me, ensure it is clearly associated with the SAP database server involved" Values: channel = "phone"` against the passed check "Outage Incident Created (High Impact/Urgency) And Linked To CI: the database holds this (1 expected): SELECT C". A successful call existed: `create_incident({"short_description": "Production-wide SAP outage - all users unable to connect", "caller_id": "USER_001", "impact": "hi)`.

On gate `9ab6935cd` (a request or duty item takes no keys) a call that leaves out an enum value is `unknown`, and the item is not asked for again.

## Why the ledger cannot send on `package` today

- **HANDBOOK: binding.** 2.56 cases are bound per run; 2199 of 2580 obligation-runs (each obligation of the package, in each run) are unbound. Of the 127 failed checks a write could meet, 18 are named by a sent item; 23 more are covered by an item that is not sent (met, unknown, held), 7 were lost to failed bindings, and 79 have no item. So at most about 32.3% of them could be named even if every covering item were open (a ceiling on recall).
- **ITSM: content.** 579 items name no tool (`reply`) and are never sent. `request` names 37 of 134 failed checks, `package` 4. 105 failed checks have no item in the package, and 42 of the checks without an item are on notifications, which the package does not name.
- **Telecom: the customer's tools.** 623 items name only `user__` tools, work that only the customer's phone can do; none is sent, and the checks are customer-device states, so 2 failed checks could be met by a write of the agent.
- **The split between binding and content is an estimate.** For the failed checks with no item, the replay asks whether the package holds an obligation that shares two or more words (five letters or more) with the check: HANDBOOK 63 of 79, ITSM 65 of 105. A check with such an obligation points to binding or status, one without to content. It is a word-overlap estimate, not a judgement.

## Labels (measurement only) and their error

Nothing from a grader enters a package, a prompt or the ledger. The graders' checks (HANDBOOK rubric items, ITSM verifiers with their SQL, Telecom environment assertions) are read after the replay, by one model call of `aws/gpt-oss-120b` per run and producer. It sees the checks without whether they passed, and the items that would be sent, and gives for each item `meets` (the work would help the check pass: the same kind of action on the same kind of record for the same case) and `breaks` (the check says that work must not exist). A passed check that gets an item of either kind is a false-open; a failed check counts for recall only through `meets`. A second call per task says which failed checks a write of the agent could have met (the denominator of recall; a reply text, a must-not check, a read or an action of another party is false). A third says, for a failed check no sent item names, which items of the ledger cover it (the `why` table).

**Error, by hand.** I read 36 sent items (22 distinct: the same obligation for another case or run counts once; chosen by the hash of their identity, per benchmark and producer: HANDBOOK package, ITSM request, duty and package, Telecom request) and wrote the checks each one concerns. The judge made 32 pairs and 31 are right (96.9%); it missed 4 pairs that I made (pair recall 88.6%); 31 of 36 items have the same set. So false-open and recall are a little low. The misses are items whose address or target differs from the check's, or a generic item such as `create_incident` that is one of several checks. The wrong pair maps a read (`retrieve_knowledge_articles`) to a check on a link. The sample is mostly HANDBOOK Crestwood and ITSM tasks of the gpt-oss runs; Telecom has one sent item in all. A first judge prompt (same object and same action) had 6 of 18 pairs missed on a first sample of 23 package items; I changed the prompt to ignore the values the item shows, and checked a new sample on the final data. The hand check is mine and one reader's: a pair can be disputed (the label for a mark-as-read item rests on the email's folder).

## Known limits and what each does to the numbers

| Limit | What the replay shows (producer `package` unless said) |
|---|---|
| HANDBOOK file obligations that name only `executePython` and `executeBash` (138) | 129 such items: 82 unknown, 32 met, 13 held, 1 not_applicable, 1 open. The false-open risk (a file written with `writeFile`) shows in the `open` ones; the main cost is recall: an `unknown` item is never sent |
| Telecom obligations that name only `user__` tools (17) | The replay uses the agent's tools only. 623 items of that shape: 609 unknown, 10 not_applicable, 4 held; none sent. A real run that lists `user__` tools could ask the agent for work only the customer can do |
| ITSM items often `unknown` when a tool is not in the task's list | 60 items name only tools that the task did not give the agent: 58 unknown, 2 held |
| Items with no tool (`reply`) | ITSM 579: 522 unknown, 57 held; Telecom 84: 75 unknown, 8 held, 1 met. Never sent |
| Spreadsheet and file items with no tool | HANDBOOK 14: 13 unknown, 1 held; none sent, so no recall from them |
| A block that names only an employee id is not attached when the binder's keys hold only the name; a corrected retry leaves other tools' items held | Not exercised: the saved arm-A runs have no blocks, so no `tool_blocked` and no retry |
| `held` is barely exercised | There were no blocks. `held` still shows, because the binder's decision for a case can be `hold` with a quote (HANDBOOK 32, ITSM 64, Telecom 16 items) |
| Saved tool results are cut | The HANDBOOK runner keeps 4,000 characters of a result (`TOOL_LOG_LIMIT`): 77 of 990 results are cut, in 18 of 18 runs. The live ledger reads up to 80,000 characters of each read. A live binding sees more of the SOP and the records, so it can find more cases and more values: **both rates could rise**, the false-open as well as the recall. ITSM and Telecom results are not cut |
| A request item made from a mention (`contact alice@corp.com` named in passing, `asked: true`) | Covered by the false-open of `request`: ITSM 0 of 95 (0.0%), Telecom 1 of 128 (0.8%), HANDBOOK 0 of 158 (0.0%). The Telecom item is of this kind, and it is kept only as an example of the `asked: true` risk: a customer's question ("is there any way to get my service restored?") became an item to resume the line, and the passed check says the service must stay off. That follow-up would have been harmful. Telecom cannot run this configuration live (†) |

`wrong` is recorded and never sent. `unbound` counts obligations that no case bound, once for each run; it is not part of the item count.

## The honest ceiling

Spec section 5: with names only, expect about +4 to +6 points; anything above that depends on how many expected values can be derived, and the value table gives that share for these items. The oracle's +25 to +36 is an upper bound with grader values, not a forecast. A replay gives no score gain, and none is estimated here beyond that range.

## Levels and profiles

Levels by the pooled rule: HANDBOOK `package`: 1, HANDBOOK `request`: 1, HANDBOOK `duty`: 1, ITSM `package`: 1, ITSM `request`: 1, ITSM `duty`: 1, τ² Telecom `package`: 1, τ² Telecom `request`: 1, τ² Telecom `duty`: 1.

No profile is changed or added. The measured best profiles stay as measured, and every profile has `producers: []` today. A level 2 would be a note, not a setting: a later profile would hold `obligations: {producers: [<producer>], item_level: follow_up}` for that benchmark; level 1 is the state of every profile now. None of these numbers is a held-out result. Spec section 5 says item levels are never set from held-out tasks, and (ruling of the controller, added to section 5 with this task) a tuning pass needs a held-out check before any profile sends.

## Cost

Spent on this task: $0.585 of $4 (model `aws/gpt-oss-120b`, list price: binding, request producer and judge). The per-run cost of each producer is in the cost table. Cached answers are re-used when the prompt is unchanged, so a re-run costs little.
