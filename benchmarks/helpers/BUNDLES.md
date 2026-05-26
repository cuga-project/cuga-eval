# Evaluation Bundles

Self-contained reproducibility packages created after each eval or compare run. They capture everything needed to understand and reproduce a benchmark result.

## Bundle Types

### Single-Run (`eval.sh`)

Created by `eval.sh` after each evaluation. Directory name: `YYYYMMDD_HHMMSS_default`.

### Comparison (`compare.sh`)

Created by `compare.sh` after multi-run comparisons. Directory name: `YYYYMMDD_HHMMSS_compare_<models>`.

## Directory Structure

### Single-Run Bundle

```
20260312_184128_default/
  metadata.json           # Full run metadata (see below)
  report.md               # Human-readable evaluation report
  config/
    run.env               # Runtime environment snapshot
    settings.groq.toml    # Model settings file (copied)
  tasks/
    bpo_test_suite_v1.json  # Ground truth task definitions
  results/
    bpo_20260312_*.json   # Raw evaluation results
  trajectories/
    <run_folder>/         # Agent trajectory data
  logs/
    bpo_fastapi.log       # Server logs
    bpo_registry.log
  langfuse_traces/
    task_1_<trace_id>.json  # Full Langfuse trace per task
```

### Comparison Bundle

```
20260312_190230_compare_gpt-oss/
  metadata.json
  report.md               # Comparison report with tables
  config/
    run_gpt-oss.env       # Per-model environment snapshots
  tasks/
    bpo_test_suite_v1.json
  policies/
    policies.json         # Policy definitions (if applicable)
  runs/
    gpt-oss_policies_run1/
      results/            # Results for this specific run
      trajectories/
      logs/
      langfuse_traces/
    gpt-oss_policies_run2/
      ...
    gpt-oss_no-policies_run1/
      ...
```

## metadata.json

Both bundle types include rich metadata:

```json
{
  "bundle_version": "2",
  "created_at": "2026-03-12T19:02:30+00:00Z",
  "bundle_type": "eval|comparison",
  "benchmark": "bpo|appworld|m3|oak_health_insurance",
  "eval_repo": {
    "git_commit": "7973246",
    "git_branch": "master",
    "git_dirty": true
  },
  "runtime_config": {
    "env_vars": {
      "MODEL_NAME": "openai/gpt-oss-120b",
      "AGENT_SETTING_CONFIG": "settings.groq.toml",
      "LANGFUSE_HOST": "http://localhost:3000",
      "DYNACONF_ADVANCED_FEATURES__LANGFUSE_TRACING": "true",
      "DYNACONF_ADVANCED_FEATURES__BENCHMARK": "bpo"
    },
    "settings_file": "settings.groq.toml",
    "models": {}
  },
  "model": {
    "model_name": "openai/gpt-oss-120b",
    "agent_setting_config": "settings.groq.toml",
    "openai_base_url": null,
    "openai_api_version": null
  },
  "cuga": {
    "version": "0.2.6",
    "git_commit": "8527c2e8",
    "git_branch": "main",
    "git_dirty": true,
    "mode": null,
    "memory_enabled": null,
    "agent_mode": null
  },
  "environment": {
    "MODEL_NAME": "...",
    "DYNACONF_*": "..."
  },
  "ground_truth": {
    "task_count": 10,
    "task_file_hashes": {
      "bpo_test_suite_v1.json": "sha256:fd382b..."
    }
  },
  "policies": {
    "policies_json_hash": "sha256:eca418..."
  }
}
```

Comparison bundles add `configs`, `runs_per_config`, and per-model `runtime_config.models` with `env_vars`.

## Creating Bundles

Bundles are created automatically by `eval.sh` and `compare.sh`. To skip bundle creation:

```bash
./eval.sh --no-bundle --task task_1
./compare.sh --no-bundle --runs 2
```

To create a zip archive alongside the directory:

```bash
./eval.sh --bundle-zip --task task_1
./compare.sh --bundle-zip --runs 2
```

## Bundle CLI (advanced)

The `benchmarks/helpers/bundle.py` module can be invoked directly:

```bash
# Single-run bundle
uv run python -m benchmarks.helpers.bundle assemble \
  --benchmark bpo \
  --result-files results/bpo_*.json \
  --task-files data/bpo_test_suite_v1.json \
  --fetch-langfuse

# Comparison bundle
uv run python -m benchmarks.helpers.bundle assemble-compare \
  --benchmark bpo \
  --config-results '{"gpt-oss:policies":["results/run1.json","results/run2.json"]}' \
  --fetch-langfuse
```

Note: must be run from the project root directory.

## Langfuse Traces

When `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set in `.env`, the bundle creator downloads full Langfuse trace data for each task. This includes all LLM calls, token counts, costs, and timing. The fetch retries up to 10 times with 2-second delays to handle ingestion lag.

## Key Design Decisions

- **Self-contained**: bundles include copies of config, tasks, and settings so results can be understood without the original environment.
- **Per-model env snapshots**: comparison bundles capture the exact environment for each model profile, including all `DYNACONF_*` overrides.
- **Ground truth hashing**: task files are SHA-256 hashed so you can verify the same test suite was used across runs.
- **Git state**: both the eval repo and CUGA agent repo commit/branch/dirty status are recorded.
