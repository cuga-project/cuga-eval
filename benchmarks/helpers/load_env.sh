#!/bin/bash

# Helper script to load environment variables for benchmarks
# Usage: source load_env.sh [benchmark_name]
# If benchmark_name is not provided, it will be derived from the calling script's directory

if [ -z "$BENCHMARK_NAME" ]; then
    BENCHMARK_NAME="${1:-}"
fi

# If still not set, try to derive from calling script's directory
if [ -z "$BENCHMARK_NAME" ] && [ -n "${BASH_SOURCE[1]}" ]; then
    CALLING_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[1]}")" && pwd)"
    BENCHMARK_NAME="$(basename "$CALLING_SCRIPT")"
fi

# Get project root (assuming this file is in benchmarks/helpers/)
HELPERS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$HELPERS_DIR/../.." && pwd)"
CONFIG_DIR="$PROJECT_ROOT/config"

# Load .env file if it exists (for secrets like API keys)
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "✓ Loading .env file (secrets)"
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Load global.env
if [ -f "$CONFIG_DIR/global.env" ]; then
    echo "✓ Loading global.env"
    set -a
    source "$CONFIG_DIR/global.env"
    set +a
fi

# Load benchmark-specific .env file if benchmark name is provided
if [ -n "$BENCHMARK_NAME" ]; then
    BENCHMARK_ENV="$PROJECT_ROOT/benchmarks/${BENCHMARK_NAME}/config/${BENCHMARK_NAME}.env"
    if [ -f "$BENCHMARK_ENV" ]; then
        echo "✓ Loading ${BENCHMARK_NAME}.env"
        set -a
        source "$BENCHMARK_ENV"
        set +a
    else
        echo "⚠ Warning: ${BENCHMARK_ENV} not found"
    fi
fi

# Default LOGURU_LEVEL to WARNING to reduce noise from cuga library.
# Use --verbose in eval scripts to restore DEBUG output.
export LOGURU_LEVEL="${LOGURU_LEVEL:-WARNING}"

# Honour VERBOSE flag set by common.sh parse_common_args
if [ "${VERBOSE:-false}" = "true" ]; then
    export LOGURU_LEVEL=DEBUG
fi
