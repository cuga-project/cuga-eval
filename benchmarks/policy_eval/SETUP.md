# Setup on a new machine

How to run IT service (ITSM) tasks of EnterpriseOps-Gym with the policy harness. Written on 2026-11-16 and checked on fresh
clones of the three repositories (GitHub) and a fresh virtual environment: the commands below ran a task to a graded result. `ENVIRONMENT.md` describes the original single-machine
setup (its paths are that machine's); where the two differ, this file is the newer one.

## What you need

- Python 3.12, [uv](https://docs.astral.sh/uv/), git, Docker.
- An OpenRouter key, or any OpenAI-compatible endpoint that serves the model you choose.

## 1. Repositories

Three repositories side by side, for example under `~/dev`:

```bash
git clone https://github.com/cuga-project/cuga-eval.git    && git -C cuga-eval  checkout policy-eval
git clone https://github.com/cuga-project/cuga-agent.git   && git -C cuga-agent checkout policy/integration
git clone https://github.com/cuga-project/polisys.git      && git -C polisys    checkout feat/cuga-hooks-integration
```

Branch names are those of 2026-11-16. `policy/integration` of cuga-agent is `main` plus the open pull requests for lifecycle hooks,
dynamic tool binding and the claim retry; it holds no policy code. polisys is the policy layer.

## 2. Python environment

One venv holds the agent, polisys and everything the benchmark's environment module imports:

```bash
cd cuga-agent
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e . -e ../polisys
export HARNESS_PYTHON=$PWD/.venv/bin/python     # the Python of the harness children
```

No other package is needed: `benchmarks/enterpriseops_gym/eog_env.py` imports from the benchmark's own clone (step 3) and the packages it
uses come with the agent. If `HARNESS_PYTHON` is not set, the harness uses the interpreter that started it.

## 3. The benchmark's clone

Our runs used this commit of the benchmark:

```bash
git clone https://github.com/ServiceNow/EnterpriseOps-Gym.git cuga-eval/benchmarks/enterpriseops_gym/vendor/EnterpriseOps-Gym
git -C cuga-eval/benchmarks/enterpriseops_gym/vendor/EnterpriseOps-Gym checkout 271f2c3
```

Unzip the databases of the tasks inside the clone (the benchmark's README asks for this too). Without them the seed files do not exist,
every tool call fails with `x-database-id header required`, and the harness stops the task with an error:

```bash
cd cuga-eval/benchmarks/enterpriseops_gym/vendor/EnterpriseOps-Gym && unzip -q gym_dbs.zip
```

`vendor/` is git-ignored. The harness imports the benchmark's MCP client and its verifier from this clone, so tasks are graded by
the benchmark's own code.

## 4. The ITSM server

Each person runs their own container. The image is the benchmark authors' (the clone's README says to pull and start one image
per domain); the tag `latest` moves, so write down the image ID of your run (`docker image inspect <image> --format '{{.Id}}'`).

```bash
docker run -d --name eog-itsm --memory 4g -p 127.0.0.1:8006:8005 shivakrishnareddyma225/enterpriseops-gym-mcp-itsm:latest
curl http://127.0.0.1:8006/health                    # 200 when it is up
export EOG_ITSM_URL=http://127.0.0.1:8006
```

The memory limit matters: at 2 GB the container was killed when 20 tasks ran in parallel. Each task seeds its own database from the clone
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
cd cuga-eval
benchmarks/policy_eval/snapshot_polisys.sh ../polisys ../cuga-agent     # prints polisys-<sha>-cuga-<sha>
```

Both repos must have no uncommitted changes to tracked files. The folder is `~/dev/cuga_snapshots/<name>` (`CUGA_SNAPSHOT_ROOT` changes it),
and `SOURCE.txt` in it names both branches and commits. Every result file records the snapshot as `code_sha`; a folder of results holds one
snapshot and one profile, and the harness stops a run that would mix two.

## 7. Run one task

List the tasks of a set, then run one of them:

```bash
cd cuga-eval/benchmarks
$HARNESS_PYTHON -I -c "import sys; sys.path.insert(0, '.'); from policy_eval.harness.adapters.itsm import ItsmAdapter; print(*ItsmAdapter().task_ids('itsm-pilot'), sep='\n')"
cd policy_eval
$HARNESS_PYTHON -I harness/run.py --bench itsm --profile baseline --set itsm-pilot --tasks <task id> \
  --snapshot <name from step 6> --trial 1 --run mine_smoke --model orhaiku55 -j 1 --proxy https://openrouter.ai/api/v1
```

- `--set` is a set id of `sets/registry.json`; without `--tasks` the whole set runs. `--profile baseline` is the agent alone (no policy);
  the other files in `profiles/` and `profiles/experiments/<name>` are policy arms.
- Results: `harness/results/<run>_t<trial>/<task>.json` (score and the benchmark's verifier checks), `trajectories/`, `logs/`.
  `harness/report.py` compares runs.
- A task with a result is skipped on a second start, unless it errored or has no score.

## Working in parallel

- Take tuning and held-out sets only from `sets/registry.json`. A held-out set is run once, after the code and setup are frozen. A set
  whose failures you traced becomes a tuning set for everyone: record that in the registry the same day (`sets/build_registry.py`).
- The ITSM sets `itsm-unseen2` and `itsm-unseen3` were never run with Haiku 5.5 or gpt-oss-120b. Nobody runs them until the eval subsets
  are defined in the planned TOML file.
- Write the decision rule (metric, threshold, no-harm limit) before a run. See `AGENTS.md`: no benchmark task text, IDs or values in prompts
  or rules, and no regex or keyword lists to decide meaning.
- Start run names with a short prefix of your own, so result folders and ledger lines do not collide.

## Known state of the tests

`pytest benchmarks/policy_eval/tests` has 10 failures and 6 errors that were there before this setup work (skill-package counts, a
`langfuse` attribute in a harness test, the default timeouts per benchmark, and the policies section of the registry). They are data checks
that fell behind newer packages and sets, not setup problems.
