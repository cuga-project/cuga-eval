#!/usr/bin/env bash
# End-to-end smoke: one AppWorld (SDK), one AppWorld (ReAct), one M3 hockey task.
# Validates bundle report.md metrics (tokens, steps, time, etc.; cost may be "--").
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VALIDATE="$ROOT/scripts/validate_bundle_report.py"
APPWORLD_TASK="${SMOKE_APPWORLD_TASK:-82e2fac_1}"

latest_bundle_report() {
  local benchmark="$1"
  local bundle_root="$ROOT/benchmarks/$benchmark/evaluation_bundles"
  local report
  report="$(find "$bundle_root" -name report.md -type f 2>/dev/null | sort | tail -1)"
  if [ -z "$report" ]; then
    echo "No bundle report.md under $bundle_root" >&2
    return 1
  fi
  echo "$report"
}

run_and_check() {
  local label="$1"
  local benchmark="$2"
  shift 2
  echo ""
  echo "========== $label =========="
  "$@"
  local report
  report="$(latest_bundle_report "$benchmark")"
  echo "Validating $report"
  uv run python -m benchmarks.helpers.validate_bundle_report "$report"
}

echo "Smoke benchmarks (ROOT=$ROOT)"

run_and_check "AppWorld SDK (cuga)" appworld \
  bash "$ROOT/benchmarks/appworld/eval.sh" --sdk --task "$APPWORLD_TASK"

run_and_check "AppWorld ReAct" appworld \
  bash "$ROOT/benchmarks/appworld/eval.sh" --agent react --task "$APPWORLD_TASK"

run_and_check "M3 hockey (m3_task_2, max-samples 1)" m3 \
  bash "$ROOT/benchmarks/m3/eval.sh" \
  --m3-data "$ROOT/benchmarks/m3/data/small_train.zip" \
  --capability m3_task_2 --domain hockey --max-samples 1

echo ""
echo "All smoke benchmark runs passed report validation."
