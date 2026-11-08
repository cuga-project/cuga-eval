# HANDBOOK integration check (2026-11-08)

Question: does the HANDBOOK adapter run end to end on the stable code with polisys `main` (after PR #3)? Not a gain test:
the 3 public tasks are a tuning set (graphs and mechanisms were built on them) and there is 1 trial.

Setup: snapshot `polisys-f88367e` (gate tag `policy/stable-v1` = `9135be1f4`), set `handbook-public3`, 1 trial, cache off,
`launchers/hb_integration_2026-11-08.sh`. Haiku 5.5 was never run on HANDBOOK before; it gets 400 steps
(`envs/pair.haiku55.handbook.env`, as Gemini) and the profile `experiments/handbook-haiku-graph-gate` (the Gemini
graph-gate profile with Haiku as the gate). gpt-oss keeps its measured profile and 70 steps.

| Agent | Arm | Crestwood | Vanguard | CareIG | Items | Cost |
|---|---|---|---|---|---|---|
| gpt-oss-120b | CUGA alone | 7/22 | 0/12 | 8/17 | 15/51 | $0.38 |
| gpt-oss-120b | loop + guide + evidence | 11/22 | 3/12 | 9/17 | 23/51 | $0.64 |
| Haiku 5.5 | CUGA alone | 20/22 | 6/12 | 10/17 | 36/51 | $0.22 |
| Haiku 5.5 | procedure tools + gate (Haiku) | 20/22 | 11/12 | 8/17 | 39/51 | $0.24 |

Integration: 12 of 12 runs finished with no error; every policy run wrote `audit.jsonl`; mechanisms fired (gpt-oss: 6
guide stops; Haiku: procedure tools used in 3 of 3 tasks, the gate checked 74 calls and blocked none). gpt-oss alone
stopped early on Vanguard (a stub workbook in 63 s).

Reading: gpt-oss 23/51 equals its earlier best (23 vs 20 of 51). Haiku alone is far above gpt-oss (36 vs 15). Haiku's +3
items come from the procedure tools, not the gate (no block), and CareIG went down 2; with 1 trial on 3 tuning tasks this is
inside the noise (earlier: 0 of 9 arm/task cells repeated over 3 trials). A gain claim needs new HANDBOOK tasks.
