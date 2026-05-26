# BPO Benchmark

BPO recruiting analytics benchmark for evaluating AI agents with tool-calling capabilities.

## Overview

This benchmark tests an agent's ability to:
- Use 13 BPO recruiting analytics APIs + 19 error-prone APIs via HTTP/OpenAPI
- Answer questions about candidate sources, hiring metrics, and skill analysis
- Handle negative cases (missing data, unsupported queries)
- Recover from error-prone API behaviors (type mismatches, HTTP errors, schema violations)

## Quick Start

### Option 1: All-in-One Script (Recommended)

The simplest way to run evaluations - handles server lifecycle automatically:

```bash
# Run all 26 tasks
./benchmarks/bpo/eval.sh

# Run specific task
./benchmarks/bpo/eval.sh --task 1

# Run multiple tasks
./benchmarks/bpo/eval.sh --task 1 --task 2 --task 12

# Run with custom task files (paths relative to benchmarks/bpo/)
./benchmarks/bpo/eval.sh --tasks data/tasks_http_errors.json
./benchmarks/bpo/eval.sh --tasks data/tasks_http_errors.json data/tasks_edge_cases.json

# Combine --tasks (file selection) with --task (ID filter within those files)
./benchmarks/bpo/eval.sh --tasks data/tasks_http_errors.json --task 30
```

The script will:
1. Start the FastAPI server (port 8095)
2. Start the Registry server (port 8001) with correct MCP config
3. Run the evaluation
4. Clean up all servers on completion (or on Ctrl+C / error)

**Environment Variables:**
- `MCP_SERVERS_FILE` - Override MCP servers config (default: `benchmarks/bpo/mcp_servers/bpo.yaml`)
- `SKIP_SERVER_START=true` - Use existing servers instead of starting new ones

### Option 2: Manual Server Management

If you need more control, run each component separately:

#### 1. Create `.env` file (one-time setup)

Create a `.env` file in the project root with your LLM credentials (see `config/.env.example` for all options):

```bash
# LLM Configuration
GROQ_API_KEY=your_groq_api_key_here
AGENT_SETTING_CONFIG=settings.groq.toml
MODEL_NAME=openai/gpt-oss-120b

# Langfuse Observability (required for tracing)
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

#### 2. Start the BPO API server (Terminal 1)

```bash
./benchmarks/bpo/run_app.sh
# Starts FastAPI server on http://127.0.0.1:8095
```

#### 3. Start the Registry server (Terminal 2)

```bash
./benchmarks/bpo/run_registry.sh
# Starts CUGA registry on http://127.0.0.1:8001
```

#### 4. Run evaluation (Terminal 3)

```bash
# Run all 26 tasks
uv run python -m benchmarks.bpo.eval_bench_sdk

# Run specific task (both formats work)
uv run python -m benchmarks.bpo.eval_bench_sdk --task 1
uv run python -m benchmarks.bpo.eval_bench_sdk --task task_1
```

### Multi-Run Comparison

```bash
# Compare 2 models, 3 runs each, with and without policies
./benchmarks/bpo/compare.sh --models gpt-oss,gpt4.1 --runs 3 --compare-policies --verbose

# Single model, 5 runs, with bundle zip
./benchmarks/bpo/compare.sh --models gpt-oss --runs 5 --bundle-zip --verbose

# Specific tasks only
./benchmarks/bpo/compare.sh --models gpt-oss --runs 2 --compare-policies --task-ids 1 2 3 4 5
```

## Configuration

Environment variables are loaded from `config/bpo.env`. See `config/.env.example` for all supported variables.

Model profiles are available via `--model-profile`: `gpt-oss`, `gpt4o`, `gpt4.1`, `opus4.5`.

## Available APIs (32 endpoints)

### Candidate Source APIs (7 + 14 error-prone)
- `candidate_source_sla_per_source` - SLA percentage per channel
- `candidate_source_total_hires_by_source` - Hire counts
- `candidate_source_candidate_volume_by_source` - Candidate volumes
- `candidate_source_funnel_conversion_by_source` - Funnel metrics
- `candidate_source_metadata_and_timeframe` - Data timeframe
- `candidate_source_definitions_and_methodology` - Metric definitions
- `candidate_source_source_recommendation_summary` - Composite metrics

### Skills APIs (6 + 5 error-prone)
- `skills_skill_analysis` - Skill statistics
- `skills_skill_impact_fill_rate` - Fill rate impact
- `skills_skill_impact_sla` - SLA impact
- `skills_skill_relevance_justification` - Relevance explanation
- `skills_successful_posting_criteria` - Success thresholds
- `skills_data_sources_used` - Data sources and models

## Policies

Consolidated policy definitions are in `policies/policies.json` (4 playbooks + 1 tool guide). Human-readable versions in `policies/*.md`.

## Evaluation Metrics

The framework measures:
- **Output Similarity**: RapidFuzz token-set ratio against ground truth
- **Exact Match**: Case-insensitive exact string match
- **Keyword Match**: Expected keywords present in response (supports OR alternatives)
- **Final Score**: Composite pass/fail based on similarity thresholds

Multi-run comparison reports include:
- **pass@N**: Fraction of tasks where at least one run passed
- **pass^N**: Fraction of tasks where all runs passed
- **Average**: Mean pass rate across runs
- **Per-task resource usage**: Tokens, cached tokens, LLM calls, duration

## Reproducibility Bundles

Every evaluation run creates a self-contained bundle in `evaluation_bundles/` with metadata, results, tasks, policies, and config needed to audit or reproduce the run.

## Test Data

- `bpo_test_suite_v1.json` / `data/tasks.json` - 26 core evaluation tasks
- `data/tasks_*.json` - 19 error/hardness tasks (5 files)
- `data/candidate_data.parquet` - ~64k candidate records

## Running Tests

```bash
# Unit tests for APIs and evaluation
uv run pytest benchmarks/bpo/tests/ -v
```

## Directory Structure

```
benchmarks/bpo/
├── config/
│   ├── bpo.env                  # Environment config
│   ├── .env.example             # Env var documentation
│   └── settings.groq.toml      # CUGA settings for Groq models
├── mcp_servers/bpo.yaml         # MCP server config (HTTP/OpenAPI)
├── data/
│   ├── bpo_test_suite_v1.json   # Test suite (26 tasks)
│   ├── tasks_*.json             # Error/hardness tasks (5 files)
│   ├── candidate_data.csv       # Source data (human-readable)
│   └── candidate_data.parquet   # Runtime data (~64k records)
├── policies/
│   ├── policies.json            # Consolidated policy definitions
│   └── *.md                     # Human-readable policy docs
├── main.py                      # FastAPI server (port 8095)
├── eval.sh                  # All-in-one evaluation script
├── run_app.sh                   # Start FastAPI server only
├── run_registry.sh              # Start CUGA registry only
├── eval_bench_sdk.py            # Evaluation script
├── compare.sh                   # Multi-run comparison script
├── compare_results.py           # Comparison report generator
├── bundle.py                    # Reproducibility bundle creation
├── api_candidate_source.py      # Candidate source APIs (7 endpoints)
├── api_candidate_source_error.py # Error-prone candidate source APIs (14)
├── api_skills.py                # Skills APIs (6 endpoints)
├── api_skills_error.py          # Error-prone skills APIs (5)
├── data_loader.py               # Data loading (singleton)
├── models.py                    # Pydantic schemas
├── llm_judge.py                 # LLM-based evaluation
├── mcp_server.py                # MCP server (FastMCP, stdio)
├── tests/                       # Unit tests
└── results/                     # Evaluation results (JSON)
```
