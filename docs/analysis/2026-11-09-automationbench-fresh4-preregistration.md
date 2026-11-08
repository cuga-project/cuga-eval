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
