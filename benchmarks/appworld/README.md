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

This installs dependencies for all benchmarks.

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

> **Important — don't commit the pyproject.toml diff.** The script edits `pyproject.toml` to point at a path that only exists on machines where the script has run. Committing those entries would re-break `uv sync` on fresh checkouts and in CI. A pre-commit hook (`scripts/check_no_local_appworld_in_pyproject.sh`) blocks the commit automatically; bypass with `--no-verify` only if you have a deliberate reason.

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

### Single Evaluation Run

```bash
# Run a specific task (SDK evaluator)
./benchmarks/appworld/eval.sh --sdk --task 82e2fac_1

# Run a predefined task group by eval-key
./benchmarks/appworld/eval.sh --sdk --eval-key test_challenge_easy

# Run with ReAct agent instead of CUGA
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
| `--agent AGENT` | Agent type for all runs (`cuga` or `react`) | `--agent react` |
| `--compare-agents` | Run both `cuga` and `react` agents and compare | `--compare-agents` |
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
| `--agent AGENT` | Agent type (`cuga` or `react`) | `--agent react` |
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

| Eval key | Description |
|---|---|
| `test_challenge_easy` | 24 easy tasks from test challenge set |
| `test_challenge_med` | 24 medium tasks from test challenge set |
| `test_challenge_hard` | 24 hard tasks from test challenge set |
| `test_normal_all_easy` | 57 easy tasks from test normal set |
| `test_normal_all_med` | 48 medium tasks from test normal set |
| `test_normal_all_hard` | 63 hard tasks from test normal set |

---

## 📝 Evaluation Configuration

The [`eval_config.toml`](eval_config.toml) file contains predefined task groups. Example structure:

```toml
[eval_config]
headless = true
test_challenge_easy = ["e775c78_1","07bb666_1","9aae7da_1", ...]
test_challenge_med = ["d9987f6_1","4815c06_1","f6936d4_1", ...]
test_challenge_hard = ["80acbaf_1","e70b117_1","6d59d90_1", ...]
```

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
