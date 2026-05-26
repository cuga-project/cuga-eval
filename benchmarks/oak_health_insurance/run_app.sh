#!/bin/bash

# Script to load environment variables and run the Oak Health Insurance FastAPI app

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HELPERS_DIR="$PROJECT_ROOT/benchmarks/helpers"

echo "Loading Oak Health Insurance configuration..."

# Load environment variables using helper script
source "$HELPERS_DIR/load_env.sh" "oak_health_insurance"

echo ""
echo "Starting FastAPI app..."
cd "$SCRIPT_DIR"
uv run uvicorn main:app --reload --port 8090
