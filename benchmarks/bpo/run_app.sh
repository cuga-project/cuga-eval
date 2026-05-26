#!/bin/bash

# Script to load environment variables and run the BPO FastAPI app

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HELPERS_DIR="$PROJECT_ROOT/benchmarks/helpers"

echo "Loading BPO configuration..."

# Load environment variables using helper script
source "$HELPERS_DIR/load_env.sh" "bpo"

echo ""
echo "Starting BPO FastAPI app on port 8095..."
cd "$PROJECT_ROOT"
uv run uvicorn benchmarks.bpo.main:app --reload --port 8095
