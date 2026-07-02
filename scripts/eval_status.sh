#!/bin/bash
# Live AppWorld eval status dashboard.
#
# Usage:
#   ./scripts/eval_status.sh              # Open browser dashboard (default)
#   ./scripts/eval_status.sh --no-open    # Serve only
#   ./scripts/eval_status.sh print        # One-shot terminal summary

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"
if [[ $# -eq 0 ]]; then
    exec uv run --no-sync python -m benchmarks.helpers.eval_status serve
fi
exec uv run --no-sync python -m benchmarks.helpers.eval_status "$@"
