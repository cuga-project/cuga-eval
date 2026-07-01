# Oak Health Insurance Benchmark

## Overview

The Oak Health Insurance benchmark evaluates agent capabilities with a realistic healthcare insurance application. It tests the agent's ability to:
- Process insurance claims
- Query coverage and benefits information
- Find in-network care providers
- Navigate health plans
- Answer general health insurance questions

The benchmark uses the [oak-bench](https://github.com/cuga-project/oak-bench) open-source package for the FastAPI application and dataset.

---

## Prerequisites

- CUGA Agent installed at `../cuga-agent`
- Python environment set up with `uv`
- API keys configured in `.env` file (repository root)
- FastAPI dependencies (installed via `uv sync`)

---

## Configuration

### Configuration Files

1. **`config/oak_health_insurance.env`** - Oak-specific settings:
   - `MCP_SERVERS_FILE` - Path to MCP servers configuration
   - `CUGA_LOGGING_DIR` - Directory for logging results
   - Policy settings and feature flags

2. **`config/global.env`** - Shared configuration (loaded automatically)

3. **`.env`** - API keys and secrets (repository root)

---

## Running the Benchmark

### Quick start — single run (default cuga agent)

```bash
cd benchmarks/oak_health_insurance
./eval.sh
```

### Quick start — compare runs across models

```bash
./compare.sh --runs 3 --models gpt-oss,gpt4o
```

---

## eval.sh — Single Evaluation Run

Starts FastAPI app, registry, runs evaluation, creates bundle.

```
Usage: ./eval.sh [OPTIONS]

Options:
  --task TASK              Run a specific task by ID/name
  --difficulty LEVEL       Filter by difficulty (easy, medium, hard)
  --no-policy              Skip loading oak policies
  --no-bundle              Skip reproducibility bundle creation
  --bundle-zip             Create zip archive of bundle
  --model-profile <name>   Model profile (for bundle metadata)
```

Examples:
```bash
./eval.sh                           # Default evaluation, all tasks
./eval.sh --task approved_claims    # Single task
./eval.sh --difficulty easy         # Filter by difficulty
./eval.sh --no-policy               # Skip policy loading
```

Result files are saved in `results/oak_health_TIMESTAMP.json`.

---

## compare.sh — Multi-Run Comparison

Orchestrates multiple eval.sh runs and produces a comparison bundle.

```
Usage: ./compare.sh [OPTIONS]

Options:
  --runs <N>              Number of runs per model (default: 1)
  --models <list>         Comma-separated model profiles (default: gpt-oss)
  --no-bundle             Skip reproducibility bundle creation
  --bundle-zip            Create zip archive of bundle
  --dry-run               Preview commands without executing
  All other args forwarded to eval.sh (e.g. --difficulty, --task)
```

Examples:
```bash
./compare.sh --runs 5                              # 5 runs, default model
./compare.sh --runs 3 --models gpt-oss,gpt4o       # Compare 2 models
./compare.sh --difficulty easy --runs 2            # Easy tasks, 2 runs
./compare.sh --dry-run                             # Preview commands
```

---

## Metrics

The benchmark tracks:
- **Keyword match rate** — whether responses contain expected keywords
- **API call tracking** — which tools were called vs expected (`enable_api_metrics=True`)
  - `expected_apis` — tools expected for the task
  - `apis_called` — tools actually called
  - `apis_missing` — expected tools not called
  - `apis_extra` — extra tools called
  - `apis_correct` — 1 if no missing APIs

---

## Policies

Oak-specific playbooks and tool enrichments are defined in `oak_policies.py`. They are loaded automatically on `setup()` unless `--no-policy` is passed.

Policies include:
- Playbooks for claims, care providers, benefits, payments, family members, plan information
- Tool enrichments for all oak tools (coverage, search_benefits, find_care_specialty, etc.)

---

## File Structure

```
benchmarks/oak_health_insurance/
├── README.md                       # This file
├── config/
│   └── oak_health_insurance.env   # Oak-specific configuration
├── eval_bench_sdk.py              # Main evaluation script
├── eval.sh                        # Single-run shell script
├── compare.sh                     # Multi-run comparison script
├── oak_policies.py                # Playbooks and tool enrichments
├── oak_mcp_servers.yaml           # MCP servers configuration
├── oak_health_test_suite_v1.json  # Test suite (from oak-bench)
├── run_app.sh                     # Script to start FastAPI app
├── run_registry.sh                # Script to start registry
├── results/                       # Evaluation result JSON files (generated)
├── logging/                       # Evaluation logs (generated)
└── trajectory_data/               # Detailed execution traces (generated)
```

The FastAPI application and its data are provided by the `cuga-oak-health` package
from [cuga-project/oak-bench](https://github.com/cuga-project/oak-bench).

---

## Langfuse Tracing (Optional)

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
   - Navigate to Project Settings → API Keys

3. **Configure in `.env`:**
```env
LANGFUSE_SECRET_KEY="your-secret-key"
LANGFUSE_PUBLIC_KEY="your-public-key"
LANGFUSE_HOST="http://localhost:3000"
```

---

## Related Documentation

- [Main README](../../README.md) - Repository overview and setup
