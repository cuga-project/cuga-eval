# Follow-up fixes: test plan, written before the code (2026-11-05)

Failure class found by reading runs of `ab-policy-types-holdout`: the policy layer's follow-ups make the agent do
writes it had rightly left out. That set is now a tuning set for this work.

## Fixes

| Arm | Change |
|---|---|
| F1 | A follow-up is a check, not an order: it says it is automated and not from the user, and the agent's stated reasons for leaving something out are shown to the checker |
| F2 | A new write is pushed only if a separate check finds that the source specifically requires that action for that item, with its conditions met |
| F12 | F1 and F2 together |

## Test

- Tasks: `ab-policy-types-fresh3`, 35 tasks, seed 20261105, drawn before any fix was written. No result file of any model
  holds these tasks. No task of the versioned or date types is left in the pool, so conflict rules are not tested here.
- Models: aws/gpt-oss-120b and aws/claude-haiku-5-5 (reasoning off), 1 trial per arm.
- Arms per model: A (no policy), B (current polisys), F1, F2, F12.
- Fixes may be corrected on `ab-policy-types-holdout` only. `ab-policy-types-fresh3` runs once, after the code is frozen.

## Criteria, fixed now

A fix passes only if, on BOTH models, against B:
1. Partial score does not fall by more than 2 points.
2. Guardrails broken per task fall, and are not higher than A by more than 0.05.

Reported next to each other: score, strict pass, guardrails per task, tasks better and worse, sign test, cost.
With 35 tasks and 1 trial a small difference is not proof; a result inside the noise is reported as such.

## No-harm check

The chosen arm also runs on one other benchmark. A fall of more than 2 points against its current profile fails it.

## Rules

No task IDs, values, domain words or tool-name patterns from the inspected tasks in code or prompts. A fix with no effect is dropped.

## Corrections made on the tuning set (ab-policy-types-holdout), before the fresh set runs

- 2026-11-06, commit d19e0f9: both fixes together lost 8.6 and 8.0 points of partial score. Reading 5 worse tasks: the
  evidence check treated missing data as a failed condition. New rule: reads and writes differ. Missing data asks the agent to
  look and to change nothing because of the message. A "no" must copy its condition and the failing value from what was read.
  The test criteria above are unchanged.

## Result on the tuning set, 2026-11-06 (35 tasks, 1 trial per arm)

Fix 1 with the read/write split fails the criteria on both models. Tasks where the evidence check never acted still changed
(gpt-oss 10 of 17, mean +4.5 points against fix 1; Haiku 9 of 18, mean -6.8), so one trial on 35 tasks has noise of about 5 points
and cannot test a 2-point limit. Before the fresh set runs, each arm needs at least 3 trials. The criteria are otherwise unchanged.
