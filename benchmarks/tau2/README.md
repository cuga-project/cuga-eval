# tau2-bench (τ²) — CUGA evaluation

Evaluates CUGA on [tau2-bench](https://github.com/sierra-research/tau2-bench), a
multi-turn customer-service benchmark. τ² drives the conversation (user simulator +
orchestrator + scoring); CUGA plugs in as the agent under test through a small
**bridge** so that CUGA's tool calls round-trip through τ²'s orchestrator (required
for correct env-state scoring).

Subsets: `mock` (10), `airline` (50), `retail` (114), `telecom` (2285; a `telecom_small`
split also exists).

## Install

From the repository root:

```bash
bash setup_tau2.sh          # clones tau2-bench (pinned) into benchmarks/tau2/, editable install, checks data
uv sync --group tau2        # install base deps + tau2
```

## Quick Start

The `./eval.sh` / `./compare.sh` commands below are run **from this directory**
(`benchmarks/tau2`) — `cd benchmarks/tau2` first. Equivalently, from the repo root use
`./scripts/eval.sh --benchmark tau2`.
Everything runs in a **single process** — τ²'s orchestrator and user simulator execute
in-process alongside CUGA, so there are no servers to start or ports to manage.

```bash
cd benchmarks/tau2   # all commands below run from here

# Default: mock subset, 1 task
./eval.sh

# 5 airline tasks with an explicit user-simulator model
./eval.sh --subset airline --num-tasks 5 --user-simulator-model openai/Azure/gpt-4.1

# Specific task ids (retail ids are 0,1,2,…), skip the reproducibility bundle
./eval.sh --subset retail --task 0 3 --no-bundle

# Multi-run comparison: N runs per model, aggregated into a report + bundle
./compare.sh --runs 3 --models gpt4.1 --subset airline --num-tasks 5
```

`--max-workers 1` is mandatory (one bridge per process) and enforced by both the
launcher and the entrypoint. Results land in `logging/results/tau2_*.json`.

### `--max-steps` (important)

τ² counts **every** message as a step (agent↔user, agent↔env). CUGA's exploratory
tool-call bursts burn through steps quickly, so too small a cap **truncates tasks
mid-action** and understates the score. Default here is **50** (τ²'s own default of 30
was measured truncating retail — 0/10 at 30 vs 3/10 at 50). Raise it further for harder
runs (`--max-steps 100`).

### Reading results

Each task's `reward` is τ²'s **env-state score in `[0, 1]`** (1.0 = final DB matches the
reference and all checks pass). Per-task the results JSON records `reward` + a
`reward_info` breakdown (`db_check`, `action_checks`, `nl_assertions`, …) — the "why"
behind a non-1.0 — plus the full `messages` transcript, `trace_id` (Langfuse), and both
model names.

## Choosing the agent (`--agent`)

Two agents can solve the tasks. Pick with `--agent` (default `cuga`):

| `--agent` | What runs | Path |
|-----------|-----------|------|
| `cuga` *(default)* | **CUGA** — the agent under test | Driven through the **bridge**: τ² runs on a background thread, CUGA responds on the main thread, tool calls round-trip through τ²'s orchestrator. |
| `llm_agent` | **τ²'s own native tool-calling agent** — a **baseline** | Runs **in-process, no bridge**: τ²'s `run_single_task` executes its own agent + user sim + env end-to-end. |

`llm_agent` is τ²'s built-in agent — a plain, policy-grounded tool-calling loop using the
model's **native** function-calling. It's the intended head-to-head control: *"does CUGA's
scaffold beat a vanilla tool-calling agent on the same model and tasks?"*

```bash
# CUGA (default)
./eval.sh --subset retail --num-tasks 20

# τ² native baseline on the SAME tasks
./eval.sh --subset retail --num-tasks 20 --agent llm_agent

# Head-to-head in one comparison report/bundle
./compare.sh --agents cuga,llm_agent --subset retail --num-tasks 20
```

**Model for the baseline.** `--agent llm_agent` needs a real, gateway-routable model —
τ² calls it directly. It defaults to the **user-simulator model** (guaranteed reachable, and
gives a same-model comparison); override with `--agent-model` (or `TAU2_AGENT_MODEL`). Creds
are selected by the model's provider prefix, exactly like the user simulator. For a clean
comparison, run both agents on the **same underlying model**. The agent used is recorded in
the experiment name (`tau2_<subset>_<agent>`) and `agent_model` in the results JSON.

**Two honest caveats.** (1) It's an *untuned* baseline — τ²'s default prompts, not an
optimized competitor. (2) Langfuse traces on this path are **score-only**: τ²'s native agent
calls the model through its own client (not the langchain handler CUGA uses), so per-LLM
spans don't nest — only the `trace_id` + reward score are recorded.

## Layout

| File | Role |
|------|------|
| `config/tau2.env` | DYNACONF flags + safety pins (e2b off; REGISTRY inherits false) |
| `eval_tau2_sdk.py` | entrypoint — config-load-first, task loop, results JSON |
| `eval.sh` / `compare.sh` | launchers (single-process, no servers) |
| `tau2_bridge.py` | ConversationBridge + decoy tools |
| `tau2_proxy.py` | CugaProxyAgent (τ² HalfDuplexAgent) + factory |
| `cuga_runner.py` | build_cuga_agent() + run_cuga_loop() hybrid + `_run_one_task` |
| `tests/` | bridge / decoys / proxy / run-loop / reporting + live smoke |

## Credentials & models

Three LLM roles are involved (all recorded in run metadata, since τ² scores are not
comparable across user-sim choices):

- **CUGA agent** — set via `AGENT_SETTING_CONFIG` / `MODEL_NAME` / `OPENAI_BASE_URL` /
  `OPENAI_API_KEY` (e.g. the LiteLLM gateway).
- **User simulator** — `--user-simulator-model` (or `TAU2_USER_SIM_MODEL`); its creds are
  passed through from the same `OPENAI_*` / `WATSONX_*` env.
- **τ² NL-assertion scorer** — τ² hardcodes `gpt-4.1-2025-04-14` for this with no override
  hook; the runner repoints it at the user-sim model + creds so scoring works on any
  gateway (otherwise retail tasks, which carry NL assertions, fail at scoring time). The
  judge actually used is recorded per task as `nl_judge_model` in the results JSON.
  **Comparability:** substituting the judge changes NL-assertion scoring, so a run's NL
  numbers are comparable only to other runs that used the *same* judge — not to the official
  leaderboard, which pins τ²'s original judge.

Put secrets in the repo-root `.env` (gitignored). Langfuse tracing (traces + per-task
reward scores) activates when `LANGFUSE_*` keys are present.
