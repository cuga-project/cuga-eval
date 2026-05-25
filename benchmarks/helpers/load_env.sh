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

# Load an env file without overriding variables already set in the environment.
# This lets model profiles exported by compare.sh take precedence over .env defaults.
_source_no_override() {
    local file="$1"
    local line key val
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line//[[:space:]]/}" ]] && continue
        if [[ "$line" =~ ^[[:space:]]*export[[:space:]]+([A-Za-z_][A-Za-z0-9_]*)=(.*) ]]; then
            key="${BASH_REMATCH[1]}"
            val="${BASH_REMATCH[2]}"
        elif [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*) ]]; then
            key="${BASH_REMATCH[1]}"
            val="${BASH_REMATCH[2]}"
        else
            continue
        fi
        # Skip if already set (allows model profile exports from compare.sh to win)
        [[ -n "${!key+x}" ]] && continue
        # Strip surrounding quotes
        val="${val#\"}" ; val="${val%\"}"
        val="${val#\'}" ; val="${val%\'}"
        export "$key=$val"
    done < "$file"
}

# Load .env file if it exists (for secrets like API keys)
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "✓ Loading .env file (secrets)"
    _source_no_override "$PROJECT_ROOT/.env"
fi

# Load global.env
if [ -f "$CONFIG_DIR/global.env" ]; then
    echo "✓ Loading global.env"
    _source_no_override "$CONFIG_DIR/global.env"
fi

# Load benchmark-specific .env file if benchmark name is provided
if [ -n "$BENCHMARK_NAME" ]; then
    BENCHMARK_ENV="$PROJECT_ROOT/benchmarks/${BENCHMARK_NAME}/config/${BENCHMARK_NAME}.env"
    if [ -f "$BENCHMARK_ENV" ]; then
        echo "✓ Loading ${BENCHMARK_NAME}.env"
        _source_no_override "$BENCHMARK_ENV"
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
