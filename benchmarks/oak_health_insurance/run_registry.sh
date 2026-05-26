#!/bin/bash

# Script to load all environment variables for Oak Health Insurance evaluation and start the registry
# This script uses the generic helper from benchmarks/helpers

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPERS_DIR="$SCRIPT_DIR/../helpers"

# Use the generic helper script
exec "$HELPERS_DIR/run_registry.sh" "oak_health_insurance"
