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
cd benchmarks/oak_health_insurance
./run_registry.sh
```

### Step 3: Run Evaluation

In a third terminal:
```bash
cd benchmarks/oak_health_insurance
uv run eval_bench_sdk.py
```

**Run specific task range:**
```bash
uv run eval_bench_sdk.py -r 0-4
```

### Step 4: View Results

Open the visualization dashboard:
```bash
cd ../..
./scripts/viz.sh oak_health_insurance
```

Results are stored in `benchmarks/oak_health_insurance/logging/` and `trajectory_data/`

### All-in-one script (recommended)

`eval.sh` handles server lifecycle automatically:

```bash
./benchmarks/oak_health_insurance/eval.sh
./benchmarks/oak_health_insurance/eval.sh --task approved_claims

# Named resumable experiment
./benchmarks/oak_health_insurance/eval.sh --experiment oak-run --task approved_claims
./benchmarks/oak_health_insurance/eval.sh --resume-experiment oak-run

# Multi-run comparison with resume
./benchmarks/oak_health_insurance/compare.sh --experiment cmp --models gpt-oss,gpt4o --runs 3
./benchmarks/oak_health_insurance/compare.sh --resume-experiment cmp --status
```

See the [main README](../../README.md#named-experiments-resume-and-background-runs) for `--background`, `--stop`, bundle repair, and replay.

---

## 📝 Evaluation Process

The evaluation script (`eval_bench_sdk.py`) performs the following steps:

1. **Load Policies** - Applies policies from `oak_policies.py`
2. **Load Tools** - Retrieves available tools from the registry
3. **Evaluate Tasks** - Processes each task in the test suite
4. **Keyword Checking** - Validates responses contain expected keywords
5. **Generate Report** - Creates results with difficulty-based filtering

---

## 🔧 Advanced Configuration

### CUGA Agent Settings

For optimal performance, configure CUGA agent settings in `config/oak_helath_insurance.env`:

**Mode Settings:**
```env
DYNACONF_ADVANCED_FEATURES__CUGA_MODE = "accurate"
DYNACONF_ADVANCED_FEATURES__LITE_MODE = false
```
**Accurate Mode Settings:**
```toml
DYNACONF_FEATURES__FORCED_APPS = ["oak_health_insurance"]
DYNACONF_FEATURES__LOCAL_SANDBOX = true
```

### User Context (Optional)

To provide context about the Oak Health Insurance app, edit the task decomposition instructions:

**File:** `../cuga-agent/src/cuga/configurations/instructions/default/task_decomposition.md`

**Add:**
```markdown
## Oak Health Insurance App:

- The tools are from Oak Health Insurance app for both the user and his family.
- The user is already connected to the app. Their member_id is 121231234 and location is stateCode:NY, zipCode:11211.
- For each sub task you create, you **must** explicitly include the member_id information and location.
```

---

## eval.sh — Single Evaluation Run

Starts FastAPI app, registry, runs evaluation, creates bundle.

```
Usage: ./eval.sh [OPTIONS]

Options:
  --task TASK              Run a specific task by ID/name
  --difficulty LEVEL       Filter by difficulty (easy, medium, hard)
  --no-policies            Skip loading oak policies
  --no-bundle              Skip reproducibility bundle creation
  --bundle-zip             Create zip archive of bundle
  --model-profile <name>   Model profile (for bundle metadata)
```

Examples:
```bash
./eval.sh                           # Default evaluation, all tasks
./eval.sh --task approved_claims    # Single task
./eval.sh --difficulty easy         # Filter by difficulty
./eval.sh --no-policies             # Skip policy loading
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

Oak-specific playbooks and tool enrichments are defined in `oak_policies.py`. `eval_bench_sdk.py` loads them automatically at evaluation startup unless `--no-policies` is passed.

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
