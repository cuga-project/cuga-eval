# 🏥 Oak Health Insurance Benchmark

## 📊 Overview

The Oak Health Insurance benchmark evaluates agent capabilities with a realistic healthcare insurance application. It tests the agent's ability to:
- Process insurance claims
- Query coverage and benefits information
- Navigate health plans
- Answer general health insurance questions

The benchmark includes a FastAPI application that simulates a real insurance system with policies, claims, and member data.

---

## 📋 Prerequisites

- CUGA Agent installed at `../cuga-agent`
- Python environment set up with `uv`
- API keys configured in `.env` file (repository root)
- FastAPI dependencies (installed via `uv sync`)

---

## ⚙️ Configuration

### Configuration Files

1. **`config/oak_health_insurance.env`** - Oak-specific settings:
   - `MCP_SERVERS_FILE` - Path to MCP servers configuration
   - `CUGA_LOGGING_DIR` - Directory for logging results
   - Policy settings and feature flags

2. **`config/global.env`** - Shared configuration (loaded automatically)

3. **`.env`** - API keys and secrets (repository root)

### Configuration Loading

The `run_app.sh` and `run_registry.sh` scripts automatically load all configurations in the correct order.

---

## 🚀 Running the Benchmark

### Step 1: Start the FastAPI Application

In one terminal:
```bash
cd benchmarks/oak_health_insurance
./run_app.sh
```

The app will run on `http://127.0.0.1:8090`

This script automatically loads:
- `.env` (secrets/API keys)
- `config/global.env` (global configuration)
- `config/oak_health_insurance.env` (Oak-specific configuration)

### Step 2: Start the CUGA Registry

In another terminal:
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
- The user is already connected to the app. Their member_id is 121231234 and location is latitude:40.7128, longitude:-74.0060.
- For each sub task you create, you **must** explicitly include the member_id information and location.
```

---

## 📊 Test Suite

The test suite (`oak_health_test_suite_v1.json`) contains tasks across different categories:
- **Claims Processing** - Submit, query, and manage claims
- **Coverage Information** - Check coverage details and limits
- **Benefits Queries** - Understand plan benefits
- **Plan Information** - Compare and select health plans
- **General Health** - Answer health-related questions

---

## 🔍 Metrics and Results

The benchmark tracks:
- **Success Rate** - Percentage of correctly completed tasks
- **Keyword Matches** - Whether responses contain expected keywords
- **Tool Usage** - Which tools were called for each task
- **Response Accuracy** - Quality of information provided
- **Execution Time** - Time taken per task

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

4. **Enable/Disable in GLOBAL settings**
Enabled by default in gloabl.env file

---

## 📁 File Structure

```
benchmarks/oak_health_insurance/
├── README.md                       # This file
├── config/
│   └── oak_health_insurance.env   # Oak-specific configuration
├── eval_bench_sdk.py              # Main evaluation script (recommended)
├── eval_bench.py                  # Alternative evaluation script
├── main.py                        # FastAPI application
├── models.py                      # Data models for insurance entities
├── data.py                        # Test data and fixtures
├── oak_policies.py                # Policy definitions
├── oak_mcp_servers.yaml           # MCP servers configuration
├── oak_health_test_suite_v1.json  # Test suite with all tasks
├── run_app.sh                     # Script to start FastAPI app
├── run_registry.sh                # Script to start registry
├── logging/                       # Evaluation results (generated)
└── trajectory_data/               # Detailed execution traces (generated)
```

---

## 🔗 Related Documentation

- [Main README](../../README.md) - Repository overview and setup
