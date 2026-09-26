# M3 (VAKRA) cross-repo parity kit

Runs the **same train subset** on two stacks under identical settings and compares
them task by task:

| arm | stack | what runs |
|---|---|---|
| `cuga_eval_off` | this repo | cuga **main** (`../cuga-agent`), plain `CugaAgent`, adapter preset `off` |
| `cuga_eval_cap2` / `cuga_eval_cap3` | this repo | cuga main + `benchmarks/m3/adapter` preset |
| `vakra_main_base` | `~/git/appworld/vakra-main` | its `cuga_v2` adapter with every `VAKRA_CUGA_*` flag unset, over **its own CUGA checkout** |
| `vakra_main_fc_canon` | `~/git/appworld/vakra-main` | the submitted `fc_canon` recipe (`cuga_runs/fc_canon_test.sh`), FC only with `--fc 1` |

Same model and judge on both sides (`azure/gpt-oss-120b` through the proxy in
`~/git/appworld/.env`, never printed), same temperature (default **1.0**, the
campaign setting; this repo's default is 0.1), policies off (as the campaign
ran), arms strictly sequential (one registry port, ~1 request/key), and **one
evaluator for every arm**: the other repo's official `evaluator/evaluator.py`
with live tool replay, against its `data/train` ground truth cut to the subset.
Each stack's native in-run judgement is kept as a secondary column.

## Subsets

The two datasets hold the same tasks under **different uuids** and record
formats (this repo's `small_train.zip` vs `vakra-main/data/train`), so the
subsets are mapped by normalized first-turn query text
(`manifests/uuid_map_*.json`). Manifests carry only ids and pass/fail flags.

| subset (`--eval-key`) | tasks | mapped to the other repo | reference on this stack (2026-09-10, native judge, t=0.1) |
|---|---|---|---|
| `parity_smoke_hockey` | 1 | 1 | off 0 → cap2 1 |
| `parity_cap2_30` | 30 (10 domains × 3) | 28 | off **30.0%** → cap2 **63.3%** |
| `parity_cap3_20` | 20 (10 domains × 2) | 19 | off **20.0%** → cap3 **35.0%** |

Campaign train numbers for the same recipes: cap2 62.6, cap3 56.7 **with FC**
(35 without); test: cap2 56.3, cap3 45.0.

## Run

```bash
bash benchmarks/m3/parity/run_parity.sh --subset parity_smoke_hockey --temperature 0.1   # stack check (~10 min)
bash benchmarks/m3/parity/run_parity.sh --subset parity_cap2_30                          # ~2 min/task/arm, serialized
bash benchmarks/m3/parity/run_parity.sh --subset parity_cap3_20 --fc 1                   # once cuga-agent#777 is in ../cuga-agent
bash benchmarks/m3/parity/run_parity.sh --subset parity_cap2_30 --dry-run                # print the commands only
```

`run_parity.sh` = `source env.sh <T>` → `preflight.sh` (containers, vendor
symlink, both venvs, both CUGA checkouts, FC availability, proxy probe — a
non-200/429 probe, or a 429 whose body says *Budget has been exceeded*, means
STOP: nothing will score; a plain 429 is just the ~1 request/key rate limit) →
the arms → `rescore.sh` → `compare.py`, which
writes `runs/<run_id>/REPORT.md`. Every arm records `meta.json` (commits, dirty
counts, flags, temperature). Arms and the rescoring resume on re-run.

Pieces can be run alone after `source benchmarks/m3/parity/env.sh`:
`run_cuga_eval_arm.sh <run> <subset> <preset>`, `run_vakra_main_arm.sh <run>
<subset> base|fc_canon`, `rescore.sh <run> <subset>`,
`python -m benchmarks.m3.parity.compare --run runs/<run> --subset <subset>`.

## Reading the report

- **Port fidelity** is `cuga_eval_<preset>` vs `vakra_main_fc_canon`: per-task
  agreement on the mapped tasks. With `--fc 0` (today) both sides run CodeAct;
  expect parity within judge noise on cap2 (FC adds ~nothing there) and a
  no-FC number on cap3 (~35) on both sides. With `--fc 1` cap3 should climb
  toward the campaign ~56 on both.
- **Baseline drift** is `cuga_eval_off` vs `vakra_main_base`: the other stack
  runs a February-2026, locally modified cuga-agent checkout, this one runs
  cuga main — differences here are informative, not a port bug.
- **Against the reference** compares this stack's arms with the 2026-09-10
  per-uuid outcomes (different judge run and temperature 0.1 then).
- Judge variance is real: n < 30 or a delta under 3 points is noise (the report
  says so per row); never conclude from a single task.

## Known differences between the stacks (check these first if numbers diverge)

- **CUGA version**: `../cuga-agent` (main; the FC pre-stage needs cuga-agent#777)
  vs `~/git/appworld/cuga-agent-main` (Feb 2026, dirty working tree) — both
  recorded in `meta.json`.
- **cap2 verbatim rule**: this repo's `cap2` preset sets `cap2_verbatim`
  (`VAKRA_CUGA_CAP2_VERBATIM`); the submitted `fc_canon_test.sh` does not export
  it. Add it to the other arm with
  `PARITY_VAKRA_EXTRA_FLAGS="VAKRA_CUGA_CAP2_VERBATIM=1"` to test that hypothesis.
- **Canonicalization**: in-graph `final_answer` function here vs the vendored
  CUGA's `FINAL_ANSWER_CANONICALIZE` dynaconf flag there.
- **Demos**: both use k=2 prose demos; this repo draws them from `small_train.zip`
  (the subset's own split — the run warns about it), the other from its full
  `data/train` domain file.
- **Policies** are off on both sides; the cap1–3 presets normally load the M3
  policy set (`use_policy_system=True`), so parity arms pass `--no-policies`.
- **Tool universe**: identical containers; both stacks emit bare MCP tool names.

## Data & secrets

No benchmark data or ground truth lives here — manifests hold uuids and
pass/fail flags only; ground truth is read at run time from the other repo.
`runs/` and `.local/` (generated model TOMLs) are gitignored. Scripts read the
proxy credentials from `~/git/appworld/.env` and never echo them.
