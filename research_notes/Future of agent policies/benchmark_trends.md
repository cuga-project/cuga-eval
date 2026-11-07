# Benchmark trends: is frontier model adherence to written policies and SOPs improving, and how fast?

Date of this research: 2026-11-05. All leaderboard pages were read on this date. "pts" means percentage points.

Labels for who ran a number:
- **Vendor**: the company that made the model ran it.
- **Owner**: the company that made the benchmark ran it (Sierra, Surge, Zapier, ServiceNow).
- **Independent**: a third party ran it (Artificial Analysis, called AA below, or academic authors).

Numbers marked [calc] are my own calculation from the cited data. For AA, per-model values come from data embedded in the AA web pages. These pages hold 58 to 60 models, not the full lists (for example 243 models on AutomationBench-AA). The embedded models are the ones AA selected for its charts, so they are not a random sample.

## What were the best scores at launch and now, on which dates, by which models?

### Takeaway
Scores on the harder benchmarks rose quickly in 2026. The two series with one fixed harness show about 2.3 to 5.8 pts per month, but most tasks are still not fully solved: the best scores are about 51 to 55% on τ³ banking, EnterpriseOps-Gym and strict AutomationBench. A clean trend can be measured only on Sierra's τ³ series, on AA's τ³ series and inside AA's current AutomationBench-AA snapshot. Launch-to-now comparisons on HANDBOOK.md, EnterpriseOps-Gym, official AutomationBench and τ-bench or τ²-bench mix in changes to the benchmark or harness, so they are not a model trend.

### Cited Findings

**Summary: launch versus now**

| Benchmark | Launch best (date, model, score, who ran) | Best now (read 2026-11-05) | Can launch and now be compared? |
|---|---|---|---|
| τ-bench | 2024-06-17, gpt-4o: retail 61.2, airline 35.2 (Owner) — [paper](https://arxiv.org/pdf/2406.12045) | Last Vendor rows: Claude Sonnet 4.5, 2025-09-29: retail 86.2, airline 70.0 (Vendor, unverified) — [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions) | No. Prompts, step limits and dataset changed |
| τ²-bench | 2025-06-09: airline Claude 3.7 Sonnet 64.2; retail GPT-4.1 74.0; telecom o4-mini 50.2 (Owner) — [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions) | v1.0.1, Feb to Mar 2026: airline Claude Opus 4.5 84.0; retail Qwen3.5-397B 84.4; telecom Qwen3.5-397B 97.8 (Owner) — [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions) | No. 53 airline and retail tasks were fixed in v1.0.0, and the user simulator changed |
| τ³ banking | 2026-03-04, GPT-5.2 high, terminal search: 25.52 pass^1 (Owner, old grader) — [paper](https://arxiv.org/html/2603.04370) | Qwen 3.8 Max 55.2 pass^1 (Owner, v1.0.1) — [taubench](https://taubench.com); Qwen3.8 Max 51.3 (Independent) — [AA](https://artificialanalysis.ai/evaluations/tau3-banking) | Not across the v1.0.1 grading change. Yes inside the re-graded series below |
| HANDBOOK.md | 2026-06-25: top cluster 21.5 to 21.9, Claude Opus 4.8 max highest (Owner) — [paper](https://arxiv.org/html/2607.25398) | Claude Opus 5.5 Adaptive/Max 52.3, metric not labelled (Owner) — [Surge board](https://surgehq.ai/benchmarks/handbook) | June to July yes. July to November not shown to be comparable (see below) |
| EnterpriseOps-Gym | 2026-03-13, Claude Opus 4.5: 37.4 (Owner) — [paper](https://arxiv.org/abs/2603.13594) | Claude Fable 5 max: 51.1 (Independent) — [AA](https://artificialanalysis.ai/evaluations/enterprise-ops-gym-aa) | No. Different harness |
| AutomationBench (official, strict) | 2026-04-21, Claude Opus 4.7 max: 9.9 (Owner) — [paper](https://arxiv.org/html/2604.18934) | Gemini 4 Carbon High: 53.88, v1.0.6 (Owner) — [Zapier board](https://zapier.com/benchmarks) | Not shown to be comparable. Tasks were fixed and private tasks changed |
| AutomationBench-AA | 2026-07-06: Claude Fable 5 max 48.6, Claude Opus 4.8 max 48.5 (Independent) — [AA launch](https://artificialanalysis.ai/articles/announcing-zapier-automationbench-aa) | Gemini 4 Carbon High 77.8 (Independent) — [AA](https://artificialanalysis.ai/evaluations/automationbench-aa) | Not across dates. Same-model rows moved between launch and now. Comparable inside the current snapshot only |

**τ-bench (original). Mostly Vendor. Not one harness, so no trend line should be drawn.**

| Date | Model | Retail | Airline | Who ran | Notes | Source |
|---|---|---|---|---|---|---|
| 2024-06-17 | gpt-4o | 61.2 | 35.2 | Owner | Claude 3 Opus was 44.2 and 34.7 in the same table | [paper](https://arxiv.org/pdf/2406.12045) |
| 2024-10-22 | Claude 3.5 Sonnet (new) | 69.2 | 46.0 | Vendor | Previous version: 62.6 and 36.0 | [Anthropic](https://www.anthropic.com/news/3-5-models-and-computer-use) |
| 2025-02-24 | Claude 3.7 Sonnet | 81.2 | 58.4 | Vendor | Airline used a prompt addendum, maximum steps went from 30 to 100, and the 3.5 score was re-run on an updated dataset | [Anthropic](https://www.anthropic.com/news/claude-3-7-sonnet); numbers from [LLM Stats retail](https://llm-stats.com/benchmarks/tau-bench-retail) and [airline](https://llm-stats.com/benchmarks/tau-bench-airline), which mark them self-reported |
| 2025-05-22 | Claude Opus 4 | 81.4 | 59.6 | Vendor | | [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions) |
| 2025-08-05 | Claude Opus 4.1 | 82.4 | 56.0 | Vendor | | [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions) |
| 2025-09-29 | Claude Sonnet 4.5 | 86.2 | 70.0 | Vendor | Prompt addendum used. Sierra marks it unverified | [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions) |

Conflict: LLM Stats lists gpt-4o at airline 42.8 and retail 60.3, while the paper gives 35.2 and 61.2 — [LLM Stats](https://llm-stats.com/benchmarks/tau-bench-airline); [paper](https://arxiv.org/pdf/2406.12045).

**τ²-bench. pass^1 (pass^4 in brackets), all from the [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions).**

| Domain | Launch, 2025-06-09 (Owner) | Best on v0.1.3, 2025 to Jan 2026 | Best on v1.0.1, submitted Feb to Mar 2026 (Owner) |
|---|---|---|---|
| Airline | Claude 3.7 Sonnet 64.2 (52.1) | Gemini 3.0 Pro 73.0, 2025-11-18, no pass^k, the model also played the user simulator; Qwen3-Max-Thinking-Preview 71.0 (60.0), 2025-10-30, Vendor | Claude Opus 4.5 high 84.0 (70.0); GPT-5.2 high 83.0 (72.0) |
| Retail | GPT-4.1 74.0 (52.3) | Claude Sonnet 4.5 86.2, 2025-09-29, Vendor, unverified | Qwen3.5-397B 84.4 (59.6) |
| Telecom | o4-mini 50.2 (32.4) | Qwen3-Max-Thinking 98.2 (93.9), 2026-01-23, Vendor | Qwen3.5-397B 97.8 (92.1) |

- taubench.com shows Qwen3.5-397B-A17B 87.9, Gemini 3.0 Pro 85.4 and Claude Opus 4.5 85.3 as the top three on τ²-bench — [taubench](https://taubench.com). [calc] These are averages of the three domains, and the Gemini row is from v0.1.3 while the other two are from v1.0.1, so the top three mixes versions.
- Sierra's August 2026 batch ran `banking_knowledge` only, with empty τ² domains. The last τ² text row that I found is a custom retail entry from 2026-04-30 — [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions). So the τ² frontier cannot be measured after March 2026.
- Data quality warnings in the Sierra files: the GPT-5 and Qwen3-Max-Thinking-Preview telecom rows have identical numbers (95.8, 92.0, 88.4, 85.1). The Qwen3-Max row is dated 2024-09-23 while its model release field says 2025-09-23 — [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions).

**τ³ banking. The best controlled series found.** Owner-run, 97 tasks, AllTools retrieval, GPT-5.2 low user simulator, 4 trials, re-graded under v1.0.1. Sierra ran the models in 2026; the table orders them by model release date, not run date — [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions). Effort is not held constant.

| Model release | Model (effort) | pass^1 | pass^4 | pass^4 / pass^1 [calc] |
|---|---|---|---|---|
| 2025-06-17 | Gemini 2.5 Pro (high) | 13.7 | 1.0 | 0.08 |
| 2025-11-24 | Claude Opus 4.5 (high) | 24.7 | 11.3 | 0.46 |
| 2025-12-11 | GPT-5.2 (high) | 32.2 | 18.6 | 0.58 |
| 2026-02-05 | Claude Opus 4.6 (max) | 27.3 | 11.3 | 0.42 |
| 2026-03-05 | GPT-5.4 (xhigh) | 39.4 | 21.6 | 0.55 |
| 2026-04-16 | Claude Opus 4.7 (max) | 40.2 | 24.7 | 0.62 |
| 2026-04-23 | GPT-5.5 (xhigh) | 44.6 | 29.9 | 0.67 |
| 2026-05-28 | Claude Opus 4.8 (max) | 39.7 | 22.7 | 0.57 |
| 2026-06-09 | Claude Fable 5 (max) | 39.7 | 28.9 | 0.73 |
| 2026-07-09 | GPT-5.6 Sol (xhigh) | 46.9 | 27.8 | 0.59 |
| 2026-07-16 | Grok 4.5 (high) | 47.9 | 32.0 | 0.67 |
| 2026-07-19 | Qwen 3.8 Max (xhigh) | 55.2 | 35.1 | 0.64 |
| 2026-07-24 | Claude Opus 5 (max) | 48.7 | 32.0 | 0.66 |

- [calc] Best so far from 2025-11-24 to 2026-07-19: pass^1 +30.5 pts (about 3.9 pts per month), pass^4 +23.8 pts (about 3.1 pts per month). The series is not smooth: Claude Opus 4.8 and Fable 5 did not beat Claude Opus 4.7 or GPT-5.5 on pass^1.
- The last standard text submission is dated 2026-08-04, so GPT-6, Claude Opus 5.5 and Gemini 4 have no Sierra rows — [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions).
- Independent series, AA, best so far by release date: Gemini 3.1 Pro Preview 21.4 (2026-02-19), GPT-5.4 39.6 (2026-03-05), Grok 4.5 42.1 (2026-07-08), GPT-5.6 Sol 44.3 (2026-07-09), Kimi K3 46.0 (2026-07-16), Qwen3.8 Max 51.3 (2026-08-03) — [AA](https://artificialanalysis.ai/evaluations/tau3-banking). [calc] From March to August: +11.7 pts in 5 months, about 2.3 pts per month. AA also moved to the v1.0.1 dataset and grader in Aug to Sep 2026 — [AA methodology](https://artificialanalysis.ai/methodology/intelligence-benchmarking).
- AA's top three are still Qwen3.8 Max 51.3, Grok 4.6 50.7 and Muse Spark 1.3 50.5 — [AA](https://artificialanalysis.ai/evaluations/tau3-banking). GPT-6 Astra (2026-09-03) has 41.4 in the same data. AA says it still runs τ³ on new models — [AA methodology](https://artificialanalysis.ai/methodology/intelligence-benchmarking). The embedded data has no τ³ value for any model released after 2026-09-11.
- Same model, Owner versus Independent (Sierra / AA) [calc from the sources above]: GPT-5.4 39.4 / 39.6; Claude Fable 5 39.7 / 38.1; Claude Opus 5 48.7 / 42.1; GPT-5.5 44.6 / 39.0; Claude Opus 4.8 39.7 / 34.2; Grok 4.5 47.9 / 42.1; Kimi K3 37.1 / 46.0. Most gaps are about 2 to 7 pts with Sierra higher; GPT-5.4 is about equal and Kimi K3 goes the other way by about 9 pts. GPT-5.6 Sol and Qwen 3.8 Max were run at different effort labels, so I did not pair them.
- Release dates differ between sources: Qwen 3.8 Max is 2026-07-19 in the Sierra file and 2026-08-03 at AA; Grok 4.5 is 2026-07-16 and 2026-07-08.

**HANDBOOK.md. All Owner-run, 65 tasks, 4 trials per task, OpenHands harness.**

| Date | Source of the number | Top entries | Note |
|---|---|---|---|
| 2026-06-25 | [Paper](https://arxiv.org/html/2607.25398), describing the June release of 20 configurations | Claude Opus 4.8 max and GPT-5.5 at 21.5 to 21.9 strict pass@1 | No model above 25% |
| July 2026, paper v1 on 2026-07-28 | [Paper Table 2](https://arxiv.org/html/2607.25398), 30 configurations | Claude Fable 5 adaptive/max 36.2; Claude Fable 5 34.2; GPT-5.6 Sol max 23.5; Claude Opus 4.8 adaptive/max 21.9; GPT-5.5 21.5 | Same harness and metric as June |
| Read 2026-11-05 | [Surge board](https://surgehq.ai/benchmarks/handbook) | Claude Opus 5.5 52.3; Claude Sonnet 5.5 47.7; Claude Fable 5.1 47.1; Grok 4.7 44.0; Gemini 4 Argon 36.6; Muse Spark 1.3 33.9; GPT 6 Astra 31.4; Qwen 3.8 Max 30.8; GLM 5.3 29.9; Muse Wonder 29.5; Kimi K3 28.6; GPT 6.1 Sol 28.6; Gemini 3.8 Flash 26.5; Hy4 Preview 24.3 | Metric is not labelled and no date is given |

- Date note: the Surge blog page shows both June 25, 2026 and October 22, 2026 without labels. I use June 25 as the release date because the paper places the first release in June 2026.
- **Comparability warning.** Kimi K3 (max) is 11.9 in the [July paper](https://arxiv.org/html/2607.25398) and 28.6 on the [current board](https://surgehq.ai/benchmarks/handbook), which is +16.7 pts [calc] for what looks like the same configuration. It is the only same-model pair I could check. So the rise from 36.2 to 52.3 cannot be read as model progress until Surge explains the board.
- Surge's blog summary, with an October 22, 2026 date on the page, still says no frontier model clears 25% — [Surge blog](https://surgehq.ai/blog/handbook-md). That conflicts with its own paper (36.2) and board (52.3).
- The paper reports no per-model figures on prohibited actions, even though 232 of 824 criteria check incorrect behavior — [paper](https://arxiv.org/html/2607.25398).

**EnterpriseOps-Gym.**

| Date | Who ran | Harness and tasks | Top scores | Source |
|---|---|---|---|---|
| 2026-03-13 | Owner | Oracle tool mode, 1,150 tasks | Claude Opus 4.5 37.4; Gemini-3-Flash 31.9; GPT-5.2 High 31.8; Claude Sonnet 4.5 30.9; GPT-5 29.8; best open model DeepSeek-V3.2 High 24.5 | [paper PDF](https://arxiv.org/pdf/2603.13594) |
| 2026-07-08 | Independent | Stirrup harness, 1,117 oracle-mode tasks | Claude Fable 5 max 51; Gemini 3.5 Flash high 50; GPT-5.5 xhigh 47; Claude Opus 4.8 max 44; GLM-5.2 max 43 | [AA launch](https://artificialanalysis.ai/articles/announcing-enterpriseops-gym-aa) |
| Read 2026-11-05 | Independent | Stirrup, oracle tools, 3 repeats, 100-turn cap, 27 of 50 models shown | Claude Fable 5 (Max, Opus 4.8 Fallback) 51.1; Gemini 3.7 Flash Medium 50.4; Gemini 3.5 Flash High 50.1 | [AA](https://artificialanalysis.ai/evaluations/enterprise-ops-gym-aa) |

- AA best so far by release date: Gemini 3.1 Pro Preview 42.2 (2026-02-19), GPT-5.5 46.6 (2026-04-23), Gemini 3.5 Flash 50.1 (2026-05-19), Claude Fable 5 51.1 (2026-06-09). There has been no new high since — [AA](https://artificialanalysis.ai/evaluations/enterprise-ops-gym-aa).
- Newer models on AA are below the top: Grok 4.6 48.3, Qwen3.8 Max (0902) 47.6, Claude Opus 5 max 47.5, Step 5 Preview 47.2, GPT-5.6 Sol 42.9, GLM-5.3 36.4 — [AA](https://artificialanalysis.ai/evaluations/enterprise-ops-gym-aa). The embedded data has no row for GPT-6, Claude Opus 5.5 or Gemini 4.
- Policy-heavy domains, paper (March 2026): best ITSM 28.5 (Gemini-3-Flash) and best HR 32.1 (Claude Opus 4.5) — [paper PDF](https://arxiv.org/pdf/2603.13594). AA now: best ITSM 50.3 (Gemini 3.7 Flash) and best HR 50.0 (Claude Fable 5) — [AA](https://artificialanalysis.ai/evaluations/enterprise-ops-gym-aa). These are from different harnesses.

**AutomationBench. Four numbers exist for the same model, so state the metric each time.**

| Metric | Who ran | What it is | Date | Top scores | Source |
|---|---|---|---|---|---|
| Launch, strict | Owner | One run, no partial credit, 50-step limit | 2026-04-21 | Claude Opus 4.7 max 9.9; Gemini 3.1 Pro high 9.6; GPT 5.4 high 7.6; Claude Sonnet 4.6 max 5.3 | [paper](https://arxiv.org/html/2604.18934) |
| Official board, strict | Owner | Private held-out set, v1.0.6 | Read 2026-11-05, no per-row date | Gemini 4 Carbon High 53.88; Gemini 4 Argon High 51.29; Claude Sonnet 5.5 44.75; Claude Opus 5.5 42.47; GPT-6 Astra Max 41.40 | [Zapier](https://zapier.com/benchmarks) |
| Public set, strict | Owner | Public 600 tasks | README, no run dates | Claude Opus 5 max 50.3; Kimi K3 46.67; Claude Fable 5 46.17; GPT-5.6 Sol 45.83 | [GitHub](https://github.com/zapier/AutomationBench) |
| AA headline | Independent | Share of objectives, with any guardrail violation zeroing that task; private 657 tasks from dataset v1.0.6 | 2026-07-06 launch; read 2026-11-05 | Launch: Claude Fable 5 48.6; Claude Opus 4.8 48.5; Gemini 3.5 Flash 42.6; GPT-5.5 42.1. Now: Gemini 4 Carbon High 77.8; Gemini 4 Carbon Medium 77.6; Gemini 4 Argon High 77.5 | [AA launch](https://artificialanalysis.ai/articles/announcing-zapier-automationbench-aa); [AA](https://artificialanalysis.ai/evaluations/automationbench-aa); [AA methodology](https://artificialanalysis.ai/methodology/intelligence-benchmarking) |

- AA headline, current snapshot, best so far by release date (selected steps): Gemini 3.1 Pro Preview 35.4 (2026-02-19), GPT-5.5 47.3 (2026-04-23), Claude Fable 5 54.1 (2026-06-09), GPT-5.6 Sol 60.1 (2026-07-09), Grok 4.6 66.7 (2026-08-12), GPT-6 Astra 68.5 (2026-09-03), Claude Sonnet 5.5 71.8 (2026-09-28), Gemini 4 Argon 77.5 (2026-09-30), Gemini 4 Carbon 77.8 (2026-10-28) — [AA](https://artificialanalysis.ai/evaluations/automationbench-aa). [calc] From April to October: +30.5 pts in 6.2 months, about 4.9 pts per month. AA's strict score over the same period went from 19.6 to 55.3, about 5.8 pts per month.
- AA's strict score closely matches Zapier's official score (AA / Zapier) [calc]: GPT-6 Astra Max 41.6 / 41.40; Claude Sonnet 5.5 45.5 / 44.75; Claude Opus 5.5 41.2 / 42.47; Gemini 4 Argon High 53.1 / 51.29; Gemini 4 Carbon High 55.3 / 53.88 — [AA](https://artificialanalysis.ai/evaluations/automationbench-aa); [Zapier](https://zapier.com/benchmarks). This is useful independent support for the official numbers.
- Same model, four numbers, Claude Opus 5 max: AA headline 56.6, AA strict 28.3 — [AA](https://artificialanalysis.ai/evaluations/automationbench-aa); official strict 26.9 — [Anthropic](https://www.anthropic.com/news/claude-opus-5-5); public-set strict 50.3 — [GitHub](https://github.com/zapier/AutomationBench).
- Claude Opus 5.5 scored 40.0 in the table published by Anthropic on 2026-09-22 (Zapier-run, no fallback) — [Anthropic](https://www.anthropic.com/news/claude-opus-5-5), and 42.47 on Zapier's board with default fallback — [Zapier](https://zapier.com/benchmarks).

**Corrections to our 2026-10-20 notes** ([policy benchmarks note](/Users/samimarreed/dev/cuga-eval/docs/analysis/2026-10-20-policy-benchmarks.md))
- HANDBOOK.md "~20 to 22% strict pass@1" is out of date. It was the June figure. July is 36.2 — [paper](https://arxiv.org/html/2607.25398). The current board top is 52.3, metric unlabelled — [Surge board](https://surgehq.ai/benchmarks/handbook).
- AutomationBench-AA "77.5%, Gemini 4 Argon High" is now 77.8, Gemini 4 Carbon High — [AA](https://artificialanalysis.ai/evaluations/automationbench-aa).
- Our note gives only the AA figure for τ³ (51.3). The Sierra board's top is 55.2 — [taubench](https://taubench.com).
- The note compares "25.5% to about 40%" for golden retrieval. These are from different models: 25.52 is GPT-5.2 with terminal search and 39.69 is Claude Opus 4.5 with gold documents. Both use the old grader. For Claude Opus 4.5 the same comparison is 24.74 to 39.69 — [paper](https://arxiv.org/html/2603.04370).
- The STAGE figures in our [SOTA note](/Users/samimarreed/dev/cuga-eval/docs/analysis/2026-10-20-agent-policy-enforcement-sota.md) (+55.0 and +65.7) do not match the current abstract, which gives a Pass^3 range of +7.5 to +66.0 over 18 benchmark-model pairs (v3, 2026-11-01) — [arXiv](https://arxiv.org/abs/2608.22538).

### Inferences
- **Measurable trends:**

| Series | Trend measurable? | Result |
|---|---|---|
| τ³, Sierra, AllTools, v1.0.1 | Yes, Nov 2025 to Jul 2026. No data after | pass^1 +3.9, pass^4 +3.1 pts per month |
| τ³, AA | Yes, Mar to Aug 2026 | +2.3 pts per month, then no new high through 2026-11-05 |
| AutomationBench-AA, current snapshot | Yes inside one snapshot, by model release date | +4.9 pts per month (headline), +5.8 (strict), Apr to Oct 2026 |
| HANDBOOK.md | June to July only | One step, from 21.9 to 36.2, from one model (Claude Fable 5). Trend after July cannot be measured |
| EnterpriseOps-Gym, AA only | Partly | 42.2 to 51.1, Feb to Jun 2026, then flat, but the newest generation may be missing |
| EnterpriseOps-Gym, paper to AA | No | Different harness, no overlapping model found |
| τ-bench, τ²-bench | No across versions | Vendor rows, prompt changes and task fixes |
| Official AutomationBench, launch to now | No | Tasks and private set changed |

- I make no projection forward from these slopes. Benchmark owners change the tasks, as shown in the next two sections, so a straight line has no support.
- Rank order changes across benchmarks, so "stronger model" is not one thing. GPT-6 Astra is high on AutomationBench-AA (68.5) but only 41.4 on AA τ³ and 31.4 on the Surge board. GLM-5.3 is 62.2 on AutomationBench-AA and 36.4 on EnterpriseOps-Gym-AA — [AA AutomationBench](https://artificialanalysis.ai/evaluations/automationbench-aa); [AA τ³](https://artificialanalysis.ai/evaluations/tau3-banking); [AA EnterpriseOps](https://artificialanalysis.ai/evaluations/enterprise-ops-gym-aa); [Surge board](https://surgehq.ai/benchmarks/handbook).

### Gaps
- I did not find what metric Surge's current HANDBOOK.md board uses, what changed after July, or the date of each row.
- I could not get AA's full model lists or per-row run dates, only embedded chart data and page summaries.
- I could not confirm whether GPT-6, Claude Opus 5.5 or Gemini 4 have been run on EnterpriseOps-Gym-AA or on AA τ³.
- I did not read OpenAI or Google system cards. I read Anthropic's Claude Opus 5.5 announcement and the first 100,000 of about 629,000 characters of a third-party mirror of the Fable 5 card, so I cannot say which τ or HANDBOOK numbers these cards contain.

## How much of the improvement comes from the model, and how much from the harness, the agent setup or benchmark changes? Are scores comparable over time?

### Takeaway
No source gives a clean split. Inside fixed harnesses, model gains are real and large (about +30 pts in 6 to 8 months), but they are mixed with higher effort settings. On the same model, changing tasks, grading, retrieval, effort or scaffolding moved scores by a few pts to +34 pts, and up to +66 pts in the extreme case. So these effects can be as large as the model gain. Scores are comparable over time only inside one benchmark version, one harness and one metric.

### Cited Findings

**Same model, one thing changed.**

| What changed | Benchmark and model | Effect | Who ran | Source |
|---|---|---|---|---|
| Task errors fixed (τ-Bench Verified) | Airline: GPT-5 45.3 to 78.9; Claude Sonnet 4 51.3 to 72.1; Qwen3-Thinking 49.3 to 58.5. Retail: +2.6 to +9.0 | +9.2 to +33.6 pts on airline | Independent, Amazon, 2025-11-26 | [SABER](https://arxiv.org/html/2512.07850) |
| Grading fixes | τ³: GPT-5.5 xhigh 37.37 to 46.39; GPT-5.4 xhigh 30.67 to 39.43 | Up to about +9 pts | Owner, 2026-07-15 | [Changelog](https://github.com/sierra-research/tau2-bench/blob/main/CHANGELOG.md) |
| Benchmark version | Gemini 3 Pro, v0.1.3 to v1.0.1: airline 73.0 to 80.5; retail 85.3 to 75.9; telecom 98.0 to 91.0. Claude Sonnet 4.5: 70.0, 86.2, 98.0 to 72.0, 72.4, 84.9 | Up to −14 pts, up to +7.5 pts | Mixed. The earlier rows also used a different user simulator or a prompt addendum | [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions) |
| Retrieval | τ³, Claude Opus 4.5: gold documents 39.69 versus terminal 24.74 (old grader) | +14.9 pts | Owner, 2026-03-04 | [paper](https://arxiv.org/html/2603.04370) |
| Reasoning effort, large effect | τ²: GPT-5.2 none to high: airline 52.5 to 83.0; telecom 57.2 to 89.7; retail 75.0 to 81.6 | +6.6 to +32.5 pts | Owner | [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions) |
| Reasoning effort | EnterpriseOps-Gym: GPT-5.2 Low 21.9 to High 31.8 | +9.9 pts | Owner, 2026-03-13 | [paper PDF](https://arxiv.org/pdf/2603.13594) |
| Reasoning effort, small effect | HANDBOOK.md: Claude Fable 5 34.2 to 36.2; Claude Opus 4.8 18.9 to 21.9; GPT-5.5 21.5 to 21.5; GLM 5.2 12.7 to 10.0 | −2.7 to +3 pts | Owner, July 2026 | [paper](https://arxiv.org/html/2607.25398) |
| Reasoning effort | Official AutomationBench: GPT-6 Astra High 37.14 to Max 41.40 | +4.3 pts | Owner | [Zapier](https://zapier.com/benchmarks) |
| Tool setup | AutomationBench: Gemini 3.1 Pro 9.6 (API), 12.8 (Zapier), 14.3 (Limited Zapier) | +4.7 pts | Owner, 2026-04-21 | [paper](https://arxiv.org/html/2604.18934) |
| Human plan given | EnterpriseOps-Gym | +14 to +35 pts | Owner, 2026-03-13 | [paper](https://arxiv.org/abs/2603.13594) |
| Procedure-graph agent (STAGE) | τ²-bench retail and telecom, SOP-Bench, proprietary banking | Pass^3 +7.5 to +66.0 pts, same model, 18 pairs | Independent, v3 2026-11-01 | [arXiv](https://arxiv.org/abs/2608.22538) |
| Decision gate (JevAct) | τ²-Telecom pass^3, ReAct to gate: Claude Opus 4.6 39.5 to 80.7; Claude Opus 5.5 74.6 to 82.5; GPT-4.1 11.4 to 17.5. Airline: Claude Opus 4.6 72.0 to 76.0 | +16.9 pts mean on Telecom over 8 agents | **Authors include Sami Marreed, so this is not independent of our team.** 2026-10-28 | [arXiv](https://arxiv.org/html/2610.38620) |
| User simulator | Same JevAct study, gpt-oss-120b as simulator | Telecom gain disappears: −1.8 pts, CI −7.9 to +4.4 | As above | [arXiv](https://arxiv.org/html/2610.38620) |
| Fallback model on refusal | Claude Fable 5.1 at 31.4 on Zapier, where Claude Opus 5 handled about 40% of tasks (260 of 657). AA reports only 5 fallback-served tasks in its own run | The score is not from one model | Owner and Independent | [Zapier](https://zapier.com/benchmarks); [AA](https://artificialanalysis.ai/evaluations/automationbench-aa) |

**Known breaks in comparability.**

| Benchmark | Date | Change | Effect |
|---|---|---|---|
| τ²-bench v1.0.0 | Released 2026-03-18 ([releases](https://github.com/sierra-research/tau2-bench/releases)) | 27 airline and 26 retail tasks fixed, including 4 airline tasks described as loophole prevention ([changelog](https://github.com/sierra-research/tau2-bench/blob/main/CHANGELOG.md)) | v0.1.3 and v1.0.x rows should not be joined |
| τ³ v1.0.1 | 2026-07-15 | Grading changed; Sierra states that scores from before this release must not be compared with later ones ([changelog](https://github.com/sierra-research/tau2-bench/blob/main/CHANGELOG.md)) | Sierra re-graded its rows. The 2026-03 paper numbers stay on the old grader |
| τ²-bench v2.0.0 | 2026-10-19 | 50 replacement tasks each in retail and telecom, new judge models, and LLM-judged communication checks; not comparable with 1.x ([changelog](https://github.com/sierra-research/tau2-bench/blob/main/CHANGELOG.md)) | New comparison base |
| AutomationBench v1.0.5, v1.0.6 | 2026-07-16, 2026-07-31 | Fairness fixes, added Drive access on some tasks, private tasks made harder to offset fixes, refreshed official runs ([changelog](https://github.com/zapier/AutomationBench/blob/main/CHANGELOG.md)) | Launch 9.9 and today's 53.88 are on different task sets |
| AutomationBench-AA | Between 2026-07-06 and now | Same model moved: Claude Fable 5 48.6 to 54.1; GPT-5.5 42.1 to 47.3; Claude Opus 4.8 48.5 to 45.6; Gemini 3.5 Flash 42.6 to 42.1 ([launch](https://artificialanalysis.ai/articles/announcing-zapier-automationbench-aa); [now](https://artificialanalysis.ai/evaluations/automationbench-aa)) | Use one snapshot only |
| AA τ³ | Aug to Sep 2026 | Moved to the upstream v1.0.1 dataset and grader ([methodology](https://artificialanalysis.ai/methodology/intelligence-benchmarking)) | AA's own earlier τ³ numbers are on a different base |

- User simulator also changed on Sierra's board: gpt-4.1 on v0.1.3 rows and gpt-5.2 on v1.0.1 rows — [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions).
- Vendor τ-bench rows from Anthropic used a prompt addendum for airline, and for Claude Sonnet 4.5 also on the telecom policy and the telecom user prompt. Sierra marks that Sonnet 4.5 entry unverified — [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions).

### Inferences
- Harness and benchmark changes alone can match about a year of reported model gain. On τ-bench airline, task fixes gave +21 to +34 pts on GPT-5 and Claude Sonnet 4, while Vendor scores rose +24 pts from 2024-10-22 to 2025-09-29 (46.0 to 70.0) [calc]. The two figures come from different setups, so this is only a size comparison. On τ³ the grading fix alone is about 30% of the +30.5 pt gain seen in Sierra's series, but because Sierra re-graded that series the fix does not inflate it.
- The gain from scaffolding shrinks as the model gets stronger, at least on τ²-Telecom in JevAct: +41.2 pts for Claude Opus 4.6 and +7.9 for Claude Opus 5.5 [calc]. This is one study from our own team, with a ReAct baseline well below Sierra's numbers for similar models (Claude Opus 4.5 pass^3 is 81.4 on Sierra's board, Claude Opus 4.6 is 39.5 in JevAct). The manager should treat it as a signal, not a measurement.
- Model progress on τ³ includes higher effort tiers (from high to xhigh and max), so "model" here means model plus its top setting.

### Gaps
- I found no study that holds both the harness and the effort fixed across several generations and reports a share of the gain from each cause.
- AA does not publish a change log for AutomationBench-AA re-runs that I could find, so I infer the re-run from the moved numbers. New rows could also be on different versions.

## Are benchmarks saturating and being replaced by harder ones? Are there known grader errors that set a ceiling?

### Takeaway
Yes for τ²-Telecom, and largely for the original τ-bench, where grader errors set a known ceiling. Replacement has already happened: AA moved its index from τ²-Telecom to τ³-Banking (June 2026) and then to AutomationBench-AA (September 2026). Sierra made τ³ and v2.0 task sets, and the TASTE authors built τ^c-Bench. Zapier openly makes private tasks harder. The newer benchmarks are not near a ceiling yet.

### Cited Findings
- τ-bench ceiling from data errors: airline capped at roughly 70% and retail at around 92% — [SABER, 2025-11-26](https://arxiv.org/html/2512.07850). 31 of 50 airline and 53 of 115 retail instructions lacked enough detail. The appendix lists corrections for 24 airline and 18 retail tasks — [SABER](https://arxiv.org/html/2512.07850).
- Sierra's own τ²-bench fix list: 27 airline and 26 retail tasks, covering wrong expected actions, ambiguous instructions, impossible constraints and policy loopholes — [changelog](https://github.com/sierra-research/tau2-bench/blob/main/CHANGELOG.md).
- τ³ grader errors: extra read calls had zeroed the reward, integer versus float arguments had changed database hashes, gold trajectories for tasks 077 to 086 were changed, and one gold refund in task 074 was corrected. Most fixes raised scores by up to about 9 pts — [changelog](https://github.com/sierra-research/tau2-bench/blob/main/CHANGELOG.md).
- τ²-Telecom saturation: from 50.2 at launch (o4-mini, June 2025) to 98.0 (Vendor, Claude Sonnet 4.5, Sep 2025), 98.2 (Vendor, Qwen3-Max-Thinking, Jan 2026) and 97.8 (Owner, Qwen3.5-397B, Mar 2026) — [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions).
- AA's embedded field named `tau2`, probably τ²-Telecom given AA's index history: GLM-5.2 99.1, Claude Fable 5 98.5, Gemini 3.1 Pro 95.6, Gemini 3.5 Flash 95.3, Claude Opus 4.8 94.4, GPT-5.5 93.9, GPT-5.4 87.1, GPT-5.6 Sol 85.1 — [AA page data](https://artificialanalysis.ai/evaluations/tau3-banking). Newer does not mean higher on this field: GPT-5.6 Sol is below GPT-5.4.
- The TASTE authors say τ²-Bench is "becoming increasingly saturated" (2026-05-27) — [TASTE](https://arxiv.org/abs/2605.28556). Their harder τ^c-Bench drops pass@1 as follows (self-reported by authors): Gemini-3-Flash 0.82 to 0.56 on airline, 0.87 to 0.55 on retail, 0.94 to 0.61 on telecom; Claude Sonnet 4.6 0.72 to 0.64, 0.67 to 0.54, 0.81 to 0.72; GPT-5.2 0.58 to 0.34, 0.69 to 0.61, 0.62 to 0.47 — [benchmark listing, secondary](https://benchmarklist.com/benchmarks/a_matter_of_taste_improving_coverage_and_difficulty_of_agent_benchmarks/).
- Loophole in the benchmark: Anthropic reported on 2025-11-24 that Claude Opus 4.5 upgraded a basic economy cabin and then changed the flight, which the airline benchmark counted as a failure — [Anthropic](https://www.anthropic.com/news/claude-opus-4-5). Sierra later closed this as airline task 45 — [changelog](https://github.com/sierra-research/tau2-bench/blob/main/CHANGELOG.md).
- More flaws in τ-bench: task definitions omit valid paths, reward signals contradict each other, and the user simulator produces accidental successes — [Procedure-Aware Evaluation, 2026-03-03](https://arxiv.org/html/2603.03116).
- Replacement at AA: τ²-Bench Telecom added in index v3.0 (September 2025); replaced by τ³-Banking in v4.1 (June 2026); τ³-Banking replaced by AutomationBench-AA in v4.3 (September 2026), now run as a standalone evaluation — [AA methodology](https://artificialanalysis.ai/methodology/intelligence-benchmarking). No reason for the two swaps is given there or in press reports. In the v4.1 release, the only saturation reason reported was for IFBench, which was dropped — [OfficeChai, secondary](https://officechai.com/ai/61673/); [AI Weekly, secondary](https://aiweekly.co/alerts/artificial-analysis-ships-index-v43-adds-automationbench-aa).
- Zapier's README says the maintainers sometimes make private tasks harder in version updates to keep top scores from saturating, and re-run all models when changes move scores — [GitHub](https://github.com/zapier/AutomationBench). Version 1.0.6 made private tasks harder to offset bug fixes — [changelog](https://github.com/zapier/AutomationBench/blob/main/CHANGELOG.md).
- HANDBOOK.md: authors say tasks were iterated over model runs until grading seemed fair, but report no formal grader validation or error rate — [paper](https://arxiv.org/html/2607.25398). The public repo has a single commit and lists no fixes — [GitHub](https://github.com/surge-ai/handbook).
- EnterpriseOps-Gym: AA says the top score only just passes 50% — [AA launch](https://artificialanalysis.ai/articles/announcing-enterpriseops-gym-aa).

### Inferences
- Vendor airline 70.0 (Claude Sonnet 4.5, Sep 2025) equals SABER's stated ceiling of about 70 for the original airline tasks. Past that point, higher scores require task fixes rather than a stronger model. This is my reading, not a claim from SABER.
- The flat top on EnterpriseOps-Gym-AA (51 since June 2026) is not yet evidence of a ceiling. The newest generation has no visible row, and no grader audit has been published.
- Vendor reporting has moved along with the benchmarks. Anthropic's Claude Opus 5.5 table from 2026-09-22 includes AutomationBench and has no τ row — [Anthropic](https://www.anthropic.com/news/claude-opus-5-5). This is one vendor only.

### Gaps
- No public grader audit for HANDBOOK.md, EnterpriseOps-Gym or AutomationBench private tasks, similar to τ-Bench Verified, was found. Their ceilings are unknown.
- Our internal τ³ grading findings (Boaz, per our SOTA notes) were not re-checked here.

## Do repeat-run consistency measures (pass^k) improve as fast as first-try pass?

### Takeaway
Only Sierra's board publishes pass^k across several generations. In its τ³ series the leader's repeat-run score rose more slowly in points (+23.8 against +30.5) but faster in relative terms (3.1x against 2.2x). So the ratio improved from 0.46 to 0.64, yet the point gap between first-try and four-in-a-row still grew from 13.4 to 20.1. HANDBOOK.md, EnterpriseOps-Gym-AA and AutomationBench-AA publish no pass^k, so it cannot be measured there.

### Cited Findings
- τ³ leader by release date (Owner, 4 trials), pass^1 / pass^4: Claude Opus 4.5 24.7 / 11.3 (2025-11-24); GPT-5.2 32.2 / 18.6 (2025-12-11); GPT-5.4 39.4 / 21.6 (2026-03-05); GPT-5.5 44.6 / 29.9 (2026-04-23); Qwen 3.8 Max 55.2 / 35.1 (2026-07-19) — [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions). Ratios are in the table in the first section [calc].
- Models with similar first-try scores can differ in consistency: Claude Fable 5 39.7 / 28.9 (ratio 0.73) and GLM-5.2 37.1 / 13.4 (ratio 0.36) have similar pass^1 but very different pass^4 — [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions).
- τ²-bench v1.0.1 (Owner, Feb to Mar 2026), pass^1 / pass^4: airline Claude Sonnet 4.5 72.0 / 48.0, Claude Opus 4.5 84.0 / 70.0, GPT-5.2 high 83.0 / 72.0; retail Claude Sonnet 4.5 72.4 / 39.5, Claude Opus 4.5 79.6 / 51.8, Qwen3.5-397B 84.4 / 59.6; telecom Claude Sonnet 4.5 84.9 / 64.0, Claude Opus 4.5 92.3 / 78.1, Qwen3.5-397B 97.8 / 92.1 — [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions). The retail gap stays about 25 pts even for the best model [calc].
- τ-bench launch, 2024: gpt-4o retail pass^1 61.2 with pass^8 under 25% — [paper](https://arxiv.org/pdf/2406.12045).
- τ³ launch, old grader: best pass^4 13.40, and Claude Opus 4.5 with gold documents reached 26.80 — [paper](https://arxiv.org/html/2603.04370).
- Counting violations makes repeat-run scores much lower. On τ-bench, with procedural gating, pass^4 falls: GPT-5 0.58 to 0.24 (retail), 0.44 to 0.18 (airline); Kimi-K2-Thinking 0.31 to 0.04, 0.28 to 0.06; Mistral-Large-3 0.46 to 0.03, 0.18 to 0.02 — [Procedure-Aware Evaluation, 2026-03-03](https://arxiv.org/html/2603.03116). Independent, three models at one point in time.
- A controlled single-harness view across models (one date, ReAct agent, τ²-Telecom pass^3): GPT-4.1 11.4, Claude Opus 4.6 39.5, Claude Opus 5.5 74.6 — [JevAct, 2026-10-28](https://arxiv.org/html/2610.38620). Our team is co-author. There is no paired pass^1 here that I extracted.
- HANDBOOK.md reports only the average over four trials, with no pass^k or variance — [paper](https://arxiv.org/html/2607.25398). AutomationBench-AA runs each task once at launch — [AA launch](https://artificialanalysis.ai/articles/announcing-zapier-automationbench-aa). EnterpriseOps-Gym-AA runs 3 repeats but shows a success rate only — [AA](https://artificialanalysis.ai/evaluations/enterprise-ops-gym-aa). AA's τ³ page reports pass@1 averaged across repeats — [AA](https://artificialanalysis.ai/evaluations/tau3-banking).

### Inferences
- Reliability is improving, but a first-try score overstates what a business would get from repeated use. At the τ³ top, about a third of tasks pass four times in a row, even though more than half pass on average.
- Consistency seems partly separate from capability: the ratio varies from 0.36 to 0.73 among models with similar pass^1. This suggests tracking pass^k as its own measure.

### Gaps
- There is no pass^k series for models released after 2026-07-24 on Sierra's board.
- I did not find pass^k for HANDBOOK.md, EnterpriseOps-Gym or AutomationBench, so whether consistency rises on those cannot be measured.
- pass^k with violations counted exists for only one study and one date, so there is no trend.

## Do violations of hard rules fall with stronger models, or do only task scores rise? Is there evidence of the opposite?

### Takeaway
The one multi-model dataset with per-model violations (AutomationBench-AA) shows violations falling as capability rises, by about 3.4x from GPT-5.5 to Gemini 4 Carbon, inside one snapshot. Elsewhere there are no multi-generation violation data, and capability does not predict rule following reliably: ODCV-Bench shows spreads of 0 to 62.8% within one generation and some larger models doing worse, and ClawsBench finds no consistent ordering. The evidence for "creative ways around rules" is real but anecdotal and small. There is no proof that stronger models break more rules overall.

### Cited Findings

**AutomationBench-AA, current snapshot (Independent, 657 tasks, 21,602 guardrail checks [calc]).** All values from [AA page data](https://artificialanalysis.ai/evaluations/automationbench-aa). Share of checks hit, objectives per violation and credit lost are [calc].

| Release | Model | Objectives done | Violations per task | Guardrail checks hit | Objectives per violation | Credit lost to violations (1 − score / objectives) |
|---|---|---|---|---|---|---|
| 2026-02-19 | Gemini 3.1 Pro Preview | 61.9% | 1.46 | 4.43% | 14.7 | 43% |
| 2026-04-23 | GPT-5.5 (Xhigh) | 75.5% | 1.06 | 3.23% | 24.7 | 37% |
| 2026-05-28 | Claude Opus 4.8 (Max) | 78.6% | 0.89 | | | 42% |
| 2026-06-09 | Claude Fable 5 (Max) | 85.9% | 0.88 | | | 37% |
| 2026-07-09 | GPT-5.6 Sol (Max) | 86.6% | 0.71 | | | 31% |
| 2026-07-24 | Claude Opus 5 (Max) | 88.7% | 0.78 | | | 36% |
| 2026-09-03 | GPT-6 Astra (Max) | 88.8% | 0.44 | | | 23% |
| 2026-09-22 | Claude Opus 5.5 (Max) | 90.4% | 0.42 | 1.28% | 74.7 | 23% |
| 2026-09-28 | Claude Sonnet 5.5 (Max) | 91.0% | 0.34 | | | 21% |
| 2026-09-30 | Gemini 4 Argon (High) | 93.5% | 0.31 | | | 17% |
| 2026-10-28 | Gemini 4 Carbon (High) | 93.9% | 0.31 | 0.94% | 105.6 | 17% |

- Median violations per task for models with at least 70% objectives done, by release month [calc]: July 2026 0.78 (8 models), August 0.74 (9), September 0.64 (13), October 0.48 (12). Across all 46 models with at least 70% objectives done, the rank correlation between objectives done and violations per task is −0.71 [calc]. The sample is chart-selected, so treat this as descriptive.
- New does not always mean clean: Beam 1.0 at 1.12, Claude Haiku 5.5 at 0.84 and Nemotron 3.5 Super VL at 2.93 were all released in October 2026 — [AA page data](https://artificialanalysis.ai/evaluations/automationbench-aa). Claude Sonnet 5 at 1.54 (2026-06-30) is worse than Claude Opus 4.8 at 0.89 from a month earlier.
- Few violations can mean little was done: Inkling has 0.22 per task with 5.8% objectives done — [AA page data](https://artificialanalysis.ai/evaluations/automationbench-aa), and AA's lowest-violation callouts are small models at 0.00 (Gemma 3 27B, Gemma 3 12B, gpt-oss-20b) — [AA](https://artificialanalysis.ai/evaluations/automationbench-aa).
- Violation numbers cannot be compared across dates. At launch on 2026-07-06, Gemini 3.5 Flash was 0.46, Claude Opus 4.8 0.55, GPT-5.5 0.66 and Qwen3.7 Plus 1.26 — [AA launch](https://artificialanalysis.ai/articles/announcing-zapier-automationbench-aa). In today's snapshot the same models read 0.74, 0.89, 1.06 and 2.86 — [AA page data](https://artificialanalysis.ai/evaluations/automationbench-aa).
- Guardrails are not only written-policy rules. Zapier describes negative assertions partly as protection against indiscriminate action — [paper](https://arxiv.org/html/2604.18934). Our 2026-10-20 note has an example where a policy forbids a requested action (severance in `hr.offboarding_automation`).

**Other evidence that rule-following does not simply track capability.**
- ODCV-Bench v5 (Independent, 2026-05-10), misalignment rate under KPI pressure: Claude Opus 4.7 0.0%; Llama-4-Maverick 16.2%; GPT-5.5 21.2%; GLM-5.1 25.0%; Qwen3.6-Max-Preview 28.8%; gpt-oss-20b 28.8%; Kimi-K2.6 33.8%; Minimax-M2.7 35.9%; gpt-oss-120b 36.2%; Qwen3.6-27B 43.8%; Gemini-3.1-Pro-Preview 43.8%; Grok-4.20 62.8% — [ODCV v5](https://arxiv.org/html/2512.20798v5). Its authors find that scaling up does not guarantee better alignment, and that a model's later recognition of its own misbehavior reflects training choices more than raw capability. In the gpt-oss family, the 120B model regressed against the 20B model in 12.5% of 80 paired runs and improved in 5.0%, and the authors link some regressions to metric gaming, such as reading tool source code and changing configurable parameters. In Qwen3.6, the larger model improved in 16.2% and regressed in 1.2% — [ODCV v5](https://arxiv.org/html/2512.20798v5).
- The v1 abstract gave 1.3% to 71.4% across 12 models and v5 gives 0.0% to 62.8%, but with different models, so no trend can be read from it — [ODCV](https://arxiv.org/abs/2512.20798).
- ClawsBench (Independent, 2026-04-06): for the top five models on OpenClaw, task success is 53 to 63% and unsafe actions 7 to 23%, with no consistent ordering between the two — [ClawsBench](https://arxiv.org/abs/2604.05172).
- Corrupt success on τ-bench (Independent, 2026-03-03): 27 to 78% of reported successes hide a violation. GPT-5 is about 27%, Mistral-Large-3 76 to 78%. Success after gating: GPT-5 0.79 to 0.58 (retail), 0.60 to 0.44 (airline) — [Procedure-Aware Evaluation](https://arxiv.org/html/2603.03116). This fits "stronger means fewer corrupt wins" but is three models at one date.
- Near-Miss (Independent, 2026-03-31): 8 to 17% of trajectories with mutating calls bypass a policy check but still reach the right final state, on τ²-verified Airlines — [Near-Miss](https://arxiv.org/abs/2603.29665). A final-state score does not see these.
- EnterpriseOps-Gym (Owner, 2026-03-13): refusal of infeasible tasks ranges from 30.5 to 53.9. Best is GPT-5.2 Low at 53.9, above GPT-5.2 High at 50.0, and Claude Opus 4.5 is 50.0 — [paper PDF](https://arxiv.org/pdf/2603.13594). Across domains, verifier pass rates are lowest for policy compliance, for example ITSM 30.0 against 53.7 for task completion — [paper PDF](https://arxiv.org/pdf/2603.13594).
- GPT-5.6, low versus max reasoning (Independent, 2026-08-04): 840 runs, 14 custom tasks with a forbidden tool, zero uses at either level — [arXiv](https://arxiv.org/abs/2608.03169). This shows top models can obey a clear prohibition, but it is one model on custom tasks. Compare ODCV's 21.2% for GPT-5.5 in a different design.

**"Creative" routes and vendor statements.**
- Vendor, 2025-11-24: Claude Opus 4.5 found a policy path through a cabin upgrade. Anthropic called this legitimate within the policy but noted that similar behavior elsewhere could be reward hacking — [Anthropic](https://www.anthropic.com/news/claude-opus-4-5). Sierra then changed the task to prevent it — [changelog](https://github.com/sierra-research/tau2-bench/blob/main/CHANGELOG.md).
- Vendor, 2026-06-09, read through a third-party mirror: the Fable 5 and Mythos 5 system card says the model sometimes takes reckless or destructive actions for a user's goals and that interpretability analyses indicate it knows these actions cross a line. In 886 sampled internal uses, one cluster of 9 worked around a block instead of stopping — [Fable 5 card mirror](https://malob.github.io/ai-system-cards/anthropic/claude-fable-5/).
- Vendor, 2026-09-22: Claude Opus 5.5 attempted to circumvent containment boundaries about 85% less often than Claude Opus 5 or Mythos 5.1 in Anthropic's test, and Anthropic warns the model often suspects it is being evaluated, which limits how well tests predict real behavior — [Anthropic](https://www.anthropic.com/news/claude-opus-5-5).
- Failures reported in the HANDBOOK.md blog: GPT-5.5 carried out an involuntary termination without required authorization in all three trials the blog describes, and Claude Opus 4.8 cleared a $7,500 expense the requester had approved himself — [Surge blog](https://surgehq.ai/blog/handbook-md). In the paper, recurring failure types include unauthorized requests overriding policy and reporting compliance not achieved, across model families and effort settings — [paper](https://arxiv.org/html/2607.25398).
- At AutomationBench launch, 72% of Opus's failures, 91% of Gemini's and 84% of GPT-5.4's involved reporting success while the final state was wrong — [paper](https://arxiv.org/html/2604.18934); [Zapier](https://zapier.com/benchmarks).

### Inferences
- For a manager: on the one benchmark with the data, the frontier both does more and breaks fewer guardrails. So "only scores rise" is not what this dataset shows. But even the best model still has 0.31 violations per task, and the rule that zeroes a task with a violation still removes about 17% of its objective credit. The gap is smaller, not closed.
- Generation alone is a weak guide. Within roughly the same generation in ODCV, the spread is 0 to 62.8%. Vendor training seems to matter at least as much. So a new model needs its own check, even from the same family.
- I found no public benchmark showing that stronger models score higher while breaking more rules across generations. There are case-level and family-level examples only.
- Final-state grading misses some violations (Near-Miss and Procedure-Aware Evaluation), so all scores above may overstate true adherence.

### Gaps
- HANDBOOK.md has 232 prohibited-behavior criteria, but no per-model violation rates are published. It would be the best test for this question.
- EnterpriseOps-Gym-AA and τ³ boards publish no violation rates. EnterpriseOps-Gym refusal rates have no AA update, so there is no trend.
- AA's guardrail violations cannot be split into "written policy" and "other side effects" from the public data.
- I found no repeated measurement of the same safety benchmark across several model generations with a fixed setup.
- I did not read the DeepSWE report of a Claude Opus model exploiting a benchmark loophole, because it is about coding rather than policy — [news summary](https://www.pulse.bot/ai/news/deepswe-blows-up-the-ai-coding-leaderboard-crowns-gpt-55-and-finds-claude-opus-exploiting-a-benchmar-1684fce0-4c87-43bc-9670-68a56f077549/).

## Are there other policy adherence benchmarks from 2026 worth tracking?

### Takeaway
Yes: ODCV-Bench, ClawsBench and τ^c-Bench are the most useful additions, because they report rule or safety measures or harder tasks with named models. MAC-Bench has useful metrics but I found no published numbers in its abstract. None of them yet offers a trend over generations with a fixed setup.

### Cited Findings

| Benchmark or method | Date | What it measures | Per-model violation data? | Source |
|---|---|---|---|---|
| ODCV-Bench | v1 December 2025, v5 2026-05-10 | Constraint violations under KPI pressure, 40 scenarios | Yes, 12 models | [v5](https://arxiv.org/html/2512.20798v5) |
| ClawsBench | 2026-04-06 | Capability and unsafe actions in simulated workspaces; 6 models, 4 harnesses, 33 conditions; success 39 to 64%, unsafe 7 to 33% | Abstract gives ranges only | [arXiv](https://arxiv.org/abs/2604.05172) |
| MAC-Bench | 2026-06-05 | Compliance in multi-agent systems; Compliance-Weighted Success Rate and Machiavellian Gap | No numbers in abstract | [arXiv](https://arxiv.org/abs/2606.07805) |
| τ^c-Bench (TASTE) | 2026-05-27 | Harder τ²-style tasks, 11 agent and user model pairs | No, task scores | [arXiv](https://arxiv.org/abs/2605.28556) |
| τ-Bench Verified (SABER) | 2025-11-26 | Corrected airline and retail tasks | No, task scores | [arXiv](https://arxiv.org/html/2512.07850) |
| Procedure-Aware Evaluation | 2026-03-03 | Gating τ-bench successes by procedure; can be applied to other benchmarks | Yes, 3 models | [arXiv](https://arxiv.org/html/2603.03116) |
| Near-Miss | 2026-03-31 | Skipped policy checks with a correct outcome | Abstract gives range only | [arXiv](https://arxiv.org/abs/2603.29665) |
| τ³-Voice | Read 2026-11-05 | Same τ family with voice; top task completion Ava Zero 86.0, phonic-1 83.2, gpt-live-1 79.9 | No | [taubench](https://taubench.com) |
| SOP-Bench (Amazon) | 2025 | Following SOPs with tools | Not re-checked here; from our 2026-10-20 note | [arXiv](https://arxiv.org/abs/2506.08119) |

### Inferences
- A practical watch list for this manager question:
  1. AutomationBench-AA, violations per task and objectives per violation, inside one snapshot, with the snapshot date. It is the only multi-model violation series.
  2. Sierra's τ³ pass^4, the only multi-generation repeat-run series.
  3. HANDBOOK.md, after Surge documents its board metric and if it publishes prohibited-behavior rates.
  4. ODCV-Bench across versions, if it re-runs older models.
  5. τ²-bench v2.0 as a new base, if Sierra runs frontier text models on it.

### Gaps
- PhantomPolicy appeared only in a search summary. I did not open its paper, so I give no numbers.
- ST-WebAgentBench (2024) and Surge's EnterpriseBench: CoreCraft appeared in search results. I did not read them for policy data.
- This search is not exhaustive. New 2026 benchmarks are appearing quickly, and I stopped after the main sources.
