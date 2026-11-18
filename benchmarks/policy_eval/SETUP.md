# Setup on a new machine

How to run EnterpriseOps-Gym tasks (HR and IT service) with the policy harness on another machine. Checked on 2026-11-17 on fresh
clones of the three repositories from GitHub, a fresh virtual environment and a fresh snapshot, up to the benchmark server.

## What you need

- Python 3.12, [uv](https://docs.astral.sh/uv/), git, Docker.
- An OpenRouter key, or any OpenAI-compatible endpoint that serves the model you choose.

Every block below starts in the folder that holds the three repositories. Set it once:

```bash
export ROOT=~/dev        # any folder; the three repositories go side by side in it
mkdir -p "$ROOT"
```

## 1. Repositories

```bash
cd "$ROOT"
git clone https://github.com/cuga-project/cuga-eval.git    && git -C cuga-eval  checkout policy-eval
git clone https://github.com/cuga-project/cuga-agent.git   && git -C cuga-agent checkout policy/integration
git clone https://github.com/cuga-project/polisys.git      # main
```

- cuga-eval: use `main` once this branch is merged.
- cuga-agent `policy/integration` is `main` plus the open pull requests for lifecycle hooks, dynamic tool binding and the claim retry;
  it holds no policy code.
- polisys is the policy layer. Its `main` has the finish check and the code guards that the HR profiles `experiments/sw-*` use
  (polisys #10, merged 2026-11-17 as `9942191`); an older polisys stops those profiles with `PolicyConfigError: unknown key`.
  Both arms of a comparison must run on one snapshot (step 6) made from this checkout.

## 2. Python environment

One venv holds the agent, polisys and everything the benchmark's environment module imports. The agent's packages come from
`cuga-agent`'s `uv.lock`, so a run uses the versions that CI tests:

```bash
cd "$ROOT/cuga-agent"
uv sync --frozen                                              # the locked versions into .venv, on the Python of .python-version
uv pip install --python .venv/bin/python -e ../polisys        # polisys on top
export HARNESS_PYTHON="$ROOT/cuga-agent/.venv/bin/python"     # the Python of the harness children
```

Do not install the agent with `uv pip install -e .`: it ignores the lock and takes the newest version each package allows (#220; among
others the Langfuse client 5.x, whose scores a Langfuse 3.x server rejects). Afterwards `uv run` and `uv sync --inexact` keep polisys; a
plain `uv sync` removes it, so repeat the second command after one.

No other package is needed: `benchmarks/enterpriseops_gym/eog_env.py` imports from the benchmark's own clone (step 3) and the packages it
uses come with the agent. If `HARNESS_PYTHON` is not set, the harness uses the interpreter that started it.

## 3. The benchmark's clone

Our runs used this commit of the benchmark. Unzip the task databases inside the clone (the benchmark's README asks for this too); without
them every tool call fails with `x-database-id header required` and the harness stops the task with an error:

```bash
cd "$ROOT"
git clone https://github.com/ServiceNow/EnterpriseOps-Gym.git cuga-eval/benchmarks/enterpriseops_gym/vendor/EnterpriseOps-Gym
git -C cuga-eval/benchmarks/enterpriseops_gym/vendor/EnterpriseOps-Gym checkout 271f2c3
(cd cuga-eval/benchmarks/enterpriseops_gym/vendor/EnterpriseOps-Gym && unzip -q gym_dbs.zip)
```

`vendor/` is git-ignored. The harness imports the benchmark's MCP client and its verifier from this clone, so tasks are graded by
the benchmark's own code. If the clone is not in this folder, a task stops with an error that names the expected path.

## 4. The benchmark servers

Each person runs their own containers, one per domain. The images are the benchmark authors' (the clone's README names them); the tag
`latest` moves, so write down the image ID of your run (`docker image inspect <image> --format '{{.Id}}'`).

```bash
# HR
docker run -d --name eog-hr --memory 4g -p 127.0.0.1:8008:8005 shivakrishnareddyma225/enterpriseops-gym-mcp-hr:latest
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8008/health      # 200 when it is up
export EOG_HR_URL=http://127.0.0.1:8008

# IT service (ITSM), only for --bench itsm
docker run -d --name eog-itsm --memory 4g -p 127.0.0.1:8006:8005 shivakrishnareddyma225/enterpriseops-gym-mcp-itsm:latest
export EOG_ITSM_URL=http://127.0.0.1:8006
```

The memory limit matters: at 2 GB a container was killed when 20 tasks ran in parallel. Each task seeds its own database from the clone
and deletes it at the end.

## 5. Keys, model and cost

Keep the key in your shell or in the git-ignored `.env` of the repo root; never write it into a tracked file.

```bash
export OPENAI_API_KEY=<your OpenRouter key>  # pragma: allowlist secret
```

Model layers: `--model orhaiku55` (Claude Haiku 5.5) and `--model orgptoss` (gpt-oss-120b), both with
`--proxy https://openrouter.ai/api/v1`. Other layers in `policy_eval/envs/model.*.env` use the original LiteLLM gateway and need its
key and address. Scores through OpenRouter are not comparable with those of the gateway routes.

Every costed call is appended to `benchmarks/policy_pilot_ledger.jsonl`, a local git-ignored file that the first call creates.
The budget cap is `POLICY_PILOT_BUDGET` in dollars (default in `benchmarks/policy_pilot_costs.py`); set your own before a large run.

## 6. The code snapshot

A run takes its code from a frozen folder, so that editing a repo does not change a running experiment:

```bash
cd "$ROOT/cuga-eval"
benchmarks/policy_eval/snapshot_polisys.sh ../polisys ../cuga-agent     # prints polisys-<sha>-cuga-<sha>
export SNAP=<the name it printed>
```

Both repos must have no uncommitted changes to tracked files. The folder is `~/dev/cuga_snapshots/<name>` (`CUGA_SNAPSHOT_ROOT` changes it),
and `SOURCE.txt` in it names both branches and commits. Every result file records the snapshot as `code_sha`; a folder of results holds one
snapshot and one profile, and the harness stops a run that would mix two.

## 7. Run one task with and without the policy system

One HR task, CUGA alone (`baseline`) and with the finish check and code guards (`experiments/sw-codeguards`), then the comparison.
Both runs share the prefix of their names (`mine_` here): the report puts runs with one prefix side by side.

```bash
cd "$ROOT/cuga-eval/benchmarks/policy_eval"
T=task_20251224_133749_739_c4ad7a70_9df76270     # a task of the set hr-adv-dev5
for A in base:baseline sw:experiments/sw-codeguards; do
  $HARNESS_PYTHON -I harness/run.py --bench hr --set hr-adv-dev5 --tasks $T --profile ${A#*:} \
    --snapshot $SNAP --trial 1 --run mine_${A%%:*} --model orhaiku55 -j 1 --proxy https://openrouter.ai/api/v1
done
$HARNESS_PYTHON -I harness/report.py --runs mine_base mine_sw
```

- `--bench` is `hr`, `itsm`, `csm`, `automationbench`, `handbook` or `tau2`; `--set` is a set id of `sets/registry.json` for that
  benchmark. Without `--tasks` the whole set runs. To list the tasks of a set:
  `$HARNESS_PYTHON -I -c "import sys; sys.path.insert(0, '..'); from policy_eval.harness.adapters.itsm import HrAdapter; print(*HrAdapter().task_ids('hr-adv-dev5'), sep='\n')"`
  (use `ItsmAdapter` and `itsm-pilot` for IT service).
- HR sets: `hr-smoke` (one task, for wiring checks) and `hr-adv-dev5` are tuning sets; the held-out sets (`hr-val7`, `hr-ts-test-*`,
  `hr-heldout`) are run only as the registry says (see "Working in parallel").
- `--profile baseline` is the agent alone (no policy); the other files in `profiles/` and `profiles/experiments/<name>` are policy arms.
- Results: `harness/results/<run>_t<trial>/<task>.json` (score and the benchmark's verifier checks), `trajectories/`, `logs/`,
  and `work/<task>/audit.jsonl` (what the policy system did).
- A task with a result is skipped on a second start, unless it errored or has no score. A task that stops before grading shows
  `not run: <reason>` and has no score.

## Other checkouts the code can read

- `TAU2_WORKTREE`: the cuga-eval checkout with tau2-bench, for the τ² adapter and set builder (default `~/dev/cuga-eval-tau2`).
- `HANDBOOK_SAMPLE`: the downloaded HANDBOOK sample (default `~/dev/untrusted/handbook-sample`), read only.
- `LANGFUSE_ENV_FILE`: the keys of a local Langfuse, for `--langfuse` (default `~/dev/langfuse-latest/cuga.env`).

## Known state of the tests

`pytest benchmarks/policy_eval/tests` has no known failures. CI runs it in a pytest process of its own (the harness puts
`benchmarks/` on `sys.path`, which would break the AppWorld and τ² suites in a shared process); `just test-regression` does the same.

About 50 harness, profile and wiring tests start a Python that must import `cuga.policy_layer` (polisys under the
name the harness gives it in a code snapshot). Set `POLICY_GATE_PYTHON` to such a Python to run them; without it they
skip with that reason.

Two tests skip on a fresh clone because their data left git on 2026-11-17: the old package builds (the last commit that
has them is `538904ea`) and the archived launchers (last in `2a5df9ee`). To run them, restore the folder named in the
skip message from that commit (`git restore --source <commit> -- <folder>`). `.gitignore` keeps it out of git. The
research tooling of the package work (rule audit, obligation replay, pipeline-vs-skill and parity checks) and its tests
left git too; they are in `45f17c47`.
