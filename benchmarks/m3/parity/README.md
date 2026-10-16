# M3 (VAKRA) cross-repo parity kit

Runs the **same train subset** on two stacks under identical settings and compares
them task by task:

| arm | stack | what runs |
|---|---|---|
| `cuga_eval_off` | this repo | cuga **main** (`../cuga-agent`), plain `CugaAgent`, adapter preset `off` |
| `cuga_eval_cap2` / `cuga_eval_cap3` | this repo | cuga main + `benchmarks/m3/adapter` preset |
| `vakra_main_base` | `~/git/appworld/vakra-main` | its `cuga_v2` adapter with every `VAKRA_CUGA_*` flag unset, over **its own CUGA checkout** |
| `vakra_main_fc_canon` | `~/git/appworld/vakra-main` | the submitted `fc_canon` recipe (`cuga_runs/fc_canon_test.sh`), FC only with `--fc 1` |
| `<any arm>_fc` | either | the same arm with native function calling on (`cuga_eval_cap3_fc`, `vakra_main_fc_canon_fc`, even `cuga_eval_off_fc`) |

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
| `parity_smoke_cap3` | 1 (beer_factory) | 1 | off 0 → cap3 1 (FC smoke) |
| `parity_est3_cap3` | 120 (22 domains) | 120 (vakra-main uuids) | **the campaign's cap3 train scorecard**: 68/120 = 56.7% (fc_canon + FC, 2026-08-18) |
| `parity_est3_smoke` | 2 | 2 | plumbing check for the est3 path |
| `parity_est3_ref30` | 30 (18 domains) | 30 (vakra-main uuids) | **cap3 reference**: 30 est3 tasks, campaign recorded 17/30 = 56.7% (its CodeAct + stepwise run: 51.7%) |
| `parity_est3_fresh30` | 30 (18 domains) | 30 (vakra-main uuids) | **cap3 confirmation set**: 30 more est3 tasks, disjoint from `parity_est3_ref30` (`make_reference.py --exclude-subset`), campaign recorded 17/30 = 56.7% |
| `parity_est2_ref30` | 30 (30 domains) | 30 (vakra-main uuids) | **cap2 reference**: 30 est2 tasks, campaign recorded 19/30 = 63.3% (scorecard 62.6%) |
| `parity_est2_fresh30` | 30 | 30 (vakra-main uuids) | **cap2 confirmation set**: 30 more est2 tasks, disjoint from `parity_est2_ref30`, campaign's recorded pass rate kept |
| `parity_est1_ref30` | 30 (22 domains) | 30 (vakra-main uuids) | **cap1 reference**: 30 est1 tasks, campaign recorded 17/30 = 56.7% (scorecard 56.3%) |
| `parity_est1_smoke3` | 3 | 3 | cap1 tool-binding smoke (2 selection-tool tasks, 1 slot-filling); campaign 3/3 rescored |

cap1 runs made before commit `1b993f8` do not measure the agent: the cap1 runner sent every
tool call to `get_data`. To check a cap1 arm, grep its `console.log` for `call_tool:`; the
names must match the recorded chain.

Campaign train numbers for the same recipes: cap2 62.6, cap3 56.7 **with FC**
(35 without); test: cap2 56.3, cap3 45.0.

## Isolation from other sessions (read first)

The cuga-agent repo's main checkout and cuga-eval's `.venv` are shared with other
sessions, which switch branches, re-sync and even re-lock at any time. Any of those
silently changes the CUGA a run imports (it happened mid-run on 2026-10-13). The kit
therefore runs in a private setup:

- `bash benchmarks/m3/parity/setup_pinned_cuga.sh <commit>` builds a linked
  worktree `../cuga-agent-parity` detached at `<commit>`, plus a kit-only venv
  (`parity/.local/venv`, synced from the committed `uv.lock`) with that worktree
  installed editable. Re-run it with a new commit to move to another CUGA.
- `env.sh` points every kit command at that venv (`UV_PROJECT_ENVIRONMENT`,
  `UV_NO_SYNC=1`). It also picks the kit's own registry port (18001 and up,
  `PARITY_REGISTRY_PORT` pins one), because `eval.sh` kills whatever holds its
  registry port and other sessions use the 80xx range.
- `preflight.sh` fails when CUGA comes from the main checkout
  (`cuga_identity.py`), and every cuga-eval arm stops before a domain whose CUGA
  differs from the one it started with.

## Run

```bash
bash benchmarks/m3/parity/run_parity.sh --subset parity_smoke_hockey --temperature 0.1   # stack check (~10 min)
bash benchmarks/m3/parity/run_parity.sh --subset parity_cap2_30                          # ~2 min/task/arm, serialized
bash benchmarks/m3/parity/run_parity.sh --subset parity_cap3_20 --fc 1                   # once cuga-agent#777 is in ../cuga-agent
bash benchmarks/m3/parity/run_parity.sh --subset parity_cap2_30 --dry-run                # print the commands only
```

`--fc-ab` runs the function-calling gate in one run and one report: arms
`cuga_eval_<preset>`, `cuga_eval_<preset>_fc`, `vakra_main_fc_canon`,
`vakra_main_fc_canon_fc`. The report's **FC effect** section gives FC off → on per
recipe (Δ, tasks gained/lost), on both stacks.

### Apples to apples with the VAKRA campaign (`parity_est3_cap3`)

`est3` is exactly the sample behind the campaign's cap3 train number (56.7%), and
the run reproduces its protocol: same 120 tasks, `fc_canon` + FC recipe,
`azure/gpt-oss-120b` agent and judge through the proxy, temperature 1.0,
policies off, the vendor evaluator, and on vakra-main 8-item chunks with a
container restart before each (as `cuga_runs/cap_estimate.sh` did).

- The tasks come from vakra-main's `data/train`, converted once into
  `parity/.local/vakra_train/` (gitignored — VAKRA data is never committed) by
  `prepare_vakra_train.py`. The same copy feeds the adapter's prose demos, as the
  campaign drew demos from the train domain files.
- cuga-eval runs it in predictions-only mode (`--no-ground-truth`): ground-truth
  mode only runs the registry YAML's small_train domains. The snapshot strips the
  registry's `<domain>_` tool prefix so the evaluator can replay the calls live.
- Arms (defaults): `cuga_eval_cap3_fc` (cuga + adapter) and
  `vakra_main_fc_canon_fc` (the campaign stack, rerun today), plus
  `vakra_main_campaign_recorded` — the campaign's own Aug-18 predictions,
  rescored today, which isolates judge/proxy drift from stack differences.
- Read the report's per-task section against the reference (the campaign's
  recorded outcomes): recorded-vs-rescored agreement is the judge's own
  noise floor.

```bash
bash benchmarks/m3/parity/run_parity.sh --subset parity_est3_smoke    # ~10 min plumbing check
bash benchmarks/m3/parity/run_parity.sh --subset parity_est3_cap3     # ~5-6 h, all three arms
```

### Reference benchmarks (`parity_est3_ref30`, `parity_est2_ref30`)

Small, fixed slices of the campaign's own scorecard samples, built by
`make_reference.py`: stratified by the campaign's recorded outcome, so each keeps
its scorecard's pass rate, and spread across domains. Each manifest carries the
recorded per-task verdicts, and the campaign's recorded predictions are rescored
next to the live arms. Any adapter change can be judged task by task against the
campaign at ~30 tasks per arm instead of 120.

Default arms are the campaign-runtime A/B: `cuga_eval_<cap>_fc@pre_parity` (the
adapter as it ran on 2026-10-12, via `variants/pre_parity.env`) against
`cuga_eval_<cap>_fc` (the presets as shipped). The report's **Variant effect**
section gives the paired delta; **Against the manifest reference** compares each
arm with the campaign's recorded verdicts, task by task.

```bash
bash benchmarks/m3/parity/run_parity.sh --subset parity_est3_ref30                 # ~2 h: A/B + recorded
bash benchmarks/m3/parity/run_parity.sh --subset parity_est3_ref30 --arms cuga_eval_cap3_fc,vakra_main_fc_canon_fc
```

Arm syntax: `cuga_eval_<preset>[_fc][@<variant>]`, where `<variant>` names a
file in `variants/` holding `M3_ADAPTER_<FIELD>` overrides:

- `pre_parity`: the adapter as it ran on 2026-10-12, before any campaign-runtime field.
- `stage1`: the first round of campaign-runtime fields, without the second round
  (bare tool names, the campaign's shortlister, tool cap 100, temperature pin,
  policy clearing). Run it against the shipped preset to measure the second round:
  `--arms cuga_eval_cap3_fc@stage1,cuga_eval_cap3_fc`.

### cap1 recovery pass

The official cap1 run re-ran its empty answers twice, in batches of 4 with a fresh
container each time, at a 300 s LLM timeout, 400 s per item and 200 s per universe
switch. Empties fell from 12.8% to 3.5%. `benchmarks/m3/cap1_recover.py` replays
that protocol on a cap1 run's results file and rewrites the submission files:

```bash
uv run --frozen python -m benchmarks.m3.cap1_recover --results <main run>/m3_task1_enterprise_incremental_<ts>.json \
    --output <dir> --container capability_1_bi_apis --adapter-preset cap1
```

For the main pass, the `cap1` preset already caps each item at 220 s; keep the
runner's own `--agent-timeout` above that (default 300) and pass
`--switch-timeout 150`, the campaign's universe-switch default.

Scoring follows the campaign's protocol (`rescore_chunked.py`, a port of
`cuga_runs/score_chunk_cap.py`): chunks of 5 tasks, each in its own evaluator
process after a fresh container restart, with a 300 s timeout and one retry. A
chunk that still fails is listed as `unscored_uuids` in `vendor_results.json`.
`PARITY_RESCORE_CHUNKED=0` restores one evaluator run per arm. The cuga-eval arm
also restarts the task container and probes the proxy before every domain, as
`cap_estimate.sh` did before each batch. A proxy still down after ~10 minutes
stops the arm, which can be resumed.

### Landing day (cuga-agent#777 merged)

1. `git -C ../cuga-agent checkout main && git -C ../cuga-agent pull`
2. `uv run --frozen pytest benchmarks/m3/tests -m "sanity or regression"` — the FC
   key-name test and the FC-binding test (a 200-tool domain must bind exactly the
   128 MiniLM-ranked tools) stop skipping on an FC checkout; both must pass.
3. `bash benchmarks/m3/parity/run_parity.sh --subset parity_smoke_cap3 --fc-ab --temperature 0.1`
   (1 task × 4 arms, ~10 min: the live FC path on both stacks).
4. The gate: `bash benchmarks/m3/parity/run_parity.sh --subset parity_cap3_20 --fc-ab`
   (~2–2.5 h at temperature 1.0). Campaign expectation: cap3 CodeAct → FC ≈ 35 → 55
   on train (vakra-main measured 44.6 → 56.7).
5. Leave `cuga_lite_bind_tools_max_count` at its default (128) — see
   `benchmarks/m3/ADAPTER.md`, *Execution mode*.

Keys: `PARITY_KEY=2` (or 3) makes `env.sh` read the `LITELLM_PROXY_API_BASE_2` /
`LITELLM_PROXY_API_KEY_2` slot of `~/git/appworld/.env` — use it when a key's
budget is exhausted.

`run_parity.sh` = `source env.sh <T>` → `preflight.sh` (containers, vendor
symlink, both venvs, both CUGA checkouts, FC availability, proxy probe — a
non-200/429 probe, or a 429 whose body says *Budget has been exceeded*, means
STOP: nothing will score; a plain 429 is just the ~1 request/key rate limit) →
the arms → `rescore.sh` → `compare.py`, which
writes `runs/<run_id>/REPORT.md`. Every arm records `meta.json` (commits, dirty
counts, flags, temperature). Everything resumes on re-run with the same
`--run-id`: cuga-eval arms run domain by domain and skip domains that already
have a prediction file (an eval.sh exit 3 — containers/daemon down — stops the
arm at once), vakra-main arms skip finished domains, rescoring recomputes.

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
