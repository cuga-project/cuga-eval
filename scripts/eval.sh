#!/bin/bash
# Top-level evaluation script for all benchmarks.
#
# Dispatches to per-benchmark eval scripts with common parameter handling.
#
# Usage:
#   ./scripts/eval.sh --benchmark bpo                          # Run BPO evaluation
#   ./scripts/eval.sh --benchmark m3                           # Run M3 evaluation
#   ./scripts/eval.sh --benchmark bpo --model-profile gpt4o    # With model profile
#   ./scripts/eval.sh --benchmark bpo --verbose --tasks ...    # Forward extra args
#   ./scripts/eval.sh --help                                   # Show help

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ "${1:-}" == "status" ]]; then
    shift
    exec bash "$SCRIPT_DIR/eval_status.sh" "$@"
fi

# Source common helpers
source "$PROJECT_ROOT/benchmarks/helpers/common.sh"

# Parse arguments
parse_common_args "$@"

# Show help
for arg in "${FORWARDED_ARGS[@]}"; do
    if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
        echo "Usage: ./scripts/eval.sh --benchmark <name> [options] [-- benchmark-specific-args]"
        echo ""
        echo "Common options:"
        echo "  --benchmark, -b <name>    Benchmark to run (required)"
        echo "  --agent <name>            Agent to run (cuga, react, codeact, deepagents, openclaw, hermes; default: cuga)"
        echo "                            Note: 'codeact' and external agents are only supported by appworld."
        echo "  --model-profile <name>    Model profile (gpt-oss, gpt4o, gpt4.1, opus4.5)"
        echo "  --dotenv                  Use .env values to override the model profile"
        echo "  --verbose, -v             Enable verbose output"
        echo "  --no-bundle               Skip reproducibility bundle creation"
        echo "  --bundle-zip              Create zip archive of bundle"
        echo "  --help, -h                Show this help"
        echo ""
        list_benchmarks
        echo ""
        echo "All other arguments are forwarded to the benchmark's eval script."
        exit 0
    fi
done

# Validate benchmark
if [ -z "$BENCHMARK" ]; then
    echo -e "${RED}Error: --benchmark is required${NC}"
    echo ""
    list_benchmarks
    exit 1
fi

BENCHMARK_DIR="$PROJECT_ROOT/benchmarks/$BENCHMARK"
if [ ! -d "$BENCHMARK_DIR" ]; then
    echo -e "${RED}Error: Benchmark '$BENCHMARK' not found at $BENCHMARK_DIR${NC}"
    echo ""
    list_benchmarks
    exit 1
fi

EXTERNAL_AGENTS="deepagents openclaw hermes"
SUPPORTED_AGENTS="cuga react codeact $EXTERNAL_AGENTS"

is_supported_agent() {
    for a in $SUPPORTED_AGENTS; do
        if [[ "$AGENT" == "$a" ]]; then
            return 0
        fi
    done
    return 1
}

if ! is_supported_agent; then
    echo -e "${RED}Error: Unsupported agent '$AGENT'. Supported agents: ${SUPPORTED_AGENTS}${NC}"
    exit 1
fi

if [[ "$AGENT" == "codeact" && "$BENCHMARK" != "appworld" ]]; then
    echo -e "${RED}Error: --agent codeact is supported only by the appworld benchmark (got '$BENCHMARK').${NC}"
    exit 1
fi

for ext in $EXTERNAL_AGENTS; do
    if [[ "$AGENT" == "$ext" && "$BENCHMARK" != "appworld" ]]; then
        echo -e "${RED}Error: --agent $ext is supported only by the appworld benchmark (got '$BENCHMARK').${NC}"
        exit 1
    fi
done

# Find the benchmark eval script
BENCHMARK_EVAL=""
BENCHMARK_EVAL="$BENCHMARK_DIR/eval.sh"

if [ ! -f "$BENCHMARK_EVAL" ]; then
    echo -e "${RED}Error: No eval script found for benchmark '$BENCHMARK'${NC}"
    echo -e "${YELLOW}Expected: $BENCHMARK_DIR/eval.sh${NC}"
    exit 1
fi

# Setup
cd "$PROJECT_ROOT"

# Load environment
source "$PROJECT_ROOT/benchmarks/helpers/load_env.sh" "$BENCHMARK"

# Apply model profile, then per-run CLI overrides
finalize_model_config

# Check Langfuse env vars
check_langfuse_env

# Export common variables for the benchmark script
export NO_BUNDLE BUNDLE_ZIP MODEL_PROFILE VERBOSE AGENT USE_DOTENV

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Evaluation: ${BENCHMARK} [${AGENT}]$(printf '%*s' $((34 - ${#BENCHMARK} - ${#AGENT})) '')║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Dispatch to benchmark script
exec bash "$BENCHMARK_EVAL" "${FORWARDED_ARGS[@]}"
