#!/usr/bin/env bash
# One parity arm on THIS stack (cuga main + cuga-eval adapter).
# usage: run_cuga_eval_arm.sh <run_id> <subset> <preset: off|cap1|cap2|cap3> [extra eval.sh args...]
# Requires: source benchmarks/m3/parity/env.sh (and a PASSing preflight).
# Runs eval.sh over the subset's eval-key with policies OFF (the campaign ran
# DYNACONF_POLICY__ENABLED=false) and snapshots the arm into parity/runs/<run_id>/cuga_eval_<preset>/.
set -uo pipefail
PARITY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$PARITY_DIR/../../.." && pwd)"
RUN_ID="${1:?run_id}"; SUBSET="${2:?subset}"; PRESET="${3:?preset}"; shift 3
[ -n "${AGENT_SETTING_CONFIG:-}" ] && [ -n "${PARITY_B1:-}" ] || { echo "source benchmarks/m3/parity/env.sh first" >&2; exit 2; }
MAN="$PARITY_DIR/manifests/$SUBSET.json"; [ -f "$MAN" ] || { echo "no manifest $MAN" >&2; exit 2; }
TASK_ID=$(python3 -c "import json;print(json.load(open('$MAN'))['task_id'])")
ARM="cuga_eval_${PRESET}"; OUT="$PARITY_DIR/runs/$RUN_ID/$ARM"; mkdir -p "$OUT"
START=$(date +%s)

ARGS=(--m3-data "$ROOT/benchmarks/m3/data/small_train.zip" --capability "m3_task_$TASK_ID" --eval-key "$SUBSET" --no-policies --no-bundle)
if [ "$PRESET" != "off" ]; then
    ARGS+=(--adapter-preset "$PRESET")
    # honoured by the adapter's FC pre-stage branch, ignored (no such field) on the PR branch
    if [ "${PARITY_FC:-0}" = "1" ]; then export M3_ADAPTER_EXECUTION_MODE=function_calling; else export M3_ADAPTER_EXECUTION_MODE=codeact; fi
fi
echo "bash benchmarks/m3/eval.sh ${ARGS[*]} $*" | tee "$OUT/command.txt"
echo "[$ARM] start $(date '+%F %T')  temperature=$PARITY_TEMPERATURE model=$PARITY_MODEL fc=${PARITY_FC:-0}"
(cd "$ROOT" && bash benchmarks/m3/eval.sh "${ARGS[@]}" "$@") 2>&1 | tee "$OUT/console.log"
RC=${PIPESTATUS[0]}
END=$(date +%s)

(cd "$ROOT" && uv run --frozen python -m benchmarks.m3.parity.snapshot snapshot-cuga-eval \
    --manifest "$MAN" --results-dir "$ROOT/benchmarks/m3/results" --since "$START" --out "$OUT") | tee "$OUT/snapshot.json"

_git() { git -C "$1" rev-parse --abbrev-ref HEAD 2>/dev/null; git -C "$1" rev-parse --short HEAD 2>/dev/null; git -C "$1" status --porcelain 2>/dev/null | wc -l | tr -d ' '; }
read -r AB AC AD <<<"$(_git "$ROOT" | tr '\n' ' ')"
read -r CB CC CD <<<"$(_git "${CUGA_AGENT_DIR:-$ROOT/../cuga-agent}" | tr '\n' ' ')"
python3 - "$OUT" <<PY
import json, sys
json.dump({
    "arm": "$ARM", "stack": "cuga-eval", "subset": "$SUBSET", "task_id": $TASK_ID, "adapter_preset": "$PRESET",
    "execution_mode": "${M3_ADAPTER_EXECUTION_MODE:-n/a}", "policies": "off", "temperature": "$PARITY_TEMPERATURE",
    "model": "$PARITY_MODEL", "models_toml": "$AGENT_SETTING_CONFIG",
    "cuga_eval": {"branch": "$AB", "commit": "$AC", "dirty_files": "$AD"},
    "cuga_agent": {"branch": "$CB", "commit": "$CC", "dirty_files": "$CD"},
    "started": $START, "finished": $END, "eval_exit_code": $RC,
}, open(sys.argv[1] + "/meta.json", "w"), indent=1)
PY
echo "[$ARM] done rc=$RC in $((END-START))s -> $OUT"
exit $RC
