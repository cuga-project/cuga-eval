# 🏒 M3 Benchmark

## 📊 Overview

The M3 benchmark evaluates multi-hop question answering capabilities across multiple domains. It tests the agent's ability to:
- Answer single-hop questions requiring one API call
- Handle multi-hop questions requiring multiple API calls
- Reason across different data sources
- Handle multi-turn conversational tasks

**Evaluation Script:** `eval_m3.py` - Unified script supporting both single-turn and multi-turn evaluation

**Datasets:**
- Single-turn: `data/<domain>.json` (e.g., `hockey.json`, `olympics.json`)
- Multi-turn: `data/<domain>_multiturn.json` (e.g., `olympics_multiturn.json`)

---

## 📋 Setup

1. **Container Runtime**
   - Docker or Podman installed and running
   - Scripts auto-detect which runtime is available

2. **Python Environment**
   ```bash
   uv venv --python=3.12 && source .venv/bin/activate
   ```

3. **VAKRA Setup**

   Download the Vakra data (M3 dataset) and start Docker containers:
   ```bash
   export HF_TOKEN=hf_your_token_here
   bash ./setup_m3.sh
   ```
   This setup vakra in `vendor/vakra`

   See [VAKRA setup guide](https://github.com/IBM/vakra/blob/main/setup.md) for details on Docker setup, environments, and data downloads.

   Verify Docker containers are running:
   ```bash
   docker ps -a
   ```

   Start containers if not running:
   ```bash
   cd vendor/vakra
   docker compose up -d
   ```

4. **CUGA Agent Setup**
   ```bash
   # From the evaluation repo root — clones cuga-agent into the *parent* directory
   # (sibling to cuga-eval), same layout as `../cuga-agent` in pyproject.toml
   bash ./setup_cuga.sh
   ```
   This installs CUGA Agent as `../cuga-agent` (next to the `cuga-eval` folder).

5. **Environment Configuration**

   **Repository root `.env` file:** (cuga-eval/.env)
   ```bash
   # Model settings
   AGENT_SETTING_CONFIG="settings.watsonx.toml"

   # WatsonX provider settings
   WATSONX_PROJECT_ID=your-project-id
   WATSONX_URL=https://us-south.ml.cloud.ibm.com
   WATSONX_APIKEY=your-api-key

   # OR for OpenAI:
   # OPENAI_API_KEY=your-api-key
   # OPENAI_BASE_URL=your-endpoint
   ```

   **M3 benchmark configuration:** (cuga-eval/benchmarks/m3/config/m3.env)
   ```bash
   # Copy example config
   cp benchmarks/m3/config/m3.env.example benchmarks/m3/config/m3.env

   # Find Docker path
   which docker

   # Edit m3.env and set CONTAINER_RUNTIME to the output of 'which docker'
   # Example CONTAINER_RUNTIME:
   CONTAINER_RUNTIME=/usr/local/bin/docker (which docker value)
   ```

   **Task-specific container configuration:**
   - **Task 1**: Edit `config/m3_registry_1.yaml`
   - **Task 2**: Edit `config/m3_registry_2.yaml`
   - **Task 3**: Edit `config/m3_registry_3.yaml`
   - **Task 4**: Edit `config/m3_registry_4.yaml`


---

## 🚀 Quick Start

### Quick Test
```bash
bash benchmarks/m3/eval.sh --task hockey_395_0
```

### M3 small_train.zip recipes (Vakra-scored)

The bundled `data/small_train.zip` is the canonical eval set: 20 domains × 10 tasks =
**200 test cases** total, split across two capabilities:

- `capability_2_dashboard_apis` (10 domains × 10 tasks = 100): authors, books,
  codebase_comments, hockey, mondial_geo, movie_platform, professional_basketball,
  soccer_2016, student_loan, talkingdata.
- `capability_3_multihop_reasoning` (10 domains × 10 tasks = 100): beer_factory,
  books, college_completion, computer_student, disney, mondial_geo, soccer_2016,
  trains, university, world_development_indicators.

All commands below use `caffeinate` so macOS doesn't sleep mid-run, and pass
`--m3-data benchmarks/m3/data/small_train.zip` so the legacy keyword data files
under `data/` aren't touched. Pass/fail comes from the Vakra LLM judges
(correctness × groundedness × exact-match); set `M3_VAKRA_LIVE_MCP=on` if you
want byte-identical-to-CLI verdicts and have the capability container running.

```bash
# 1) cuga, max 1 task in hockey domain
caffeinate -i bash benchmarks/m3/eval.sh \
  --m3-data benchmarks/m3/data/small_train.zip \
  --capability m3_task_2 --domain hockey --max-samples 1

# 2) cuga, all hockey tasks (10 samples)
caffeinate -i bash benchmarks/m3/eval.sh \
  --m3-data benchmarks/m3/data/small_train.zip \
  --capability m3_task_2 --domain hockey

# 3) react, max 1 task in hockey domain
caffeinate -i bash benchmarks/m3/eval.sh --agent react \
  --m3-data benchmarks/m3/data/small_train.zip \
  --capability m3_task_2 --domain hockey --max-samples 1

# 4) compare cuga vs react, 1 run, hockey
caffeinate -i bash benchmarks/m3/compare.sh --compare-agents --runs 1 \
  --m3-data benchmarks/m3/data/small_train.zip \
  --capability m3_task_2 --domain hockey --max-samples 1

# 5) compare cuga vs react, 5 runs each, ALL 200 tasks
#    Heads-up: 200 tasks × 5 runs × 2 agents = 2000 agent invocations + judge
#    LLM calls. Plan for hours, not minutes. Drop --capability if you want both
#    capability_2 and capability_3.
caffeinate -i bash benchmarks/m3/compare.sh --compare-agents --runs 5 \
  --m3-data benchmarks/m3/data/small_train.zip
```

Notes:
- `M3DataLoader` was extended to expose the GT `answer` per turn, and
  `eval_m3_react.py` learned to convert merged samples → its single-turn
  `test_case` shape, so react can read the zip just like cuga. Multi-turn
  samples are skipped with a warning if any appear (the bundled zip is all
  single-turn).

### M3 unlabeled / no-ground-truth recipes

For datasets that ship only an `input/` side (e.g. the Vakra test set under
`vendor/vakra/data/test/capability_2_dashboard_apis/`), pass
`--no-ground-truth`. The flag tells the loader to skip the missing `output/`,
runs the agent against the test domains, **skips Vakra/judge scoring entirely**,
and dumps each domain's prediction to
`benchmarks/m3/results/_vakra/prediction/<domain>.json` in the same shape the
Vakra evaluator expects. The summary is a per-sample tool-call count instead
of pass/fail.

The data path can be the capability dir itself or its parent — the loader
resolves either layout. The YAML's hard-coded domain list is overridden at
runtime from the data source, so unlabeled test domains run without editing
`config/m3_registry_m3_data.yaml`.

```bash
# 1) cuga, one sample on a single test domain (smoke test)
caffeinate -i bash benchmarks/m3/eval.sh \
  --m3-data vendor/vakra/data/test/capability_2_dashboard_apis \
  --no-ground-truth \
  --capability m3_task_2 --domain california_schools --max-samples 1

# 2) cuga, full vakra test set for capability 2 (17 domains)
caffeinate -i bash benchmarks/m3/eval.sh \
  --m3-data vendor/vakra/data/test/capability_2_dashboard_apis \
  --no-ground-truth \
  --capability m3_task_2 --bundle-zip

# 3) cuga, full vakra test set across all capabilities the loader finds
caffeinate -i bash benchmarks/m3/eval.sh \
  --m3-data vendor/vakra/data/test \
  --no-ground-truth --bundle-zip

# 4) react agent, same shape (writes to the same prediction dir)
caffeinate -i bash benchmarks/m3/eval.sh --agent react \
  --m3-data vendor/vakra/data/test/capability_2_dashboard_apis \
  --no-ground-truth \
  --capability m3_task_2 --domain california_schools --max-samples 1
```

`--no-ground-truth` requires `--m3-data`. Predictions accumulate per-domain
in `results/_vakra/prediction/`; a separate `results/m3_config_no_gt_*.json`
holds the raw run metadata.
- For zip mode, capability-2 / capability-3 Docker containers must be running
  (they're what the registry talks to). The first command in the script will
  surface a clear error if a container is missing.
- Per-task Vakra detail (judge scores + explanations) prints inline; the full
  judge JSON lands at `benchmarks/m3/results/_vakra/results.json`.


### Task 1 (Sel/Slots APIs)
```bash
# Set data directory
export M3_DATA_DIR="vendor/vakra/data/test/capability_1_bi_apis/input"

# Run with limited samples for testing
uv run python benchmarks/m3/eval_m3_task_1_enterprise_style.py \
  --container capability_1_bi_apis \
  --domain movie \
  --runtime docker \
  --max-samples 5
```

### Task 2 (Multi-hop queries via registry)
```bash
# Set data directory
export M3_DATA_DIR="vendor/vakra/data/test/capability_2_dashboard_apis/input"

# Run all tasks in config
uv run python benchmarks/m3/eval_m3.py \
  --from-config benchmarks/m3/config/m3_registry_2.yaml \
  --max-samples-per-domain 5
```

### Task 3 (Multi-hop reasoning)
```bash
# Set data directory
export M3_DATA_DIR="vendor/vakra/data/test/capability_3_multihop_reasoning/input"

# Run all tasks in config
uv run python benchmarks/m3/eval_m3.py \
  --from-config benchmarks/m3/config/m3_registry_3.yaml \
  --max-samples-per-domain 5
```

### Task 4 (Multi-turn multi-hops)
```bash
# Set data directory
export M3_DATA_DIR="vendor/vakra/data/test/capability_4_multiturn/input"

# Multi-turn format is auto-detected from data structure
uv run python benchmarks/m3/eval_m3.py \
  --from-config benchmarks/m3/config/m3_registry_4.yaml \
  --max-samples-per-domain 5
```

### Registry Status
```bash
# Check registry applications
curl http://127.0.0.1:8001/applications

# Check tools for a domain
curl http://127.0.0.1:8001/applications/hockey/apis | python3 -c "import sys, json; print(len(json.load(sys.stdin)))"
```


**Config file structure** (`m3_registry.yaml`):
```yaml
services:
  - m3_task_2:
      transport: "stdio"
      type: "mcp_server"  # Required for registry mode
      description: "M3 Task 2 environment"

      command: "/opt/podman/bin/podman"  # or ${CONTAINER_RUNTIME:-docker}
      args:
        - "exec"
        - "-i"
        - "-e"
        - "MCP_DOMAIN={domain}"  # Replaced per domain
        - "{taks 2 container name}"
        - "python"
        - "/app/m3-rest/mcp_server.py"

      metadata:
        task_id: 2
        container: "{taks 2 container name}"
        # multiturn format is auto-detected from data structure
        domains:
          - "hockey"
          - "olympics"
          - "address"
```

**Multiturn Auto-Detection:**
The script automatically detects whether data is single-turn or multi-turn based on the JSON structure:
- **Multi-turn**: Has `uuid`, `sample_id`, or `dialogue` fields
- **Single-turn**: Has `test_cases` field

No need to specify `multiturn: true` in the config!


### Batching for Large-Scale Evaluation

When evaluating many domains (e.g., 80 domains), use `--batch-size` to process tasks in manageable batches:

```bash
# Process 80 domains in batches of 20 tasks
uv run python eval_m3.py --from-config config/m3_registry.yaml --batch-size 20
```

**How Batching Works:**
1. **Splits tasks into batches**: If you have 80 tasks and `--batch-size 20`, creates 4 batches
2. **Processes each batch in parallel**: Tasks within a batch run concurrently
3. **Cleans up between batches**: Forces garbage collection and brief pause between batches
4. **Manages resources**: Prevents overwhelming system resources with too many concurrent tasks

**Benefits:**
- ✅ Prevents resource exhaustion on large-scale runs
- ✅ Allows progress monitoring per batch
- ✅ Enables recovery from partial failures
- ✅ Better memory management through cleanup between batches

**When to Use:**
- Running 20+ domains/tasks
- Limited system resources (memory, CPU)
- Long-running evaluations where you want progress checkpoints
- Testing with a subset before full run (combine with `--max-samples-per-domain`)

---

## 🏗️ Architecture

### Registry Mode Architecture (Config Mode)

```
eval_m3.py
  ↓
Registry Server (http://127.0.0.1:8001)
  ├─ MCP Manager
  │  ├─ hockey (206 tools)
  │  ├─ olympics (122 tools)
  │  └─ address (139 tools)
  ↓
FastMCP Client (stdio transport per domain)
  ↓
podman/docker exec -i -e MCP_DOMAIN=<domain> task_<task-id>_m3_environ
  ↓
FastAPI REST wrapper MCP server (/app/m3-rest/mcp_server.py)
  ↓
FastAPI REST API (localhost:8000 inside container)
  ↓
M3 database tools (<domain>.sqlite)
```

**Registry Mode Features:**
- ✅ **Automatic Registry Management**: Script starts/stops registry server
- ✅ **Config Expansion**: `{domain}` placeholders expanded to separate services
- ✅ **Tool Name Prefixing**: Tools prefixed with domain (e.g., `hockey_get_players`)
- ✅ **Domain Isolation**: Each domain has its own service in registry
- ✅ **Health Checks**: Retry logic ensures registry is ready before evaluation
- ✅ **Cleanup**: Existing registry processes cleaned up before starting new one




## 📝 Evaluation Process

The evaluation script performs:

1. **Config Expansion** - Expands `{domain}` placeholders to separate services
2. **Registry Startup** - Starts registry server with expanded config
3. **Health Checks** - Verifies registry is ready (up to 20 retries)
4. **Tool Loading** - Registry loads tools from each domain's container
5. **Domain Sequential** - Each task processes its domains one at a time
6. **Auto-Detection** - Detects single-turn vs multi-turn from data structure
7. **Agent Evaluation** - Cuga agent processes each test case
8. **Keyword Checking** - Validates responses contain expected keywords
9. **Save Results** - Generates JSON results in `results/` directory
10. **Cleanup** - Registry server continues running for inspection

---

## 📊 Results and Metrics

### Results Location

- **Standard Results**: `benchmarks/m3/results/m3_config_YYYYMMDD_HHMMSS.json`
- **Ground Truth Format**: `benchmarks/m3/results/m3_ground_truth_YYYYMMDD_HHMMSS.json`
- **Trajectory Data**: `benchmarks/m3/logging/trajectory_data/`
- **Activity Logs**: `benchmarks/m3/logging/`

The ground truth format file is compatible with the M3 benchmark evaluation format and includes:
- Task metadata (uuid, domain, num_turns)
- Dialogue structure with queries and responses
- Tool call sequences with arguments and results
- Multi-turn conversation history

### Metrics Tracked

- **Success Rate** - Percentage of correctly answered questions
- **Keyword Match Rate** - Whether responses contain expected keywords
- **Tool Calls** - Which tools were used for each question
- **Response Quality** - Accuracy of multi-hop reasoning

### View Results

```bash
# View latest results
cat benchmarks/m3/results/m3_*.json | tail -1 | python3 -m json.tool

# Open visualization dashboard
cd ../..
./scripts/viz.sh m3
```

---

## 🔧 Troubleshooting

### Container Not Found

```bash
# Check if containers are running
podman ps | grep m3_environ
# or
docker ps | grep m3_environ

# Start containers (see enterprise-benchmark docs)
```

### No Tools Loaded

```bash
# Verify container has FastAPI running
podman exec task_2_m3_environ curl -s http://localhost:8000/openapi.json | head

# Check MCP server works
podman exec -i -e MCP_DOMAIN=hockey task_2_m3_environ python /app/m3-rest/mcp_server.py
```

### Wrong Database/Domain

The `--domain` flag must match available databases in the container:
- `hockey` → `/app/db/hockey/hockey.sqlite`
- `olympics` → `/app/db/olympics/olympics.sqlite`
- `address` → `/app/db/address/address.sqlite`

### Results Location

- **Standard Results**: `benchmarks/m3/results/m3_task1_enterprise_YYYYMMDD_HHMMSS.json`
- **Ground Truth Format**: `benchmarks/m3/results/<timestamp>/task_1/<domain>.json`
- **Logs**: `benchmarks/m3/logging/`

The ground truth format output matches the M3 benchmark evaluation format used by `eval_m3.py`, with the same structure:
- Organized by timestamp and task folders
- One JSON file per domain
- Compatible with M3 benchmark evaluation tools

### Architecture

```
eval_m3_task_1_enterprise_style.py
  ↓
Persistent stdio connection (per domain)
  ↓
podman/docker exec -i -e MCP_DOMAIN=<domain> task_1_m3_environ
  ↓
FastAPI REST wrapper MCP server (/app/m3-rest/mcp_server.py)
  ↓
Single CugaAgent instance (reused for all queries)
  ├─ get_data(tool_universe_id=uuid) - Switch universe
  ├─ filter_data(...) - Query data
  └─ retrieve_data(...) - Get results
  ↓
Tool calls tracked via ToolCallTracker.record_call()
```

### Documentation

See [ENTERPRISE_STYLE_EVAL.md](./ENTERPRISE_STYLE_EVAL.md) for detailed documentation including:
- Architecture comparison
- Implementation details
- Tool call tracking mechanism
- Testing and validation

---

## 🔗 Related Documentation

- [Main README](../../README.md) - Repository overview and setup
- [Enterprise-Style Evaluation](./ENTERPRISE_STYLE_EVAL.md) - Detailed documentation for Task 1 enterprise-style implementation
