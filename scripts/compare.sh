#!/bin/bash
# Top-level comparison script for all benchmarks.
#
# Orchestrates multiple eval runs and produces comparison reports.
#
# Usage:
#   ./scripts/compare.sh --benchmark bpo --runs 5              # 5 runs of BPO
#   ./scripts/compare.sh --benchmark m3 --runs 3 --verbose     # 3 M3 runs
#   ./scripts/compare.sh --benchmark bpo --runs 5 --output report.md
#   ./scripts/compare.sh --dry-run --benchmark bpo --runs 3    # Preview
#   ./scripts/compare.sh --help                                # Show help

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source common helpers
source "$PROJECT_ROOT/benchmarks/helpers/common.sh"

# Parse arguments
parse_common_args "$@"

# Show help
for arg in "${FORWARDED_ARGS[@]}"; do
    if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
        echo "Usage: ./scripts/compare.sh --benchmark <name> --runs <N> [options] [-- benchmark-specific-args]"
        echo ""
        echo "Common options:"
        echo "  --benchmark, -b <name>    Benchmark to run (required)"
        echo "  --agent <name>            Agent to run (cuga, react; default: cuga)"
        echo "  --agents <list>           Comma-separated agents to compare (e.g. cuga,react)"
        echo "  --compare-agents          Shorthand for --agents cuga,react"
        echo "  --runs <N>                Number of runs (default: 1)"
        echo "  --output, -o <file>       Save comparison report to file"
        echo "  --model-profile <name>    Model profile (gpt-oss, gpt4o, gpt4.1, opus4.5)"
        echo "  --dry-run                 Print what would be run without executing"
        echo "  --no-bundle               Skip reproducibility bundle creation"
        echo "  --verbose, -v             Enable verbose output"
        echo "  --help, -h                Show this help"
        echo ""
        list_benchmarks
        echo ""
        echo "All other arguments are forwarded to the benchmark's compare script."
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

if [[ "$AGENT" != "cuga" && "$AGENT" != "react" ]]; then
    echo -e "${RED}Error: Unsupported agent '$AGENT'. Supported agents: cuga, react${NC}"
    exit 1
fi

# Find the benchmark compare script
BENCHMARK_COMPARE=""
for candidate in "$BENCHMARK_DIR/compare.sh"; do
    if [ -f "$candidate" ]; then
        BENCHMARK_COMPARE="$candidate"
        break
    fi
done

if [ -z "$BENCHMARK_COMPARE" ]; then
    echo -e "${RED}Error: No compare script found for benchmark '$BENCHMARK'${NC}"
    echo -e "${YELLOW}Expected: $BENCHMARK_DIR/compare.sh${NC}"
    exit 1
fi

# Setup
cd "$PROJECT_ROOT"

# Load environment
source "$PROJECT_ROOT/benchmarks/helpers/load_env.sh" "$BENCHMARK"

# Apply model profile
apply_model_profile_if_set

# Check Langfuse env vars
check_langfuse_env

# Export common variables
export RUNS OUTPUT_FILE DRY_RUN NO_BUNDLE BUNDLE_ZIP MODEL_PROFILE VERBOSE AGENT AGENTS COMPARE_AGENTS

# Banner: when comparing multiple agents, show the agent list instead of the singular AGENT.
BANNER_AGENT_LABEL="$AGENT"
if [[ "$AGENTS" == *,* ]]; then
    BANNER_AGENT_LABEL="$AGENTS"
fi
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Compare: ${BENCHMARK} [${BANNER_AGENT_LABEL}] (${RUNS} runs)$(printf '%*s' $((27 - ${#BENCHMARK} - ${#BANNER_AGENT_LABEL} - ${#RUNS})) '')║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Dispatch to benchmark script, forwarding --runs/--output/--agents if set
DISPATCH_ARGS=()
DISPATCH_ARGS+=(--runs "$RUNS")
if [ -n "$OUTPUT_FILE" ]; then
    DISPATCH_ARGS+=(--output "$OUTPUT_FILE")
fi
if [ "$DRY_RUN" = "true" ]; then
    DISPATCH_ARGS+=(--dry-run)
fi
# Propagate AGENTS so the per-benchmark compare.sh can iterate over them.
# We always pass --agents (resolved to at least the singular AGENT in parse_common_args).
DISPATCH_ARGS+=(--agents "$AGENTS")
if [ "$COMPARE_AGENTS" = "true" ]; then
    DISPATCH_ARGS+=(--compare-agents)
fi
DISPATCH_ARGS+=("${FORWARDED_ARGS[@]}")

exec bash "$BENCHMARK_COMPARE" "${DISPATCH_ARGS[@]}"
