#!/bin/bash
# AppWorld analytics — thin wrapper around scripts/analyze.sh.
#
# Usage:
#   ./analyze.sh --analytics trace_compare
#   ./analyze.sh --analytics trace_compare --config my_experiment.conf
#   ./analyze.sh --analytics trace_compare --pairing-mode n_pairs --n 5
#   ./analyze.sh --analytics trace_compare --task-ids e775c78_1 fd1f8fa_2
#
# All options are forwarded to scripts/analyze.sh with --benchmark appworld.
# See scripts/analyze.sh for the full option reference.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/../../scripts/analyze.sh" --benchmark appworld "$@"
