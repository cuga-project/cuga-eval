#!/bin/bash
# AppWorld evaluation runner with repository-managed environment setup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HELPERS_DIR="$PROJECT_ROOT/benchmarks/helpers"

source "$HELPERS_DIR/load_env.sh" "appworld"

cuga-eval appworld "$@"
