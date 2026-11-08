# CSM (EnterpriseOps-Gym): pre-registration

Written 2026-11-08, before any run of the arms below. Agent: CUGA, `aws/claude-haiku-5-5`, snapshot `polisys-7dc68b0`.
The policy layer's models are Haiku 5.5 as well. Proxy 8801 (cache off).

## Sets

| Set | Tasks | Role | Rule |
|---|---|---|---|
| `csm-probe` | 12 | tuning (failures read) | 12 longest policy versions, one task each, seed 20261108 |
| `csm-tune2` | 18 | tuning | rest of the pool, seed 20261109, first 18 |
| `csm-heldout` | 53 | held-out | rest of the pool after `csm-tune2`; run once, after freeze |

The pool is the 83 CSM tasks without same-name verifiers (upstream issue #23).

## Arms

| Arm | Profile | Package |
|---|---|---|
| A | `baseline` (CUGA alone) | none |
| K | `experiments/csm-readback` (general read-back turn) | none |
| R | `experiments/csm-rules` (typed rules + write verifier) | CSM `skill_v1` |
| C | `experiments/csm-combo` (HANDBOOK combo: procedure tools, must-not gate with gate fix, `sop_literal`, `readback_sop`) | CSM `skill_v1` |

## Decision rule

- **Tuning** (30 tasks, 3 trials per arm): choose the arm with the highest mean partial score among the arms that pass the no-harm check against A on both strict and partial. The no-harm check is policy − A ≥ −2 × SE, with SE = sqrt(2 × mean per-task variance of A / trials / tasks). If two arms are within 1 SE of each other, take the one with fewer parts.
- **Held-out** (53 tasks, 3 trials, one run): the chosen arm against A.
  - The gain is claimed only if the paired per-task strict difference is > 0 with a sign-flip p < 0.05.
  - The no-harm check for strict and partial is reported in the same table.
  - If the chosen arm fails no-harm on the held-out set, the policy system stays off for CSM, and this is reported as a failure.
- The tuning score is reported next to the held-out score.

Packages are built from the policy text and the tool schemas only (compiler skill). No task, verifier or run result is read by the builder. Decision tests (skill step 8) are skipped for now.

## Results (2026-11-08)

Tuning (30 tasks × 3, Haiku 5.5): CUGA alone 14.4 / 47.5 (strict / partial); read-back 25.6 / 52.7 (+11.1 / +5.2, p 0.038, no-harm ok); combo 15.6 / 46.4 (no-harm ok); rules + verifier 14.4 / 40.8 (fails no-harm on partial: role-grant rules make the agent refuse writes). Chosen: read-back.

Held-out (53 tasks × 3, one run): CUGA alone 26.4 / 56.0; read-back 27.0 / 60.8. Strict +0.6, sign-flip p 0.455: **the pre-registered gain is not shown**. Partial +4.8 (one-sided sign-flip p 0.048, 95% bootstrap CI −0.6 to +10.8; 16 tasks better, 10 worse). No-harm passes on both (SE 2.6 / 1.6). Cost: tuning $2.73, held-out $2.14.

## With the grader defect fixed (2026-11-09, recomputed from saved runs)

Defect: 56 `equals` checks store `expected_value` as text; where the text is an integer ("1") the upstream comparison
with the integer COUNT always fails. `benchmarks/enterpriseops_gym/numeric_string_fix.py` passes such a check when the
text integer equals the number; every other check keeps the upstream result. Applied to every arm; new runs store it
beside the upstream result (`passed_numeric_fix`).

| Set | Arm | Strict upstream → fixed | Partial upstream → fixed | vs CUGA alone, fixed (strict / partial) |
|---|---|---|---|---|
| Tuning 30 | CUGA alone | 14.4 → 18.9 | 47.5 → 55.7 | |
| Tuning 30 | read-back | 25.6 → 31.1 | 52.7 → 60.6 | +12.2 (p 0.034) / +4.8 |
| Tuning 30 | combo | 15.6 → 23.3 | 46.4 → 55.3 | +4.4 / −0.4 |
| Tuning 30 | rules + verifier | 14.4 → 15.6 | 40.8 → 42.9 | −3.3 / −12.8 (fails no-harm) |
| Held-out 53 | CUGA alone | 26.4 → 28.3 | 56.0 → 58.7 | |
| Held-out 53 | read-back | 27.0 → 28.3 | 60.8 → 63.6 | 0.0 / +5.0 (p 0.046) |

The conclusions do not change: the held-out strict gain is not shown; partial +5.

## Round 2 (pre-registered 2026-11-09, before the runs): request checklist and no-ask rule

From the gap analysis (`2026-11-08-csm-strict-gaps.md`): two general rules in polisys `work_method` (`request_checklist`,
`no_ask`, polisys 32100d8, snapshot `polisys-32100d8`). Arms on the 30 tuning tasks, 3 trials, Haiku 5.5:
`experiments/csm-rb-cl` (read-back + checklist), `csm-rb-na` (read-back + no-ask), `csm-rb-clna` (both), against the
saved runs of A (CUGA alone) and read-back.

Decision: strict with the grader fix is the metric. An arm goes on if it beats read-back alone by at least 1 SE (paired)
and passes no-harm against A on strict and partial. The CSM held-out set is spent, so the claim comes from a fresh
domain (EnterpriseOps-Gym HR, sets drawn before any run) and an AutomationBench no-harm check on fresh3 (tuning set).
