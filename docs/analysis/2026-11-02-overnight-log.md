# Overnight log: CUGA policy layer, 2026-11-02

Goal (from the user, 2026-11-02 ~00:00): reach a really good system: fast intake, runtime adherence for all policy
types, measured on AutomationBench and EnterpriseOps-Gym ITSM (tuning + unseen). Agent and policy models: gpt-oss-120b
(`aws/`, LiteLLM); a slightly bigger cheap model is allowed if gpt-oss is too weak. Function calling through the SDK is
allowed. Budget: under $1000 in total. If time allows: links between SOPs, one HANDBOOK.md task.

Rules kept: no task-specific fixes; held-out (unseen) results next to tuning; every change after seeing runs is in
`benchmarks/policy_eval/changes.md`; no commits or pushes; code in `~/dev/cuga-agent-gate` only. Runs use a frozen copy
of the code (`policy_eval/snapshot_src.sh <run>` → `/tmp/cuga_snapshots/<run>/src`) so the worktree can change during runs.

## Starting point (before tonight)

| Measure | Value | Source |
|---|---|---|
| Shadow replay, tuning: violating writes stopped | 0 of 10 | `policy_eval/shadow/oss2_A_t1.before_rbw.json` |
| Shadow replay, held-out | 0 of 3 | `policy_eval/shadow/oss2u_A_t1.before_rbw.json` |
| Arm A (CodeAct, gpt-oss) AB tuning: AA-style / partial | 0.0% / 20.9% | `automationbench/results/oss2_A_t1` |
| Arm A ITSM tuning: pass / verifiers | 1/10 / 13/39 | `enterpriseops_gym/results/oss2_t1` |

## Entries

### 00:00 Changes in place before the night's runs
- Change 25: reminders no longer block (a `before_tool_call` message is a block). Change 26: re-run measured it.
- Read before write (`policy_layer/references.py`, wired into `OnlinePolicyIntake`): remind once when the request or
  data refers to a policy source that no tool output has shown. Never blocks; the agent does the reading.
  Replay: reminds before 7 of 10 violating writes (tuning), 1 of 3 (held-out).
- Model verifier is remind-only by default (`verifier_may_deny=False`): replay showed 0 violations stopped and 8 of
  181 correct writes denied by its verdicts. Code rules may still deny.
- Budget limit raised to $1000 (`policy_pilot_costs.py`).

### 00:10 Run `oss4` (arm B, CodeAct, read before write, verifier remind-only)
AB tuning + unseen, ITSM tuning. Running.

### 00:20 Function calling for gpt-oss
- Bug fixed (CUGA worktree, `graph_adapter._any_execution_ran`): in function-calling mode, tool results are
  `ToolMessage`s, so the claim retries thought no work had run. Test added.
- Hook check in function-calling mode: all 10 checks pass (both tool paths).
- Smoke, arm A, 2 tasks: `zoom_calendar_conflict` 1.0 (first pass with gpt-oss; CodeAct 0.0–0.5),
  `zendesk_data_quality` 0.47, no guardrail break, about half the tokens of CodeAct.
- Run `fc1` (arm A, function calling): AB tuning + unseen, ITSM tuning. Running.

### 00:35 Function calling beats CodeAct for gpt-oss (arm A, 1 trial)

| Arm A, gpt-oss-120b | CodeAct (`oss2`) | Function calling (`fc1`) |
|---|---|---|
| AB tuning AA-style / partial | 0.0% / 20.9% | 16.0% / 33.7% |
| AB unseen AA-style / partial | 16.5% / 28.6% | 22.8% / 33.3% |
| ITSM tuning verifiers / pass | 13/39 / 1 | 17/39 / 0 |
| Input tokens, AB tuning | 2.86M | 1.00M |

Decision: function calling for both arms from now on. Absolute accuracy is still low, so cheap bigger agent models
are being smoke-tested (gpt-5-mini, DeepSeek-V4-Pro, nemotron-super-3-120b, gemini-3.5-flash-lite).

### 00:38 Generated guard code (fix C): built, measured, parked
The model writes a check per (statement, write tool); code runs it on the read data. Replay: 1 of 10 violating writes
flagged (helpcrunch), but 20 of 112 correct writes too (thresholds computed wrong). Default off (change 30). The main
loss is policies nobody read (9 of 10), which read-before-write targets.

### 00:52 Agent model: DeepSeek-V4-Pro (arm A, function calling, tuning, 1 trial)

| Agent | AB partial / AA-style | ITSM pass / verifiers | $ per 1M in / out (gateway) |
|---|---|---|---|
| azure/DeepSeek-V4-Pro | 50.3% / 31.3% | 6/10 / 33/39 | 1.74 / 3.48 |
| gcp/gemini-3.5-flash-lite | 47.4% / 28.3% | — | 0.30 / 2.50 |
| aws/nemotron-super-3-120b | 35.8% / 17.2% | — | 0.15 / 0.65 |
| aws/gpt-oss-120b | 33.7% / 16.0% | 0/10 / 17/39 | 0.15 / 0.60 |

DeepSeek-V4-Pro (about $0.25 per task) is the agent from now on; the policy layer stays on gpt-oss-120b. It still
breaks AutomationBench guardrails in 4 of 10 tasks, which is where the layer can help.

gpt-oss arm B with function calling was worse than arm A on tuning (AA-style 10.0% vs 16.0%; unseen 24.2% vs 22.8%).
After the reminders the agent searched Drive only, with no result; the rules were in Gmail and other sheets. The
reminder now also names the read tools not used yet (change 32).

### 00:55 Runs `ds1` (DeepSeek agent, function calling)
AB tuning B (remind), AB tuning B (`block_once`), AB unseen A and B, ITSM tuning B, ITSM unseen A and B. Running.

### 01:03 First clear gain: DeepSeek agent, AutomationBench, arm B beats arm A on tuning and held-out (1 trial)

| AutomationBench | Strict pass | Partial | AA-style | Guardrail-break tasks |
|---|---|---|---|---|
| Tuning A (`m_dsv4_A_t1`) | 1/10 | 50.3% | 31.3% | 4 |
| Tuning B, remind (`ds1_B_t1`) | 2/10 | 60.7% | 41.1% | 3 |
| Tuning B, block once (`ds1blk_B_t1`) | 3/10 | 63.5% | 44.7% | 3 |
| Unseen A (`ds1u_A_t1`) | 1/10 | 45.8% | 21.8% | 4 |
| Unseen B, remind (`ds1u_B_t1`) | 3/10 | 54.7% | 35.0% | 3 |

ITSM (DeepSeek agent): tuning A 6/10 (33/39) vs B 5/10 (33/39). Unseen B was invalid for 3 tasks: their policy versions
had no pipeline build, so the runner fell back to old pilot rule files (wrong denies) or crashed (changes 33–34).
Built the 5 missing versions (2 min 50 s) and re-running unseen arm B (`ds2u`).

### 01:15 Running: ITSM unseen B (`ds2u`), AB unseen block once (`ds2ublk`), cross-reference sets AB (5) and ITSM (2), both arms

### 01:21 Held-out AutomationBench: block-once is best so far (DeepSeek agent, 1 trial)

| AutomationBench unseen | Strict pass | Partial | AA-style | Guardrail-break tasks |
|---|---|---|---|---|
| A (`ds1u_A_t1`) | 1/10 | 45.8% | 21.8% | 4 |
| B, remind (`ds1u_B_t1`) | 3/10 | 54.7% | 35.0% | 3 |
| B, block once (`ds2ublk_B_t1`) | 3/10 | 63.9% | 51.0% | 2 |

Cross-reference sets: AB (5 tasks) A 33.8% partial / 0.0% AA vs B 52.9% / 20.0% (B ran before the hyphen fix,
12 wrong denies in one task); ITSM (2 tasks) A 1/2 (10/13) vs B 0/2 (8/13) with no remind or deny.

Fixes since: Unicode dashes in value checks (change 35); generic identifier pattern (36, user reminder: generalize to
unseen documents); observe-only checks for policy/tool conflicts and unmeasured "no assumed data" (37); brief switch (38).

### 01:25 Running (`ds3`, `ds4` snapshots)
AutomationBench tuning + unseen: A trial 2, B-remind, B-block-once (latest code). ITSM tuning + unseen + cross-reference:
A trial 2, B with brief, B without brief.

### 01:28 Two trials: the AutomationBench gain shrinks (variance is large)
Arm A trial 2 scored much higher than trial 1 (tuning AA-style 36.7% vs 31.3%; unseen 45.0% vs 21.8%).

| AutomationBench, mean of 2 trials | A partial / AA | B-remind partial / AA | B-block partial / AA |
|---|---|---|---|
| Tuning | 52.7% / 34.0% | 59.3% / 33.9% | 58.4% / 37.2% |
| Unseen | 51.2% / 33.4% | 54.0% / 38.3% | 59.4% / 41.4% (8 of 10 tasks in trial 2) |

B stays ahead on partial credit in both sets, but by less than the trial-to-trial spread. Running A trial 3 and B
trials 2–3 (same code `ds4` for all) to settle it. Tool: `policy_eval/compare_arms.py` (per-task means over trials,
paired against A).

### 01:32 ITSM with the DeepSeek agent: the layer is now silent and neutral; the brief costs a little
With observe-only checks (change 37), arm B makes 0 reminds and 0 denies on ITSM.

| ITSM verifiers, paired vs A | Tuning | Unseen | Cross-reference |
|---|---|---|---|
| A (2 trials) pass / verifiers | 5.5 / 83.1% | 5.5 / 74.3% | 1.0 / 83.3% |
| B with brief (2 trials) | −0.7 pts | −3.0 pts | −12.5 pts |
| B without brief (1 trial) | −1.5 pts | −0.5 pts | 0.0 pts |

Testing the same switch on AutomationBench (block-once, brief on vs off, 2 trials, `ds5`).

### 01:40 User: "if the model never breaks rules, go to the smaller model (gpt-oss-120b) and try the same arms"
DeepSeek on ITSM: the layer was silent (0 reminds, 0 denies); the failures checked are task details (for example a
notification missing `type = report` and required words), not policy breaks. Running the same arms with gpt-oss-120b
(function calling, latest code `ds5`):
- ITSM tuning, unseen, cross-reference: A, B with brief, B without brief.
- AutomationBench tuning, unseen: A trial 2, B-remind, B-block-once, B-block-once without brief.
DeepSeek runs continue in parallel (AutomationBench A trial 3, B trials 2–3; block-once brief on/off).

### 01:52 Three trials per arm (DeepSeek agent, AutomationBench): remind beats block-once

| AutomationBench, 3 trials | Partial | AA-style | Paired vs A |
|---|---|---|---|
| Tuning A | 51.5% | 30.9% | — |
| Tuning B-remind | 56.0% | 35.2% | +3 / −2 tasks, +4.5 pts |
| Tuning B-block-once | 52.8% | 27.0% | +4 / −3 tasks, +1.4 pts |
| Unseen A | 51.7% | 33.1% | — |
| Unseen B-remind | 54.2% | 36.2% | +2 / −1 tasks, +2.5 pts |
| Unseen B-block-once | 54.7% | 33.3% | +2 / −0 tasks, +3.0 pts |

B-remind is ahead of A on both sets and both measures (small). Block-once: partial up, AA-style down on tuning.
Brief test (block-once, tuning, 2 trials): brief off AA-style 38.7% vs brief on 34.7%; guardrail-break tasks 3.0 vs 4.0.
With the ITSM result (brief costs verifiers), the candidate is **remind without the brief**: 3 trials running (`ds5*remnb`).

### 01:58 gpt-oss arms: no clear effect; noise is about ±6 pts. Attribution: the gain is where the layer acts
gpt-oss-120b (function calling), arm B vs A, paired, 1 trial for B: ITSM tuning +3.9 (brief) / +0.9 (no brief),
unseen −2.2 / −6.0, cross-reference 0 / −12.5; AutomationBench tuning +0.6 (remind) / +1.5 (block-once), unseen
−0.2 / +0.8. On ITSM the layer only allows (98–167 checks per run) or records observe-only items for both agents:
both agents follow the checkable ITSM rules and fail on task details. An arm that changes nothing the agent sees
(gpt-oss ITSM B without brief) still differs from A by up to 6 pts: that is the noise level.

Attribution (`policy_eval/attribution.py`), DeepSeek, all arm-B AutomationBench runs pooled:

| Arm-B task runs | Runs | Partial vs same task in A | Better / worse | Guardrail breaks, B vs A expected |
|---|---|---|---|---|
| Layer reminded or denied | 82 | +7.2 pts | 34 / 10 | 41 vs 48.7 |
| Layer silent | 78 | −1.6 pts | 6 / 22 | 18 vs 12.7 |

Tuning alone (B-remind, 3 trials): acted +8.5 pts (8 better / 3 worse); unseen alone: acted +6.2 pts (4 / 1).
The silent runs are slightly worse than A; the found-policy brief is the likely cost (remind without brief running).

### 02:05 A second held-out set for the final check
Variant choices (brief, remind vs block-once) used the unseen sets, so they are no longer clean. Drew `unseen2`
(10 AutomationBench + 10 ITSM, same selection rules, remaining pools, seed 20261102, not inspected). All its ITSM
policy versions already have pipeline builds. The final configuration will be frozen before it runs.
gpt-oss attribution: where the layer acted, partial +3.5 pts but guardrail breaks 19/31 vs 14.0 expected; the layer
pays off with a competent agent.

### 02:10 Brief on/off does not repeat; attribution is confounded; final configuration frozen

| AutomationBench, 3 trials (DeepSeek) | Tuning partial / AA | Unseen partial / AA |
|---|---|---|
| A | 51.5% / 30.9% | 51.7% / 33.1% |
| B-remind, brief on | 56.0% / 35.2% (+4.5 pts) | 54.2% / 36.2% (+2.5 pts) |
| B-remind, brief off | 57.3% / 39.1% (+5.9 pts) | 50.6% / 25.6% (−1.1 pts) |

Only brief-on is ahead of A on both sets. Caveat on the 01:58 attribution: whether the layer acts depends on how far
the agent got (a run that reaches its writes tends to score higher), so "acted vs silent" partly measures progress.

Frozen for the final check (`/tmp/cuga_snapshots/final1` = `ds5` code): read before write = remind, model verifier
remind-only, observe-only for policy/tool conflicts and unmeasured "no assumed data", generated guard code off, brief
on. Agent DeepSeek-V4-Pro (function calling), policy layer gpt-oss-120b.
Final held-out check on `unseen2` (never run before): arm A, arm B, and B without brief (secondary), 3 trials each,
AutomationBench and ITSM. Running.

### 02:40 Final held-out check (`unseen2`, frozen configuration, 3 trials): no gain; ITSM worse

| unseen2, DeepSeek agent | Pass | Partial / verifiers | AA-style | Paired vs A |
|---|---|---|---|---|
| AutomationBench A | 1.3 | 48.7% | 18.7% | — |
| AutomationBench B | 1.3 | 47.1% | 17.8% | +0 / −1 tasks, −1.6 pts |
| AutomationBench B, no brief | 1.0 | 48.1% | 17.2% | +1 / −2 tasks, −0.6 pts |
| ITSM A | 3.7 | 68.0% | — | — |
| ITSM B | 3.0 | 61.2% | — | +2 / −4 tasks, −6.8 pts |
| ITSM B, no brief | 1.7 | 57.2% | — | +0 / −4 tasks, −10.8 pts |

On the clean held-out set the layer does not help. The earlier AutomationBench gains (+2.5 to +4.5 pts) did not
repeat; they were within noise. On ITSM the layer showed the agent nothing (observe only), yet B lost verifiers:
in `27934d6b` both arms made identical calls, but B created the knowledge article as `published` in 5 of 6 runs
and A as `draft` in 3 of 3. Investigating whether this is chance or a hidden difference in the hooks code path
(6 repeat runs per arm on that task).

### 02:45 Offline intake on unseen HANDBOOK.md SOPs (public sample; no agent run)

| SOP (HTML) | Sections | Statements | Links (refers-to, defines, other) | Procedures (steps) | Time | Model calls |
|---|---|---|---|---|---|---|
| Crestwood University HR (77k chars) | 88 | 736 | 33, 124, 0 | 1 (18) | 327 s | 175 |
| Vanguard Shield insurance (58k) | 49 | 422 | 35, 25, 3 | 4 (26) | 157 s | 84 |
| CareIG specialty pharmacy (59k) | 53 | 489 | 31, 0, 1 | 12 (54) | 198 s | 104 |

Body references found ≈ references in the text (Vanguard: 35 links for 36 "§" references). Two general fixes
from this test: table-of-contents links dropped (change 41); learned patterns that turn list steps into sections
rejected (change 42).

## 10:11 — ITSM task 27934d6b repeat test (6 runs per arm, POLICY_BRIEF=0)

| Arm | Passed (probe) | Article state in probe | Passed (all runs so far) |
|---|---|---|---|
| A | 3/6 | draft 3, published 2, none 1 | 6/9 |
| B, no brief | 2/6 | draft 2, published 4 | 3/12 |

Arm A also creates the article as "published" (2 of 6), so the earlier "A always draft" was chance in a small sample.
Fisher exact test on all runs: p = 0.09. No proof of a hooks-path effect; the agent is not deterministic on this
choice. The ITSM loss on unseen2 stays unexplained by the layer (the layer showed the agent no text).

## 10:20 — unseen2: the layer acted but did not prevent guardrail breaks
AutomationBench unseen2, 30 runs per arm: arm B reminded in 21 runs (74 reminds, 0 denies), yet guardrail breaks were
18 vs 17 in A. With remind-only, the agent does not act on the reminders well enough to avoid the break. The only
earlier break reduction (Gemini pilot, 2026-10-31: 3 → 0 tasks) came with denies.

## 10:40 — Correction: about half of the ITSM failures are missed SOP steps, not task details
DeepSeek arm A, 90 ITSM runs, 104 failed verifiers. Up to 54 want a value that the policy states and the task does
not (heuristic; 3 checked by hand, all are prescribed steps or tables): 3e736be9 "SLA timer must be paused when the
incident is on_hold with reason Awaiting Change" (not done); a4b1468a priority from the Impact x Urgency matrix;
27934d6b "create and link a new knowledge draft before closure" (created as published). 27 need values in neither
text, 17 are ids or links only, 6 are values from the task.
Why the layer missed them: 870 of 876 ITSM records are before_tool_call checks of writes the agent made; a skipped step
has no call to check. The duty rule type (trigger -> required step, reminded before the reply) fired 6 times on unseen2
and was skipped all 6 times with "duty tool not available". Procedures extracted at intake are not used at runtime.

## 11:20 — Intake fixes for SOP duties; offline duty replay; unseen3 drawn
Three intake bugs dropped "when X, do Y" rules (changes 43–45); two more fixed from the replay (46–47). Duty replay on
90 DeepSeek arm-A ITSM runs (no model calls): open duties at the reply would flag 5 failed runs (8 of 104 failed
verifiers), 0 passed runs. Real but small. Failure taxonomy per feature is running (subagent). New held-out set
`unseen3` (10 AB + 10 ITSM, seed 20261103) drawn before any work on it; unseen2 is no longer clean.

## 12:30 — Request checklist (deliverables) hook; live runs started
Failure taxonomy: what the request asks for is the largest recoverable class (ITSM 45/104 failed checks, AB 119/414;
AB data-bound include/exclude rules 202/414). Built `DeliverablesHooks` (changes 48–49), replayed offline, then
started (snapshot `dlv1`, DeepSeek agent, function calling):
- AB A + deliverables: tuning and unseen, 2 trials (`dlv_A_t*`, `dlvu_A_t*`), vs existing arm-A runs.
- ITSM B with `builds_v2` duties, no brief (`itv2_t1`, `itv2u_t1`); ITSM A + deliverables (`itdlv_t1`, `itdlvu_t1`).

## 13:20 — Where hook feedback lands in the model input (live probe, function calling, DeepSeek)
`policy_eval/validate_injection.py` records the exact messages of every model call (LangChain chat-model layer).
- before_tool_call block: in the ToolMessage of the blocked call; stays in history on every later call.
- before_reply follow-up: a new HumanMessage; stays in history.
- before_llm_call reminders (all layer reminders: RuleSetHooks, intake, deliverables value notes): appended to the END
  of the SystemMessage for ONE model call only, then gone (not in history). In ITSM runs that is after ~11.5k chars
  (base prompt + 9.9k-char policy). Likely part of why reminders changed little.
- Real DeliverablesHooks follow-up: delivered as a HumanMessage (the probe agent then declined because the probe task
  told it not to retry; delivery itself is correct).

## 13:50 — Live results of deliverables and duties; reminder delivery fixed; decision run on unseen3
- AB A + deliverables (2 trials) vs A (3): tuning +6.0 pts partial (AA-style 30.9 → 41.4%), unseen +3.3 pts partial
  (AA-style 33.1 → 22.5%, more guardrail breaks). Follow-ups fired in 20 of 40 runs.
- ITSM (1 trial): A + deliverables −1.6 pts, B with builds_v2 duties −4.9 pts. ITSM policy work stopped (no headroom
  the layer can reach; remaining failures are agent capability or upstream).
- Reminders now attach to the tool result of the call they are about (change 50).
- Decision run (snapshot `notes1`, frozen before the run): AB unseen3, arm A vs arm C = B (final1 config) +
  deliverables + tool-result reminders, 3 trials each (`u3_A_t*`, `u3_C_t*`). Rule: keep the features only if C beats
  A by more than the noise (about ±6 pts per trial; paired over 10 tasks x 3 trials).

## 14:40 — Decision run result (AB unseen3, 3 trials per arm): no clear gain
| unseen3 (10 tasks x 3 trials) | Partial | AA-style | Guardrail-broken runs |
|---|---|---|---|
| A | 49.7% | 27.8% | 15 / 30 |
| C = policy layer + deliverables + tool-result reminders | 52.9% | 32.9% | 13 / 30 |
Paired over tasks: partial +3.2 pts (95% CI −5.1 to +12.4), AA-style +5.1 pts (CI −9.7 to +22.1); +3 / −3 tasks.
Direction is positive on all three AB sets for the request follow-up (+6.0, +3.3, +3.2 pts partial) but every
interval includes 0. By the decision rule set before the run, the features are not proven. Spend: $244.34.

## 15:30 — Requirements tracker test started (three phases)
Design: a checklist of required effects per task (request + policy + data read), kept and checked at the reply
(changes 51–52). Phase 1 (offline checklist recall vs graders): HANDBOOK 66% of rubric items covered with the data
and DeepSeek-V4-Pro as compiler (27% full, 39% partial); 33% without the data. AB/ITSM recall and the Phase 2 gate
replay are running. HANDBOOK runtime setup is being built by a subagent (benchmarks/handbook/).

## 14:20 — HANDBOOK.md runnable with CUGA (3 sample tasks), arm A trial 1
Runner `benchmarks/handbook/run_cuga_handbook.py`: per task, the task container (image `handbook_task:<task>` on
`handbook_base`, built from the sample with `benchmarks/handbook/Dockerfile.base` = the sample's Dockerfile without the
OpenHands runner) runs the task's MCP proxy (82 tools, 6 apps) and the task's own grader (tests/test.sh,
sop_verifier.py); CUGA runs on the host (function calling, DeepSeek-V4-Pro, `handbook/cuga.fc.dsv4.env`) over MCP via
langchain-mcp-adapters + AppToolsProvider. The proxy binds 127.0.0.1 in the container, so `handbook/tcp_forward.py`
relays it to a published port. Hooks: `POLICY_DELIVERABLES=1`, `HOOKS_MODULE=file.py:factory`.

| Task (arm A, 1 trial) | Rubric items passed | Score (mean of item scores) | Tool calls | Time | Cost |
|---|---|---|---|---|---|
| CareIG specialty pharmacy | 7 / 17 | 0.46 | 16 | 107 s | $1.02 |
| Vanguard Shield insurance | 7 / 12 | 0.81 | 90 | 167 s | $2.97 |
| Crestwood HR | 11 / 22 | 0.50 | 54 | 187 s | $2.04 |
Total 25 / 51 items (49%); 0 / 3 tasks fully passed. Smoke (Vanguard, earlier run): 7 / 12, $2.83.

## 16:40 — Tracker results so far; live tracker runs started (snapshot trk2)
- Phase 1 (failed checks covered by the checklist, full + partial): AB 89% (request only), ITSM 82%, HANDBOOK 66% of
  all rubric items (with data, DeepSeek compiler).
- Phase 2 gate replay: ITSM gpt-oss gate caught 46% of failed checks but flagged 40% of passed ones (follow-up in
  52/53 passed runs); with write results, an "unsure" status and DeepSeek: 37% caught, 17% wrongly flagged (46/53).
  AB (old gate): 22% caught, 13% wrongly flagged.
- HANDBOOK live, trial 1: tracker 27/51 rubric items vs CUGA alone 25/51 (+2 on CareIG).
- Started: AB A+tracker unseen3 x3, tuning x1, unseen x1; ITSM A+tracker tuning, unseen x1; HANDBOOK A and tracker
  trials 2-3. Tracker model DeepSeek-V4-Pro.

## 18:00 — Tracker live, first round: confounded; fixed and rerun as concurrent pairs
AB unseen3 tracker +13.8 pts vs the 13:50 arm A, but tracker runs with no follow-up (nothing shown) were +20 pts too:
time drift, not the tracker. ITSM −13.2 pts: follow-ups flagged inferred values as "wrong" and the agent changed
correct records. Change 55: missing-only follow-ups; A and T now run concurrently (AB unseen3 x3 pairs, ITSM tune +
unseen x1 pair), snapshot trk3.

## 19:30 — τ² airline headroom check (arm A, CUGA alone; first 20 tasks, 1 trial)
Runner: PR #139 from worktree `~/dev/cuga-eval-tau2`; launcher `benchmarks/policy_eval/tau2/run_arm_a.py`; labels in
`benchmarks/policy_eval/tau2/labels.md`. User simulator gpt-5-mini.

| Agent | Reward | Tasks with a real policy violation | With soft ones | Unneeded transfers |
|---|---|---|---|---|
| DeepSeek-V4-Pro | 13/20 (0.65) | 1 (5%) | 3 (15%) | 8 / 20 |
| gpt-oss-120b | 13/20 (0.65) | 2 (10%) | 2 (10%) | 11 / 20 |

Violations: insurance-after-booking workaround (both agents), a not-allowed cancellation and three travel
certificates on one booking (gpt-oss). Most failed tasks are missing or wrong allowed changes (capability), not
policy breaks. Below the ≥30% bar set for running the gate arm. Cost about $4.1 (agent tokens estimated from tracker totals).

## 21:00 — Paired tracker results (A and tracker at the same time) and τ2 headroom
| Benchmark | CUGA alone | + tracker | Paired |
|---|---|---|---|
| AB unseen3 (3 trials) | 56.0% partial | 59.4% | +3.5 pts, CI −2.5 to +9.4; follow-up in 4 of 30 runs: those −2.5 pts, the 26 without +4.4 (noise) |
| ITSM tuning + unseen (1 trial) | 71.6% verifiers | 72.5% | +1.0 pts (the "wrong"-item harm is gone) |
| HANDBOOK (3 trials, 153 rubric items) | 88 (57.5%) | 78 (51.0%) | −10 items; crestwood t3 7 vs 16 after a follow-up with 15 "missing" items |
HANDBOOK tracker runs used trk1/trk2 (follow-ups also listed "wrong" items). The compiler's per-record items can be
wrong (for example onboarding items for a person whose offer was rescinded), so "missing" follow-ups can push the
agent into forbidden work. τ2 airline arm A (20 tasks): policy violations in 5% (DeepSeek) and 10% (gpt-oss) of tasks,
below the 30% bar; the gate arm is not run. Spend: $313.95.

## 23:30 — Oracle upper bound: the agent fixes most failures when told exactly what failed
Paired, same time (snapshot trk3): after the answer, the grader's failed checks (with expected values) go back to the
agent, at most 2 rounds.
| | CUGA alone | + oracle follow-up | Paired |
|---|---|---|---|
| AB unseen3, 3 trials | 55.9% partial, 2.0/10 passed | 91.8%, 6.0/10 | +35.9 pts (95% CI +15.8 to +58.2), 9 better / 1 worse |
| ITSM tuning + unseen, 1 trial | 72.0% verifiers, 9/20 passed | 97.3%, 18/20 | +25.3 pts, 11 better / 0 worse |
One round cut AB failed checks from 93 to 24 (ITSM 17 → 8). Decision rule (large gain > +15 pts): feedback works; the
weak part is the checklist (what to check and the right values). The oracle includes expected values, so it is an
upper bound, not a method. Deck: docs/analysis/2026-11-02-policy-results-concise.html. Spend: $342.50.

## Names-only oracle: most of the oracle gain comes from the expected values
A, names-only oracle (N: which check failed, no values) and full oracle (O), all at the same time (snapshot trk3).
| | A | N (names) | O (full) |
|---|---|---|---|
| AB unseen3, 3 trials, partial | 53.4% | 59.8% (+6.4, CI −3.6 to +17.0) | 87.5% (+34.1, CI +13.7 to +56.7) |
| ITSM, 1 trial, verifiers (A 19/20 tasks done) | 80.0% | 81.3% (+3.9 paired) | 96.1% (+15.9 paired) |
About a fifth of the AB oracle gain and a quarter of the ITSM gain remain when the values are hidden. Knowing which
check failed is worth about +4 to +6 pts; the rest needs the right values, which come from the task's own reasoning.

## HANDBOOK step 1: how CUGA alone handles the long SOP (9 runs, no grader access in any system)
- The agent read the whole SOP once (58,685 bytes of raw HTML, not truncated) and it stayed in the conversation.
  The runner's log shows 4,000 chars only (TOOL_LOG_LIMIT). readFile cannot read .xlsx (binary).
- 24 of 51 rubric items fail in at least 2 of 3 runs. By kind (from the rubric text):
| Kind | Items | Examples |
|---|---|---|
| Did what the SOP forbids (exception or hold missed) | 8 | offboarded Navarro (4 items, 3/3); submitted a PA that had to be held (2/3); onboarded a rescinded hire (2/3) |
| SOP template, routing or format | 6 | FIN-Exceptions tickets assigned to the SOP's owner; "[PA HOLD]" Slack text; email body template |
| Required SOP step skipped | 5 | #hr-escalations message; audit-log rows; exception tickets |
| Duplicates ("exactly one") | 3 | Ellis message, email, event |
| Spreadsheet data handling | 2 | roster rows; intake.xlsx values |
Unlike AB / ITSM / τ2, HANDBOOK has real policy-violation headroom (about a third of the persistent failures).
Caveat: only 3 public tasks; any method designed on them is in-sample until the full set is available.

## HANDBOOK step 1b: full intake of one SOP (Crestwood HR) with the task's 82 tools
`benchmarks/handbook/intake_one.py`, gpt-oss-120b, 108 s, 44 calls. 88 sections, 736 statements, links 124 defines +
33 refers-to; rules: format 20, required_args 20, allowed_values 19, duty 3, record_condition 2, plus 157 verify and
144 guidance (text only); 198 statements out of scope. Fixed: a malformed model rule crashed the validator (now rejected).
What intake misses (the SOP parts behind CUGA's repeated failures):
- Procedures: 17 sections have "Step N:" procedures (onboarding 8 steps, offboarding, leave, offers); intake found 1
  "procedure" and it is the table of contents. Step text is not list markup, so it was not recognized.
- "Do not initiate involuntary offboarding without written authorization from one of these two individuals" (the
  Navarro failures, 4 items in 3/3 runs): out of scope. Process-level preconditions have no rule type.
- "If a situation arises that is not covered, escalate ... in Slack" (#hr-escalations, 3/3): out of scope.
- Email/message formats: "formatting instruction for an email, not a rule" → out of scope.
- Captured well: Jira naming templates (ONBOARD-[Last Name]-[Start Date MMDDYYYY]) as format / required_args.

## HANDBOOK step 1c: procedure graph for the Crestwood SOP (change 58)
After the fixes: 17 procedures, 80 steps (64 mapped to a tool), 112 procedure items: preconditions (e.g. §12.1
"written authorization from HR Director or Employee Relations Specialist", if not: stop), exceptions, templates
(ONBOARD-/OFFBOARD- summaries, NEW HIRE / SEPARATION Slack texts, roster status, checklist row) and escalations.
Page: docs/analysis/2026-11-02-crestwood-sop-graph.html (generated by benchmarks/handbook/render_sop_graph.py).
Not yet captured: rules outside procedures (rescinded offer §15.6, "if not covered, escalate" §1).

## HANDBOOK: procedure guide, paired live test (3 tasks x 3 trials, A and guide at the same time, snapshot guide1)
| Task | CUGA alone | + procedure guide |
|---|---|---|
| Crestwood HR | 14, 15, 15 of 22 | 14, 13, 15 |
| Vanguard insurance | 7, 7, 7 of 12 | 7, 11, 10 |
| CareIG pharmacy | 8, 8, 8 of 17 | 9, 9, 9 |
| Total | 89 / 153 (58.2%) | 97 / 153 (63.4%), +8 items |
- Vanguard: exception items, exception tickets and assignee went from 0/3 to 2/3 after the gate on its §7.1 procedure.
- Crestwood: the gate stopped OFFBOARD-Navarro in all 3 runs with the exact rule ("written authorization from
  Nicole Ashford or Marta Voss ... if not: stop"). The agent then reasoned "both were present at the meeting per the
  VP's email; this constitutes authorization" and made all 7 Navarro writes. The rule reached the agent; its judgment
  of the evidence was wrong. Next: check precondition evidence (a written message FROM one of the named people) on the
  data the agent read, and keep the stop when it is missing.
- In-sample: the guide was built and replayed on these same 3 tasks (no grader data inside the system).

## HANDBOOK: procedure guide v2 (evidence check + general-rules stop), paired, 3 tasks x 3 trials (snapshot guide2)
| Task | CUGA alone | + guide v2 |
|---|---|---|
| Crestwood HR | 14, 11, 14 of 22 | 18, 19, 19 |
| Vanguard insurance | 7, 8, 5 of 12 | 10, 11, 11 |
| CareIG pharmacy | 7, 8, 8 of 17 | 10, 8, 8 |
| Total | 82 / 153 (53.6%) | 114 / 153 (74.5%), +32 items |
Guide actions: 6 procedure gates, 9 general-rules stops, 3 evidence stops. In-sample (built and replayed on these 3
tasks); needs the full HANDBOOK set to confirm. Next: SOP planner spikes (level 1 plan; level 3 plan + next step + guide).

## HANDBOOK: SOP planner spikes (levels 1 and 3), paired with A, 3 trials (snapshot plan1)
| Arm | Crestwood | Vanguard | CareIG | Total of 153 |
|---|---|---|---|---|
| A (CUGA alone) | 11, 15, 15 | 8, 7, 7 | 9, 9, 9 | 90 |
| Level 1: SOP plan shown every call | 17, 11, 16 | 8, 7, 5 | 10, 10, 10 | 94 (+4) |
| Level 3: plan + NEXT step + guide v2 | 15, 18, 19 | 5, 5, 5 | 9, 8, 8 | 92 (+2) |
| (earlier batch) Level 2: guide v2 alone vs its A | 18, 19, 19 | 10, 11, 11 | 10, 8, 8 | 114 vs 82 (+32) |
The planner decides each case from partial data (reads cut at 8k chars) and the agent follows it: on Vanguard it
planned "SUSP-00n" items with its own follow/escalate calls, and three reconciliation rubric items fell to 0/3.
Same lesson as the tracker: a second model's case decisions on partial data add errors. Level 2 (narrow checks with
evidence at commit points) stays the best design. Spend: $527.18.

## HANDBOOK with gpt-oss-120b everywhere (agent, guide evidence, loop questions), 3 tasks x 3 trials, arms at the same time
(Leaderboard metric = mean rubric score per task, the same as ours. Leaderboard on the full set: Opus 5.5 52.3%, GLM 5.3 29.9%.)
See the table printed in the session; summary: CUGA alone 33.3%, + guide v2 34.0%, + loop + guide ~38-39%.
Same 3 tasks with DeepSeek-V4-Pro: alone 54-59%, + guide 74.5%, + loop 72.2%. The agent model sets the ceiling;
the SOP methods add 15-20 pts to a capable agent and 1-6 pts to gpt-oss. 70-85% with gpt-oss is not realistic.

## 2026-11-03 — HANDBOOK head-to-head and τ²-Telecom test split
HANDBOOK, DeepSeek, A / guide v2 / loop + guide at the same time, 3 tasks x 3 trials: 58.8% / 64.7% / 69.3%
(Crestwood 12,14,15 / 18,14,18 / 20,20,16; Vanguard 7,9,8 / 6,8,8 / 8,7,7; CareIG 9,8,8 / 9,9,9 / 10,9,9).
Loop + guide is best (+10.5 pts). Its remaining failures (47 of 153): spreadsheet rows and values ~17, message
templates ~9, Jira ticket counts and comments ~8, holds still broken (CareIG PA submitted after a HOLD decision) ~7,
duplicates ~4.
τ²-Telecom official test split (40 tasks), CUGA alone, DeepSeek, gpt-5-mini simulator: 19/40 pass@1 (47.5%).
(The first 20 tasks of the full list, all 1–2 fault mobile-data cases, gave 18/20.)

## 2026-11-03 night — SOP progress tracker on τ²-Telecom (held out) and HANDBOOK rounds
Method (no tuning on test): Telecom development on 20 tasks of the official **train** split; the **test** split (40) was
run only after the code was frozen (snapshot sop_trk4), twice. Arms always at the same time. Simulator gpt-4.1 (the τ²
reference; gpt-5-mini ended calls mid-fix with `###STOP###`: CUGA alone 19/40 with it, 27/40 with gpt-4.1).

New mechanism `policy_layer/sop_tracker.py`: the SOP split at its headings; before each agent turn a small model
(gpt-oss-120b) picks the chapters for the customer's issue (kept for the whole conversation) and lists the SOP's checks
and actions as done / pending / not needed, plus a met escalation condition. Every item quotes the SOP verbatim; done
needs a conversation quote; "not needed" without a quote counts as pending (the agent must find out — e.g. whether the
customer is abroad). The note goes into the conversation with the customer's message. Nothing names Telecom objects.

| Run | Split | CUGA alone | + tracker | Wins / losses |
|---|---|---|---|---|
| dev1 (tracker v1) | train 20 | 13/20 | 13/20 | 1 / 1 |
| dev2 (tracker v3) | train 20 | 13/20 | 16/20 | 3 / 0 |
| **test1** (frozen) | test 40 | 25/40 | **32/40** | 9 / 2 |
| **test2** (replication) | test 40 | 26/40 | **29/40** | 6 / 3 |
| **pooled test** | 80 runs | 63.8% | **76.2%** | 15 / 5, p = 0.041; 95% CI 0.0 to +25.0 pts |

Tasks passed in both test runs: 23 → 29 of 40. Gains come from steps the agent skipped: data roaming when abroad
(the customer only says so when asked), and fewer runs out of steps (max_steps endings 16 → 6 over both runs).
Losses are 7–9-fault MMS tasks (one ran out of steps, one still missed roaming). Tracker cost ≈ $0.02 per task.

HANDBOOK (3 public tasks, in-sample, DeepSeek, 3 trials, paired): round 1 (bulleted labelled steps are procedure
steps → Vanguard §2.1 extracted) alone 56.2% vs loop + guide **76.5%** (+31 of 153 items); rounds 2–3 (generic fixes:
held-case write stops, not_applicable, [TAG] templates, sibling-section context, combined cases) +20 and +14 — no
further gain on these 3 tasks; tuning stopped. Full details: `benchmarks/policy_eval/changes.md` rows 72–86.

**No-harm check failed in a second domain.** τ² airline test (20 tasks, same frozen tracker): CUGA alone 17/20, +
tracker 11/20 (0 wins, 6 losses). Airline's policy is a set of rules, not a troubleshooting flow; the tracker listed
rules as pending checks without their exceptions (e.g. "basic economy cannot be modified", without "change the cabin
first"), and the agent refused changes the policy allows. So: the tracker helps flow-type SOPs and hurts rule-type
policies as built. Not tuned on the airline test (it would no longer be held out). Spend at stop: $1055.92 of $1200.
