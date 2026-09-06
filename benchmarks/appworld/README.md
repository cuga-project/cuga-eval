## 🌍 AppWorld Evaluation

## 📊 Overview

The AppWorld benchmark evaluates agent capabilities with complex web application automation and task completion. It tests the agent's ability to:
- Navigate and interact with web applications
- Complete multi-step tasks across different apps
- Handle realistic application workflows
- Reason about application state and context

---

## 📋 Prerequisites

- `uv` installed for environment management
- API keys configured in `.env` at the repository root when required by your model provider
- Git LFS installed (`brew install git-lfs` on macOS)

---

## 🚀 Setup

### 1. Install CUGA agent (if not already done)

From the repository root:

```bash
./setup_cuga.sh
```

This clones the `cuga-agent` repository to `../cuga-agent` and sets up the base environment.

### 2. Install base dependencies (if not already done)

From the repository root:

```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv sync
```

This installs dependencies for all benchmarks except AppWorld (which is
opt-in via the `appworld` group — see step 3 below).

### 3. Install AppWorld

```bash
# Install Git LFS (required for AppWorld's data files)
git lfs install

# One-stop setup (run from the repository root). Clones the AppWorld repo
# into benchmarks/appworld/appworld if it isn't there, registers it as an
# editable dependency in the `appworld` group, and downloads the data.
./setup_appworld.sh
```

The `setup_appworld.sh` script:
- Loads [`config/appworld.env`](config/appworld.env)
- Clones [`https://github.com/StonyBrookNLP/appworld`](https://github.com/StonyBrookNLP/appworld) into [`benchmarks/appworld/appworld`](appworld) if not already present
- Runs `uv add --editable --no-workspace benchmarks/appworld/appworld --group appworld`, which writes a `[tool.uv.sources]` entry and a `[dependency-groups].appworld` entry into your **local** `pyproject.toml` and installs the package editable
- Runs `appworld install --repo` and `appworld download data` from inside the clone

If [`benchmarks/appworld/appworld/data`](appworld/data) already exists, you'll be prompted before re-downloading.

> **Important — don't commit the `pyproject.toml` / `uv.lock` diff.** The script edits both `pyproject.toml` and `uv.lock` to point at a path that only exists on machines where the script has run. Committing those entries would re-break `uv sync` on fresh checkouts and in CI. A pre-commit hook (`scripts/check_no_local_appworld.sh`) blocks the commit automatically for either file; bypass with `--no-verify` only if you have a deliberate reason.

### 4. Day-to-day sync

After the initial setup:

```bash
uv sync --group appworld   # base deps + AppWorld
uv sync                    # base deps only (AppWorld is removed from venv;
                           #   re-add with --group appworld)
```

Both forms succeed regardless of whether the appworld clone exists. The `appworld` group is opt-in, so running other benchmarks (BPO, M3, Oak) never requires AppWorld to be installed.
---

## 🚀 Running the Benchmark

The `eval.sh` and `compare.sh` scripts handle the full server lifecycle (start, health-check, cleanup) automatically.

### Agent Options

AppWorld supports three agent backends via `--agent`:

- **`cuga`** (default) — `CugaAgent` from `cuga.sdk` with the full policy system and MCP tool loading
- **`react`** — pre-PR-31 baseline: `appworld_eval_react.py` with a short embedded prompt that instructs the model to *"Write small chunks of code and validate each step"*. Behaves in a ReAct-flavored way: each step is typically a tiny Python block with a single API call, and the model defers branching/looping decisions to the next LLM turn after observing the result.
- **`codeact`** — `appworld_eval_codeact.py` with the `instructions.txt` few-shot prompt that demonstrates richer code blocks (`for` loops, conditionals, multiple API calls + computation per step). Encourages true CodeAct: workflow logic is encoded **inside** the generated code rather than spread across LLM turns.

Both share the same harness (Python REPL via `world.execute()` with variables persisting across steps), so the mechanism is identical. The ReAct vs CodeAct distinction here is about **where decisions live**: with the `react` prompt the model makes decisions between turns (ReAct-flavored), with the `codeact` prompt the model embeds branching, iteration, and error handling directly in code (true CodeAct). `--agent codeact` also adds engineering improvements over the baseline: stop sequences on the closing code fence, a larger trim budget, and pre-authentication of all task apps. `--agent codeact` is only supported by AppWorld; other benchmarks reject it with a clear error.

### Single Evaluation Run

```bash
# Run a specific task (SDK evaluator)
./benchmarks/appworld/eval.sh --sdk --task 82e2fac_1

# Run a predefined task group by eval-key
./benchmarks/appworld/eval.sh --sdk --eval-key test_challenge_easy

# Run with CodeAct agent (improved loop, instructions.txt few-shot prompt)
./benchmarks/appworld/eval.sh --sdk --agent codeact --eval-key test_challenge_easy

# Run with ReAct agent (pre-PR-31 baseline with short embedded prompt)
./benchmarks/appworld/eval.sh --sdk --agent react --eval-key test_challenge_easy

# Run with a specific model profile
./benchmarks/appworld/eval.sh --sdk --model-profile gpt4.1 --eval-key test_challenge_easy

# Filter by difficulty level (1=easy, 2=medium, 3=hard)
./benchmarks/appworld/eval.sh --specific-task-levels 1

# Skip evaluation bundle creation
./benchmarks/appworld/eval.sh --sdk --eval-key test_challenge_easy --no-bundle
```

### Comparison Runs (`compare.sh`)

Runs `eval.sh` multiple times and collects results into an evaluation bundle.

```bash
# 5 runs with the default model
./benchmarks/appworld/compare.sh --sdk --eval-key test_challenge_easy --runs 5

# Compare two models, 3 runs each
./benchmarks/appworld/compare.sh --sdk --eval-key test_challenge_easy --models gpt-oss,gpt4.1 --runs 3

# Compare CUGA agent vs ReAct agent
./benchmarks/appworld/compare.sh --sdk --eval-key test_challenge_easy --compare-agents --runs 3

# Preview commands without executing
./benchmarks/appworld/compare.sh --sdk --eval-key test_challenge_easy --models gpt-oss,gpt4.1 --runs 2 --dry-run

# Create a zip archive of the evaluation bundle
./benchmarks/appworld/compare.sh --sdk --eval-key test_challenge_easy --runs 3 --bundle-zip
```

#### `compare.sh` Parameters

| Parameter | Description | Example |
|---|---|---|
| `--runs N` | Number of runs per model/agent | `--runs 5` |
| `--models M1,M2` | Comma-separated model profiles to compare | `--models gpt-oss,gpt4.1` |
| `--agent AGENT` | Agent type for all runs (`cuga`, `react`, or `codeact`) | `--agent codeact` |
| `--compare-agents` | Run both `cuga` and `react` agents and compare (for three-way comparison, pass `--agents cuga,react,codeact` explicitly) | `--compare-agents` |
| `--dry-run` | Preview commands without executing | `--dry-run` |
| `--no-bundle` | Skip evaluation bundle creation | `--no-bundle` |
| `--bundle-zip` | Create a zip archive of the evaluation bundle | `--bundle-zip` |
| `--experiment <name>` | Named resumable workspace (`evaluation_bundles/<name>/`) | `--experiment my-appworld` |
| `--resume-experiment <name>` | Resume a named experiment | `--resume-experiment my-appworld` |
| `--resume` | Resume the last experiment (`.last_experiment`) | `--resume` |
| `--background` | Run in background (requires experiment flags) | `--background` |
| `--status` | Show run/compare progress without starting servers | `--status` |
| `--stop` | Stop a background run | `--stop` |

All other flags (e.g. `--sdk`, `--eval-key`, `--task`, `--model-profile`) are forwarded to each `eval.sh` invocation.

#### Named experiments and compare resume

```bash
# Long eval — name it, interrupt, resume (failed tasks retried; successes skipped)
./benchmarks/appworld/eval.sh --sdk --experiment aw-run --eval-key test_challenge_easy
./benchmarks/appworld/eval.sh --resume-experiment aw-run

# Background + status
./benchmarks/appworld/eval.sh --sdk --experiment aw-run --eval-key test_challenge_easy --background
./benchmarks/appworld/eval.sh --status

# Resumable multi-run comparison
./benchmarks/appworld/compare.sh --sdk --experiment cmp --eval-key test_challenge_easy --runs 5
./benchmarks/appworld/compare.sh --resume-experiment cmp

# Replay / repair a bundle
uv run python -m benchmarks.helpers.bundle replay \
  --bundle-dir benchmarks/appworld/evaluation_bundles/aw-run
```

Experiment flags auto-enable `--sdk`. See the [main README](../../README.md#named-experiments-resume-and-background-runs).

### Leaderboard submissions (full test_normal / test_challenge)

Everything is driven by keys in [`eval_config.toml`](eval_config.toml). One cuga-eval workspace
(`evaluation_bundles/<name>`) and one AppWorld experiment directory
(`appworld/experiments/outputs/<prefix>_<split>`) per split. Never create a second workspace for
the same prefix+split. For an agent-guided walkthrough use `/appworld-leaderboard`.

**0. Prepare batch keys (once per split)**

```bash
uv run python -m benchmarks.appworld.leaderboard split-key test_challenge_all --batch-size 100
uv run python -m benchmarks.appworld.leaderboard split-key test_normal_all --batch-size 100
```

Writes `<key>_b1..bN` batch keys; scenarios `_1/_2/_3` of a base always stay in the same batch.

**1. First batch**

```bash
./benchmarks/appworld/eval.sh --sdk --experiment cuga_v1_chal --leaderboard cuga_v1 \
    --eval-key test_challenge_all_b1 --background
```

Watch with `./benchmarks/appworld/eval.sh --status --resume-experiment cuga_v1_chal` (or
`uv run python -m benchmarks.appworld.leaderboard status --bundle-dir benchmarks/appworld/evaluation_bundles/cuga_v1_chal`).

**2. Inspect and decide what to retry**

Prefer the harness lists over cuga-viz's "Failed" tab (it only lists score == 0.0 and misses
AppWorld's fractional scores):

```bash
uv run python -m benchmarks.appworld.leaderboard retry-key errored     --bundle-dir benchmarks/appworld/evaluation_bundles/cuga_v1_chal --of-key test_challenge_all_b1
uv run python -m benchmarks.appworld.leaderboard retry-key uncompleted --bundle-dir benchmarks/appworld/evaluation_bundles/cuga_v1_chal --of-key test_challenge_all_b1
```

Either appends a key like `cuga_v1_chal_errored = [...]` to `eval_config.toml`. Only retry
timeouts/connection resets/5xx/empty LLM replies — a genuine agent mistake is not retried on a
leaderboard run (one attempt per task).

**3. Retry (same workspace, same AppWorld dir)**

```bash
./benchmarks/appworld/eval.sh --resume-experiment cuga_v1_chal --eval-key cuga_v1_chal_errored
```

A key that `retry-key` wrote for **this** workspace re-runs every id even if its partial is clean —
the workspace records the key name in `metadata.json` (`retry_keys`), so an unrelated key that
merely ends in `_failed` never gains that power. For a hand-written key add `--force-retry`.

**4. Next batches**

```bash
./benchmarks/appworld/eval.sh --resume-experiment cuga_v1_chal --eval-key test_challenge_all_b2 --background
# inspect / retry, then b3, b4, ...
```

Batch keys skip ids that already completed. Ids must belong to the workspace's split or the run aborts.

**5. Validate + official numbers**

```bash
uv run python -m benchmarks.appworld.leaderboard validate cuga_v1 --split test_challenge
uv run python -m benchmarks.appworld.leaderboard evaluate cuga_v1_test_challenge --split test_challenge \
    --bundle-dir benchmarks/appworld/evaluation_bundles/cuga_v1_chal
```

`validate` checks the experiment directory before anything is packed:

| Check | Result if it fails |
|---|---|
| Every expected task id has an output directory | listed under "missing tasks" — exits 1 |
| Every task has its required result files | listed under "missing files in `<task>`" — exits 1 |
| Every base task has all its scenarios (`_1`/`_2`/`_3`) | listed under "bases missing a scenario" — exits 1 |
| Task has more than 1 environment interaction | listed under "tasks with <=1 environment interaction" — exits 1 unless `--allow-low-interactions` |

SDK eval (`--sdk` / `--leaderboard`) still calls AppWorld APIs over HTTP to the registry (port
9111), so those calls never go through `world.execute`. After each task the harness copies
`invoke_result.tool_calls` (ToolCallTracker) into `logs/environment_io.md` and `logs/api_calls.jsonl`
**without re-executing** them, and keeps the harness `complete_task` interaction last.

Pass `--allow-low-interactions` to `validate`/`pack` only when the ≤1-interaction tasks are one of:

- the task really made no AppWorld API call besides `complete_task` (crash / no-op), or
- the known logging gap: the merge could not run or found nothing to copy, so only the harness
  `complete_task` interaction was recorded even though the agent did call APIs over the registry.

It never silences a missing-task, missing-file or missing-scenario failure — those always exit 1.
`evaluate` prints TGC + SGC by difficulty and writes them into the workspace `report.md`
under "AppWorld official metrics".

**6. Pack both splits**

```bash
./benchmarks/appworld/pack_leaderboard.sh cuga_v1 "CUGA" "CUGA lite via SDK" "gpt-4.1" "gpt-4.1-2025-04-14" \
    https://github.com/cuga-project/cuga-agent
```

Refuses unless both splits validate — or just the one split, with `--only test_normal` /
`--only test_challenge`. Then runs `appworld evaluate` (writes `evaluations/<split>.json` under
the AppWorld experiment dir — not the cuga-eval workspace `report.md`; that is step 5), skipping it
when that file is already newer than every task output (`--re-evaluate` forces it), then
`appworld pack`, unpacks the bundle into a temp dir and
byte-compares every file; prints the two `leaderboard.bundle` paths and the
`/add-to-leaderboard --python … --appworld … cuga_v1` comment for the PR. Don't trust `appworld
pack` output alone — it prints WARNINGs and still writes the bundle, and says nothing about
absent task dirs; only `pack_leaderboard.sh` / `leaderboard pack` verify.

### `eval.sh` Parameters

| Parameter | Description | Example |
|---|---|---|
| `--task ID` | Run a specific task | `--task 82e2fac_1` |
| `--eval-key KEY` | Run a predefined task group from `eval_config.toml` | `--eval-key test_challenge_easy` |
| `--sdk` | Use the SDK evaluator | `--sdk` |
| `--agent AGENT` | Agent type (`cuga`, `react`, or `codeact`) | `--agent codeact` |
| `--model-profile P` | Apply a model profile (`gpt-oss`, `gpt4o`, `gpt4.1`, `opus4.5`) | `--model-profile gpt4.1` |
| `--specific-task-levels N` | Filter tasks by difficulty level (1, 2, 3) | `--specific-task-levels 1` |
| `--no-bundle` | Skip evaluation bundle creation | `--no-bundle` |
| `--bundle-zip` | Create a zip archive of the evaluation bundle | `--bundle-zip` |
| `--experiment <name>` | Named resumable workspace | `--experiment my-appworld` |
| `--resume-experiment <name>` | Resume a named experiment | `--resume-experiment my-appworld` |
| `--resume` | Resume last experiment | `--resume` |
| `--background` | Background run (requires experiment flags) | `--background` |
| `--status` | Show progress without starting servers (also prints leaderboard status when the workspace has a leaderboard block) | `--status` |
| `--stop` | Stop background run | `--stop` |
| `--leaderboard <prefix>` | Tag this run for official AppWorld leaderboard submission (implies `--sdk`); see [Leaderboard submissions](#leaderboard-submissions-full-test_normal--test_challenge) | `--leaderboard cuga_v1` |
| `--force-retry` | Re-run listed tasks even if a clean partial already exists | `--force-retry` |
| `--dry-run` | Print the evaluator command that would run and exit without starting servers | `--dry-run` |

---

## ⚙️ Configuration

### Configuration Files

1. **[`config/appworld.env`](config/appworld.env)** - AppWorld-specific settings:
   - `MCP_SERVERS_FILE` - Path to MCP servers configuration
   - `CUGA_LOGGING_DIR` - Directory for logging results
   - `APPWORLD_ROOT` - Path to the cloned AppWorld repository

2. **[`config/global.env`](../../config/global.env)** - Shared configuration (loaded automatically)

3. **[`.env`](../../.env.example)** - API keys and secrets at the repository root

### Evaluation Task Groups

Predefined task groups are defined in [`eval_config.toml`](eval_config.toml):

#### Combined sets (recommended for performance validation)

These keys merge the corresponding difficulty tier from the challenge and normal test sets. Use them after significant CUGA prompt or architecture changes to get a balanced cross-dataset signal at each difficulty level.

| Eval key | Tasks | Description |
|---|---|---|
| `test_easy` | 43 | Easy tasks from challenge (24) + normal (19) sets |
| `test_med` | 40 | Medium tasks from challenge (24) + normal (16) sets |
| `test_hard` | 45 | Hard tasks from challenge (24) + normal (21) sets |

#### Individual sets

| Eval key | Tasks | Description |
|---|---|---|
| `test_challenge_easy` | 24 | Easy tasks from test challenge set |
| `test_challenge_med` | 24 | Medium tasks from test challenge set |
| `test_challenge_hard` | 24 | Hard tasks from test challenge set |
| `test_normal_easy` | 19 | Easy tasks from test normal set (one per scenario) |
| `test_normal_med` | 16 | Medium tasks from test normal set (one per scenario) |
| `test_normal_hard` | 21 | Hard tasks from test normal set (one per scenario) |
| `test_normal_all_easy` | 57 | All easy tasks from test normal set (all variants) |
| `test_normal_all_med` | 48 | All medium tasks from test normal set (all variants) |
| `test_normal_all_hard` | 63 | All hard tasks from test normal set (all variants) |

---

## 📝 Evaluation Configuration

The [`eval_config.toml`](eval_config.toml) file contains predefined task groups. The `eval_key` setting controls which group runs by default when no `--eval-key` flag is passed.

You can modify this file to create custom task groups or adjust existing ones.

---

## 📊 Available Metrics

The benchmark tracks various metrics through the tracker and Langfuse integration:

### Tracker Metrics
- `total_tasks` - Total number of tasks evaluated
- `tasks_completed` - Number of successfully completed tasks
- `success_rate` - Percentage of successful completions
- `avg_steps` - Average steps per task
- `avg_duration` - Average task duration
- `exceptions_count` - Number of exceptions encountered
- `api_calls` - API calls made per task

### Langfuse Metrics (Optional)
- `total_llm_calls` - Total number of LLM API calls
- `total_tokens` - Total tokens used (input + output)
- `total_cost` - Estimated cost of LLM calls
- `node_timings` - Timing information for each node
- `llm_call_details` - Detailed information about each LLM call
- `generation_timings` - Token generation timing data
- `full_execution_time` - Total execution time
- `total_cache_input_tokens` - Cached token usage

### Run Receipt Metrics (SDK path, `--sdk`)
When run via the SDK path, the eval tool reads a `RunReceipt` directly from
the agent instead of the Langfuse metrics above (no Langfuse round-trip),
additionally breaking tokens down into `input_tokens`, `output_tokens`,
`cache_read_tokens`, `reasoning_tokens`, plus `tool_call_count`, `llm_time_s`,
`tool_time_s`, and `wall_time_s`. `total_cost`, `node_timings`,
`llm_call_details`, and `generation_timings` have no receipt equivalent and
are not populated when the receipt path is used. Note also that
`full_execution_time` changes basis on the receipt path: it's
`agent.invoke()` wall time rather than a Langfuse trace-span duration, so the
Duration column isn't directly comparable between a bundle from before this
change and one from after.

---

## 📊 Langfuse Tracing (Optional)

For detailed tracing and analytics, you can enable Langfuse integration.

### Setup Langfuse

1. **Run Langfuse locally** (in a different folder):
```bash
git clone https://github.com/langfuse/langfuse.git
cd langfuse
docker compose up
```

2. **Get API Keys:**
   - Access UI at `http://localhost:3000`
   - Log in or create account
   - Navigate to Project Settings → API Keys
   - Copy `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`

3. **Configure in `.env`:**
```env
LANGFUSE_SECRET_KEY="your-secret-key"
LANGFUSE_PUBLIC_KEY="your-public-key"
LANGFUSE_HOST="http://localhost:3000"
```

---

## 📁 File Structure

```text
benchmarks/appworld/
├── README.md                      # This file
├── config/
│   └── appworld.env               # AppWorld-specific configuration
├── eval_config.toml               # Evaluation task groups configuration
├── eval.sh                        # Single evaluation run script
├── compare.sh                     # Multi-run comparison script
├── mcp_servers_appworld.yaml      # MCP servers configuration
├── appworld/                      # Cloned AppWorld repository
├── logging/                       # Evaluation results (generated)
├── evaluation_bundles/            # Evaluation bundles (generated)
└── utils/                         # Helper utilities
```

---

## 🔗 Related Documentation

- [Main README](../../README.md) - Repository overview and setup
