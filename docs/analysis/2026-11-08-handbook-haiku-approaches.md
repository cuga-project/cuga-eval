# HANDBOOK, Haiku 5.5: approaches toward a full pass on one task (2026-11-08)

Goal: a general method for enterprise work from long SOP documents, found by trying up to 10 approaches. Agent Haiku 5.5.
Task for round 1: Vanguard (`insurance_vanguard_shield_mutual_9b2f7a29`, 12 rubric items). The 3 public tasks are a tuning
set, so every number here is in-sample.

Base: `experiments/handbook-haiku-graph-gate` (procedure tools + gate with Haiku), best Haiku arm of the recheck: 42.7 of 51
(CUGA alone 38.7); Vanguard 11, 8, 10.

Failure analysis of 12 Haiku runs (`/tmp/aud/hb_vanguard_analysis.md`, rubric used only to know which items failed):
an approval posted by the agent's own account taken as the manager's approval (5 runs, 3-5 items each; runs that looked
up the poster 7 of 7 right, the others 0 of 5); flag cells holding text (5 runs); analysis done but no system writes, ending
with an offer (2 runs); SOP column names instead of the request's (2 runs); a gate block on an absence it had not read (1 run).
One item (a flag value for a case the SOP does not define) may be a benchmark defect; no rule targets it.

## Round 1 (plan, written before the run)

polisys `129b89b` (snapshot `polisys-129b89b`): `notes.work_method` (general rules in `work_method.py`) and
`checkers.gate.missing_needs_read`, both off by default. Vanguard only, 3 trials per arm, all arms at the same time.

| Arm | Adds to the base |
|---|---|
| r1-base | nothing |
| r1-actors | a rule that needs a role is met only by a confirmed person, never by the acting account |
| r1-worksheet | one row per record before any write: inputs with sources, decision, required outputs; exact comparisons in code |
| r1-scope | a request under an SOP authorizes its internal writes; the request's names win; flag cells hold one value |
| r1-idem | look for an existing record before creating one; resolve an account once |
| r1-readback | one read-back turn before the final answer: each record's required outputs, from the systems |
| r1-gateread | the gate blocks on a missing thing only when it read the record that should hold it |
| r1-all | all of the above |

Decision rule: rank arms by mean items over 3 trials. An arm goes to round 2 (all 3 tasks) if its mean is at least the
base mean + 1 item, or if it reaches 12 of 12 in any trial. Round 2 keeps an approach only if its total over the 3 tasks is
not below the base and no task falls by more than 1 item on the mean.

## Round 1b (plan, written before the run)

polisys `c396487` (snapshot `polisys-c396487`) adds `organizers.procedure_push`: after each read with new data, a router (`llm_cards`, Haiku) picks
the procedures that govern it and the system attaches their full text to that tool result; the gate's scope includes them.
Same task, 3 trials, its own base at the same time.

| Arm | Change from the base |
|---|---|
| r1b-base | nothing |
| r1b-push | + procedure push (procedure tools stay on) |
| r1b-pushonly | procedure push instead of the procedure tools: the system alone decides which procedures the agent sees |
| r1b-advisory | + the SOP loop in advisory style (cases and checks by Haiku, one work turn, no stops) |

Same decision rule as round 1.

## Round 1 result (Vanguard, 3 trials, items of 12)

| Arm | Trials | Mean |
|---|---|---|
| r1-all | 12, 11, 12 | 11.67 |
| r1-readback | 11, 12, 12 | 11.67 |
| r1-scope | 12, 10, 12 | 11.33 |
| r1-base | 11, 11, 11 | 11.00 |
| r1-gateread | 11, 10, 11 | 10.67 |
| r1-worksheet | 7, 11, 12 | 10.00 |
| r1-actors | 12, 9, 8 | 9.67 |
| r1-idem | 11, 8, 10 | 9.67 |
| r1b-base | 8, 5, 9 | 7.33 |
| r1b-advisory | 12, 11, 10 | 11.00 |
| r1b-pushonly | 6, 11, 12 | 9.67 |
| r1b-push | 11, 11, (running) | |

No arm beats its base by 1 item on the mean; arms qualify by a 12 in a trial. The two bases at the same time differ by 3.7.

## Round 2 (plan, written before the run)

All 3 tasks, 3 trials, snapshot `polisys-c396487` for every arm, at the same time: r2-base (handbook-haiku-graph-gate),
r2-readback, r2-all, r2-scope, r2-advisory. Kept: total mean items over the 3 tasks not below r2-base, and no task's mean
more than 1 item below r2-base. Ranked by total mean; full passes per task reported.

## Round 2 result (3 tasks, 3 trials, items: Crestwood /22, Vanguard /12, CareIG /17)

| Arm | Crestwood | Vanguard | CareIG | Total mean /51 | Full passes | vs base | Rule |
|---|---|---|---|---|---|---|---|
| r2-base | 20, 20, 21 | 8, 10, 10 | 11, 13, 11 | 41.3 | 0 | | |
| r2-readback | 21, 22, 21 | 10, 11, 11 | 12, 12, 13 | 44.3 | 1 | +3.0, worst task +0.7 | kept |
| r2-scope | 21, 21, 22 | 12, 12, 12 | 13, 11, 9 | 44.3 | 4 | +3.0, worst task -0.7 | kept |
| r2-all | 21, 21, 22 | 12, 12, 12 | 11, 14, 7 | 44.0 | 4 | +2.7, worst task -1.0 | kept (at the limit) |
| r2-advisory | 21, 20, 14 | 12, 9, 7 | 12, 10, 14 | 39.7 | 1 | -1.7, worst task -2.0 | dropped |

In-sample (tuning tasks). The read-back turn is the only arm at or above the base on every task. The request-scope and cells
rules give a full pass on Vanguard in 3 of 3 trials. The CareIG 7 of r2-all is one run: a wrong decision (an alert the SOP
did not call for), then the read-back turn's "correction" added an email and a log row.
