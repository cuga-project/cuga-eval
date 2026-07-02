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

AppWorld supports multiple agent backends via `--agent`:

- **`cuga`** (default) — `CugaAgent` SDK path (`eval_appworld_sdk.py`) with `CombinedToolProvider` MCP tools
- **`deepagents`** — [LangChain Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview) with the same registry LangChain tools
- **`openclaw`** — OpenClaw agent with LangChain tool bridge
- **`hermes`** — Hermes client with ReAct tool loop over registry tools
- **`react`** — pre-PR-31 baseline: `appworld_eval_react.py` (Python REPL via `world.execute()`)
- **`codeact`** — `appworld_eval_codeact.py` with richer in-code workflow logic

External agents (`deepagents`, `openclaw`, `hermes`) share the same AppWorld system prompt and MCP tool set as the CUGA SDK path for fair comparison.

### External Agent Dependencies

Install optional agent SDKs alongside AppWorld:

```bash
uv sync --group appworld --group appworld-agents
# Or install individually:
uv sync --group appworld --group deepagents
uv sync --group appworld --group openclaw
```

Hermes (`pip install hermes`) conflicts with CUGA's `litellm` dependency (`jsonschema` version mismatch). The Hermes adapter falls back to the eval LLM (same as CUGA) when the native client is unavailable — install Hermes only if you need the native client in an isolated environment.

### Smoke test (no CUGA, no AppWorld servers)

Verify external agents can reach your LLM before running full AppWorld evals:

```bash
# 1. Copy Azure/LiteLLM settings into repo-root .env:
#    AGENT_SETTING_CONFIG=settings.openai.toml
#    OPENAI_API_KEY=...
#    OPENAI_BASE_URL=https://ete-litellm.bx.cloud9.ibm.com
#    MODEL_NAME=Azure/gpt-5.2-chat-2025-12-11

# 2. Install Deep Agents SDK (optional groups for openclaw)
uv sync --group deepagents

# 3. Run smoke test (uses eval LLM for all three; no registry/AppWorld)
./benchmarks/appworld/smoke_external.sh

# Single agent
./benchmarks/appworld/smoke_external.sh --agents deepagents

# Try native OpenClaw/Hermes SDKs instead of eval LLM
./benchmarks/appworld/smoke_external.sh --native-sdk
```

Pass criteria: direct LLM check returns `OK`, each agent calls the `ping` tool and answers `Final Answer: success`.

Required API keys (set in `.env` at repo root):

| Agent | Environment variables |
|---|---|
| CUGA / Deep Agents / Hermes (via eval LLM) | `OPENAI_API_KEY` or `GROQ_API_KEY` (per `AGENT_SETTING_CONFIG`) |
| OpenClaw | `OPENCLAW_API_KEY` |
| Hermes (native client) | Hermes provider key from `hermes setup` |

Both share the same harness (Python REPL via `world.execute()` with variables persisting across steps) for `react`/`codeact`, so the mechanism is identical. The ReAct vs CodeAct distinction here is about **where decisions live**: with the `react` prompt the model makes decisions between turns (ReAct-flavored), with the `codeact` prompt the model embeds branching, iteration, and error handling directly in code (true CodeAct). `--agent codeact` also adds engineering improvements over the baseline: stop sequences on the closing code fence, a larger trim budget, and pre-authentication of all task apps. `--agent codeact` is only supported by AppWorld; other benchmarks reject it with a clear error.

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

# Run with Deep Agents (registry LangChain tools)
./benchmarks/appworld/eval.sh --agent deepagents --eval-key test_challenge_easy

# Run with OpenClaw or Hermes
./benchmarks/appworld/eval.sh --agent openclaw --eval-key test_challenge_easy
./benchmarks/appworld/eval.sh --agent hermes --eval-key test_challenge_easy

# Run with a specific model profile
./benchmarks/appworld/eval.sh --sdk --model-profile gpt4.1 --eval-key test_challenge_easy

# Filter by difficulty level (1=easy, 2=medium, 3=hard)
./benchmarks/appworld/eval.sh --specific-task-levels 1

# Skip evaluation bundle creation
./benchmarks/appworld/eval.sh --sdk --eval-key test_challenge_easy --no-bundle
```

### Live status dashboard

Track progress while external-agent or compare runs are in flight. In a **second terminal**:

```bash
./scripts/eval_status.sh
# or: ./scripts/eval.sh status
```

This opens a browser dashboard at `http://127.0.0.1:8765/status.html` that auto-refreshes every 2s. It reads `benchmarks/appworld/experiments/.eval_status.json`, updated after each task completes.

```bash
./scripts/eval_status.sh print      # one-shot terminal summary
./scripts/eval_status.sh --no-open    # serve without opening browser
uv run eval-status path               # print status file location
```

Disable status writes with `EVAL_STATUS=0`.

### Comparison Runs (`compare.sh`)

Runs `eval.sh` multiple times and collects results into an evaluation bundle.

```bash
# 5 runs with the default model
./benchmarks/appworld/compare.sh --sdk --eval-key test_challenge_easy --runs 5

# Compare two models, 3 runs each
./benchmarks/appworld/compare.sh --sdk --eval-key test_challenge_easy --models gpt-oss,gpt4.1 --runs 3

# Compare CUGA SDK vs Deep Agents, OpenClaw, and Hermes
./benchmarks/appworld/compare.sh --eval-key test_challenge_easy --compare-agents --runs 1

# Compare specific agents explicitly
./benchmarks/appworld/compare.sh --eval-key test_challenge_easy --agents cuga,deepagents --runs 3

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
| `--agent AGENT` | Agent type (`cuga`, `react`, `codeact`, `deepagents`, `openclaw`, `hermes`) | `--agent deepagents` |
| `--compare-agents` | Run `cuga`, `deepagents`, `openclaw`, and `hermes` and compare (CUGA uses SDK path) | `--compare-agents` |
| `--dry-run` | Preview commands without executing | `--dry-run` |
| `--no-bundle` | Skip evaluation bundle creation | `--no-bundle` |
| `--bundle-zip` | Create a zip archive of the evaluation bundle | `--bundle-zip` |

All other flags (e.g. `--sdk`, `--eval-key`, `--task`, `--model-profile`) are forwarded to each `eval.sh` invocation.

### `eval.sh` Parameters

| Parameter | Description | Example |
|---|---|---|
| `--task ID` | Run a specific task | `--task 82e2fac_1` |
| `--eval-key KEY` | Run a predefined task group from `eval_config.toml` | `--eval-key test_challenge_easy` |
| `--sdk` | Use the SDK evaluator | `--sdk` |
| `--agent AGENT` | Agent type (`cuga`, `react`, `codeact`, `deepagents`, `openclaw`, `hermes`) | `--agent deepagents` |
| `--model-profile P` | Apply a model profile (`gpt-oss`, `gpt4o`, `gpt4.1`, `opus4.5`) | `--model-profile gpt4.1` |
| `--specific-task-levels N` | Filter tasks by difficulty level (1, 2, 3) | `--specific-task-levels 1` |
| `--no-bundle` | Skip evaluation bundle creation | `--no-bundle` |
| `--bundle-zip` | Create a zip archive of the evaluation bundle | `--bundle-zip` |

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
