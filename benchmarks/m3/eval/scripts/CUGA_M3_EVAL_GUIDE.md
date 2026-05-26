# Cuga M3 Evaluation Guide

End-to-end guide for setting up and running the M3 benchmark with the Cuga agent.

---

## Overview

The M3 benchmark evaluates an agent's ability to query structured databases via REST APIs.
It is organised into two task types:

| Task | Type | Description |
|------|------|-------------|
| Task 1 | Handle-based | Python tools MCP server; agent calls `get_data(tool_universe_id=uuid)` |
| Task 2 | REST API | FastAPI container exposing 9,800+ endpoints across 40+ domains |

The evaluation pipeline:

```
setup_m3_eval.sh          ← one-time environment setup (Step 1)

eval_m3.py                ← starts registry server, runs agent, shuts server down
    │
    └── run_eval_background.sh  ← wraps eval_m3.py for background execution (Step 2B)
            │
            └── monitor_eval.sh  ← monitors a background run (Step 3)
```

---

## Step 1 — One-Time Environment Setup

Run the setup script once to prepare the full environment.
It will:

1. Detect (or prompt for) the container runtime (`podman` / `docker`)
2. Configure LLM API keys in `.env`
3. Clone and install `cuga-agent` via `setup_cuga.sh` (into the parent directory, sibling to this repo)
4. Install Python dependencies with `uv sync`
5. Create required directories (`logging/`, `results/`, `eval/logs/`)
6. Check that M3 containers are running — and **automatically provision them** if not

```bash
# From the project root:
bash benchmarks/m3/eval/scripts/setup_m3_eval.sh
```

### Configuration options

All configurable values are at the top of the script:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENTERPRISE_BENCHMARK_DIR` | `vendor/enterprise-benchmark` | Where to clone the enterprise-benchmark repo |
| `ENTERPRISE_BENCHMARK_REPO` | `git@github.ibm.com:AI4BA/enterprise-benchmark.git` | SSH clone URL |
| `CONTAINER_INIT_WAIT` | `60` | Seconds to wait after starting containers |

Override any of them inline:

```bash
ENTERPRISE_BENCHMARK_DIR=/custom/path \
CONTAINER_INIT_WAIT=120 \
bash benchmarks/m3/eval/scripts/setup_m3_eval.sh
```

### What happens when containers are missing

If the required M3 containers (`task_1_m3_environ`, `task_2_m3_environ`) are not found,
the script automatically:

1. Clones `enterprise-benchmark` into `vendor/enterprise-benchmark/`
2. Creates a Python venv and installs deps
3. Runs `make download` — **you will be prompted for a Hugging Face token** (~30 GB download)
4. Builds the container image (`make build`)
5. Starts all containers (`$CONTAINER_RUNTIME compose up -d`)
6. Waits `CONTAINER_INIT_WAIT` seconds, then verifies containers are healthy

Get your Hugging Face token from ANU

---

## Step 2 — Run the Evaluation

`eval_m3.py` manages the full lifecycle: it starts the registry server, runs the agent
against all configured domains, then shuts the server down.

### Option A: Foreground (simple)

```bash
cd benchmarks/m3
uv run python eval_m3.py --from-config config/m3_registry.yaml
```

Run a specific task only:

```bash
uv run python eval_m3.py --from-config config/m3_registry.yaml --task m3_task_2
```

Limit samples per domain (useful for testing):

```bash
uv run python eval_m3.py --from-config config/m3_registry.yaml --max-samples-per-domain 3
```

### Option B: Background (recommended for full runs)

`run_eval_background.sh` invokes `eval_m3.py` in the background, captures all output
to a timestamped log file, and writes a JSON status file you can poll.

```
./run_eval_background.sh [batch_size] [data_dir] [model_name]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `batch_size` | _(empty)_ | Number of domains to run in parallel per batch. Empty = all in parallel. |
| `data_dir` | _(empty)_ | Path to directory containing input JSON files. Empty = default `data/`. |
| `model_name` | _(empty)_ | LLM model identifier (e.g. `meta-llama/llama-3-70b`). Empty = value from `.env`. |

You can also export `MODEL_NAME` as an environment variable instead of passing it as an argument.

```bash
cd benchmarks/m3/eval/scripts

# Run with batch size 10 (recommended for 40 domains)
./run_eval_background.sh 10

# Run without batching (all domains in parallel)
./run_eval_background.sh

# Run with a custom data directory
./run_eval_background.sh 10 /path/to/data

# Run with a specific model
./run_eval_background.sh 10 "" meta-llama/llama-3-70b

# Run with a specific model, no batching
./run_eval_background.sh "" "" meta-llama/llama-3-70b

# Run with a specific model via environment variable
MODEL_NAME=meta-llama/llama-3-70b ./run_eval_background.sh 10
```

**Output:**
```
==================================================
M3 Evaluation - Background Runner
==================================================
Timestamp:       20260227_001234
Config:          .../config/m3_registry.yaml
Batch Size:      10
Data Directory:  .../data (default)
Model:           meta-llama/llama-3-70b
Log File:        ../logs/eval_20260227_001234.log
PID File:        ../logs/eval_20260227_001234.pid
Status File:     ../logs/eval_20260227_001234.status
==================================================

✅ Evaluation started in background
   PID: 12345
   Log: tail -f ../logs/eval_20260227_001234.log
   Status: cat ../logs/eval_20260227_001234.status
```

---

## Step 3 — Monitor a Background Evaluation (Optional)

In a **separate terminal**, pass the status and log files printed by `run_eval_background.sh`:

```bash
cd benchmarks/m3/eval/scripts
./monitor_eval.sh ../logs/eval_20260227_001234.status ../logs/eval_20260227_001234.log
```

**Monitor output:**
```
==================================================
M3 Evaluation Status - 2026-02-27 00:15:00
==================================================
Status:              running
Start Time:          2026-02-27 00:12:34 CST
Execution Time:      0h 2m 26s
Batch Size:          10
Progress:            3/40 domains completed
Completion:          7%
==================================================
```

The monitor updates every 30 minutes and exits automatically when the evaluation finishes.

---

## File Layout

```
benchmarks/m3/
├── config/
│   ├── m3.env                  ← benchmark config (CONTAINER_RUNTIME, etc.)
│   └── m3_registry.yaml        ← task/domain definitions
├── data/
│   ├── hockey.json             ← Task 2 test data
│   ├── olympics.json
│   └── books.json              ← Task 1 test data
├── eval/
│   ├── logs/                   ← background eval logs (gitignored)
│   └── scripts/
│       ├── setup_m3_eval.sh       ← one-time setup (Step 1)
│       ├── run_eval_background.sh ← background runner (Step 2B)
│       ├── monitor_eval.sh        ← progress monitor (Step 3)
│       └── CUGA_M3_EVAL_GUIDE.md  ← this file
├── results/                    ← evaluation results (gitignored)
└── eval_m3.py                  ← main evaluation script (Step 2)
```

---

## Manual Status Checks

```bash
# View current status
cat benchmarks/m3/eval/logs/eval_*.status

# Check if evaluation is still running
ps -p $(cat benchmarks/m3/eval/logs/eval_*.pid)

# Tail the log
tail -f benchmarks/m3/eval/logs/eval_*.log

# Count completed domains
grep -c "Completed domain:" benchmarks/m3/eval/logs/eval_*.log
```

---

## Stopping a Background Evaluation

```bash
# Graceful stop
kill $(cat benchmarks/m3/eval/logs/eval_*.pid)

# Force stop
kill -9 $(cat benchmarks/m3/eval/logs/eval_*.pid)
```

---

## Troubleshooting

### Registry server fails with `FileNotFoundError`

The container runtime (`podman`/`docker`) is not on PATH or the path in `m3.env` is wrong.

```bash
# Check what's in m3.env
grep CONTAINER_RUNTIME benchmarks/m3/config/m3.env

# Re-run setup to auto-detect and fix it
bash benchmarks/m3/eval/scripts/setup_m3_eval.sh
```

### Containers not running

```bash
# Check container status
podman ps -a   # or: docker ps -a

# Start stopped containers
podman start task_1_m3_environ task_2_m3_environ

# Or re-run setup (will rebuild if needed)
bash benchmarks/m3/eval/scripts/setup_m3_eval.sh
```

### Scripts not executable

```bash
chmod +x benchmarks/m3/eval/scripts/run_eval_background.sh \
         benchmarks/m3/eval/scripts/monitor_eval.sh \
         benchmarks/m3/eval/scripts/setup_m3_eval.sh
```

### Monitor not updating

The monitor updates every 30 minutes by design. Check the log directly:

```bash
tail -f benchmarks/m3/eval/logs/eval_*.log
```

### Evaluation stuck

```bash
# Check if process is running
ps -p $(cat benchmarks/m3/eval/logs/eval_*.pid)

# View recent output
tail -100 benchmarks/m3/eval/logs/eval_*.log

# Stop and restart
kill $(cat benchmarks/m3/eval/logs/eval_*.pid)
./benchmarks/m3/eval/scripts/run_eval_background.sh 10
```

---
