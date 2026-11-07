# Best method so far: SOP-aware loop + procedure guide (2026-11-03)

**Result:** on HANDBOOK.md, CUGA with DeepSeek-V4-Pro goes from **58.8% to 69.3%** of rubric items (+10.5 pts) with the
loop + guide, in a head-to-head where all arms ran at the same time. The guide alone gives +5.9 pts.
**Limit:** 3 public tasks, which were also used to build the method (in-sample); no task was fully passed in any arm.

## What it is

Two parts that use the SOP's **procedure graph** (built offline from the SOP document):

| Part | Role | File (`~/dev/cuga-agent-gate/src/cuga/policy_layer/`) |
|---|---|---|
| Offline intake | SOP → procedures (steps + tool per step), preconditions, exceptions, templates, escalations, general rules; every item has a verbatim quote | `handlers/procedures.py`, `handlers/procedure_rules.py`, `builder.py` |
| **Procedure guide** (checker) | Hook on every write: stops the first write of a procedure once with its rules; on retry, a small model checks the proof for hard preconditions (authorization, approval, written, signed) on the data read, at most 2 stops; template check; general-rules stop for writes that fit no procedure | `procedure_guide.py` |
| **SOP loop** (organizer) | Runs CUGA in phases: explore (writes blocked) → find cases → per case: typed questions (which procedure, preconditions, exceptions, general rules, already done?) → **decision in code** (follow / stop / hold / escalate) → one scoped CUGA turn per case → finish turn (request again; decisions stand) | `sop_loop.py` |

Design rules that made it work (each learned from a failed variant):
- Narrow questions with evidence, decision in code. A second model deciding whole cases (planner) added errors.
- An independent check beats the agent checking itself (Navarro: the agent "verified" and was wrong; the narrow
  check "is there a message *from* the named person?" was right in 3/3).
- A list turned into one combined output (digest, workbook) is one case; hold/stop decisions are repeated in the
  finish turn.
- Feedback goes into the conversation (tool results, user turns), not into the system prompt.

## Results (HANDBOOK, 3 tasks, rubric items; arms at the same time)

| Batch | CUGA alone | Guide v2 | Loop + guide |
|---|---|---|---|
| Head-to-head, 3 trials (2026-11-03) | 58.8% | 64.7% | **69.3%** |
| Guide v2 batch, 3 trials | 53.6% | **74.5%** | — |
| Loop rounds 1–3, 6 trials | 59.2% | — | **72.2%** |

Per task, head-to-head: Crestwood 12, 14, 15 → 20, 20, 16; Vanguard 7, 9, 8 → 8, 7, 7; CareIG 9, 8, 8 → 10, 9, 9.

Other settings:
- gpt-oss-120b as the agent: 33.3% alone → 39.9% with loop + guide. The agent model sets the ceiling.
- Without an SOP (AutomationBench, rules from data): neutral to negative. Switch SOP mode on only when an SOP is given.
- Leaderboard reference (full set, same metric = mean rubric score): Opus 5.5 52.3%, GLM 5.3 29.9%.

## Where it still loses points (loop + guide, 47 of 153 items)

Spreadsheet rows and values ~17 · message templates ~9 · Jira ticket counts and comments ~8 · holds still broken ~7 ·
duplicates ~4. Planned fixes: enforce hold/stop decisions in code, duplicate guard, per-case reviewer that reads back
the state, decision model (Kev-4B) for the typed questions.

## How to run (cuga-eval/benchmarks)

```
CUGA_ENV_FILE=cuga.fc.dsv4.env CUGA_SRC=<code snapshot>/src SOP_LOOP=1 \
HOOKS_MODULE=$PWD/handbook/guide_hooks.py:make_hooks POLICY_GUIDE_EVIDENCE=1 POLICY_MODEL_NAME=aws/gpt-oss-120b \
~/dev/cuga-agent-gate/.venv/bin/python -I handbook/run_cuga_handbook.py --tasks all --run <run> --arm B --trial 1 -j 3
```
- Intake of an SOP: `handbook/intake_one.py <task>` (needs the task's tool list: `handbook/dump_tools.py <task>`).
- Picture of a procedure graph: `handbook/render_sop_graph.py <build.json> <out.html>`.
- Loop questions model: `POLICY_LOOP_MODEL` (default azure/DeepSeek-V4-Pro); evidence model: `POLICY_GUIDE_MODEL`
  (default aws/gpt-oss-120b).

## Before claiming it

- Held-out test on the full HANDBOOK set (request to Surge drafted: `2026-11-02-surge-handbook-request-draft.md`).
- Nothing is committed yet (`~/dev/cuga-agent-gate`, branch `feat/policy-gate`; cuga-eval benchmark folders).

Flow pictures: `2026-11-03-loop-guide-flow-mobile.html`. Full log: `2026-11-02-overnight-log.md`, `history.md`.
