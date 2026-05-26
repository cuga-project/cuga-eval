#!/bin/bash
# Analytics runner — works for any benchmark.
#
# Default parameters are read from analytics/{analytics}/config/default.conf
# and can be overridden via --config or individual CLI flags.
#
# Usage:
#   ./scripts/analyze.sh --benchmark appworld --analytics trace_compare
#   ./scripts/analyze.sh --benchmark m3 --analytics trace_compare
#   ./scripts/analyze.sh --benchmark appworld --analytics trace_compare --config my_experiment.conf
#   ./scripts/analyze.sh --benchmark appworld --analytics trace_compare --bundles all --since 2026-04-20
#   ./scripts/analyze.sh --benchmark appworld --analytics trace_compare --pairing-mode n_pairs --n 5
#   ./scripts/analyze.sh --benchmark appworld --analytics trace_compare --task-ids e775c78_1 fd1f8fa_2

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ANALYTICS_ROOT="$PROJECT_ROOT/analytics"

# ---------------------------------------------------------------------------
# Pre-scan for --benchmark, --analytics, --config (before config file is loaded)
# --benchmark is optional here; it can also come from the config file.
# ---------------------------------------------------------------------------
BENCHMARK_CLI=""
ANALYTICS=""
CONFIG_NAME="default.conf"
ARGS=("$@")
idx=0
while [[ $idx -lt ${#ARGS[@]} ]]; do
    case "${ARGS[$idx]}" in
        --benchmark) BENCHMARK_CLI="${ARGS[$((idx+1))]}"; idx=$((idx+2)) ;;
        --analytics) ANALYTICS="${ARGS[$((idx+1))]}"; idx=$((idx+2)) ;;
        --config)    CONFIG_NAME="${ARGS[$((idx+1))]}"; idx=$((idx+2)) ;;
        *)           idx=$((idx+1)) ;;
    esac
done

if [[ -z "$ANALYTICS" ]]; then
    echo "Error: --analytics is required."
    echo "Usage: ./scripts/analyze.sh --analytics <name> [--benchmark <name>] [options]"
    exit 1
fi

# Map analytics name to folder and pipeline script
case "$ANALYTICS" in
    trace_compare)
        ANALYTICS_DIR="$ANALYTICS_ROOT/trace_comparison_rules"
        PIPELINE_SCRIPT="$ANALYTICS_DIR/pipeline.py"
        ;;
    *)
        echo "Error: unknown analytics '$ANALYTICS'. Available: trace_compare"
        exit 1
        ;;
esac

# ---------------------------------------------------------------------------
# Load config file (default.conf unless --config overrides it)
# ---------------------------------------------------------------------------
CONFIG_FILE="$ANALYTICS_DIR/config/$CONFIG_NAME"
if [[ -f "$CONFIG_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$CONFIG_FILE"
    echo "Loaded config: $CONFIG_FILE"
else
    echo "Error: config file not found: $CONFIG_FILE"
    exit 1
fi

# CLI --benchmark overrides config BENCHMARK
if [[ -n "$BENCHMARK_CLI" ]]; then
    BENCHMARK="$BENCHMARK_CLI"
fi

if [[ -z "$BENCHMARK" ]]; then
    echo "Error: benchmark not set. Add BENCHMARK to the config file or pass --benchmark."
    exit 1
fi

# ---------------------------------------------------------------------------
# Parse remaining CLI args (override config defaults)
# ---------------------------------------------------------------------------
TASK_IDS_ARGS=()
BUNDLES_ARGS=()

idx=0
while [[ $idx -lt ${#ARGS[@]} ]]; do
    case "${ARGS[$idx]}" in
        --benchmark)    idx=$((idx+2)) ;;  # already handled in pre-scan
        --analytics)    idx=$((idx+2)) ;;
        --config)       idx=$((idx+2)) ;;
        --agent-config) AGENT_CONFIG="${ARGS[$((idx+1))]}"; idx=$((idx+2)) ;;
        --rules)        RULES="${ARGS[$((idx+1))]}";        idx=$((idx+2)) ;;
        --pairing-mode) PAIRING_MODE="${ARGS[$((idx+1))]}"; idx=$((idx+2)) ;;
        --n)            N="${ARGS[$((idx+1))]}";            idx=$((idx+2)) ;;
        --max-pairs)    MAX_PAIRS="${ARGS[$((idx+1))]}";    idx=$((idx+2)) ;;
        --model)        MODEL="${ARGS[$((idx+1))]}";        idx=$((idx+2)) ;;
        --prompt-file)  PROMPT_FILE="${ARGS[$((idx+1))]}";  idx=$((idx+2)) ;;
        --since)        SINCE="${ARGS[$((idx+1))]}";        idx=$((idx+2)) ;;
        --bundles)
            idx=$((idx+1))
            while [[ $idx -lt ${#ARGS[@]} && ! "${ARGS[$idx]}" =~ ^-- ]]; do
                BUNDLES_ARGS+=("${ARGS[$idx]}"); idx=$((idx+1))
            done ;;
        --task-ids)
            idx=$((idx+1))
            while [[ $idx -lt ${#ARGS[@]} && ! "${ARGS[$idx]}" =~ ^-- ]]; do
                TASK_IDS_ARGS+=("${ARGS[$idx]}"); idx=$((idx+1))
            done ;;
        *) echo "Warning: unknown argument '${ARGS[$idx]}'"; idx=$((idx+1)) ;;
    esac
done

# Use CLI --bundles if provided, else fall back to config BUNDLES
if [[ ${#BUNDLES_ARGS[@]} -gt 0 ]]; then
    BUNDLES_FINAL=("${BUNDLES_ARGS[@]}")
else
    IFS=' ' read -ra BUNDLES_FINAL <<< "$BUNDLES"
fi

# ---------------------------------------------------------------------------
# Build pipeline command
# ---------------------------------------------------------------------------
CMD=(uv run --no-sync python "$PIPELINE_SCRIPT"
    --benchmark "$BENCHMARK"
    --agent-config "$AGENT_CONFIG"
    --rules "$RULES"
    --bundles "${BUNDLES_FINAL[@]}"
    --pairing-mode "$PAIRING_MODE"
    --model "$MODEL"
    --prompt-file "$PROMPT_FILE"
)

if [[ -n "$N" ]]; then
    CMD+=(--n "$N")
fi

if [[ -n "$MAX_PAIRS" ]]; then
    CMD+=(--max-pairs "$MAX_PAIRS")
fi

if [[ -n "$SINCE" ]]; then
    CMD+=(--since "$SINCE")
fi

if [[ ${#TASK_IDS_ARGS[@]} -gt 0 ]]; then
    CMD+=(--task-ids "${TASK_IDS_ARGS[@]}")
fi

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
echo "Benchmark:  $BENCHMARK"
echo "Analytics:  $ANALYTICS"
echo ""

cd "$PROJECT_ROOT"
"${CMD[@]}"
