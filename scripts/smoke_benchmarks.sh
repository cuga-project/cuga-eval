#!/usr/bin/env bash
# End-to-end smoke: one AppWorld (SDK), one AppWorld (ReAct), one M3 hockey task.
# Validates bundle report.md metrics (tokens, steps, time, etc.; cost may be "--").
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APPWORLD_TASK="${SMOKE_APPWORLD_TASK:-82e2fac_1}"
RUN_START_TS=$(date +%s)

latest_bundle_report() {
  local benchmark="$1"
  local bundle_root="$ROOT/benchmarks/$benchmark/evaluation_bundles"
  local newest="" newest_mtime=0
  local f mtime
  while IFS= read -r -d '' f; do
    mtime=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f")
    if [ "$mtime" -ge "$RUN_START_TS" ] && [ "$mtime" -gt "$newest_mtime" ]; then
      newest_mtime=$mtime
      newest=$f
    fi
  done < <(find "$bundle_root" -name report.md -type f -print0 2>/dev/null || true)
  if [ -z "$newest" ]; then
    echo "No report.md from this smoke run under $bundle_root" >&2
    return 1
  fi
  echo "$newest"
}

free_port() {
  local port="$1"
  command -v lsof >/dev/null 2>&1 || return 0
  lsof -ti ":$port" >/dev/null 2>&1 || return 0

  echo "Freeing port $port..."
  lsof -ti ":$port" | xargs kill 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    lsof -ti ":$port" >/dev/null 2>&1 || return 0
    sleep 1
  done
  echo "Port $port still occupied; sending SIGKILL..."
  lsof -ti ":$port" | xargs kill -9 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    lsof -ti ":$port" >/dev/null 2>&1 || return 0
    sleep 1
  done
  echo "Port $port still occupied after SIGKILL" >&2
  return 1
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
  uv run --frozen python -m benchmarks.helpers.validate_bundle_report "$report"
}

echo "Smoke benchmarks (ROOT=$ROOT, RUN_START_TS=$RUN_START_TS)"

run_and_check "AppWorld SDK (cuga)" appworld \
  bash "$ROOT/benchmarks/appworld/eval.sh" --sdk --task "$APPWORLD_TASK"

run_and_check "AppWorld ReAct" appworld \
  bash "$ROOT/benchmarks/appworld/eval.sh" --agent react --task "$APPWORLD_TASK"

free_port 8001
run_and_check "M3 hockey (m3_task_2, max-samples 1)" m3 \
  bash "$ROOT/benchmarks/m3/eval.sh" \
  --m3-data "$ROOT/benchmarks/m3/data/small_train.zip" \
  --capability m3_task_2 --domain hockey --max-samples 1

echo ""
echo "All smoke benchmark runs passed report validation."
