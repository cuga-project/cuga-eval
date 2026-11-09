# AutomationBench fresh4: pre-registration (the one frozen run)

Written 2026-11-09, before the run. Code and setup frozen: snapshot `polisys-7dc68b0` (the snapshot of the tuning runs),
`AB_AGENT_RULES=1`, `AB_WORLD_CLOCK` on (default), proxy 8801 (cache off), 3 trials. No Langfuse tracing (the traced
snapshot differs from the tuned code).

## Set

`ab-policy-types-fresh4`: 20 tasks, `select_policy_types.py --seed 20261109`, excluding every earlier subset, holdout and
fresh set. Only 20 tasks were left in the pool (types control, approval, multi_source, one_doc; 5 each). No model has
run any of them (registry, 2026-11-09).

## Arms

| Arm | Profile | Models | What |
|---|---|---|---|
| R | `baseline` | Haiku 5.5, gpt-oss-120b | CUGA + general AutomationBench rules |
| B | `experiments/ab-sf-data` | Haiku 5.5, gpt-oss-120b | + listing, corrections and examples as data (`listing_data`), supersedes, read-back |
| L | `experiments/automationbench-gptoss-b4tf-list` | gpt-oss-120b only | the gpt-oss tuning winner on fresh3 (secondary) |

Tuning scores to report next to this run: fresh3 (35 tasks, 3 trials) and the 10-task best-method rounds
(`2026-11-08-listing-preregistration.md`, `2026-11-08-automationbench-best-method.md`).

## Decision rule (per model)

- Primary: B against R, paired per task. A gain is claimed only if the strict difference is > 0 with sign-flip p < 0.05.
  Also report strict without the frozen upstream-flagged checks (`upstream_flagged_checks_fresh4_2026-11-09.json`,
  built from upstream issues and PRs only, committed before any result of this run is read) and partial, each with the
  paired difference, 95% bootstrap CI and sign-flip p.
- No-harm (AGENTS.md): B − R ≥ −2 × SE on strict and on partial, with SE = sqrt(2 × mean per-task variance of R /
  trials / tasks); guardrail breaks of B may not exceed R by more than 2 × their SE. A model that fails it is not
  supported, and the failure is reported.
- Secondary (gpt-oss): the same tests for L against R, reported apart; not a second primary claim.

## Result (2026-11-09, 300 runs, 0 errors; script `benchmarks/automationbench/fresh4_stats.py`)

Paired per task, 20 tasks x 3 trials. Strict and partial in %, guardrail breaks per run. CI = 95% bootstrap, p = sign-flip
(one-sided, gain).

| Comparison | Strict | Strict w/o flagged | Partial | Guardrail breaks | No-harm |
|---|---|---|---|---|---|
| Haiku B vs R | 30.0 → 33.3 (+3.3, CI −6.7..+13.3, p 0.38) | 45.0 → 48.3 (+3.3, p 0.39) | 72.4 → 77.0 (+4.6, CI −2.1..+12.4, p 0.12) | 0.38 → 0.35 | ok |
| gpt-oss B vs R | 5.0 → 16.7 (+11.7, CI +1.7..+23.3, p 0.062) | 5.0 → 18.3 (+13.3, p 0.062) | 29.1 → 52.1 (+23.1, CI +12.7..+34.5, p < 0.001) | 1.23 → 0.53 | ok |
| gpt-oss L vs R (secondary) | 5.0 → 11.7 (+6.7, CI +1.7..+13.3, p 0.064) | 5.0 → 15.0 (+10.0, p 0.064) | 29.1 → 51.7 (+22.7, CI +14.0..+31.9, p < 0.001) | 1.23 → 0.47 | ok |

Decision by the rule above: **no strict gain is claimed for either model** (p ≥ 0.05). gpt-oss: the strict CI excludes 0
but the sign-flip p is 0.062 (few tasks change), so it does not meet the rule. Partial gain for gpt-oss is clear (+23 points,
p < 0.001) and guardrail breaks fall by more than half. No-harm passes for both models on strict, partial and guardrail
breaks. For gpt-oss R, SE on strict is 0 (no task varies across trials in R), so the no-harm strict check is degenerate there.

Tuning scores next to these (in-sample): Haiku sf-data vs sf-base, 10 tasks x 3 trials: +16.7 strict without flagged, +23.5
partial (`2026-11-08-automationbench-best-method.md`). The held-out Haiku gain (+3.3 / +4.6) is much smaller than in tuning.
