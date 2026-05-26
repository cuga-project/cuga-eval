#!/bin/bash

# Script to load environment variables and run AppWorld

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HELPERS_DIR="$PROJECT_ROOT/benchmarks/helpers"

echo "Loading AppWorld configuration..."

# Load environment variables using helper script
source "$HELPERS_DIR/load_env.sh" "appworld"

echo ""
echo "Starting AppWorld..."
cd "$PROJECT_ROOT"
uv run cuga start appworld
