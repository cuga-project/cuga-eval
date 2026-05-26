# Running M3 Benchmark with Enterprise-Benchmark Container

This guide explains how to run the M3 benchmark in `cuga-eval` using the FastAPI container from `enterprise-benchmark`.

## Prerequisites Setup

### Step 1: Download BIRD-Bench Databases

The M3 benchmark requires SQLite databases from the BIRD-Bench dataset. Use the download script from enterprise-benchmark:

```bash
cd <path-to-enterprise-benchmark>

# Install download dependencies
pip install -r requirements_bird_download.txt

# Download BIRD databases (train and dev splits)
python download_bird_databases.py

# This will download and extract databases to:
# - enterprise-benchmark/apis/m3/rest/db/hockey/
# - enterprise-benchmark/apis/m3/rest/db/olympics/
# - ... (80 domains total)
```

**What this does:**
- Downloads BIRD-Bench train and dev datasets
- Extracts SQLite databases
- Places them in `apis/m3/rest/db/` with proper structure
- Each domain gets its own directory with a `.sqlite` file

### Step 2: Build and Start the FastAPI Container

Use the enterprise-benchmark's `run_benchmark.sh` script to set up the container:

```bash
cd <path-to-enterprise-benchmark>

# Build and start the M3 FastAPI container
./run_benchmark.sh --task-id 2 --skip-container=false --domain hockey --max-samples 1

# Or manually with docker-compose
cd apis/m3/rest
docker-compose up -d --build
```

**What this does:**
- Builds the FastAPI container with all 80 domains
- Starts the container on port 8000
- Mounts the `db/` directory (read-only)
- Exposes 9,800+ API endpoints

**Verify the container:**
```bash
# Check container is running
docker ps | grep fastapi-mcp-server

# Test health endpoint
curl http://localhost:8000/health
# Output: {"status":"healthy"}

# Browse API docs
open http://localhost:8000/docs
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  enterprise-benchmark/apis/m3/rest                              │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Docker Container: fastapi-mcp-server                    │  │
│  │                                                          │  │
│  │  FastAPI (port 8000)                                     │  │
│  │  - /v1/hockey/* (122 endpoints)                          │  │
│  │  - /v1/olympics/* (148 endpoints)                        │  │
│  │  - 80 domains, 9,800+ total endpoints                    │  │
│  │  - SQLite databases in ./db/                             │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ http://localhost:8000/openapi.json
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  cuga-eval/benchmarks/m3                         │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  MCP Registry Server (port 8001)                         │  │
│  │  - Loads FastAPI OpenAPI spec                            │  │
│  │  - Filters by domain (hockey)                            │  │
│  │  - Converts to MCP tools                                 │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│                              ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Cuga Agent (eval_m3.py)                                 │  │
│  │  - Loads tools from registry                             │  │
│  │  - Runs evaluation tasks                                 │  │
│  │  - Generates results                                     │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Prerequisites

1. **Enterprise-benchmark repository** with M3 container built:
   ```bash
   cd <path-to-enterprise-benchmark>/apis/m3/rest
   docker-compose build
   ```

2. **BIRD-Bench databases** downloaded and placed in `enterprise-benchmark/apis/m3/rest/db/`
   - Download from: https://bird-bench.github.io/
   - Structure: `db/hockey/hockey.sqlite`, `db/olympics/olympics.sqlite`, etc.

3. **Environment variables** set in `<path-to-cuga-eval>/.env`:
   ```bash
   MODEL_NAME="gemini-2.5-flash"
   OPENAI_API_KEY="your-key"
   OPENAI_BASE_URL="https://your-litellm-endpoint"
   ```

## Quick Start

### Option 1: Automated Script (Recommended)

```bash
cd <path-to-cuga-eval>

# Run with default settings (hockey domain)
./benchmarks/m3/run_with_container.sh

# Run with specific domain
export ENTERPRISE_BENCHMARK_DIR="<path-to-enterprise-benchmark>"
./benchmarks/m3/run_with_container.sh
```

The script will:
1. ✅ Check if FastAPI container is running (start if needed)
2. ✅ Verify FastAPI is accessible
3. ✅ Start MCP registry server
4. ✅ Load hockey tools from FastAPI
5. ✅ Run the evaluation
6. ✅ Show results

### Option 2: Manual Setup

#### Step 1: Start the FastAPI Container

```bash
cd <path-to-enterprise-benchmark>/apis/m3/rest
docker-compose up -d --build

# Verify it's running
docker ps | grep fastapi-mcp-server
curl http://localhost:8000/health
curl http://localhost:8000/docs
```

#### Step 2: Start the Registry Server

```bash
cd <path-to-cuga-eval>/benchmarks/m3
bash run_registry.sh
```

In another terminal, verify the registry loaded tools:
```bash
curl http://localhost:8001/applications
curl http://localhost:8001/applications/hockey/apis | python3 -m json.tool | head -50
```

#### Step 3: Run the Evaluation

```bash
cd <path-to-cuga-eval>
python benchmarks/m3/eval_m3.py
```

## Configuration Files

### 1. `benchmarks/m3/mcp_servers/fastapi_container.yaml`
Points to the FastAPI container's OpenAPI spec:
```yaml
services:
  - hockey:
      url: "http://localhost:8000/openapi.json"
      description: "Hockey API from FastAPI container"
      path_filter: "/v1/hockey/"
```

### 2. `benchmarks/m3/config/m3.env`
Configures which MCP server file to use:
```bash
MCP_SERVERS_FILE="benchmarks/m3/mcp_servers/fastapi_container.yaml"
DYNACONF_ADVANCED_FEATURES__REGISTRY=true
```

### 3. `.env` (root)
Model and API configuration:
```bash
MODEL_NAME="gemini-2.5-flash"
OPENAI_API_KEY="your-key"
OPENAI_BASE_URL="https://your-litellm-endpoint"
```

## Switching Between Configurations

### Use FastAPI Container (Local SQLite)
```bash
# In benchmarks/m3/config/m3.env
MCP_SERVERS_FILE="benchmarks/m3/mcp_servers/fastapi_container.yaml"
```

### Use Remote API Endpoints
```bash
# In benchmarks/m3/config/m3.env
MCP_SERVERS_FILE="benchmarks/m3/mcp_servers/hockey_yaml.yaml"
```

## Troubleshooting

### Container Not Starting
```bash
# Check logs
docker logs fastapi-mcp-server -f

# Rebuild
cd <path-to-enterprise-benchmark>/apis/m3/rest
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Registry Not Loading Tools
```bash
# Check registry logs
tail -f /tmp/m3_registry.log

# Verify FastAPI is accessible
curl http://localhost:8000/openapi.json | python3 -m json.tool | head -50

# Check registry loaded apps
curl http://localhost:8001/applications
```

### Port Conflicts
```bash
# Kill process on port 8000 (FastAPI)
lsof -ti:8000 | xargs kill -9

# Kill process on port 8001 (Registry)
lsof -ti:8001 | xargs kill -9
```

### Model Errors
```bash
# Check available models on your LiteLLM endpoint
curl -H "Authorization: Bearer $OPENAI_API_KEY" \
  $OPENAI_BASE_URL/v1/models | python3 -m json.tool

# Update MODEL_NAME in .env to match an available model
```

## Viewing Results

Results are saved to `benchmarks/m3/results/`:

```bash
# View latest results
ls -t benchmarks/m3/results/m3_*.json | head -1 | xargs cat | jq '.'

# View summary
ls -t benchmarks/m3/results/m3_*.json | head -1 | xargs cat | jq '.[] | {task_name, success, match_rate}'
```

## Running Different Domains

To run olympics instead of hockey:

1. Update `benchmarks/m3/mcp_servers/fastapi_container.yaml`:
   ```yaml
   services:
     - olympics:
         url: "http://localhost:8000/openapi.json"
         description: "Olympics API from FastAPI container"
         path_filter: "/v1/olympics/"
   ```

2. Update the data file in `eval_m3.py` or use command line args:
   ```bash
   python benchmarks/m3/eval_m3.py --data benchmarks/m3/data/olympics.json
   ```

## Integration with run_benchmark.sh

The `enterprise-benchmark/run_benchmark.sh` script is designed for a different architecture (direct MCP connection). To use it with Cuga:

1. Use the container setup described here
2. Run `eval_m3.py` from cuga-eval
3. The container provides the same APIs that run_benchmark.sh expects

## Summary

✅ **Fixed Issues:**
1. Model configuration (using gemini-2.5-flash)
2. Registry feature enabled
3. MCP server pointing to FastAPI container
4. Automated setup script

✅ **What Works:**
- FastAPI container serves 9,800+ endpoints
- Registry loads tools from container's OpenAPI spec
- Cuga agent evaluates tasks using these tools
- Results are saved and can be analyzed

✅ **Key Files:**
- `run_with_container.sh` - Automated setup and execution
- `fastapi_container.yaml` - MCP server configuration
- `m3.env` - Benchmark configuration
- `.env` - Model and API keys
