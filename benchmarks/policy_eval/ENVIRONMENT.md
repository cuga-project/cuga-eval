# Policy evaluation: working environment

Where the code, environments, keys, ledger and results are. No key values are written here.

## Repos and branches

| Repo | Path | Branch | Role |
|---|---|---|---|
| cuga-agent-gate | `~/dev/cuga-agent-gate` | `policy/stable` | CUGA code with the policy layer (`src/cuga/policy_layer`). A linked worktree of `~/dev/cuga-agent`. |
| cuga-eval | `~/dev/cuga-eval` | `evaluation-work` | The harness (one runner), benchmark modules, offline tools, results of offline replays, docs. |
| cuga-eval-tau2 | `~/dev/cuga-eval-tau2` | `exp/tau2-policy-runner` | Linked worktree of cuga-eval: the code and venv that the τ² adapter runs on (see the τ² section). |

- Code work happens in `cuga-agent-gate` only. Never edit or switch branches in `~/dev/cuga-agent`.
- The `best/*` branches of `cuga-agent-gate` are the code of measured results. Keep them. Do not rebase or delete.
- Everything is committed locally. Nothing is pushed.
- Never run `git checkout -- <file>` or `git restore` in `cuga-eval`: uncommitted live files were lost that way before. Read `git status` and `git diff` first.
- Every change to the policy system is logged in `benchmarks/policy_eval/changes.md`.

## Virtual environments

| Venv | Python | `cuga` comes from | Used for |
|---|---|---|---|
| `~/dev/cuga-agent-gate/.venv` | 3.12 | `~/dev/cuga-agent-gate/src` (editable) | unit tests of the policy layer, the harness parent, the children of IT service tasks and of HANDBOOK, offline replays and tools in `policy_eval/` |
| `~/dev/cuga-eval/benchmarks/automationbench/.venv` | 3.13 | `~/dev/cuga-agent/src` (editable); a snapshot overrides it: the harness puts it first on the path | the children of AutomationBench tasks, with `AutomationBench` installed |
| `~/dev/cuga-eval-tau2/.venv` | 3.13 | `~/dev/cuga-agent/src` (editable); a snapshot overrides it: the harness puts it first on the path | the children of τ² tasks, with `tau2` installed |

`~/dev/cuga-eval/.venv` (Python 3.13) also exists. It is the general cuga-eval environment (AppWorld and other benchmarks), not used by the policy work.

How a run is started and how it takes a code snapshot is in "One runner" and "Code snapshots" below.

## Environment files and keys

- Model and feature settings are composed from layers in `benchmarks/policy_eval/envs/`, last wins:

| Layer | File | Holds |
|---|---|---|
| base | `base.env` | the function-calling agent: settings every run shares |
| model | `model.gptoss.env`, `model.dsv4.env`, `model.gemini38.env` | `MODEL_NAME`, `AGENT_SETTING_CONFIG` |
| benchmark | `bench.automationbench.env`, `bench.itsm.env`, `bench.handbook.env`, `bench.tau2.env` | benchmark mode (`itsm` sets no key); τ²: a conversation, so the agent is not autonomous, and tools stay in the process |
| pair (optional) | `pair.gemini38.handbook.env` | `CUGA_LITE_MAX_STEPS=400`: Gemini on HANDBOOK needs 400 steps |
| `extra` | argument of `compose` | a dict; it wins over every layer; a value `None` removes the key |

- `compose(model, bench, extra) -> Path` (`envs/compose_env.py`) writes `$TMPDIR/cuga_eval_envs/cuga.<model>.<bench>.<hash>.env` and returns the path; the harness sets `ENV_FILE` to it for each child. Equal settings give the same path. A key name with KEY, TOKEN, SECRET or PASSWORD, or a value that looks like a key, is refused.
- Settings that are not in a layer are `extra`: dynamic tool binding on the full toolset (`DYNACONF_ADVANCED_FEATURES__CUGA_LITE_FC_DYNAMIC_TOOLS: "apps"`, in both AutomationBench best profiles); CodeAct instead of function calling (`CUGA_LITE_EXECUTION_MODE` and `CUGA_LITE_FC_PROMPT_FRAGMENTS` set to `None`); and the oldest text agent (verify gate on, and five more keys set to `None`). τ² leaves the tool-call caps, summarization and one sandbox key at the agent's defaults, as its old runner always did. The constants `FC_DYNAMIC`, `NO_FC`, `TEXT_AGENT`, `TAU2_AGENT` in `compose_env.py` hold them.
- `MODEL_NAME` is a run setting. It comes from the model layer of the composed file (`--model` of the harness picks the layer). The harness reads it as the agent's model (`agent_model` of the runtime, the level choice, the model of the agent's usage when a receipt names none). The policy layer does not read it, and a model client with no name raises.
- The old per-benchmark `cuga*.env` files are in `launchers/archive/envs/<benchmark>/`, as a record. They hold no secrets. Before they moved, the layers gave the same key/value pairs for 13 of the 20 (0 differences, read as the old runners read them and with python-dotenv). 7 had no overlay for their agent model: `cuga.fc.flashlite.env`, `cuga.fc.gpt5mini.env`, `cuga.fc.nemo.env` (AutomationBench and EnterpriseOps-Gym) and `automationbench/cuga.env` (GLM-5.3-Flash baseline, 1800 s timeout, verify gate on). A run on one of those models needs a new `model.<name>.env` layer. The check itself (`compose_env.py --check`, `OLD_FILES`) lives at the tag `policy/pre-migration-removal`.
- Secrets are in `~/dev/cuga-eval/.env` (git-ignored). Names used by the runners: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENROUTER_API_KEY`, and the `LANGFUSE_*` variables (the harness does not pass those to its children). `~/dev/cuga-eval/.env.example` shows the layout. `~/dev/cuga-eval-tau2/.env` is a symlink to `~/dev/cuga-eval/.env` (one file, not a second copy).
- These names and `OPENAI_BASE_URL` are all that the policy layer reads from the environment: the secret of its small models and the decision model, the gateway address, and every secret-looking variable, whose values the audit keeps out of its lines. No policy setting comes from there. `tests/test_runtime_assembly.py` (`ALLOWED_READS`) names each read.
- Several `OPENAI_API_KEY` lines (some commented) can exist in `.env`, one per LiteLLM key. `benchmarks/enterpriseops_gym/pick_key.py <sha256 prefix>` prints the one whose hash starts with the prefix. Use it only inside command substitution, as `export OPENAI_API_KEY=$(python3 -I pick_key.py <prefix>)`. Never echo a key, never print `.env`, never commit either.
- The ignore rules cover `.env`. Before every commit, check that no key, token or `.env` content is staged.

## Cost ledger

- `benchmarks/policy_pilot_ledger.jsonl`: one line per costed call group (run, task, tokens, cost). The harness and the offline tools append to it through `benchmarks/policy_pilot_costs.py`.
- `benchmarks/policy_pilot_costs.py` holds the prices and the budget cap (`POLICY_PILOT_BUDGET`, default in the file). Check the spent total before any run.

## Where results live

| What | Where | In git |
|---|---|---|
| Old AutomationBench runs | `benchmarks/automationbench/results/<run>/` | no (ignored) |
| Old EnterpriseOps-Gym runs | `benchmarks/enterpriseops_gym/results/<run>/` | no (ignored) |
| Old HANDBOOK runs | `benchmarks/handbook/results/<run>/` | no (ignored) |
| Old τ² runs | `~/dev/cuga-eval-tau2/benchmarks/tau2/logging_<tag>_<arm>_s<i>/` (`results/`, `trajectory_data/`, `usage.jsonl`) | no |
| Runs of the harness, any benchmark | `benchmarks/policy_eval/harness/results/<run>_t<trial>/` (`<task>.json` in the common schema, `logs/`, `trajectories/`, `work/<task>/`, which holds `audit.jsonl`: one line for each decision of the policy layer, 13 fields, none for a baseline run) | no |
| Run stdout and parent logs | `*.out`, `*_parent.log`, `*.log` | no (ignored) |
| Offline replays, rule audits, builds, tests | `benchmarks/policy_eval/<tool>/` (for example `rule_audit/`, `store_gate_replay/`, `builds_v4/`) | yes |
| Summary of what was tried and measured | `benchmarks/policy_eval/changes.md`, `docs/analysis/` | yes |

## Task sets

`benchmarks/policy_eval/sets/registry.json` lists every tuning and held-out task set and which agent model has run its tasks. `python3 benchmarks/policy_eval/sets/build_registry.py` rebuilds it from the set files and the result folders and prints, per model, the held-out sets that model has not run. Run it again after new results.

- Entry: `id`, `benchmark` (`automationbench`, `itsm`, `handbook`, `tau2-telecom`, `tau2-airline`), `path` and `key` (where the task ids are; `build_registry.task_ids(entry)` reads them), `rule`, `seed`, `n`, `status` (`tuning` or `heldout`, the role the set was made for), `seen_by` (`{model: [run prefixes]}`) and `seen_n` (`{model: number of the set's tasks it ran}`).
- `seen_by` is matched by benchmark and task id, never by run name. Every result file counts, also an errored, smoke or discarded run, because the model has read the task. The model is the agent model: `model` in AutomationBench and EnterpriseOps-Gym results, `agent_model` in τ² results, `receipt.models` in HANDBOOK results (their `model` is null). A result with no determinable model would be listed under `unknown` (there is none today). The policy-layer models (gate, tracker, detector) are not counted.
- A run prefix is the result folder name without the trial suffix (`ph_AF_t1` becomes `ph_AF`); for τ² it is the logging folder without `logging_` and the shard (`logging_test1_A_s0` becomes `test1_A`).
- `handbook-public3` has no set file: its ids are in the script and `path` is the untrusted sample folder, which the script does not open.
- Before using a held-out set for a decision, read `seen_by` and `seen_n` for the model you use, and the list of sets that share tasks (printed at the end of the script output).

## One runner: the harness

`benchmarks/policy_eval/harness/`: `run.py` (runner), `result.py` (schema, reader of the old files), `report.py`, `adapters/`. It is the only way to run a benchmark with the policy system. An adapter gets the benchmark logic from a module of its benchmark: `automationbench/ab_env.py`, `enterpriseops_gym/eog_env.py`, `handbook/hb_env.py`, and for τ² the code of the τ² worktree (see its section).

```
~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/harness/run.py \
    --bench itsm --profile itsm-rules --set itsm-unseen --snapshot <name> --trial 1 --run <run> -j 4
python3 -I benchmarks/policy_eval/harness/report.py --runs <arm> <arm>      # also over old result folders
```

- The parent needs `python-dotenv`, so start it with a venv. It starts each task's child in that benchmark's venv (`adapter.python`). HANDBOOK children run with `-I`.
- `--bench` is `automationbench`, `itsm`, `handbook` or `tau2`. `--profile` is a file name in `profiles/`. `--set` is an id of `sets/registry.json`; `--tasks` picks some of its tasks. `--snapshot` is required: a missing snapshot stops the run for every benchmark, and a child whose `cuga` would come from anywhere else refuses to start. `code_sha` comes from `SOURCE.txt`. `--model` is the model layer (default `gptoss`). `--proxy` sets `OPENAI_BASE_URL` (the old AutomationBench runner used `retry_proxy.py` by default; the harness calls the gateway unless told). The AutomationBench adapter uses the full toolset, as the measured `-F` arms did.
- A run folder holds one code and one profile. A scored result with another `code_sha` or `profile_hash` stops the run before any task starts; `--rerun-mismatch` runs such tasks again and replaces their files. `report.py` prints both values per arm and marks an arm with more than one.
- Nothing about the experiment comes from the environment: the profile sets the policy layer, the composed env file sets the agent, and `POLICY_*`, `SOP_*`, `HOOKS_*`, `HB_*` and `LANGFUSE_*` do not reach the children.
- Not graded, with `error` and no score, and not counted by the report: `wiring: ...` (`RuntimeWiringError`; a task whose policy version has no package), `not run: ...` (the task could not be prepared), `gateway: ...`, `grader: ...`. The parent exits with code 2, and a later start with the same run name runs those tasks again. An agent error or a timeout is graded, as in the old runners. An error on any turn stays in the result and ends the turns, also in the middle of a τ² conversation or of a loop. `INFRA_ERRORS` in `run.py` is the list of gateway errors: 403, 429, 5xx, timeouts of a call, connection errors.
- Agent time per task without `--timeout`, `adapter.default_timeout`: what each benchmark has used, because one value for all would stop long runs and grade what they left, with no error.

| Benchmark | Default | Old runner | Old runs that took longer than 1800 s |
|---|---|---|---|
| HANDBOOK | 3600 s | 3600 s | 4 of 414 |
| ITSM | 1200 s | 1200 s | 0; the longest took 868 s |
| AutomationBench | 1800 s | 1800 s | the same limit |
| τ² | 1800 s | **no limit** | 0 of 430; the longest took 826 s. This is the one difference |

- A result names what it ran on: `code_sha` (the snapshot), `profile_hash`, `package_version` (`<version>+<file hash>`) and `env_hash` (the composed env file, so a changed `base.env` shows).
- After a run: `python3 -I benchmarks/policy_eval/tools/scan_run.py <run> ...` looks in trajectories and logs for an agent that read answers or looked outside its workspace. Exit code 1 means there is something to read.
- `EVAL_NO_SKIP=1` turns each skip of `tests/test_harness.py` into a failure: saved folders and venvs are not in git, and on another machine the regression tests would pass by skipping.
- A run name of the report finds `<name>`, `<name>_t<n>`, `<a>_<x>_<b>_t<n>` for `<a>_<b>` (`hbq_A` finds `hbq_ci_A_t1`) and `logging_<name>_s<n>`. An old folder that holds two arms needs `<name>:<arm>`. Arms of one experiment share the first word of their name: it groups them, and each group is reported with the role of its task set.
- Ledger: one line per component, with `component` and `model`. `costs.record` refuses usage that names no model. The τ² user simulator is a component.

## Launchers and the old routes

Run with `harness/run.py`. No live launcher stays. `benchmarks/policy_eval/launchers/archive/` holds, as a frozen record of what past runs executed, these scripts with their history (`git mv`). None of them is updated, and most no longer run where they are: they name paths that moved, and they read code that is gone.

| Files | What they were |
|---|---|
| `run_cuga.py`, `run_cuga_eog.py`, `run_cuga_handbook.py` | The old runners. The benchmark logic that the adapters need moved, unchanged, to `ab_env.py` and `hb_env.py` |
| `run_policy_types.sh`, `run_all.sh`, `watch.sh`, `run_store_task.sh`, `run_store_task_oss.sh`, `run_hbq.sh`, `launch_paired.py`, `run_arm_a.py` | Launchers of those runners and of τ² |
| `run_pg_frozen.sh`, `run_ph_frozen.sh`, `run_pv5_frozen.sh`, `run_pv5b_frozen.sh` | Frozen copies from before. They name `/tmp/cuga_snapshots` |
| `guide_hooks.py`, `plan_hooks.py`, `tracker_hooks.py` | Factories for `HOOKS_MODULE` of the old HANDBOOK runner |
| `dump_agent_prompt.py`, `shadow_replay.py`, `validate_hooks.py`, `validate_injection.py` | Tools that ran an old runner's `run_one` or took its `child_env`, and read policy switches |
| `envs/<benchmark>/cuga*.env` | The old env files (see above) |

Everything old stays reproducible from local tags. Nothing is pushed. `policy/pre-migration-removal` marks the last commit with the old path: on the gate repo `b81fcf3e5`, on this repo `23b8b089`. `policy/pre-migration-removal-tau2` on this repo marks `2722169a` of the τ² branch. To use an old route, unpack both (never `git worktree` or `git gc` in the gate repo):

```
git -C ~/dev/cuga-agent-gate archive <gate commit> src | tar -x -C <temp>/gate
git -C ~/dev/cuga-eval archive policy/pre-migration-removal benchmarks | tar -x -C <temp>/eval
```

Then link what is not in git into the unpacked `benchmarks/` (`.venv`, results, `vendor`), link `.env` into `<temp>/eval/`, replace the unpacked `benchmarks/policy_pilot_ledger.jsonl` with a link to the live one (otherwise a paid run writes its cost to the copy and the budget cap does not count it), and start the runner with `CUGA_SRC=<temp>/gate/src`. The measured code of a best result is on its `best/*` branch.

| Old route | It ended at | Where it lives |
|---|---|---|
| Arm D-F, the request checklist as the hook `DeliverablesHooks` (`POLICY_DELIVERABLES=1`): runs `pt_DF_t1/2`, `dlv_A_t*`, `dlvu_A_t*`, `u3_C_t*`, `itdlv_t1`, `itdlvu_t1` | This branch. A profile gets the producer `request` of the obligation ledger instead, which is not the same wiring | Gate commit `675dc1756` plus the old runner at the tag |
| Every arm set by switches of `POLICY_*`, `SOP_*`, `HOOKS_*`, `HB_*` | This branch. A measured arm has a profile; the others can be written as one | The tag. The table of each switch and its config field, and the gaps, are the docstring of `config_from_env` at the tag (`src/cuga/policy_layer/policy_config.py`) |
| Oracle arm: the grader's failed checks go back to the agent (`POLICY_ORACLE`), an upper bound | This branch: no profile can do it, on purpose | Old runners at the tag |
| AutomationBench `--toolset limited_zapier` and `api` (arm A-O), `--arm` labels, plain-model baseline of `run_all.sh` | This branch | Old runner and launchers at the tag |
| SOP planner spikes and the tracker as a factory on HANDBOOK (`plan_hooks.py`, `tracker_hooks.py`) | This branch | The tag |
| `golden_hooks.py capture`, which wrote `profiles/golden_hooks.json` from the old runners | This branch. `check` stays, and the JSON is the frozen reference. `profiles/golden_other_configs.json` holds the configs of the cases that no profile uses, written once by `config_from_env` | The tag |
| `compose_env.py --check` against the old env files | This branch | The tag |

`best_profiles.json` keeps `runner`, `recipe`, `switches` and `env_file` as the record of what was measured.

Live tools that still read a name of the old switches, outside the policy layer and the harness: `POLICY_MODEL_NAME` as the default of `--model` in `enterpriseops_gym/build_rules.py` and `--policy-model` in `deliverables_replay.py`, and as the fallback model of `policy_pilot_costs.record` for usage that names none; `HB_BUILDS` as the output folder of `handbook/intake_one.py`. `POLICY_GATE_PYTHON` (tests) is a path and `POLICY_PILOT_BUDGET` is the spending cap.

## τ² stays a separate worktree

`~/dev/cuga-eval-tau2` (branch `exp/tau2-policy-runner`) is a linked worktree of this repo with its own `.venv`. The τ² adapter runs its children there. It is not merged into `evaluation-work`, for two reasons:

- The τ² library is a separate editable checkout (`benchmarks/tau2/tau2-bench`, pinned by `setup_tau2.sh`, git-ignored) that `pyproject.toml` and `uv.lock` register there only. Upstream `pyproject.toml` has no such entry, so that a fresh `uv sync` works; installing τ² into the other venvs would change their locked dependencies.
- τ² runs the orchestrator, the user simulator and CUGA in one process and allows one worker per process. The harness starts one process per task, from one code snapshot, so `-j N` is the parallelism. The old folders of results are `~/dev/cuga-eval-tau2/benchmarks/tau2/logging_<tag>_<arm>_s<i>/`.

What is committed there: the runner `benchmarks/tau2/cuga_runner.py`, the `logging_*/` ignore rule, and the `pyproject.toml` / `uv.lock` registration of `tau2` (a local-only commit; do not cherry-pick it into a PR). The `logging_*/` folders stay on disk and are ignored.

The runner stays as benchmark logic. The adapter imports `_MESSAGE_TOOL`, `_patch_tau2_nl_assertion_model` and `_populate_sim_outputs` from it, and the bridge and the proxy from their modules. `harness/adapters/tau2.py` has its own loop and join (differences from `run_cuga_loop` and `_run_one_task` are listed in change 142). The old loop, with its `SOP_*` reads, is still in the file because the worktree's own tests and `eval_tau2_sdk.py` use it, and `test_runtime_golden.py` compares its hand-off guard with `HandoffGuard`. Nothing in `evaluation-work` starts it.

## Code snapshots

A run takes its CUGA code from a frozen copy of the gate worktree, so that editing `~/dev/cuga-agent-gate` does not change a running experiment.

- Create: `benchmarks/policy_eval/snapshot_src.sh <name>` copies `~/dev/cuga-agent-gate/src` to `~/dev/cuga_snapshots/<name>/src` and prints that path.
- Use: `policy_eval/harness/run.py --snapshot <name>`. The child puts the snapshot first in `sys.path` and refuses if `cuga` still comes from elsewhere, and each result holds `code_sha`.
- A missing snapshot stops the run, for every benchmark, before any task starts.
- To see which code a command would import: `PYTHONPATH=<snapshot>/src ~/dev/cuga-agent-gate/.venv/bin/python -c "import cuga; print(cuga.__file__)"`.
- Of the old results, only AutomationBench results record the snapshot (`provenance.cuga_source`). For the others, the snapshot is in the run name or in `changes.md`.
- `~/dev/cuga_snapshots/<name>/SOURCE.txt` has two lines: the short commit sha and the number of uncommitted entries.
- A dirty gate tree is an error. `--allow-dirty` overrides it and records the count; a snapshot with a count above 0 is not described by its sha. Commit first, then snapshot. Use a name that includes the sha, for example `stable-df870b97f`.
- Re-using a name replaces that snapshot. Do not re-use the name of a snapshot that a running experiment uses.
- Snapshots from before 2026-11-04 are in `/tmp/cuga_snapshots/` (lost on restart). They are not copied. The code of a measured result is on the `best/*` branches of `cuga-agent-gate`; check one out in a separate location and snapshot it if that code is needed again. The frozen launchers in `launchers/archive/` and the logs of old runs still name `/tmp/cuga_snapshots`.
