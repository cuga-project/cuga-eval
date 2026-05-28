# 🧪 CUGA Evaluation Framework

## 📖 What is This Repository?

This repository contains:
- **Evaluation benchmarks** for testing CUGA agent capabilities
- **Standardized evaluation scripts** with consistent metrics and reporting
- **Configuration management** for reproducible experiments
- **Integration with Langfuse** for detailed tracing and analytics

### Available Benchmarks

| Benchmark | Description | Domain |
|-----------|-------------|--------|
| **[BPO](benchmarks/bpo/README.md)** | BPO recruiting analytics with 32 tool APIs, policies, and error resilience testing | Recruiting Analytics |
| **[Oak Health Insurance](benchmarks/oak_health_insurance/README.md)** | Healthcare insurance application with claims, coverage, and benefits tasks | Healthcare |
| **[M3](benchmarks/m3/README.md)** | Multi-hop question answering using hockey domain data | Knowledge Retrieval |
| **[AppWorld](benchmarks/appworld/README.md)** | Complex web application automation and task completion | Web Automation |

---

## 📋 Prerequisites

Before getting started, ensure you have:

- **Python 3.12 or 3.13** (`pyproject.toml` pins `>=3.12,<3.14`)
- **uv** – Modern Python package manager ([installation guide](https://github.com/astral-sh/uv))
- **CUGA Agent** – Must be located at `../cuga-agent` (parent directory)
- **IBM network access** – Required only for the `gpt4o`, `gpt4.1`, and `opus4.5` model profiles, which route through the IBM-internal LiteLLM gateway (`ete-litellm.bx.cloud9.ibm.com`). The default `gpt-oss` profile uses public Groq and does not need it.
- **Docker** (optional) – For running Langfuse tracing locally

---

## ⚙️ Installation

### 1. Clone this repository
```bash
git clone https://github.com/cuga-project/cuga-eval.git
cd cuga-eval
```

### 2. Run setup script
```bash
# Clone CUGA agent and set up the base environment
./setup_cuga.sh
```

This script:
- Clones the `cuga-agent` repository to `../cuga-agent` (if not already present)
- Exports environment variables for the current terminal session
- Creates the logging directory

### 3. Set up Python environment
```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv sync
```

This installs the base dependencies needed for all benchmarks except AppWorld.

### 4. Configure environment variables
```bash
cp .env.example .env
```

Edit `.env` and add your API keys. The fields below match what ships in `.env.example`; see that file for the full list and inline comments.
```env
# Required: at least one LLM provider key (Groq is the default)
GROQ_API_KEY="your-groq-api-key"  # pragma: allowlist secret

# Default model settings (override per-run with --model-profile)
AGENT_SETTING_CONFIG=settings.groq.toml
MODEL_NAME=openai/gpt-oss-120b

# Optional: Langfuse tracing (see below). Default points at SaaS;
# switch to http://localhost:3000 for a local Docker instance.
DYNACONF_ADVANCED_FEATURES__LANGFUSE_TRACING=true
LANGFUSE_SECRET_KEY="your-langfuse-secret-key"  # pragma: allowlist secret
LANGFUSE_PUBLIC_KEY="your-langfuse-public-key"  # pragma: allowlist secret
LANGFUSE_HOST="https://us.cloud.langfuse.com"
```

### 5. Per-benchmark setup

Steps 1–4 above (clone, `setup_cuga.sh`, `uv venv && uv sync`, `.env`) are enough to run **BPO** and **Oak Health Insurance** out of the box. **M3** and **AppWorld** each need one extra setup step. The four subsections below are independent — run only the ones for benchmarks you actually want to use.

At-a-glance:

| Benchmark | Extra setup? | Command |
|---|---|---|
| BPO | None — base `uv sync` is enough | – |
| Oak Health Insurance | None — base `uv sync` is enough | – |
| M3 | Yes (one-time) | `./setup_m3.sh` |
| AppWorld | Yes (one-time) | `git lfs install && ./setup_appworld.sh` |

#### BPO — no extra setup

BPO is ready to run after the base install. Skip ahead to [Quick Start](#-quick-start) or see [`benchmarks/bpo/README.md`](benchmarks/bpo/README.md).

#### Oak Health Insurance — no extra setup

Oak is ready to run after the base install. See [`benchmarks/oak_health_insurance/README.md`](benchmarks/oak_health_insurance/README.md).

#### M3 (Vakra) Setup

If you plan to run the M3 benchmark:

```bash
# Hugging Face token for downloading ~30 GB of benchmark data (read access is enough).
# Create one at https://huggingface.co/settings/tokens
export HF_TOKEN=hf_your_token_here

# Clones vakra, downloads data, builds containers.
./setup_m3.sh
```

See [`benchmarks/m3/README.md`](benchmarks/m3/README.md) for full details.

#### AppWorld Setup

If you plan to run the AppWorld benchmark:

```bash
# Git LFS is required for AppWorld's data files.
git lfs install

# One-stop setup: clones the upstream repo into benchmarks/appworld/appworld,
# registers it as an editable dependency in the `appworld` group, and
# downloads the benchmark data.
./setup_appworld.sh
```

The script uses `uv add --editable --no-workspace benchmarks/appworld/appworld --group appworld`,
which writes a `[tool.uv.sources]` entry and `[dependency-groups].appworld` entry
into your **local** `pyproject.toml` (and a corresponding `[[package]]` block
into `uv.lock`). These edits are intentional and should **not** be committed —
they point at a directory that only exists on machines that have run
`setup_appworld.sh`. A pre-commit hook (`scripts/check_no_local_appworld.sh`)
blocks the commit automatically if those entries slip into a staged change to
either `pyproject.toml` or `uv.lock`.

After setup:
- `uv sync --group appworld` installs/refreshes with AppWorld available.
- `uv sync` (no group) keeps working; it will remove AppWorld from the venv
  since the group is opt-in. Re-add it any time with `uv sync --group appworld`.

See [`benchmarks/appworld/README.md`](benchmarks/appworld/README.md) for full details.

#### Running multiple benchmarks

The setup steps are independent — run each one when you want that benchmark, in any order. The base `uv sync` always succeeds regardless of which benchmark-specific setups have or haven't been run, so a fresh checkout or CI job that only needs BPO/Oak/M3 never has to touch AppWorld, and vice versa.

---

## 🚀 Quick Start

Every benchmark can be run with a **single command** from either the project root or the benchmark's own directory. The `eval.sh` script handles server lifecycle (start, health-check, cleanup) automatically.

### Running from project root

```bash
# Top-level dispatcher
./scripts/eval.sh --benchmark bpo
./scripts/eval.sh --benchmark oak_health_insurance --model-profile gpt4o
./scripts/eval.sh --benchmark m3
./scripts/eval.sh --benchmark appworld
```

### Running from benchmark directory (local)

```bash
cd benchmarks/bpo && ./eval.sh
cd benchmarks/oak_health_insurance && ./eval.sh
cd benchmarks/m3 && ./eval.sh
cd benchmarks/appworld && ./eval.sh
```

### Model profiles

Available profiles: `gpt-oss`, `gpt4o`, `gpt4.1`, `opus4.5`

### Agent Selection

The evaluation framework supports two agent types:

- **`cuga`** (default) - The full CUGA agent with planning, reflection, and advanced features
- **`react`** - A lightweight ReAct-style agent for iterative reasoning and tool execution

Use the `--agent` flag to select the agent type:

```bash
# Run with CUGA agent (default)
./scripts/eval.sh --benchmark bpo --task 1 2

# Run with ReAct agent
./scripts/eval.sh --benchmark bpo --agent react --task 1 2

# Compare agents on same tasks
./benchmarks/bpo/eval.sh --task 1 2 3                    # CUGA agent
./benchmarks/bpo/eval.sh --agent react --task 1 2 3      # ReAct agent
```

**What is the ReAct Agent?**

The ReAct (Reasoning + Acting) agent is a lightweight, prompt-based agent that uses iterative reasoning with tool calls and observations. It provides a simpler alternative to the full CUGA agent for baseline comparisons and research. The ReAct agent:
- Works with BPO, M3 (single-turn only), and AppWorld via the `--agent react` flag
- Uses the same MCP tools and evaluation infrastructure
- Enables direct comparison of agent architectures on the same tasks

> **Note:** Oak Health Insurance does not currently support `--agent` selection — its `eval.sh` runs the CUGA agent only. M3's `--multiturn` mode is also CUGA-only and will error out if combined with `--agent react`.


---

## 📋 Command Reference

All commands work from **both** project root and local benchmark directory.

### BPO Benchmark

```bash
# ── Eval ──────────────────────────────────────────────────────
# 2 tasks, model from .env (default profile is gpt-oss)
./benchmarks/bpo/eval.sh --task 1 2

# From local:
cd benchmarks/bpo && ./eval.sh --task 1 2

# With ReAct agent
./benchmarks/bpo/eval.sh --agent react --task 1 2

# BPO-specific: disable policies (baseline run)
./benchmarks/bpo/eval.sh --task 1 2 3 --no-policies

# Custom task files (paths relative to benchmarks/bpo/)
./benchmarks/bpo/eval.sh --tasks data/tasks_http_errors.json --task 1
./benchmarks/bpo/eval.sh --tasks data/tasks_http_errors.json data/tasks_edge_cases.json

# Available task files: data/bpo_test_suite_v1.json (default),
#   data/tasks_http_errors.json, data/tasks_edge_cases.json,
#   data/tasks_schema_violations.json, data/tasks_type_mismatch.json,
#   data/tasks_undocumented.json

# ── Compare by model ─────────────────────────────────────────
./benchmarks/bpo/compare.sh --models gpt-oss,gpt4o --runs 1 --task 1 2 3

# ── Compare with/without policies ────────────────────────────
./benchmarks/bpo/compare.sh --models gpt-oss --compare-policies --runs 1 --task 1 2 3

# ── Dry-run (preview commands without executing) ─────────────
./benchmarks/bpo/compare.sh --models gpt-oss,gpt4o --compare-policies --runs 2 --dry-run
```

### Oak Health Insurance

```bash
# ── Eval ──────────────────────────────────────────────────────
# Single task
./benchmarks/oak_health_insurance/eval.sh --task approved_claims

# From local:
cd benchmarks/oak_health_insurance && ./eval.sh --task approved_claims

# Note: Oak Health Insurance does not support --agent (CUGA only).

# Oak-specific: filter by difficulty
./benchmarks/oak_health_insurance/eval.sh --difficulty easy

# ── Compare by model ─────────────────────────────────────────
./benchmarks/oak_health_insurance/compare.sh --models gpt-oss,gpt4o --runs 1 --task approved_claims

# ── Dry-run ──────────────────────────────────────────────────
./benchmarks/oak_health_insurance/compare.sh --models gpt-oss,gpt4o --runs 2 --dry-run
```

### M3 Benchmark

```bash
# ── Eval (single-turn) ───────────────────────────────────────
# Specific task
./benchmarks/m3/eval.sh --task hockey_395_0

# From local:
cd benchmarks/m3 && ./eval.sh --task hockey_395_0

# With ReAct agent (single-turn only — react + --multiturn is rejected)
./benchmarks/m3/eval.sh --agent react --task hockey_395_0

# M3-specific: multi-turn evaluation (CUGA agent only)
./benchmarks/m3/eval.sh --multiturn

# M3-specific: filter by difficulty
./benchmarks/m3/eval.sh --difficulty easy

# ── Compare by model ─────────────────────────────────────────
./benchmarks/m3/compare.sh --models gpt-oss,gpt4o --runs 1 --task hockey_395_0

# ── Dry-run ──────────────────────────────────────────────────
./benchmarks/m3/compare.sh --models gpt-oss,gpt4o --runs 2 --dry-run
```

### AppWorld

```bash
# ── Eval ──────────────────────────────────────────────────────
# Specific task
./benchmarks/appworld/eval.sh --task 82e2fac_1

# From local:
cd benchmarks/appworld && ./eval.sh --task 82e2fac_1

# With ReAct agent
./benchmarks/appworld/eval.sh --agent react --task 82e2fac_1

# AppWorld-specific: specific task levels
./benchmarks/appworld/eval.sh --specific-task-levels 1

# AppWorld-specific: run a predefined task group from eval_config.toml
# (e.g. test_challenge_easy, test_normal_all_med — see benchmarks/appworld/eval_config.toml)
./benchmarks/appworld/eval.sh --eval-key test_challenge_easy

# ── Compare by model ─────────────────────────────────────────
./benchmarks/appworld/compare.sh --models gpt-oss,gpt4o --runs 1 --task 82e2fac_1

# ── Dry-run ──────────────────────────────────────────────────
./benchmarks/appworld/compare.sh --models gpt-oss,gpt4o --runs 2 --dry-run
```

### Top-Level Dispatchers

```bash
# Eval via dispatcher (applies model profile + env loading)
./scripts/eval.sh --benchmark bpo --model-profile gpt4o --task 1 2
./scripts/eval.sh --benchmark oak_health_insurance --model-profile gpt-oss --task approved_claims
./scripts/eval.sh --benchmark m3 --model-profile gpt4o --task hockey_395_0

# With ReAct agent
./scripts/eval.sh --benchmark bpo --agent react --task 1 2
./scripts/eval.sh --benchmark m3 --agent react --model-profile gpt4o --task hockey_395_0

# Compare via dispatcher
./scripts/compare.sh --benchmark bpo --runs 3
./scripts/compare.sh --benchmark m3 --runs 2
```

### Common flags

Flags accepted by every `eval.sh` (and forwarded by every `compare.sh`):

| Flag | Effect |
|---|---|
| `--verbose`, `-v` | Set loguru level to DEBUG. Useful for diagnosing tool-call or agent-graph behaviour. |
| `--quiet`, `-q` | Set loguru level to WARNING. Drops the per-step INFO chatter for cleaner CI logs. |
| `--task <id>...` | Run only the listed task(s) (numeric IDs, task names, or — for AppWorld — task UUIDs). |
| `--agent cuga\|react` | Pick agent. `cuga` is the default; `react` runs the lightweight ReAct baseline. Not all benchmarks support both (see Agent Selection above). |
| `--model-profile <name>` | Pick model profile (`gpt-oss`, `gpt4o`, `gpt4.1`, `opus4.5`). Default comes from `.env`. |
| `--no-bundle` | Skip reproducibility bundle creation. |
| `--bundle-zip` | Zip the bundle for sharing. |

Benchmark-specific flags:

| Flag | Benchmark | Effect |
|---|---|---|
| `--eval-key <key>` | AppWorld | Run a predefined task group from `benchmarks/appworld/eval_config.toml` (e.g. `test_challenge_easy`, `test_normal_all_hard`). |
| `--specific-task-levels 1 2 3` | AppWorld | Filter by difficulty level. |
| `--multiturn` | M3 | Run multi-turn evaluation (CUGA agent only). |
| `--difficulty easy\|medium\|hard` | M3, Oak | Filter tasks by difficulty. |
| `--no-policies` | BPO | Disable CUGA policies (for baselining). |

### Reproducibility Bundles

Every `eval.sh` and `compare.sh` run automatically creates a **reproducibility bundle** — a self-contained directory with all metadata, results, tasks, and (for BPO) policies needed to audit or reproduce the run.

```bash
# Bundle is created automatically after each eval/compare run
./benchmarks/bpo/eval.sh --task 1 2

# Skip bundle creation
./benchmarks/bpo/eval.sh --task 1 2 --no-bundle

# Create a zip archive of the bundle (for sharing)
./benchmarks/bpo/eval.sh --task 1 2 --bundle-zip
./benchmarks/bpo/compare.sh --models gpt-oss,gpt4o --runs 2 --task 1 2 --bundle-zip
./benchmarks/appworld/eval.sh --task 82e2fac_1 --bundle-zip
./benchmarks/appworld/compare.sh --models gpt-oss,gpt4o --runs 2 --task 82e2fac_1 --bundle-zip
```

Bundle structure (single-run):
```
20260311_201832_gpt-oss/
├── metadata.json          # Git info, model config, timestamps
├── config/
│   ├── run.env            # Runtime environment variables
│   └── settings.<profile>.toml # CUGA model settings (e.g. settings.groq.toml for gpt-oss, settings.openai.toml for gpt4o/gpt4.1/opus4.5)
├── results/               # Evaluation result JSON files
├── tasks/                 # Task definition files
├── logs/                  # Server and console logs
│   └── bpo_console.log    # Full console output
└── policies/              # policies.json (BPO only)
```

Bundle structure (comparison):
```
20260311_202731_compare_gpt-oss_gpt4o/
├── metadata.json
├── report.md              # Comparison report (BPO only)
├── config/
├── runs/
│   ├── gpt-oss_policies_run1/results/
│   ├── gpt-oss_policies_run2/results/
│   ├── gpt4o_policies_run1/results/
│   └── gpt4o_policies_run2/results/
├── tasks/
└── policies/              # (BPO only)
```

Bundles are stored in `benchmarks/{benchmark}/evaluation_bundles/` and are git-ignored.

---

## 🔧 Configuration

The evaluation framework uses a hierarchical configuration system:

### Configuration Files

1. **`.env`** (root directory)
   - Contains secrets and API keys
   - Not committed to version control
   - Created from `.env.example`

2. **`config/global.env`**
   - Shared configuration across all benchmarks
   - Common settings like logging, timeouts, etc.

3. **`benchmarks/{benchmark}/config/{benchmark}.env`**
   - Benchmark-specific configuration
   - MCP server paths, feature flags, etc.

### Configuration Loading

Benchmark scripts automatically load configurations in this order:
1. `.env` (secrets)
2. `config/global.env` (global settings)
3. `benchmarks/{benchmark}/config/{benchmark}.env` (benchmark settings)

Later configurations override earlier ones for the same keys.

---

## 📊 Langfuse Tracing (Optional)

Langfuse provides detailed tracing and analytics for LLM calls, tokens, costs, and execution timings during evaluations.

### Setup Langfuse

1. **Run Langfuse locally** (in a different folder, not under this repository):
   ```bash
   git clone https://github.com/langfuse/langfuse.git
   cd langfuse
   docker compose up
   ```

2. **Get API Keys**:
   - Access the Langfuse UI at `http://localhost:3000`
   - Log in or create a new account
   - Navigate to **Project Settings** → **API Keys**
   - Copy your `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`

3. **Configure in `.env` file**:
   ```env
   LANGFUSE_SECRET_KEY="your-secret-key"
   LANGFUSE_PUBLIC_KEY="your-public-key"
   LANGFUSE_HOST="http://localhost:3000"
   ```

### Available Metrics

When Langfuse is enabled, evaluations collect:
- `total_llm_calls` - Total number of LLM API calls
- `total_tokens` - Total tokens used (input + output)
- `total_cost` - Estimated cost of LLM calls
- `node_timings` - Timing information for each node
- `llm_call_details` - Detailed information about each LLM call
- `generation_timings` - Token generation timing data
- `full_execution_time` - Total execution time
- `total_cache_input_tokens` - Cached token usage

For more details, see the Langfuse sections in individual benchmark READMEs.

---

## 📈 Analytics

The [`analytics/`](analytics/README.md) folder contains decision intelligence analytics that run on evaluation bundle data to explain agent failures and guide improvements.

| Analytics | Description |
|---|---|
| [Trace Comparison](analytics/trace_comparison_rules/README.md) | Compares successful vs. failed traces **on the same tasks** to identify failure clusters, root causes, and remediation actions |

See [Trace Comparison README](analytics/trace_comparison_rules/README.md) for setup and usage instructions.

---

## 🛠️ Development

### Adding New Benchmarks

To add a new benchmark:

1. Create a new directory under `benchmarks/`
2. Add a `README.md` with detailed instructions
3. Create a `config/{benchmark}.env` file
4. Implement an `eval.sh` and Python evaluator. The `templates/` directory contains a few starting points (`eval_loop_template.py`, `calculate_test_score.py`, `simple_example.json`); for the full benchmark layout, copy from an existing one (BPO and M3 are the most complete references).
5. Add MCP servers configuration if needed

For examples, see existing benchmark implementations.

---

## 📊 Results and Visualization

Evaluation results are stored in benchmark-specific directories:
- `benchmarks/{benchmark}/logging/` - Evaluation logs and results
- `benchmarks/{benchmark}/logging/trajectory_data/` - Detailed execution traces

Use the visualization tool to explore results:
```bash
./scripts/viz.sh <benchmark-name>
```

---

## 🤝 Contributing

When contributing:
1. Follow the existing benchmark structure
2. Update relevant README files
3. Test your changes thoroughly
4. Document any new configuration options

---
