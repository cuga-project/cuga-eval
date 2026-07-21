#!/bin/bash
# Multi-run comparison script for the tau2-bench (τ²) benchmark
#
# Orchestrates multiple eval.sh runs (across models/agents) and produces a
# comparison report + comparison bundle. Like eval.sh, τ² needs NO servers, so
# there is no server lifecycle to manage across runs (the one simplification
# versus bpo/appworld's compare.sh).
#
# Usage:
#   ./compare.sh --runs 3                                 # 3 runs, default model
#   ./compare.sh --models gpt-oss,gpt4o --runs 2          # compare 2 models
#   ./compare.sh --runs 3 --subset airline --num-tasks 5  # forward τ² flags
#   ./compare.sh --dry-run                                # preview commands
#
# Options:
#   --runs <N>         runs per configuration (default: 1)
#   --models <list>    comma-separated model profiles (default: gpt-oss)
#   --agents <list>    comma-separated agents (default: cuga)
#   --output <file>    save comparison report to file
#   --no-bundle        skip reproducibility bundle creation
#   --bundle-zip       create zip archive of bundle
#   --dry-run          print planned commands without executing
#   All other args forwarded to eval.sh (e.g. --subset, --num-tasks, --verbose)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Source common helpers if available
if [ -f "$PROJECT_ROOT/benchmarks/helpers/common.sh" ]; then
    source "$PROJECT_ROOT/benchmarks/helpers/common.sh"
else
    GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'
    RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
fi

# Source model profiles
if [ -f "$PROJECT_ROOT/scripts/model_profiles.sh" ]; then
    source "$PROJECT_ROOT/scripts/model_profiles.sh"
fi

RUNS="${RUNS:-1}"
DRY_RUN="${DRY_RUN:-false}"
OUTPUT_FILE="${OUTPUT_FILE:-}"
MODELS="${MODELS:-gpt-oss}"
AGENTS="${AGENTS:-cuga}"
NO_BUNDLE="${NO_BUNDLE:-false}"
BUNDLE_ZIP="${BUNDLE_ZIP:-false}"
FORWARDED_ARGS=()

# Parse arguments
ARGS=("$@")
idx=0
while [[ $idx -lt ${#ARGS[@]} ]]; do
    arg="${ARGS[$idx]}"
    case "$arg" in
        --runs)     RUNS="${ARGS[$((idx+1))]}"; idx=$((idx+2)) ;;
        --output)   OUTPUT_FILE="${ARGS[$((idx+1))]}"; idx=$((idx+2)) ;;
        --models)   MODELS="${ARGS[$((idx+1))]}"; idx=$((idx+2)) ;;
        --agents)   AGENTS="${ARGS[$((idx+1))]}"; idx=$((idx+2)) ;;
        --no-bundle) NO_BUNDLE=true; idx=$((idx+1)) ;;
        --bundle-zip) BUNDLE_ZIP=true; idx=$((idx+1)) ;;
        --dry-run)  DRY_RUN=true; idx=$((idx+1)) ;;
        *)          FORWARDED_ARGS+=("${ARGS[$idx]}"); idx=$((idx+1)) ;;
    esac
done

# Split models and agents into arrays
IFS=',' read -ra MODEL_LIST <<< "$MODELS"
IFS=',' read -ra AGENT_LIST <<< "$AGENTS"

# Build configurations: model:agent (τ² has no policies dimension).
CONFIGS=()
for model in "${MODEL_LIST[@]}"; do
    for agent in "${AGENT_LIST[@]}"; do
        CONFIGS+=("${model}:${agent}")
    done
done

echo -e "${BLUE:-}╔════════════════════════════════════════════════════════════╗${NC:-}"
echo -e "${BLUE:-}║  tau2-bench (τ²): Multi-Run Comparison                     ║${NC:-}"
echo -e "${BLUE:-}╚════════════════════════════════════════════════════════════╝${NC:-}"
echo ""
echo -e "  Agents:            ${CYAN:-}${AGENTS}${NC:-}"
echo -e "  Models:            ${CYAN:-}${MODELS}${NC:-}"
echo -e "  Runs per config:   ${CYAN:-}${RUNS}${NC:-}"
echo -e "  Configurations:    ${CYAN:-}${#CONFIGS[@]}${NC:-}"
if [[ -n "$OUTPUT_FILE" ]]; then
    echo -e "  Output file:       ${CYAN:-}${OUTPUT_FILE}${NC:-}"
fi
if [[ ${#FORWARDED_ARGS[@]} -gt 0 ]]; then
    echo -e "  Extra eval args:   ${CYAN:-}${FORWARDED_ARGS[*]}${NC:-}"
fi
echo ""

# Results directory (where eval_tau2_sdk writes tau2_*.json).
RESULTS_DIR="$SCRIPT_DIR/logging/results"
mkdir -p "$RESULTS_DIR"

if [[ "$DRY_RUN" == "true" ]]; then
    echo -e "${YELLOW:-}DRY RUN — showing planned commands:${NC:-}"
    echo ""
    for config in "${CONFIGS[@]}"; do
        IFS=':' read -r model agent <<< "$config"
        for ((r=1; r<=RUNS; r++)); do
            echo -e "  [${config} run ${r}/${RUNS}] ./eval.sh --model-profile ${model} --agent ${agent} ${FORWARDED_ARGS[*]}"
        done
    done
    echo ""
    exit 0
fi

failed=0
total_runs=0

# Collect result files grouped by config label (bash 3 compat).
CONFIG_RESULT_KEYS=()
CONFIG_RESULT_VALS=()

for config in "${CONFIGS[@]}"; do
    IFS=':' read -r model agent <<< "$config"

    echo -e "${BLUE:-}══════════════════════════════════════════════════════════════${NC:-}"
    echo -e "${CYAN:-}Configuration: ${config}${NC:-}"
    echo -e "${BLUE:-}══════════════════════════════════════════════════════════════${NC:-}"

    # Apply model config (profile + optional .env overrides)
    if type apply_model_config &>/dev/null; then
        if ! apply_model_config "$model"; then
            echo -e "${RED:-}Error: Failed to apply model config '$model'${NC:-}"
            exit 1
        fi
    fi

    eval_args=()
    if [[ "$NO_BUNDLE" == "true" ]]; then
        eval_args+=(--no-bundle)
    fi

    # Snapshot existing result files before running this config.
    before_files=$(ls -1 "$RESULTS_DIR"/tau2_*.json 2>/dev/null | sort)

    for ((r=1; r<=RUNS; r++)); do
        total_runs=$((total_runs+1))
        echo -e "${CYAN:-}[${config}]${NC:-} Run ${GREEN:-}${r}/${RUNS}${NC:-}"
        if "$SCRIPT_DIR/eval.sh" --model-profile "$model" --agent "$agent" "${eval_args[@]}" "${FORWARDED_ARGS[@]}"; then
            echo -e "${GREEN:-}✓${NC:-} Run ${r} complete"
        else
            echo -e "${RED:-}✗ Run ${r} failed${NC:-}"
            failed=$((failed+1))
        fi
        echo ""
    done

    # Collect only the NEW result files produced by this config's runs.
    after_files=$(ls -1 "$RESULTS_DIR"/tau2_*.json 2>/dev/null | sort)
    recent_files=$(comm -13 <(echo "$before_files") <(echo "$after_files"))
    CONFIG_RESULT_KEYS+=("$config")
    CONFIG_RESULT_VALS+=("$recent_files")
done

echo -e "${GREEN:-}All runs complete.${NC:-} (${failed} failed out of ${total_runs})"
echo ""

# Build JSON input: {"model:agent": ["file1.json", ...]}
JSON_PARTS=()
for ci in "${!CONFIG_RESULT_KEYS[@]}"; do
    config="${CONFIG_RESULT_KEYS[$ci]}"
    files="${CONFIG_RESULT_VALS[$ci]}"
    [[ -z "$files" ]] && continue
    file_list=""
    pfirst=true
    for f in $files; do
        [[ "$pfirst" != "true" ]] && file_list+=","
        pfirst=false
        file_list+="\"${f}\""
    done
    JSON_PARTS+=("\"${config}\":[${file_list}]")
done

JSON_INPUT="{"
jfirst=true
for part in "${JSON_PARTS[@]}"; do
    [[ "$jfirst" != "true" ]] && JSON_INPUT+=","
    jfirst=false
    JSON_INPUT+="$part"
done
JSON_INPUT+="}"

echo -e "${GREEN:-}✓${NC:-} Comparison complete!"

# Create comparison bundle unless skipped.
if [[ "${NO_BUNDLE:-false}" != "true" && "$JSON_INPUT" != "{}" ]]; then
    echo ""
    echo -e "${YELLOW:-}Creating comparison bundle...${NC:-}"

    # compare_report's `compare` subcommand reads the config→results JSON from stdin.
    REPORT_TMP=$(mktemp /tmp/tau2_report_XXXXXX)
    echo "$JSON_INPUT" | uv run --no-sync python -m benchmarks.helpers.compare_report compare \
        --output "$REPORT_TMP" || true
    if [[ -n "$OUTPUT_FILE" && -f "$REPORT_TMP" ]]; then
        cp "$REPORT_TMP" "$OUTPUT_FILE"
        echo -e "${GREEN:-}✓${NC:-} Report saved to: ${OUTPUT_FILE}"
    fi

    # Build per-model env snapshot for bundle metadata.
    MODEL_ENVS_JSON=""
    if type build_model_envs_json &>/dev/null; then
        MODEL_ENVS_JSON=$(build_model_envs_json "${MODEL_LIST[@]}")
    fi

    BUNDLE_CMD=(uv run python -m benchmarks.helpers.bundle assemble-compare
        --benchmark tau2
        --config-results "$JSON_INPUT"
        --report "$REPORT_TMP")
    if [[ -n "$MODEL_ENVS_JSON" ]]; then
        BUNDLE_CMD+=(--model-envs "$MODEL_ENVS_JSON")
    fi
    LOG_JSON="{\"shared\":[\"/tmp/tau2_console.log\"]}"
    BUNDLE_CMD+=(--log-files "$LOG_JSON")
    BUNDLE_CMD+=(--fetch-langfuse)
    if [[ "${BUNDLE_ZIP:-false}" == "true" ]]; then
        BUNDLE_CMD+=(--zip)
    fi

    (cd "$PROJECT_ROOT" && "${BUNDLE_CMD[@]}")
    rm -f "$REPORT_TMP"
fi
