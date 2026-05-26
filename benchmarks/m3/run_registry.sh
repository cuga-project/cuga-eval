#!/bin/bash

# Script to load all environment variables for M3 evaluation and start the registry
# This script uses the generic helper from benchmarks/helpers

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPERS_DIR="$SCRIPT_DIR/../helpers"

# Use the generic helper script
exec "$HELPERS_DIR/run_registry.sh" "m3"
