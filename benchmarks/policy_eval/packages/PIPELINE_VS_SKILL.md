# Pipeline against skill

Stabilization task 3.5, 2026-11-05 (change 135). Question: can the open-model pipeline (`builder.py` with `rule_repair.py` for the rules, `procedure_compiler.py` for the procedures and must-not rules) replace the Claude skill today, by the bar of design spec section 9? This is a measurement. Nothing switches automatically, no existing package or build was changed, and no experiment was run (no agent run; only builds, offline tests and saved runs).

Regenerate the tables: `~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/tools/pipeline_vs_skill.py render --md benchmarks/policy_eval/packages/PIPELINE_VS_SKILL.md`. The tables come from `packages/pipeline_vs_skill.json` (made by `measure`, which reads the packages, the blind tests and the saved runs), the judge answers are in `pipeline_vs_skill_judge.json`, and the hand check is in `pipeline_vs_skill_handcheck.json`. Text outside the two table markers is written by hand; its numbers are copied from the tables.

## What was run

- **Documents (7).** The original file of each, as the skill read it: tau2 retail, tau2 airline, tau2 Telecom (`main_policy.md` and `tech_support_manual.md`), ITSM `e2891a7b98` (the system prompt), and the three HANDBOOK SOPs (Crestwood, Vanguard, CareIG; HTML from the public sample). Input is policy text and tool schemas only: no grader data, no tests, no earlier build.
- **Models (2).** `aws/gpt-oss-120b` and `azure/DeepSeek-V4-Pro`, `max_tokens` 16000, 75 s read timeout with 3 retries. One run per document and model (14 builds). Packages are saved under a new source: `packages/<bench>/<id>/pipeline_gptoss/` and `pipeline_dsv4/` (`package.json`, `compiled_graph.json`, `run.json`; the model cache is not committed). The package holds no tests: `measure` reads the skill package's blind tests for every row.
- **What the pipeline made.** Rules: `build_policy_set(repair=True)` on the converted policy set that the skill package was made from (`set.json`, so statement ids are the same and the tests apply). Procedures and must-nots: `compile_sop` on the original file as markdown (the HANDBOOK HTML through the converter's markdown). The builder also makes its own procedures (step graphs from numbered statements); both are measured.
- **Same tests, same runs.** Catches and false denies are on the skill package's blind decision tests (the pipeline did not see them), the ones the tool schema accepts; the tests the schema rejects are shown apart. Passed runs are the saved arm-A runs the skill's audit used. One denominator per column.
- **Must-not recall** is of the skill's must-not texts (each once, over all its procedures). A skill text is recalled when a pipeline text states the same prohibition. Rule of the match: a verbatim containment after folding case, spaces, dashes and quotes; otherwise a judge model reads the skill text and the 8 pipeline texts that share most words with it (word overlap only chooses what the judge reads; it never decides). The judge's stated rule is in the code (`MUST_NOT_USER`): the candidate forbids the reference's action in the reference's situation with the same values and limits; it may be more general or leave out a lead-in that only names the context; it does not match when it forbids a part of the case, other values, another case or the opposite. Pool `A` is where the skill puts must-nots: the `must_not` lists of procedures (compiler and builder), the escalation `must_not`, and the builder's exceptions and preconditions. `anywhere` also counts steps, global rules and the quote of every rule (including guidance rules, which show the statement to the agent and check nothing). The bar uses `A`. Section 3a splits `A` by source: the compiler's `must_not` lists and the builder's texts. Most of the matches are builder texts, so recall `A` mostly measures the builder, and the compiler's share is shown as a floor.
- **Procedure recall.** The compiler's procedures carry no statement ids, so the judge (`PROC_USER`) names the covering procedure and the skill steps it holds; a skill procedure is recalled when a candidate covers it and holds at least half of its steps. The builder's procedures are compared by statement id (at least half of the skill procedure's step statements in one builder procedure), with no model.
- **Judge.** `aws/gpt-oss-120b` for recall (cheap; its error is measured below); `azure/DeepSeek-V4-Pro` sorts the `verify` statements by missing rule type.
- **Cost.** Ledger $1625.13 before, $1631.56 after: +$6.42 of the $8 limit (14 builds $6.16, judge and sorter calls $0.27). The ledger first missed $0.039 (18 calls lost when several stages flushed at once; fixed in fix round 1, and a correcting ledger line added). Builds are priced at the list price of each model.

<!-- tables:start (tools/pipeline_vs_skill.py) -->
## 1. Can the pipeline replace the skill today?

| Benchmark | Documents run | Replace the skill today? | Reason |
| --- | --- | --- | --- |
| tau2 retail | 1 | no | best model gpt-oss-120b, missed 2: retail: false denies 18 against 0; retail: must-not recall 50% |
| tau2 airline | 1 | no | best model DeepSeek-V4-Pro, missed 1: airline: false denies 2 against 0 |
| tau2 Telecom | 1 | no | best model gpt-oss-120b, missed 2: telecom: catches 0.0% against 13.7%; telecom: must-not recall 50% |
| ITSM (EnterpriseOps-Gym) | 1 | no | best model gpt-oss-120b, missed 1: e2891a7b98: false denies 1 against 0 |
| HANDBOOK (SOPs) | 3 | no | best model gpt-oss-120b, missed 3: hr_crestwood_u: false denies 143 against 0; medical_careig: false denies 157 against 0; medical_careig: must-not recall 70% |

A model passes a document when all three conditions of the spec's bar hold on it (table 2). Nothing switches automatically. The catches condition (not more than 5 points below the skill) cannot fail on tau2 airline, HANDBOOK crestwood, HANDBOOK vanguard, HANDBOOK careig: the skill's catches are under 5%, so an empty package passes it. On those documents the verdict rests on the other two conditions.

## 2. The bar, per document and model

| Document | Basis of the numbers | Model | Catches, pipeline against skill (condition: not more than 5 points below the skill) | Allow tests denied, pipeline against skill (percent of the allow tests) | Catches minus allow tests denied (points; near 0: the rules do not tell the two apart) | False denies, pipeline against skill (condition: not higher) | Must-not recall (at least 80%) | All three | `validate` errors (beside the bar) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tau2 retail | unseen, no run | gpt-oss-120b | 57.4% against 36.2% (met) | 43.9% against 0.0% | +13.5 | 18 against 0 of 41 (missed) | 50% (missed) | no | 0 |
| tau2 retail | unseen, no run | DeepSeek-V4-Pro | 23.4% against 36.2% (missed) | 7.3% against 0.0% | +16.1 | 3 against 0 of 41 (missed) | 64% (missed) | no | 6 |
| tau2 airline | seen, not tuned | gpt-oss-120b | 47.4% against 3.5% (met; cannot fail, the skill is under 5%) | 46.9% against 0.0% | +0.4 | 23 against 0 of 49 (missed) | 87% (met) | no | 0 |
| tau2 airline | seen, not tuned | DeepSeek-V4-Pro | 7.0% against 3.5% (met; cannot fail, the skill is under 5%) | 4.1% against 0.0% | +2.9 | 2 against 0 of 49 (missed) | 93% (met) | no | 3 |
| tau2 Telecom | tuning | gpt-oss-120b | 0.0% against 13.7% (missed) | 0.0% against 0.0% | +0.0 | 0 against 0 of 44 (met) | 50% (missed) | no | 0 |
| tau2 Telecom | tuning | DeepSeek-V4-Pro | 2.0% against 13.7% (missed) | 2.3% against 0.0% | -0.3 | 1 against 0 of 44 (missed) | 75% (missed) | no | 0 |
| ITSM e2891a7b98 | tuning | gpt-oss-120b | 50.6% against 53.1% (met) | 0.7% against 0.0% | +49.9 | 1 against 0 of 147 (missed) | 100% (met) | no | 0 |
| ITSM e2891a7b98 | tuning | DeepSeek-V4-Pro | 51.2% against 53.1% (met) | 6.1% against 0.0% | +45.1 | 9 against 0 of 147 (missed) | 33% (missed) | no | 4 |
| HANDBOOK crestwood | tuning | gpt-oss-120b | 50.4% against 2.9% (met; cannot fail, the skill is under 5%) | 46.3% against 0.0% | +4.2 | 143 against 0 of 309 (missed) | 80% (met) | no | 18 |
| HANDBOOK crestwood | tuning | DeepSeek-V4-Pro | 74.2% against 2.9% (met; cannot fail, the skill is under 5%) | 74.4% against 0.0% | -0.2 | 230 against 0 of 309 (missed) | 75% (missed) | no | 25 |
| HANDBOOK vanguard | tuning | gpt-oss-120b | 1.4% against 1.4% (met; cannot fail, the skill is under 5%) | 0.0% against 0.0% | +1.4 | 0 against 0 of 58 (met) | 83% (met) | yes | 11 |
| HANDBOOK vanguard | tuning | DeepSeek-V4-Pro | 63.9% against 1.4% (met; cannot fail, the skill is under 5%) | 65.5% against 0.0% | -1.6 | 38 against 0 of 58 (missed) | 87% (met) | no | 1 |
| HANDBOOK careig | tuning | gpt-oss-120b | 49.6% against 0.6% (met; cannot fail, the skill is under 5%) | 52.0% against 0.0% | -2.4 | 157 against 0 of 302 (missed) | 70% (missed) | no | 52 |
| HANDBOOK careig | tuning | DeepSeek-V4-Pro | 87.5% against 0.6% (met; cannot fail, the skill is under 5%) | 86.4% against 0.0% | +1.1 | 261 against 0 of 302 (missed) | 81% (met) | no | 35 |

## 3. All measures, one denominator per column

Catches and false denies are on the skill's blind decision tests that the tool schema accepts (the same tests for every row of a document). Passed runs are the saved arm-A runs of the policy; a deny on a passed run is a conflict with the grader. Must-not recall is of the skill's must-not texts (each once): `A` counts the places the skill puts them (procedure must-not lists, exceptions, preconditions), `anywhere` also counts steps, global rules and rule quotes.

| Document | Source | Deny tests caught (deny or remind) | False denies (allow tests) | False reminders | Rejected by the tool schema (apart, not in the columns before) | Passed runs denied | Passed runs reminded | Must-not recall | Procedure recall |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tau2 retail | skill_v1 | 17 of 47 (36.2%) (deny 17) | 0 of 41 (0.0%) | 0 | 0 deny, 0 allow | no runs | no runs | 14 (reference) | 6 (reference) |
| tau2 retail | pipeline_gptoss | 27 of 47 (57.4%) (deny 27) | 18 of 41 (43.9%) | 0 | 0 deny, 0 allow | no runs | no runs | 7 of 14 (50%); anywhere 14 | compiler 1 of 6 (16.7%), steps 4 of 29 (made 5); builder 0 of 6 (made 0) |
| tau2 retail | pipeline_dsv4 | 11 of 47 (23.4%) (deny 11) | 3 of 41 (7.3%) | 0 | 0 deny, 0 allow | no runs | no runs | 9 of 14 (64%); anywhere 14 | compiler 2 of 6 (33.3%), steps 5 of 29 (made 5); builder 0 of 6 (made 0) |
| tau2 airline | skill_v1 | 2 of 57 (3.5%) (deny 2) | 0 of 49 (0.0%) | 0 | 0 deny, 0 allow | 0 of 43 | 0 of 43 | 15 (reference) | 5 (reference) |
| tau2 airline | pipeline_gptoss | 27 of 57 (47.4%) (deny 27) | 23 of 49 (46.9%) | 0 | 0 deny, 0 allow | 8 of 43 | 0 of 43 | 13 of 15 (87%); anywhere 15 | compiler 5 of 5 (100.0%), steps 48 of 55 (made 7); builder 0 of 5 (made 0) |
| tau2 airline | pipeline_dsv4 | 4 of 57 (7.0%) (deny 4) | 2 of 49 (4.1%) | 0 | 0 deny, 0 allow | 9 of 43 | 0 of 43 | 14 of 15 (93%); anywhere 15 | compiler 3 of 5 (60.0%), steps 36 of 55 (made 7); builder 0 of 5 (made 0) |
| tau2 Telecom | skill_v1 | 7 of 51 (13.7%) (deny 7) | 0 of 44 (0.0%) | 0 | 0 deny, 0 allow | 1 of 95 | 0 of 95 | 4 (reference) | 9 (reference) |
| tau2 Telecom | pipeline_gptoss | 0 of 51 (0.0%) (deny 0) | 0 of 44 (0.0%) | 0 | 0 deny, 0 allow | 0 of 95 | 0 of 95 | 2 of 4 (50%); anywhere 3 | compiler 4 of 9 (44.4%), steps 24 of 59 (made 19); builder 0 of 9 (made 5) |
| tau2 Telecom | pipeline_dsv4 | 1 of 51 (2.0%) (deny 1) | 1 of 44 (2.3%) | 0 | 0 deny, 0 allow | 0 of 95 | 0 of 95 | 3 of 4 (75%); anywhere 4 | compiler 4 of 9 (44.4%), steps 22 of 59 (made 19); builder 0 of 9 (made 5) |
| ITSM e2891a7b98 | skill_v1 | 86 of 162 (53.1%) (deny 58) | 0 of 147 (0.0%) | 6 | 20 deny, 18 allow | 2 of 93 | 18 of 93 | 3 (reference) | 8 (reference) |
| ITSM e2891a7b98 | pipeline_gptoss | 82 of 162 (50.6%) (deny 60) | 1 of 147 (0.7%) | 6 | 20 deny, 18 allow | 2 of 93 | 18 of 93 | 3 of 3 (100%); anywhere 3 | compiler 0 of 8 (0.0%), steps 0 of 28 (made 0); builder 3 of 8 (made 3) |
| ITSM e2891a7b98 | pipeline_dsv4 | 83 of 162 (51.2%) (deny 62) | 9 of 147 (6.1%) | 5 | 20 deny, 18 allow | 7 of 93 | 18 of 93 | 1 of 3 (33%); anywhere 3 | compiler 0 of 8 (0.0%), steps 0 of 28 (made 0); builder 1 of 8 (made 1) |
| HANDBOOK crestwood | skill_v1 | 10 of 345 (2.9%) (deny 4) | 0 of 309 (0.0%) | 1 | 0 deny, 0 allow | no passed run in 60 | no passed run in 60 | 20 (reference) | 26 (reference) |
| HANDBOOK crestwood | pipeline_gptoss | 174 of 345 (50.4%) (deny 174) | 143 of 309 (46.3%) | 0 | 0 deny, 0 allow | no passed run in 60 | no passed run in 60 | 16 of 20 (80%); anywhere 19 | compiler 4 of 26 (15.4%), steps 41 of 191 (made 7); builder 13 of 26 (made 17) |
| HANDBOOK crestwood | pipeline_dsv4 | 256 of 345 (74.2%) (deny 256) | 230 of 309 (74.4%) | 0 | 0 deny, 0 allow | no passed run in 60 | no passed run in 60 | 15 of 20 (75%); anywhere 19 | compiler 4 of 26 (15.4%), steps 42 of 191 (made 7); builder 13 of 26 (made 17) |
| HANDBOOK vanguard | skill_v1 | 1 of 72 (1.4%) (deny 1) | 0 of 58 (0.0%) | 0 | 107 deny, 94 allow | 0 of 2 | 0 of 2 | 30 (reference) | 17 (reference) |
| HANDBOOK vanguard | pipeline_gptoss | 1 of 72 (1.4%) (deny 1) | 0 of 58 (0.0%) | 0 | 107 deny, 94 allow | 2 of 2 | 0 of 2 | 25 of 30 (83%); anywhere 29 | compiler 17 of 17 (100.0%), steps 108 of 127 (made 20); builder 12 of 17 (made 15) |
| HANDBOOK vanguard | pipeline_dsv4 | 46 of 72 (63.9%) (deny 46) | 38 of 58 (65.5%) | 0 | 107 deny, 94 allow | 2 of 2 | 0 of 2 | 26 of 30 (87%); anywhere 30 | compiler 16 of 17 (94.1%), steps 106 of 127 (made 20); builder 13 of 17 (made 16) |
| HANDBOOK careig | skill_v1 | 2 of 345 (0.6%) (deny 2) | 0 of 302 (0.0%) | 0 | 0 deny, 0 allow | no passed run in 54 | no passed run in 54 | 27 (reference) | 26 (reference) |
| HANDBOOK careig | pipeline_gptoss | 171 of 345 (49.6%) (deny 171) | 157 of 302 (52.0%) | 0 | 0 deny, 0 allow | no passed run in 54 | no passed run in 54 | 19 of 27 (70%); anywhere 24 | compiler 12 of 26 (46.2%), steps 93 of 241 (made 15); builder 8 of 26 (made 11) |
| HANDBOOK careig | pipeline_dsv4 | 302 of 345 (87.5%) (deny 302) | 261 of 302 (86.4%) | 0 | 0 deny, 0 allow | no passed run in 54 | no passed run in 54 | 22 of 27 (81%); anywhere 27 | compiler 8 of 26 (30.8%), steps 60 of 241 (made 15); builder 8 of 26 (made 11) |

## 3a. Must-not recall by source

Pool `A` mixes two sources. `compiler`: the `must_not` lists of `procedure_compiler.py` (procedures and escalation). `builder`: the builder's procedure exceptions, preconditions and `must_not`, which often repeat the statement's own quote. A skill text counts under the source of the text it matched. The compiler share is a floor: a verbatim match takes the compiler's text first, but a judge match takes the text the judge named, and it may name a builder text when a compiler text also fits. The last two columns count pipeline must-nots that match no skill text.

| Document | Source | Recall `A` | Matched through a compiler `must_not` list | Matched through a builder text | Compiler must-nots (matched a skill text) | Builder texts in the pool (matched a skill text) | Compiler must-nots that match no skill text | Builder texts that match no skill text |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tau2 retail | pipeline_gptoss | 7 of 14 | 0 (floor) | 7 | 13 (0 matched) | 12 (7 matched) | 13 | 5 |
| tau2 retail | pipeline_dsv4 | 9 of 14 | 2 (floor) | 7 | 12 (1 matched) | 16 (7 matched) | 11 | 9 |
| tau2 airline | pipeline_gptoss | 13 of 15 | 4 (floor) | 9 | 21 (4 matched) | 18 (9 matched) | 17 | 9 |
| tau2 airline | pipeline_dsv4 | 14 of 15 | 6 (floor) | 8 | 21 (6 matched) | 13 (8 matched) | 15 | 5 |
| tau2 Telecom | pipeline_gptoss | 2 of 4 | 1 (floor) | 1 | 21 (1 matched) | 6 (1 matched) | 20 | 5 |
| tau2 Telecom | pipeline_dsv4 | 3 of 4 | 2 (floor) | 1 | 11 (2 matched) | 5 (1 matched) | 9 | 4 |
| ITSM e2891a7b98 | pipeline_gptoss | 3 of 3 | 0 (floor) | 3 | 2 (0 matched) | 16 (3 matched) | 2 | 13 |
| ITSM e2891a7b98 | pipeline_dsv4 | 1 of 3 | 0 (floor) | 1 | 1 (0 matched) | 11 (1 matched) | 1 | 10 |
| HANDBOOK crestwood | pipeline_gptoss | 16 of 20 | 0 (floor) | 16 | 15 (0 matched) | 83 (15 matched) | 15 | 68 |
| HANDBOOK crestwood | pipeline_dsv4 | 15 of 20 | 0 (floor) | 15 | 9 (0 matched) | 75 (15 matched) | 9 | 60 |
| HANDBOOK vanguard | pipeline_gptoss | 25 of 30 | 11 (floor) | 14 | 51 (11 matched) | 85 (13 matched) | 40 | 72 |
| HANDBOOK vanguard | pipeline_dsv4 | 26 of 30 | 11 (floor) | 15 | 40 (11 matched) | 52 (15 matched) | 29 | 37 |
| HANDBOOK careig | pipeline_gptoss | 19 of 27 | 5 (floor) | 14 | 31 (5 matched) | 98 (14 matched) | 26 | 84 |
| HANDBOOK careig | pipeline_dsv4 | 22 of 27 | 11 (floor) | 11 | 28 (11 matched) | 71 (11 matched) | 17 | 60 |

## 3b. Why the skill's own deny tests are not caught by rules

The deny tests that the tool schema accepts, by what the tested statement became in the skill package (`COVERAGE.md` table 3, from `coverage_matrix.json`). Each cell is caught of tests. A rule on one call cannot catch a deny test on an obligation, a step or a statement with no outcome: that is most of HANDBOOK and Telecom. The stored ITSM tests carry statement ids of an older split, so they cannot be placed.

| Document | Deny tests | code rule | verify | obligation or step | guidance, duty or global rule | definition | question only | no outcome | statement id not in the package |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tau2 retail | 47 | 16 of 20 | 1 of 19 | 0 of 2 | 0 of 3 | - | - | 0 of 3 | - |
| tau2 airline | 57 | 2 of 2 | 0 of 46 | 0 of 7 | - | 0 of 1 | - | 0 of 1 | - |
| tau2 Telecom | 51 | 5 of 10 | 0 of 8 | 2 of 28 | - | - | 0 of 2 | 0 of 3 | - |
| ITSM e2891a7b98 | 162 | - | - | - | - | - | - | - | 86 of 162 |
| HANDBOOK crestwood | 345 | 7 of 9 | 0 of 13 | 1 of 184 | 2 of 21 | 0 of 19 | 0 of 4 | 0 of 95 | - |
| HANDBOOK vanguard | 72 | 1 of 1 | 0 of 2 | 0 of 53 | 0 of 3 | 0 of 1 | 0 of 1 | 0 of 11 | - |
| HANDBOOK careig | 345 | 2 of 9 | 0 of 29 | 0 of 256 | 0 of 7 | 0 of 31 | 0 of 1 | 0 of 12 | - |

## 4. Cost per document and validate errors

| Document | Source | Cost of the build | Calls, time | Failed calls | validate errors / warnings (`legacy=False`) | Error codes |
| --- | --- | --- | --- | --- | --- | --- |
| tau2 retail | skill_v1 | made by an agent; not measured | - | - | 0 / 1 | - |
| tau2 retail | pipeline_gptoss | $0.033 (rules $0.028, procedures $0.005) | 55 calls, 158 s | 0 | 0 / 4 | - |
| tau2 retail | pipeline_dsv4 | $0.137 (rules $0.117, procedures $0.019) | 59 calls, 88 s | 0 | 6 / 12 | unknown_role 6 |
| tau2 airline | skill_v1 | made by an agent; not measured | - | - | 0 / 1 | - |
| tau2 airline | pipeline_gptoss | $0.055 (rules $0.049, procedures $0.006) | 103 calls, 205 s | 0 | 0 / 0 | - |
| tau2 airline | pipeline_dsv4 | $0.167 (rules $0.145, procedures $0.022) | 80 calls, 140 s | 0 | 3 / 1 | unknown_role 3 |
| tau2 Telecom | skill_v1 | made by an agent; not measured | - | - | 0 / 1 | - |
| tau2 Telecom | pipeline_gptoss | $0.108 (rules $0.093, procedures $0.015) | 224 calls, 382 s | 0 | 0 / 0 | - |
| tau2 Telecom | pipeline_dsv4 | $0.381 (rules $0.326, procedures $0.055) | 169 calls, 247 s | 0 | 0 / 0 | - |
| ITSM e2891a7b98 | skill_v1 | made by an agent; not measured | - | - | 0 / 5 | - |
| ITSM e2891a7b98 | pipeline_gptoss | $0.047 (rules $0.045, procedures $0.002) | 55 calls, 168 s | 0 | 0 / 3 | - |
| ITSM e2891a7b98 | pipeline_dsv4 | $0.373 (rules $0.357, procedures $0.016) | 66 calls, 92 s | 0 | 4 / 4 | rule_no_trigger 4 |
| HANDBOOK crestwood | skill_v1 | made by an agent; not measured | - | - | 0 / 6 | - |
| HANDBOOK crestwood | pipeline_gptoss | $0.303 (rules $0.293, procedures $0.011) | 463 calls, 751 s | 0 | 18 / 35 | quote_not_verbatim 9, rule_conflict 9 |
| HANDBOOK crestwood | pipeline_dsv4 | $1.874 (rules $1.814, procedures $0.060) | 501 calls, 537 s | 0 | 25 / 192 | quote_not_verbatim 1, rule_conflict 22, rule_no_trigger 1, unknown_role 1 |
| HANDBOOK vanguard | skill_v1 | made by an agent; not measured | - | - | 0 / 12 | - |
| HANDBOOK vanguard | pipeline_gptoss | $0.181 (rules $0.153, procedures $0.027) | 228 calls, 623 s | 0 | 11 / 2 | quote_not_verbatim 11 |
| HANDBOOK vanguard | pipeline_dsv4 | $0.914 (rules $0.789, procedures $0.125) | 197 calls, 424 s | 0 | 1 / 2 | rule_conflict 1 |
| HANDBOOK careig | skill_v1 | made by an agent; not measured | - | - | 0 / 0 | - |
| HANDBOOK careig | pipeline_gptoss | $0.254 (rules $0.235, procedures $0.019) | 404 calls, 759 s | 0 | 52 / 9 | quote_not_verbatim 51, rule_conflict 1 |
| HANDBOOK careig | pipeline_dsv4 | $1.331 (rules $1.234, procedures $0.097) | 360 calls, 535 s | 0 | 35 / 33 | quote_not_verbatim 1, rule_conflict 24, rule_no_trigger 10 |

Cost of the builds in this table: $6.16. Judge calls are counted in section 8.

## 5. Known pipeline defects, per version

| Document | Source | `quote_not_verbatim` errors | Checks lost to a step (skill hard-rule statements the pipeline made a step only) | Skill hard-rule statements with no outcome in the pipeline | Fragments typed `must` (fewer than 5 words, or starting in lower case) | Threshold rules on a text argument (a number read out of an id or a name) | Rule types that denied the allow tests (tests denied, by type) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tau2 retail | pipeline_gptoss | 0 | 0 of 13 | 0 of 13 | 18 of 65 (0 with no outcome) | 4 | threshold 18 |
| tau2 retail | pipeline_dsv4 | 0 | 0 of 13 | 0 of 13 | 7 of 48 (0 with no outcome) | 3 | reference_status 3, threshold 3 |
| tau2 airline | pipeline_gptoss | 0 | 0 of 2 | 0 of 2 | 21 of 87 (0 with no outcome) | 0 | allowed_values 22, membership 22, record_condition 1 |
| tau2 airline | pipeline_dsv4 | 0 | 0 of 2 | 0 of 2 | 22 of 81 (0 with no outcome) | 0 | record_condition 1, threshold 1 |
| tau2 Telecom | pipeline_gptoss | 0 | 0 of 10 | 0 of 10 | 66 of 171 (0 with no outcome) | 0 | - |
| tau2 Telecom | pipeline_dsv4 | 0 | 0 of 10 | 0 of 10 | 52 of 127 (0 with no outcome) | 0 | role_permission 1 |
| ITSM e2891a7b98 | pipeline_gptoss | 0 | 8 of 55 (4.2:3, 4.2:4, 4.2:5) | 7 of 55 | 5 of 52 (0 with no outcome) | 0 | derived_value 1 |
| ITSM e2891a7b98 | pipeline_dsv4 | 0 | 2 of 55 (6:3, 6:4) | 7 of 55 | 5 of 49 (0 with no outcome) | 0 | derived_value 1, reference_status 8 |
| HANDBOOK crestwood | pipeline_gptoss | 9 | 0 of 11 | 1 of 11 | 128 of 594 (0 with no outcome) | 0 | allowed_values 122, format 133, required_args 81 |
| HANDBOOK crestwood | pipeline_dsv4 | 1 | 0 of 11 | 0 of 11 | 128 of 610 (0 with no outcome) | 1 | allowed_values 149, format 166, required_args 27, role_permission 10, threshold 10 |
| HANDBOOK vanguard | pipeline_gptoss | 11 | 0 of 2 | 0 of 2 | 45 of 266 (0 with no outcome) | 0 | - |
| HANDBOOK vanguard | pipeline_dsv4 | 0 | 0 of 2 | 0 of 2 | 52 of 298 (0 with no outcome) | 2 | allowed_values 21, format 38, threshold 7 |
| HANDBOOK careig | pipeline_gptoss | 51 | 0 of 11 | 0 of 11 | 101 of 424 (0 with no outcome) | 0 | format 157 |
| HANDBOOK careig | pipeline_dsv4 | 1 | 0 of 11 | 0 of 11 | 102 of 429 (0 with no outcome) | 3 | format 261, threshold 62 |

## 5a. What `compile_sop` takes as a procedure, offline

The compiler picks a section as a procedure when at least two of its lines start like `Step 1`, `1.`, `If`, `When`, `Day 1` or `- ` (`STEP_LINE`). It has no pattern for `**Step 1:**` (a bold line start) or for a `*` bullet. The table counts the sections it selects as the file is, with a leading `**` removed from each line, and with `*` bullets also read as `-` (no model call; these two readings are not changes to the compiler). The last column is the characters of the general sections that the call over them drops (`general_text[:40000]`). The first column is what the measures above used; its procedure counts for Crestwood, ITSM and CareIG are tool defects, not what a model can do.

| Document | Skill procedures | As the file is | Leading `**` removed | `*` bullets also read as `-` | General text cut (characters) |
| --- | --- | --- | --- | --- | --- |
| tau2 retail | 6 | 5 | 5 | 5 | 0 |
| tau2 airline | 5 | 7 | 7 | 7 | 0 |
| tau2 Telecom | 9 | 19 | 19 | 24 | 0 |
| ITSM e2891a7b98 | 8 | 0 | 0 | 10 | 0 |
| HANDBOOK crestwood | 26 | 7 | 25 | 25 | 10855 |
| HANDBOOK vanguard | 17 | 20 | 20 | 20 | 0 |
| HANDBOOK careig | 26 | 15 | 16 | 16 | 13722 |

## 6. Tuning status of the documents

| Document | Source | Basis | Why (`audit_report.basis_of`) |
| --- | --- | --- | --- |
| tau2 retail | pipeline_gptoss | unseen, no run | no task set and no change names this policy in the `policies` section of the registry. Note: no run has used this policy (no task set, no change) |
| tau2 retail | pipeline_dsv4 | unseen, no run | no task set and no change names this policy in the `policies` section of the registry. Note: no run has used this policy (no task set, no change) |
| tau2 airline | pipeline_gptoss | seen, not tuned | held-out sets tau2-airline-test (run by aws/gpt-oss-120b, azure/DeepSeek-V4-Pro) (no tuning set and no change names it). Note: the official test split (20 tasks) was run before this package existed: the headroom checks `a20_ds` and `a20_oss`, and the no-harm check of the SOP tracker `air1` (arms A and T, 5 trials, change 87). The runs and the agent writes were reviewed (change 87, `tau2/labels.md`). The result of `air1` (tracker 17/20 against 11/20) is the evidence for design decision 1 of the design spec (route by the shape of the policy source), and Task 5.3 (rule-list route) implements that decision and is checked on this package. The package was made from the policy text only and no rule, test or setting was changed from these runs, but the tasks, the runs and the failures are seen: numbers on this split are not a clean bar |
| tau2 airline | pipeline_dsv4 | seen, not tuned | held-out sets tau2-airline-test (run by aws/gpt-oss-120b, azure/DeepSeek-V4-Pro) (no tuning set and no change names it). Note: the official test split (20 tasks) was run before this package existed: the headroom checks `a20_ds` and `a20_oss`, and the no-harm check of the SOP tracker `air1` (arms A and T, 5 trials, change 87). The runs and the agent writes were reviewed (change 87, `tau2/labels.md`). The result of `air1` (tracker 17/20 against 11/20) is the evidence for design decision 1 of the design spec (route by the shape of the policy source), and Task 5.3 (rule-list route) implements that decision and is checked on this package. The package was made from the policy text only and no rule, test or setting was changed from these runs, but the tasks, the runs and the failures are seen: numbers on this split are not a clean bar |
| tau2 Telecom | pipeline_gptoss | tuning | tuning sets tau2-telecom-dev20; held-out sets tau2-telecom-fresh40 (run by azure/DeepSeek-V4-Pro), tau2-telecom-test (run by aws/gpt-oss-120b, azure/DeepSeek-V4-Pro); the held-out tasks of this policy are not independent of its tuning |
| tau2 Telecom | pipeline_dsv4 | tuning | tuning sets tau2-telecom-dev20; held-out sets tau2-telecom-fresh40 (run by azure/DeepSeek-V4-Pro), tau2-telecom-test (run by aws/gpt-oss-120b, azure/DeepSeek-V4-Pro); the held-out tasks of this policy are not independent of its tuning |
| ITSM e2891a7b98 | pipeline_gptoss | tuning | tuning sets itsm-pilot, itsm-tune; the pipeline was repaired on it in changes 105, 107, 112, 113, 114, 115, 116, 117, 118, 131; held-out sets itsm-unseen (run by aws/gpt-oss-120b, azure/DeepSeek-V4-Pro), itsm-unseen2 (run by azure/DeepSeek-V4-Pro), itsm-unseen3 (run by azure/DeepSeek-V4-Pro); the held-out tasks of this policy are not independent of its tuning |
| ITSM e2891a7b98 | pipeline_dsv4 | tuning | tuning sets itsm-pilot, itsm-tune; the pipeline was repaired on it in changes 105, 107, 112, 113, 114, 115, 116, 117, 118, 131; held-out sets itsm-unseen (run by aws/gpt-oss-120b, azure/DeepSeek-V4-Pro), itsm-unseen2 (run by azure/DeepSeek-V4-Pro), itsm-unseen3 (run by azure/DeepSeek-V4-Pro); the held-out tasks of this policy are not independent of its tuning |
| HANDBOOK crestwood | pipeline_gptoss | tuning | tuning sets handbook-public3 |
| HANDBOOK crestwood | pipeline_dsv4 | tuning | tuning sets handbook-public3 |
| HANDBOOK vanguard | pipeline_gptoss | tuning | tuning sets handbook-public3 |
| HANDBOOK vanguard | pipeline_dsv4 | tuning | tuning sets handbook-public3 |
| HANDBOOK careig | pipeline_gptoss | tuning | tuning sets handbook-public3 |
| HANDBOOK careig | pipeline_dsv4 | tuning | tuning sets handbook-public3 |

## 7. Rule types the skill authors asked for

130 `verify` statements of the packages (one per statement and benchmark; benchmarks: automationbench 47, handbook 29, itsm 14, tau2 40; the three tau2 domains count as one benchmark; AutomationBench is the hand-made gold builds). A model sorted them twice with two readings of one question (section 8 gives its error against a hand check). A kind named by both readings is `wanted`; a kind named by either one is `possible`. A statement can need more than one kind; 28 are named by neither reading for any kind (they need judgment, a sequence of calls, a role or another check). Spec section 4 allows a new type only with statements from at least 2 benchmarks.

Hand correction: `g_a029ae9d66` is taken off `array`. A priority table for meetings ('Meeting has C-level attendee (CTO, CEO, CFO, COO, CIO)', 'Meeting has PRIORITY ...'): a rule about which meeting gets which priority, not a check on a list argument. Both readings of the sorter named `array`; read by hand it is not one. It was the only statement outside tau2 that put `array` over the 2-benchmark bar.

| Missing type | Wanted (both readings) | By benchmark | Meets the bar | Possible (either reading) | Could meet the bar | Examples of wanted |
| --- | --- | --- | --- | --- | --- | --- |
| text_match | 12 | automationbench 7, handbook 2, itsm 1, tau2 2 | yes | 45 (automationbench 22, handbook 14, itsm 1, tau2 8) | yes | automationbench `g_55b15fd05f`: (Customer Type \| Low Max \| Normal Max \| Description \| Notes) standard \| 2 \| 4 \| Standard: <=2 low, 3-4 normal, 5+ high \|<br>automationbench `g_85ef085bb4`: (Customer Type \| Low Max \| Normal Max \| Description \| Notes) trial \| 0 \| 1 \| Trial: 0 low, 1 normal, 2+ high \| Customers |
| when_prefix | 2 | handbook 2 | no | 4 (handbook 4) | no | handbook `r_reply_no_resend`: Replies to previous emails: Treat as a continuation of the existing case. Do not re-send previous templates.<br>handbook `r_reply_no_ticket`: Replies to previous emails: Treat as a continuation of the existing case. Do not create a new ticket. |
| forbid_tool | 1 | handbook 1 | no | 5 (automationbench 2, handbook 2, itsm 1) | yes | handbook `r_no_dm`: Do not use direct messages for case-related communication. |
| array | 10 | tau2 10 | no | 11 (automationbench 1, tau2 10) | yes | tau2 `r_bags_add_only`: The user can add but not remove checked bags.<br>tau2 `r_book_max_passengers`: Each reservation can have at most five passengers. |
| record_compare | 30 | automationbench 4, handbook 4, itsm 10, tau2 12 | yes | 54 (automationbench 19, handbook 10, itsm 11, tau2 14) | yes | automationbench `g_55b15fd05f`: (Customer Type \| Low Max \| Normal Max \| Description \| Notes) standard \| 2 \| 4 \| Standard: <=2 low, 3-4 normal, 5+ high \|<br>automationbench `g_5c336dc546`: (region \| min_registrants \| notes) Americas \| 3 \| (region \| min_registrants \| notes) EMEA \| 4 \| Higher threshold due to  |

## 8. The judge and its error

Recall judge: `aws/gpt-oss-120b` (489 answers kept). Type sorter: `azure/DeepSeek-V4-Pro` (14 answers kept). Their cost is in the ledger under `pipeline_vs_skill_judge`; the answers are in `pipeline_vs_skill_judge.json`, so a re-run asks nothing.

Hand-checked sample: The implementer read each verdict against the texts (must-not: the reference text and the candidates the judge saw; procedure: the skill procedure and the compiled procedures; kinds: the statement). Recall verdicts are `match` or `no_match`. A kinds verdict is the set of missing rule types named; two sets agree when they are equal. Fix round 1 added one must-not case found earlier (a known false match of the first sample) and one correction of the sorter.

Recall verdicts (must-not and procedure): 27 read, the judge agreed with the hand verdict on 23 (85%), error 4 of 27.

| Kind | Checked | Agreed | Error |
| --- | --- | --- | --- |
| kinds (loose) | 22 | 12 | 45% |
| kinds (strict) | 22 | 13 | 41% |
| must-not | 11 | 10 | 9% |
| procedure | 16 | 13 | 19% |

Kinds named by both readings (`wanted`): 6 of 7 also named by hand (precision 86%); 6 of 15 kinds named by hand were found (recall 40%), on 22 statements.

Kinds named by either reading (`possible` and `wanted`): 11 of 19 also named by hand (precision 58%); 11 of 15 kinds named by hand were found (recall 73%), on 22 statements.

Disagreements:

- procedure tau2_retail/retail dsv4: modify-pending-order | judge match, hand no_match. the candidate 'Modify payment' covers one of the three actions of 'Modify pending order' (address, payment, items): narrower
- procedure tau2_telecom/telecom dsv4: troubleshooting-mobile-data-problems | judge no_match, hand match. DeepSeek's graph has 'Diagnosing Mobile Data Issues' (tech_support_manual s16), which is the skill's procedure; the judge did not pick it
- must-not handbook/insurance_vanguard_shield_mutual_9b2f7a29 gptoss: Route to AP for payout only when CLM-910 and CLM-920 are not active, the structured alloca | judge match, hand no_match. added in fix round 1 (a false match known from the first sample, still in the result): the candidate covers one of the three conditions (ambiguous survival); the other two (CLM-910 and CLM-920 active, allocation comment incomplete) are not covered
- procedure handbook/insurance_vanguard_shield_mutual_9b2f7a29 dsv4: 1.3 | judge match, hand no_match. the candidate is an overview of the SOP (section 1.3 of the markdown), not the Jira field conventions; it only names the same fallback once
- kinds (loose) tau2 : r_return_refund: The refund must either go to the original payment method, or an existing  | judge text_match, hand record_compare. 
- kinds (strict) tau2 : r_return_refund: The refund must either go to the original payment method, or an existing  | judge text_match, hand record_compare. 
- kinds (loose) tau2 : r_same_passenger_count: The user can modify passengers but cannot modify the number of pas | judge array, hand array, record_compare. 
- kinds (strict) tau2 : r_same_passenger_count: The user can modify passengers but cannot modify the number of pas | judge array, hand array, record_compare. 
- kinds (loose) tau2 : r_comp_eligible: Do not compensate if the user is regular member and has no travel insuran | judge record_compare, text_match, hand record_compare. 
- kinds (strict) tau2 : r_comp_eligible: Do not compensate if the user is regular member and has no travel insuran | judge none, hand record_compare. 
- kinds (loose) itsm : r_approvals: Agent (agent): Cannot bypass approvals. Manager (manager): Can approve/reject | judge forbid_tool, hand none. 
- kinds (loose) handbook : r_p1_p2_no_move: P1 / P2 emails | Leave in Inbox. Flag as important. Do NOT move to a fold | judge text_match, when_prefix, hand none. 
- kinds (loose) handbook : v_4_3_7: Do not respond to legal threats or attorney communications — post to #compliance  | judge text_match, hand none. 
- kinds (loose) handbook : v_3_13: Template files | Blank form masters — copy to docs/ before use, never edit in plac | judge none, hand text_match. 
- kinds (strict) handbook : v_3_13: Template files | Blank form masters — copy to docs/ before use, never edit in plac | judge none, hand text_match. 
- kinds (strict) automationbench : g_2ab01d0974: Only amortize items where the current date falls within the coverage period | judge none, hand record_compare. 
- kinds (loose) automationbench : g_a4c153044e: Correction on the Software License prepaid: the total should be $7,200 not $ | judge record_compare, hand none. 
- kinds (loose) automationbench : g_ed7e3efa54: POSITIVE mentions (praise, recommendations, upgrades): Like the tweet. | judge text_match, hand none. 
- kinds (strict) automationbench : g_8bf291eb05: Only add topics with meaningful growth (at least 50% increase) | judge none, hand record_compare. 
- kinds (strict) automationbench : g_2e0e79c964: The 50% growth threshold from Content Ops still applies as a secondary filte | judge none, hand record_compare. 
- kinds (loose) automationbench : g_9c357324e1: (Rule | Condition | Action | Notes) Event window | Count feature_use events  | judge none, hand record_compare. 
- kinds (strict) automationbench : g_9c357324e1: (Rule | Condition | Action | Notes) Event window | Count feature_use events  | judge none, hand record_compare. 
- kinds (strict) automationbench : g_eb61017d98: (Policy | Condition | Action | Notes) Stale trial override | Customer tagged | judge none, hand record_compare. 
<!-- tables:end -->

## Reading

**By the bar, no benchmark can switch today.** Every row of section 1 is `no`. The three conditions fail in different ways, and two of them say less than they appear to:

- **False denies are the main failure.** The pipeline's code rules deny good calls on every benchmark. Where they exist, most come from a few rule types (section 5): a `threshold` rule on a text argument (retail: "Exchange or modify order tools can only be called once per order" became a limit of 1 on `order_id`, and the number read from `#W1000001` is above it: the 18 false denies of gpt-oss; the validator accepts a threshold on a string), `format`, `allowed_values` and `required_args` rules on HANDBOOK, `membership` and `allowed_values` on airline, and `reference_status` on `update_problem` in DeepSeek's ITSM build (8 of its 9 false denies: a record property that binds creation is applied to a partial update). Each denied allow test is one call a good agent would make. The skill packages have 0 false denies on all seven documents.
- **The catches condition is empty on 4 of 7 documents.** The check is one-sided: the pipeline must be not more than 5 points below the skill. On Crestwood, Vanguard, CareIG and airline the skill catches under 5% of the deny tests, so the threshold is zero or less and an empty package passes. Table 2 marks those rows. The reason is not the schema: most deny tests there are on statements that a rule on one call cannot decide (section 3b): on Crestwood 184 of 345 are on obligations or steps and 95 on statements with no outcome; on Vanguard 64 of 72 (53 on obligations or steps, 11 with no outcome; the 201 tests that the tool patterns reject are apart and not in the 72); on CareIG 268 of 345. The bar therefore says little on HANDBOOK: with the condition empty, the verdict rests on false denies and must-not recall alone.
- **Rules do not separate catches from over-denying.** Where the pipeline "catches" many deny tests it denies as many allow tests (table 2, the two columns next to each other): Crestwood with DeepSeek 74.2% against 74.4%, CareIG with gpt-oss 49.6% against 52.0%, Vanguard with DeepSeek 63.9% against 65.5%, airline with gpt-oss 47.4% against 46.9%. Those rules deny nearly every call to the tool. Only ITSM, where the pipeline has been repaired for many rounds, has catches near the skill (82 and 83 of 162 against 86) with a low share of allow tests denied (0.7% and 6.1%).
- **Must-not recall mostly measures the builder, not the compiler.** At least 80% on 7 of 14 rows (section 2), but pool `A` includes the builder's exception and precondition quotes, which often repeat the statement the skill used. Section 3a: ITSM with gpt-oss reaches 3 of 3 and Crestwood with gpt-oss 16 of 20, and neither has one match through a compiler `must_not` list (retail with gpt-oss: 7 of 14, 0 through the compiler). Vanguard with gpt-oss has 11 of its 25 through the compiler's lists and CareIG with gpt-oss 5 of 19; the compiler column is a floor (a judge match may name a builder text when a compiler text also fits). Most pipeline must-nots match no skill text: Vanguard with gpt-oss has 136 texts in pool `A` and 24 matched (51 compiler texts, 11 matched). So what `procedure_compiler.py` can do on must-nots is not isolated by these figures; read recall `A` as the pipeline's, with the builder inside it. The earlier explanation (missing compiler procedures) was wrong for ITSM, which reaches 100% with none.
- **The judge sample is small.** One false match is known in the 11 must-not verdicts I read: "Route to AP for payout only when CLM-910 and CLM-920 are not active, ..." was matched to a text that covers one of three conditions (Vanguard, gpt-oss; 24 of 30 would still be 80%). Crestwood with gpt-oss sits exactly at 16 of 20: one wrong match gives 75% and the condition flips. A recall figure of one item either way can change a `met`.
- **Passed runs.** Airline: gpt-oss and DeepSeek deny 8 and 9 of 43 passed runs; the skill denies 0. Vanguard: both pipelines deny 2 of the 2 passed runs; the skill 0. ITSM: gpt-oss 2 of 93 (as the skill), DeepSeek 7 of 93. HANDBOOK Crestwood and CareIG have no passed run, so only the tests speak there.

**The nearest rows, and why none is a "yes".**

- **ITSM with gpt-oss misses on one test, and the test is contestable.** The one false deny of 147 is the `allow` test `update_incident {incident_id: INC001, priority: moderate}` (statement `itsm-e2891a7b98:9:2`, an id of the older split). Its record holds priority `high` and no impact or urgency; the test writer's reason is "Priority 'moderate' is in the allowed list; agent has CRUD on incidents and is the assignee". The pipeline's `derived_value` rule denies it: "`priority` is computed from impact, urgency, which are not known for this call". The policy says priority "is determined automatically by the system based on a below pre-defined matrix of Impact x Urgency", and the sibling `deny` test (`itsm-e2891a7b98:6:1`, priority `low` on a medium x medium record) is labelled a deny because "manually overriding priority ... contradicts the automatic alignment". Reading 1 (test writer): the value is valid and the agent may update the incident, so allow. Reading 2 (sibling test): any manual write of priority contradicts a system-determined value, so the allow label is wrong and the pipeline is right. Spec section 9 adds that a record property binds creation, not partial updates, which favors reading 1 for an update that does not touch impact or urgency. The label is not changed. **Open question** for the policy owner: may the agent write `priority` on an update? A package with a `policy_question` on it is the place; the skill package has priority questions already (6 to 8 per ITSM version). Read as a deny, gpt-oss would meet all three conditions on ITSM. That would not mean the pipeline is ready: ITSM is a `tuning` document (ten repair changes), the compiler made 0 procedures there (the skill has 8), the builder's procedures recall 3 of 8, 8 of the 55 statements that the skill enforces with a hard rule are lost to a step, and its 3 of 3 must-nots are builder texts. The DeepSeek build of ITSM has 9 false denies, 8 of them `reference_status` on `update_problem`.
- **Airline with DeepSeek misses only false denies: 2 of 49.** Catches cannot fail there, must-nots are 93%, and the two false denies are one `record_condition` and one `threshold` (section 5). It also denies 9 of 43 passed runs where the skill denies none. The result is one run of a model that may not be deterministic, so a second run could move the verdict either way; airline is `seen, not tuned` (tasks and failures seen), so it is not a clean bar.
- **Vanguard with gpt-oss meets all three conditions and is not a "yes".** It has 11 `validate` errors (`quote_not_verbatim`) and 2 of the 2 passed runs denied. Only 72 deny tests reach the rule layer (201 of 331 use names that the tool patterns reject), and of those 64 are on obligations, steps or statements with no outcome (section 3b), so there is little for a call rule to catch or to deny: its catches (1 of 72) equal the skill's.
- **DeepSeek-V4-Pro does not repair the pipeline's false denies.** It costs about 5 times more than gpt-oss at list price (section 4), makes fewer false denies on retail and airline and more on Telecom, ITSM and HANDBOOK, and has more `rule_conflict` warnings (retail, Crestwood, CareIG). The model is not the cause; the rule types and the validator are.

**Procedures: the compiler's procedure counts are a tool defect, not a measure of the model.** `compile_sop` picks a section as a procedure by a line pattern (`_is_procedure`: at least two lines that match `STEP_LINE`, which has patterns for `Step 1`, `1.`, `Day 1`, `If`, `When`, `Upon`, `Before`, `After` and `- ` and none for a bold line start such as `**Step 1:**` or for a `*` bullet). Section 5a counts offline what it would take with two small readings (no change was made):

| Document | As the file is | Leading `**` removed | `*` bullets also read as `-` | Skill |
|---|---|---|---|---|
| Crestwood | 7 | 25 | 25 | 26 |
| ITSM | 0 | 0 | 10 | 8 |
| CareIG | 15 | 16 | 16 | 26 |
| Vanguard | 20 | 20 | 20 | 17 |

The Crestwood procedure row (7 of 26) and the ITSM row (0 of 8) are tool defects: with a bold line start allowed Crestwood has 25, and with `*` read as `-` ITSM has 10. CareIG's gap (15 against 26) is partly the same and partly something else. Also `general_text[:40000]` drops 10,855 characters of the general sections on Crestwood and 13,722 on CareIG, so their general rules are cut. These numbers do not measure what the model can do on procedures. No compiler fix and no re-run was made in this plan: a re-run is under $0.50 and would not change a verdict. In retail the compiler takes definition sections (`User`, `Product`) and misses `Return delivered order` and `Cancel pending order`. Where the pattern works (Vanguard: 17 of 17 and 16 of 17 recalled, airline 5 of 5 and 3 of 5), the step text is the SOP's own. The builder's procedures (step graphs from numbered statements) recall fewer: 13 of 26 for Crestwood and 0 for the three tau2 documents. No model call failed in the 14 builds (0 failed calls).

**Known pipeline defects, per version (section 5), reported and not fixed.**

- `quote_not_verbatim`: the model shortens a quote with "...". Mostly gpt-oss on HANDBOOK (Crestwood 9, Vanguard 11, CareIG 51); DeepSeek 1, 0 and 1. None on tau2 or ITSM in these builds.
- A step that carries a checkable value and has no enforcement: ITSM, gpt-oss 8 of the 55 statements the skill enforces with a hard rule (including `4.2:3`, `4.2:4`, `4.2:5`, the Task 3.1 case), DeepSeek 2 (`6:3`, `6:4`). None on the other documents.
- Classifier fragments typed `must` (table cells and list items such as `unique order id`): 18 of 65 typed-must statements on retail with gpt-oss, up to 128 of 594 on Crestwood; none stays without an outcome, so `validate` does not flag them (they reach the rule model as statements).
- Seen in this task (section 5): `threshold` rules on a text argument (retail 4 with gpt-oss and 3 with DeepSeek; CareIG 3, Vanguard 2 and Crestwood 1 with DeepSeek) and `unknown_role` errors in DeepSeek's builds of retail (6), airline (3) and Crestwood (1): a role rule for a role the policy does not name.

**Tuning status.** ITSM `e2891a7b98` is `tuning`: the pipeline was repaired on it in ten changes, so its numbers are the pipeline's best case. Telecom and the three HANDBOOK SOPs are `tuning` (a tuning set names them). Airline is `seen, not tuned` (tasks and failures seen; the pipeline and the package were not changed from them). Retail is `unseen, no run`, the one clean document for the pipeline: it has no run, so only the tests speak. That label ends when a fix derived from retail ships (for example the threshold-on-text rule above): after that, retail is a tuning document for the pipeline. The skill packages carry the same labels. No document here is held-out.

**Rule types the authors asked for (section 7).** Counts are from a model that sorted the `verify` statements twice; against my hand check on 22 statements, a kind named by both readings was right 6 of 7 times and found 6 of 15 hand-named kinds; a kind named by either reading found 11 of 15 and was right 11 of 19. So `wanted` is a floor with high precision and `possible` a ceiling. One hand correction was made: both readings named `array` for AutomationBench `g_a029ae9d66`, a meeting priority table and not a check on a list argument; without it arrays are tau2 only. Hand reading of the statements behind the types:

| Type | Meets spec section 4 (statements from at least 2 benchmarks) | Hand-confirmed statements |
|---|---|---|
| text contains or does not contain | Yes | Vanguard `r_slack_no_wire_details` and `r_a1_needs_pdf` (Template A-1 named in the body), ITSM `r_incident_severe_default` (words in the description), AutomationBench `g_a234306475` (competitor names), `g_fc866e139a` (exact batch code) |
| arrays and counts | **No** | tau2 only: airline `r_book_max_passengers` (at most five), `r_book_payment_counts`, `r_bags_add_only`. The sorter's "yes" rested on one misread statement (`g_a029ae9d66`). The one other candidate of the looser reading, AutomationBench `g_c879ff01b6` (an open ticket needs at least one tag), is a hand-made gold table row and was not confirmed. Spec section 4 keeps arrays as judgment rules |
| comparison with a record | Yes | tau2 `r_payment_gift_card` (balance covers the total), `r_items_same_product`; ITSM `r_problem_close`; CareIG `v_4_3_2` (`Drug_Source` is not CareIG); AutomationBench `g_8bf291eb05` (growth at least 50%) |
| prefix in `when` | No | only Crestwood `r_reply_no_ticket` and `r_reply_no_resend` (a reply to a previous e-mail) |
| forbid a tool outright | No | only Crestwood `r_no_dm`; the AutomationBench candidates (`g_c58d03cbd0`, `g_23568b776c`) are conditional on who asks, on a generic sheet tool |

At the floor, text contains and comparison with a record hold. No type was added. The bar is a count of statements across benchmarks; whether a new type pays for itself (how many of its statements a rule would then catch without false denies) is not measured here, and the false-deny finding above argues for fixing the existing types first.

## Limits

- One run per document and model. gpt-oss on the AWS route is deterministic (T is ignored), DeepSeek may not be; no second run was made, and the airline DeepSeek verdict rests on one.
- The judge's error on recall in the hand sample (section 8): procedures 3 of 16 (two false matches, one missed match), about one in five, so a procedure-recall figure is soft by that much; must-nots 1 of 11 (the known false match above). Both samples are small, and a single must-not decides `met` or `missed` on Crestwood. The type sorter is weak (error 41% and 45% by exact set); read section 7 as counts with a floor and a ceiling.
- Must-not recall is measured against the skill's must-nots, which come from the same agent that wrote the skill package: it measures agreement with the skill, not completeness against the text. Its pool mixes the compiler's and the builder's texts (section 3a).
- HANDBOOK has 2 passed runs in 165, so passed-run denies say little. The ITSM tests carry statement ids of an older split (0 of 347 exist), which affects only per-statement views; the lost-check and outcome counts of ITSM use the new ids of the packages.
- The `tau2` documents have `verify`-heavy skill packages (airline 22 of 29 rules): the skill's catches there are low by design, so the one-sided catches condition cannot fail on airline and favors the pipeline whenever it over-denies.
- Pipeline procedures from the compiler are in the store-graph shape (strings), the skill's in the package shape (steps with ids and actions): recall compares texts, not runtime behavior.
- No runtime check of the pipeline packages was run (`runtime_check.py` covers `skill_v1`).
