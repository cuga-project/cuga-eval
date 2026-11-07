# Stability gate report (Task 6.2)

Gate run on 2026-11-05 by the stabilization plan (`docs/superpowers/plans/2026-11-04-policy-architecture-stabilization.md`, Task 6.2). Gate repo `~/dev/cuga-agent-gate`, branch `policy/stable`, final commit `9135be1f4` (the G1 smoke and the G10 reading are on `b2d6e0e96`; see below). Eval repo `~/dev/cuga-eval`, branch `evaluation-work`, base commit `4c548bbd`. τ² worktree `~/dev/cuga-eval-tau2`, `9fd6d0d1`. Nothing was pushed.

**Final commit.** A review of the whole branch gave one fix wave (change 144), so the tag moved from `b2d6e0e96` to `9135be1f4`. None of it changes a measured number today, and golden has 0 differences. G3, G4, G7 and golden were run again on `9135be1f4`, and no result moved except test counts (G7). The G1 smoke ran on `b2d6e0e96`, and no agent has run on `9135be1f4`: **the first agent run on the final commit is the re-baseline.**

## Result

**Status: DONE_WITH_CONCERNS.** 9 checks pass, 1 is a partial pass (G6), none fails. `policy/stable-v1` is set on the gate repo (see the end of this file for the commit).

| # | Check | Result | Note |
|---|---|---|---|
| G1 | One command for all | Pass | 8 valid result files, $1.40 in all (limit $3). Hooks acted on every best profile; the τ² navigator did not fire on the first task and fired on a second one |
| G2 | Policy off is unchanged | Pass | 7 tests named below, and the 6 baseline result files of G1 |
| G3 | Config only | Pass | The only environment reads are keys and the gateway address |
| G4 | Reports reproduce | Pass | All 4 number sets equal |
| G5 | Rules reproduce | Pass | `skill_v1` 106, 0 false denies, 2 of 93; `v4A` 104, 1, 2. `builds_v5` 102 is below 104 (accepted). Tuning version |
| G6 | Compile coverage | **Partial pass** | `skill_v1` validates with 0 errors; "no unexplained statement" is not met in full: 133 deny tests on 126 statements have no outcome; pipeline and older builds have recorded errors |
| G7 | Tests | Pass | Run again on the final commit. Only the 7 `cuga_lite` environment failures of change 71 (and the τ² `test_run_emits_results_json`), by name |
| G8 | Reproducible | Pass | By ruling, 6 uncommitted cuga-eval paths of other work are listed, not staged |
| G9 | Obligations known | Pass | 9 producer rows, all level 1, none held-out |
| G10 | Docs true | Pass | Spec status table and hub page corrected; section 5 read in full after fix round 1 |

## G1: one command for all benchmarks

Snapshot `stable-b2d6e0e96` (made with `snapshot_src.sh` from the clean gate repo, `code_sha` `b2d6e0e96` in all result files). Command, one per arm, the two arms of each benchmark started at the same time:

```
~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/harness/run.py --bench <b> --profile <p> --set <set> \
    --snapshot stable-b2d6e0e96 --trial 1 --run g1_<name> -j 1 --tasks <task>
```

Tasks and sets are the ones of the Task 2.3 smoke (found from the `smk_*` results): IT service `task_20260114_174427_042_99ba2325_7915481a` (`itsm-tune`), AutomationBench `marketing.email_campaign_analytics` (`ab-policy-types-holdout`), HANDBOOK `hr_crestwood_university_79786c46` (`handbook-public3`), τ² Telecom `[mobile_data_issue]data_saver_mode_on|user_abroad_roaming_enabled_off[PERSONA:Easy]` (`tau2-telecom-test`). Agent `aws/gpt-oss-120b`. These are smoke runs: one task each, so the scores say nothing.

| Benchmark, task | Arm | Score | Task 2.3 smoke (code `ba8474dd6`) | Cost | Smoke cost | What fired (audit lines and usage) |
|---|---|---|---|---:|---:|---|
| IT service `..._7915481a` | `baseline` | 0, 1 of 3 verifiers | same | $0.0017 | $0.0026 | nothing |
| | `itsm-rules` | 0, 1 of 3 verifiers | same | $0.0021 | $0.0020 | 3 audit lines on `create_knowledge_article`: 2 allow, 1 observe (rules); verifier 1 model call, allow. No stop, as in the smoke |
| AutomationBench `marketing.email_campaign_analytics` | `baseline` | 0.10 | 0.30 | $0.0073 | $0.0136 | nothing |
| | `automationbench-gptoss-b4tf` | 1.00, 0 guardrails broken | 0.82, 1 broken | $0.0143 | $0.0382 | 19 audit lines: discovery, intake (2 `policy_found`, 3 `detected`, 7 `not_policy`, 2 allow, `complete`); requirements tracker `compiled` and 2 `followup`); detector 5 calls, intake 13, decisions 2, tracker 3. No `block_once` (the smoke had 2) |
| HANDBOOK `hr_crestwood_university_79786c46` | `baseline` | 9 of 22 | 8 of 22 | $0.129 | $0.141 | nothing |
| | `handbook-gptoss-loop-guide-evidence` | 9 of 22 | 10 of 22 | $0.472 | $0.151 | 12 audit lines: loop 5 `follow`, 1 `stop`, 1 SOP exception, 2 write denies; guide 3 denies (`google_mail__mark_emails`, `jira__create_issue` twice). Loop 74 model calls (smoke 7), agent 9 turns (smoke 3), 866 s (smoke 251 s) |
| τ² Telecom `[mobile_data_issue]data_saver_mode_on\|user_abroad_roaming_enabled_off[PERSONA:Easy]` | `baseline` | 1 | 1 | $0.0986 | $0.0939 | nothing |
| | `tau2-telecom-gptoss-navigator` | 1 | 0 | $0.221 | $0.325 | **nothing fired**: no hand-off was attempted, navigator 0 model calls, 0 audit lines |
| same task, run again (`g1b_*`) | both arms | 1 and 1 | | $0.0986 each | | Same cost to the sixth digit and 36 steps in both arms and in the first baseline run: a repeat of the same requests, consistent with the gateway's answer cache. It adds no evidence. Navigator 0 calls |
| τ² Telecom, one more task `[service_issue]airplane_mode_on\|lock_sim_card_pin[PERSONA:Easy]` (`g1c_*`; the DeepSeek runs of the old Telecom set handed off on it in 2 of 2 runs) | `baseline` | 1 | not in the smoke | $0.0976 | | nothing |
| | `tau2-telecom-gptoss-navigator` | 1 | not in the smoke | $0.158 | | **navigator fired**: 4 audit lines (`transfer_to_human_agents` blocked, the hand-off reply blocked, then 2 `allow_after_cap`: "2 hand-offs were blocked, and the limit is 2"); Kev 5 calls |

8 valid result files for the 4 benchmarks with the two arms of each (`g1_*`), with no error and no gateway failure. The two extra τ² pairs are not counted in the 8: the first τ² best-arm run did not exercise its hook, so a second task was run to see whether the hook works on the stable code. It does. A hook that never fires on a best profile would otherwise have been a failed check.

**Ledger:** $1632.14 before, $1633.54 after: **+$1.40** (limit $3). Most expensive task: $0.472 (HANDBOOK best arm; limit $1). The 12 result files sum to $1.40 (10 `g1_`/`g1b_` files $1.14, the 2 `g1c_` files $0.26).

**Differences from the Task 2.3 smoke.** One run each, so most are noise, but two are large:

- HANDBOOK best arm, three data points (`harness/results`): the Task 2.3 smoke `smk_hb_best_t1` (code `ba8474dd6`), the Task 2.4 run `smk24_hb_best_t1` (code `2eadb7f33`) and this gate's `g1_hb_best_t1` (`b2d6e0e96`).

| Run | Cost | Agent / loop cost | Agent turns (final answers) | Loop calls | Cases handled | Score | Wall |
|---|---:|---|---:|---:|---:|---:|---:|
| `smk_hb_best_t1` (`ba8474dd6`) | $0.151 | $0.143 / $0.008 | 3 | 7 | 1 | 10 of 22 | 251 s |
| `smk24_hb_best_t1` (`2eadb7f33`) | $0.315 | $0.288 / $0.027 | 9 | 70 | 7 | 6 of 22 | 544 s |
| `g1_hb_best_t1` (`b2d6e0e96`) | $0.472 | $0.444 / $0.028 | 9 | 74 | 7 | 9 of 22 | 866 s |

  Both later runs have 9 final answers and processed all 7 cases; the Task 2.3 smoke has 3 and one case, so the smoke is the short outlier and not a regression signal. The extra cost is in the agent (more turns and more input tokens), not in the loop. Planning figure for one HANDBOOK loop task on this profile: about $0.3 to $0.5, 9 to 15 minutes. Whether a change between `ba8474dd6` and `2eadb7f33` made the loop handle more cases was not tested (3 gate commits lie between them); costs use list prices of `aws/gpt-oss-120b` ($0.15 and $0.60 per 1M tokens).
- AutomationBench best arm: cost $0.014 against $0.038, with intake 13 calls (smoke 16) and decisions 2 (smoke 4); no `block_once` this time. One run; the hook counts vary because gpt-oss answers differ between runs.
- τ² best arm, first task: 1 against 0 in the smoke. In the smoke the agent tried a hand-off and the navigator blocked it; in this run the agent never tried one. One run.

**Parts that the checklist said were not exercised live (Task 2.3):**

| Part | Fired in G1? |
|---|---|
| `verifier_for` | **No.** No profile sets `checkers.method_choice`; only unit tests cover it |
| τ² message tool | **No.** It is in the agent's tool list (`send_message_to_user`, passed by the adapter) and the navigator builds with it, but the agent never called it in the 3 τ² best-arm runs, so the mid-turn path did not run |
| Guide's evidence model | **No.** 0 calls again (the guide denied 3 writes with no model call, as in the old runs) |
| HANDBOOK per-case loop | **Yes.** 74 model calls, 7 cases, plan and follow-up lines in the audit |
| τ² navigator (`wrap_tools`, `after_reply`) | **Yes** on the third task, not on the first two |

**Scan** (`tools/scan_run.py`) on all 12 runs: 0 hits except 2 `grep` hits in the HANDBOOK baseline: `strings employee_roster.xlsx | grep -i "E-1014"`, inside the container, on the task's own file (the same as in the smoke). 0 `Traceback`, 0 `UnboundLocalError`. No reads of grader files or of paths outside the workspace.

**Pass**: 8 valid result files, hooks acted on the best profile of every benchmark, a failed hook check (τ² navigator, first task) was resolved on a second task.

## G2: policy off is unchanged

Run now, all pass: gate `test_a_baseline_run_has_no_hook_and_the_write_runs` (hooks tests), `test_a_baseline_run_writes_no_file_and_wraps_nothing`, `test_no_decision_with_the_trace_off_and_none_in_a_baseline_run` (3 passed); eval `test_the_baseline_adds_nothing` (`baseline.yaml`), `test_the_baseline_profile_adds_nothing_with_the_real_model_factory`, `test_a_baseline_task_leaves_no_audit_in_its_folder`, `test_a_baseline_prompt_is_unchanged_byte_for_byte_in_each_adapter` (4 passed). Live: the 6 baseline result files of G1 (4 in the 8, and 2 more τ²) have no verdicts, only the `agent` component (and the τ² user simulator), and a work folder with `logging/` only (no `audit.jsonl`). **Pass.**

## G3: configuration only

In the gate's `policy_layer` (not tests), the only reads of the environment are `OPENAI_BASE_URL` and the key named by the model client (`llm.py`), `OPENROUTER_API_KEY` (`detectors.py`, `runtime.py`), and the secret-name scan that keeps keys out of audit lines (`trace.py`). No `POLICY_*`, `SOP_*`, `HOOKS_*` or `HB_*` is read there (same on `9135be1f4`). `src/cuga/backend/server/main.py` reads `POLICY_EMBEDDING_*`: that is CUGA's own server setting for its embedding model, not the policy layer. `policy_layer/tests/test_runtime_assembly.py` (`ALLOWED_READS`) names each read and is part of the G7 run. In the eval repo, the live code reads `POLICY_MODEL_NAME` as a default of `--model` in `build_rules.py` and `deliverables_replay.py`, and `HB_BUILDS` in `intake_one.py`: offline tools, no run (listed in `ENVIRONMENT.md`). The harness removes `POLICY_`, `SOP_`, `HOOKS_`, `HB_` variables from each child. **Pass.**

## G4: reports reproduce

`harness/report.py` on the saved files, no model call, run now:

| Runs | Expected | Result | Basis (set and label in `sets/registry.json`) |
|---|---|---|---|
| `ph_AF` `ph_B4TF` | +18.9, 24/6, p = 0.001 | 23.8% to 42.7%, +18.9, 24 / 6 / 5, p = 0.001 | `ab-policy-types-holdout`: held out when first run, label **seen** (gpt-oss ran all 35) |
| `pq_AF` `pq_B4TF` `pq_B4TFM` | +8.8, 14/6/11, p = 0.115; +4.6, 13/9/9 | +8.8, 14 / 6 / 11, p = 0.115; +4.6, 13 / 9 / 9, p = 0.523 | `ab-policy-types-holdout2`: held out when first run, label **seen** |
| `hbq_A` `hbq_GR` `hbq_GW` | 49 / 51 / 54 of 153 | 49, 51, 54 of 153 | `handbook-public3`: **tuning** (in-sample) |
| `test1_A,test2_A` `test1_T,test2_T` | 63.8% to 76.2%, 9/3, p = 0.146 | 63.8% to 76.2%, 9 / 3 / 28, p = 0.146 | `tau2-telecom-test`: held out when first run, label **seen** (DeepSeek ran all 40) |

Also tests in `test_harness.py` (`EVAL_NO_SKIP=1`, no skip). Run again on `9135be1f4`: all 4 equal. `report.py` now prints the label of the set and what the agent model has run of it (`set ab-policy-types-holdout (seen; aws/gpt-oss-120b ran 35 of 35)`), and the `code_sha` and `profile_hash` of each arm: `ph_*` `2107a0756`, `pq_*` `ee4615fca`, each arm one value, no profile hash recorded; `hbq_*` and `test1_*`, `test2_*` none recorded. **Pass.**

## G5: rules reproduce

`rule_audit.py report` on ITSM `e2891a7b98`, code and Cedar only (no model; `--verifier` not used), on the 347 blind tests and the 182 saved arm-A runs, output to a temp folder (`--out`), so no package file changed. **All numbers are a tuning version:** `e2891a7b98` is the version the pipeline was repaired on and the only one with gold.

| Package | Caught, of 182 | False denies, of 165 allow tests | Passed runs denied, of 93 |
|---|---:|---:|---:|
| `skill_v1` (made from text alone) | **106** | **0** | **2** |
| `builds_v4_v4A` | 104 | 1 | 2 |
| `builds_v5` (pipeline) | 102 | 1 | 2 |

The plan's bar is at least 104, at most 1 false deny, 2 of 93. `skill_v1` and `v4A` meet it. `builds_v5` is 102 and below the bar: the controller accepted it (a ruling of Task 3.1: the 2 lost catches are 2 value checks that a step cannot enforce; no hand edit). **What G5 shows:** it reproduces the audit of the old measured set (the 347 tests and 182 runs of changes 114 and 117) on current code. It says nothing about the packages the profiles run: `profiles/*.yaml` use `builds` (`itsm-rules`, and the Telecom navigator profile), `claude_v1` (`handbook-gemini-graph-gate`) and `v3` (both HANDBOOK loop profiles), not `skill_v1`. **No audit numbers exist for the `builds` package that `itsm-rules` runs** (`packages/itsm/e2891a7b98/builds` has no `AUDIT.md`). **Pass** (for `skill_v1` and `v4A`; `builds_v5` below 104, accepted).

## G6: compile coverage

`packages/COVERAGE.md` (15 `skill_v1` packages and 10 AutomationBench gold builds), and `validate` on all 84 package files (`tools/validate_all.py`, which calls the code behind `cli validate`; `--strict` checks every package as a new one; and `cli validate` run by hand on `skill_v1`, `builds_v5` and `v4A` of `e2891a7b98`).

| Check | Result |
|---|---|
| `skill_v1` (15) | 0 errors in strict mode. Warnings only: `rule_conflict` (a duty against a role rule), `schema_conflict`, `unbound_value`, `not_in_text`, `exception_without_rule` |
| `COVERAGE.md` | No row is empty. 15 packages have 0 must or must-not statements with no outcome. 8 of the 9 ITSM versions have "no tests"; AutomationBench gold builds hold no text and no tests |
| Packages with errors | `builds_v5` 9 packages, 10 `quote_not_verbatim` (these appear only when the package is checked as a new one: `--strict`, or `cli validate` without `--legacy`; the default `validate_all.py` run reads `builds_v5` as legacy and shows none) (the model shortened a quote with "..."); `pipeline_gptoss` 3 and `pipeline_dsv4` 6 packages with `quote_not_verbatim`, `rule_conflict`, `unknown_role`, `rule_no_trigger`; older measured builds (`builds_v2`, `builds_v4*`, HANDBOOK `v3`, `v4`) with `invalid_slots`, `rule_conflict`; legacy sources `builds`, `gold`, `claude_v1`, Telecom `builds` have `coverage_incomplete` and `rule_no_trigger` in strict mode. All are in `packages/VALIDATION.md` and none was changed (measured packages stay as measured) |

**"No unexplained statement" is not met in full.** "0 statements with no outcome" trusts the author's own modality: blind decision tests found **133 deny tests on 126 statements that have no outcome**, because the author left them unmarked (Crestwood 95 on 88, Vanguard 19, CareIG 12, Telecom 3, airline 1, retail 3). Packages that must validate clean: `skill_v1` (they do). Packages with recorded exceptions: `builds_v5` and the other pipeline builds, and the measured and converted builds above. **Partial pass.**

## G7: tests

| Suite | Command | Result |
|---|---|---|
| Policy layer, hooks, CUGA-lite (gate, `9135be1f4`) | `.venv/bin/python -m pytest -q -p no:cacheprovider src/cuga/policy_layer/tests src/cuga/backend/hooks/tests src/cuga/backend/cuga_graph/nodes/cuga_lite/tests` | 4192 passed, 3 skipped (AppWorld corpus not vendored), 2 failed |
| All of `cuga_lite` | same, `src/cuga/backend/cuga_graph/nodes/cuga_lite` | 1245 passed, 4 skipped, **7 failed** |
| Eval repo | `EVAL_NO_SKIP=1 .venv/bin/python -m pytest -q benchmarks/policy_eval/tests` | 323 passed, 0 skipped |
| Golden (no agent) | `cd benchmarks && ~/dev/cuga-agent-gate/.venv/bin/python -I policy_eval/tools/golden_hooks.py check` | 34 cases, 9 of 9 profiles match, 0 differences |
| Rule parity (no agent) | `policy_eval/tools/package_parity.py rules` | 52 builds, 3910 rules, 23460 cases, 0 raised calls, 0 rule differences |
| τ² worktree | `.venv/bin/python -m pytest -q benchmarks/tau2/tests` | 28 passed, 1 skipped (needs `TAU2_USER_SIM_MODEL`), 1 failed |

Known environment failures, by name. Change 71 listed 7 in `cuga_lite` ("e2b not installed, receipt tests need an API key"), and these are the same 7:

| Test | Cause |
|---|---|
| `executors/tests/test_e2b_lite.py::TestExecuteInE2BSandbox::test_successful_execution_with_output`, `::test_execution_error_handling`, `::test_empty_locals_handling` | `e2b` is not installed in the venv |
| `tests/test_run_receipt_integration.py::test_receipt_attached_when_flag_enabled`, `::test_receipt_is_none_when_flag_disabled` | No `OPENAI_API_KEY` in the shell. Both pass with a dummy value set (2 passed) |
| `executors/filesystem/tests/test_workspace_fs.py::test_shared_assets_seed_into_empty_thread_workspace`, `::test_download_upload_callable_but_not_structured_tools` | The temp folder is `/private/var/...` and the test compares it with `/var/...` (macOS link). The branch has no change in `executors/` against `main` |
| τ² `benchmarks/tau2/tests/test_reporting.py::test_run_emits_results_json` (outside the policy suites) | `FileNotFoundError: Could not find models configuration file` (`settings.openai.gptoss-default.toml` under `~/dev/cuga-agent`) |

No new failure. **Pass.**

## G8: reproducible

| Item | Result |
|---|---|
| `code_sha` in each result | `b2d6e0e96` in all 12 result files (the 8 of G1 and 4 more τ²); the snapshot `SOURCE.txt` says `b2d6e0e96` and 0 uncommitted entries |
| Gate repo `git status` | clean (0 entries) at `b2d6e0e96`, and at `9135be1f4` |
| τ² worktree `git status` | clean (0 entries) at `9fd6d0d1` |
| cuga-eval `git status`, before the Task 6.2 commit | Not this plan's, by the controller's ruling, not staged: `docs/analysis/2026-11-04-manager-review-deck.html` and `docs/analysis/2026-11-04-manager-review-notes.md` (modified), `docs/analysis/2026-11-05-problems-across-benchmarks-deck.html` and `docs/analysis/2026-11-05-problems-across-benchmarks-notes.md`, `reports/`, `research_notes/` (untracked). No other uncommitted path |
| `/tmp` in launchers | `benchmarks/policy_eval/launchers/` holds only `archive/` (0 hits outside it). In `harness/`, `profiles/`, `envs/` and `snapshot_src.sh` the only hit is a comment saying snapshots do not live in `/tmp` |

**Pass**, with the exception of the controller's ruling for the 6 paths above.

## G9: obligations known

`obligation_replay/REPORT.md` (Task 4.3, change 138): 3 benchmarks by 3 producers (`package`, `request`, `duty`) = 9 rows; each has a level chosen by the pooled rule (false-open at most 10% of passed checks and recall at least 30% of failed checks): **all 9 are level 1** (recall below 30%; Telecom: recall not known, 2 failed checks a write could meet). None was measured on a held-out set: HANDBOOK is in-sample, ITSM and Telecom runs are on tuning policies or sets that a model has seen. A level 2 from a replay on tuning sets is a note, never a setting. **Pass** (every producer has a level; none is above 1).

## G10: docs match the code

Read against the code on `b2d6e0e96`. Corrections made to `docs/superpowers/specs/2026-11-04-policy-system-design.md`:

| Statement before | Code | Spec now |
|---|---|---|
| Table status words "New", "Merge", "extend", "wire everywhere" | Package, ledger, level switch, config, runtime assembly, audit are built | Status column rewritten with what each part does today |
| `resolve_conflicts` listed as the way a tie is settled | No caller outside tests (not `cli`, skill, `build_runtime`) | Said so in section 10 |
| `priority_classes` "Built" | Only `validate_package` and an audit note (`priority_findings`) read it | "Validate only" in sections 10 and 12 |
| Config sample `authority: {company_domains, may_change_rules}` | Both are in `NOT_READ_YET`: `build_runtime` raises when set; `authority.supersedes` is read | Sample and sections corrected |
| The ledger "reads Scope" with the gate | The ledger has no retrieval scope (ruling, Task 5.2) | Section 3 row corrected |
| "Exactly one outcome per statement" | Ruling (Task 3.1): at least one; `validate` warns on `out_of_scope` plus another outcome | "At least one" in sections 4 and 9 |
| `on_task_end` writes the audit; `session_start` loads the package | The audit file is written at each decision (`trace.AuditLog`); the package is loaded in `build_runtime` | Section 6 rows corrected |
| Kev narrow questions are stage 2 of `WriteChecks` | Online intake (`sources.data`) only; `WriteChecks` has rules, gate, verifier | Section 6 and the "Not built" list say so |
| Level 3 includes read-before-write | A setting of `IntakeHooks` (`read_before_write`), not in `components_for` | Section 7 table and "Not built" list |
| "Coverage today" table (pipeline compiler never measured; HANDBOOK no audit, airline and retail no package) | 84 packages; compiler measured on 7 documents; the 25 packages of `COVERAGE.md` have an `AUDIT.md` | Table rewritten; pipeline result added |
| Principle 13 "trace wired only in the AutomationBench runner" | All 4 adapters write `audit.jsonl` | Corrected |
| `changes.md` entries 1–121 | 1–143 | Corrected |

New in the spec: a status paragraph at the top pointing to this report, and decision 5 in section 14 (open policy questions need an owner).

The hub page `docs/analysis/2026-11-04-policy-research-hub.html` now shows the architecture as built (status of each box, the hooks, the levels, the routing table, the package and obligation tables, compile coverage, the gap table). It has 7 new lessons, each with its source: skill from text alone; the pipeline cannot replace the skill; the obligation replay (all level 1, and why); the tracker's route by declared shape; `k_hops` and the label gap; no package is held-out; the corrections (the pilot's ITSM arm B most likely ran with no brief on 7 runs, old τ² navigator smokes invalid, Telecom 0 of 160 gateway errors). Numbers name their basis (tuning, seen, unseen). Render check with a DOM probe at 390 px: `scrollWidth` 390, no element beyond the viewport outside a scrolling table, 23 lessons, no console error. The manager deck was not touched.

Fix round 1 (a review of this report) added: section 5, `item_level` unset uses `observe` (it did not raise); level 1 has no checklist (`ObligationLedger` has no `before_llm_call`, and `show` changes nothing); level 3 has no `model` checks (only code checks run), and the same for `check: code | kev | model`; `LevelHooks` does not exist (`Shadow`, `WriteChecks`). Hub: level 1 text, 143 changes, ledger $1,633.54, the date, the $6.16 and $6.42 of lesson 18, and "held out when first run, set now labeled seen" in place of "held-out" and "unseen" for the AutomationBench +18.9 and +8.8.

**Pass** (read and corrected; the items above are what the reading found).

## Problems this gate did not hide

- **G6 is a partial pass, in those words.** The statement "0 statements with no outcome" is true only as far as the author marked them; blind tests find 133 deny tests on 126 unmarked statements. The pipeline packages (`builds_v5`, `pipeline_*`) have recorded validate errors that were not repaired.
- **The first τ² navigator run exercised nothing.** The result is valid and the hook is wired, but a best profile whose hook never fires would be a failed check. A second task showed it firing, with 2 blocks. The two extra τ² pairs cost $0.45 and are outside the 8 files.
- **Parts that no live run of this gate exercised.** The experiment plan starts from this list:
  - The three named in Task 2.3: `verifier_for` (no profile sets a method choice), the τ² message tool (in the tool list; the agent never called it), the guide's evidence model (0 calls).
  - **`WriteChecks`**: all 9 profiles set `write_checks: off`, so every profile keeps its separate hooks.
  - **The level switch**: no profile uses `auto` or a `control.level`; `components_for` and `resolve_level` ran only in unit tests.
  - **The obligation ledger and its producers** (`package`, `request`, `duty`): no profile names a producer; the replay (G9) is offline, on saved runs.
  - **Routers `bm25_kev` and `llm_cards`**, and **`k_hops`**: no profile sets `checkers.router`; `bm25_kev` and `llm_cards` have not run against a real model through the registry, and `k_hops` has no labels on `skill_v1` ids.
  - **The declared-rule-list route** (`shapes: [rules]`) and **`notes.brief_guidance`**: no profile sets them.
  - **`skill_v1` packages**: no profile runs them (profiles use `builds`, `claude_v1`, `v3`).
- **HANDBOOK loop cost: about $0.3 to $0.5 per task** on three runs ($0.15, $0.32, $0.47); the $0.15 smoke handled 1 case against 7 in both later runs, so it is the outlier. See G1.
- **`builds_v5` is 102 of 182, below the plan's 104.** Accepted by the controller (2 value checks that a step cannot enforce).
- **Spec section 5 (obligations)** was read in full in fix round 1, after a review found false status words in it (listed in G10). The status table, sections 3, 4, 6 to 12, 14 and 17 were read against the code in the first pass.
- **7 `cuga_lite` tests fail in this environment** (e2b not installed; no API key in the shell; a macOS temp-folder link). They fail on `main` too; the branch has no change in `executors/`.

## After the gate

What the experiment plan must decide. This list decides nothing, and no experiment was run or planned here.

1. **Re-baseline first.** The best profiles are older than the stable code (`best/*` snapshots against `b2d6e0e96`). Parity tests check wiring, not scores. Every best profile is measured again on the stable code before any new method is compared. The profile files now carry `write_checks: off`, so their `profile_hash` is new. The G1 smoke ran on `b2d6e0e96`, so the first agent run on the final commit `9135be1f4` is this re-baseline.
   - **ISO date compare, a possible behavior change on `automationbench-gptoss-b4tf`** (`ruleset.py:177-203`, change 134). Two ISO dates are now compared as dates; before, each side was read as its first number, so "created after 2025-01-01" compared by year. This profile compiles its rules online, with `record_condition` and `gt`, `ge`, `lt`, `le` (`handlers/prose.py:42`). The golden check cannot see this: it compares wiring, and these rules come from a model during a run.
   - **Checked backwards on the saved runs: no measured rule was such a compare.** The 932 result and trajectory files of `ph_*` and `pq_*` keep no rule body, but the 264 `policy_trace/*.json` files beside them do. They hold 446 compile answers for `ph_B3TF`, `ph_B4TF`, `pq_B4TF` and `pq_B4TFM` (0 cut, 0 with an error); 33 name `record_condition`, and none has an ISO date as a `value`. All 866 compile answers saved under `automationbench/results` have none. So +18.9 and +8.8 do not depend on this change; a new run can still compile such a rule.
   - **The new harness keeps less for this check.** It saves `overlay` in the trajectory, which holds the text and types of each statement and no `op`, `field` or `value`. The audit's `compiled` line holds a count and the rule types. The trace events stay in memory, and only `policy_trace_summary` is saved. So from now on a date statement can be found, and how it was compiled cannot. It needs the compiled rules saved in the trajectory (not done here).
2. **`handbook-gemini-graph-gate` needs its own re-baseline:** its measured 139 of 153 (gate `f69ebbec8`) came from a different grounding rule, so it does not carry over by parity alone. See `git diff f69ebbec8..b2d6e0e96 -- src/cuga/policy_layer/store_gate.py`:
   - The gate prompt changed by 3 lines in the move to the shared gate, and the DECISION line of a rule gained `; then: ...`.
   - **The evidence check changed.** `quoted_in` (`store_gate.py:93-105`) now takes `policy=` and refuses a quote that is also in the rules in scope, and it accepts a quoted span inside the evidence. The measured code looked only at the first words of the evidence. Commit `28c29b667` (change 108) is after the measured commit, and it was measured only in replay: a gpt-oss gate on 12 saved HANDBOOK arm-A runs, never the Gemini gate and never live. In that replay the 6 false blocks went (an SOP sentence quoted as evidence), and 9 other blocks came from the spans, so blocks went from 6 to 9 (7 on failed runs, 2 on the one passed run).
   - **The exact package bytes of the GW runs are unproven** (deferred at Task 2.1). A GW result names the path of its graph and holds no hash, and the package file `claude_v1/package.json` was last committed after those runs.
3. **Ledger recall and binding.** All 9 producer rows are level 1. HANDBOOK `package` has recall 14.2% and 2199 items counted `unbound` in the status table; ITSM `request` recall is 27.6% against the bar of 30%; Telecom has too few failed checks a write could meet to know. What raises recall (binding, content, the customer's tools) is open, and so is a held-out set to check any level 2.
4. **Retrieval labels on `skill_v1` ids.** The saved labels use `claude_v1` procedure ids, so `k_hops` cannot be scored on the only gate-buildable packages that have links. `bm25_kev` and `llm_cards` have not run against a real model through the registry.
5. **Compiler `STEP_LINE` defect.** `compile_sop` misses `**Step 1:**` and `*` bullets (Crestwood 7 to 25 sections, ITSM 0 to 10), so procedure recall of the pipeline is understated on 2 rows. A re-run costs under $0.50.
6. **New rule types that meet the bar.** `text_match` (12 statements) and `record_compare` (30 statements), each named from 4 benchmarks, meet the spec's bar of 2 benchmarks (`packages/PIPELINE_VS_SKILL.md`, section 7). Whether to add them, and what each would catch, is open.
7. **ITSM priority question.** The one false deny test (`update_incident` with `priority=moderate`) has two readings (the priority matrix, or "determined automatically"). It is a policy question, not relabelled. An answer would not make the pipeline ready.
8. **Open `policy_questions` need an owner.** 597 across the 15 `skill_v1` packages (52 for ITSM `e2891a7b98`; HANDBOOK 25, 14, 25; Telecom 14; airline 11; retail 7). Every rule keeps its safe default level until someone answers.
9. **Held-out sets.** No package is held-out. Airline is `seen, not tuned`; retail and ITSM `80cd3ebb50` are `unseen, no run`. A fresh set is needed for any claim.

## Tag

`policy/stable-v1` is a local tag on the gate repo at commit `9135be1f4` (branch `policy/stable`). It was first set on `b2d6e0e96` after every check above was recorded (eval commit `374f5701`), and moved after the fix wave of the final review (change 144), when G3, G4, G7 and golden were run again. G1 ran on `b2d6e0e96`: no agent has run on `9135be1f4` yet. Not pushed.
