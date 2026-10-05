#!/usr/bin/env bash
# One parity arm on THIS stack (cuga main + cuga-eval adapter), domain by domain, resumable.
# usage: run_cuga_eval_arm.sh <run_id> <subset> <preset: off|cap1|cap2|cap3> [extra eval.sh args...]
# Requires: source benchmarks/m3/parity/env.sh (and a PASSing preflight).
# For every domain of the subset: eval.sh over the subset's eval-key restricted to that
# domain, policies OFF (the campaign ran DYNACONF_POLICY__ENABLED=false), then a snapshot
# into parity/runs/<run_id>/cuga_eval_<preset>/. A domain whose prediction file already
# exists is skipped, so re-running the same run_id resumes after an interruption; an
# environment failure (eval.sh exit 3: containers/daemon down) stops the arm immediately.
set -uo pipefail
PARITY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$PARITY_DIR/../../.." && pwd)"
RUN_ID="${1:?run_id}"; SUBSET="${2:?subset}"; PRESET="${3:?preset}"; shift 3
[ -n "${AGENT_SETTING_CONFIG:-}" ] && [ -n "${PARITY_B1:-}" ] || { echo "source benchmarks/m3/parity/env.sh first" >&2; exit 2; }
MAN="$PARITY_DIR/manifests/$SUBSET.json"; [ -f "$MAN" ] || { echo "no manifest $MAN" >&2; exit 2; }
TASK_ID=$(python3 -c "import json;print(json.load(open('$MAN'))['task_id'])")
DOMS=$(python3 -c "import json;print(' '.join(json.load(open('$MAN'))['ids_by_domain']))")
FC="${PARITY_FC:-0}"
ARM="cuga_eval_${PRESET}"; [ "$FC" = "1" ] && ARM="${ARM}_fc"
OUT="$PARITY_DIR/runs/$RUN_ID/$ARM"; mkdir -p "$OUT/prediction"
ARM_START=$(date +%s); FINAL_RC=0

# Execution mode. The settings key reaches every agent (also the plain `off` one); the
# adapter's execution_mode sets the per-invoke keys for presets. Non-FC arms must UNSET the
# settings key: cuga resolves configurable > model profile > settings, and a CodeAct preset
# sets nothing per invoke.
if [ "$FC" = "1" ]; then
    export DYNACONF_ADVANCED_FEATURES__CUGA_LITE_EXECUTION_MODE=function_calling
    export M3_ADAPTER_EXECUTION_MODE=function_calling
else
    unset DYNACONF_ADVANCED_FEATURES__CUGA_LITE_EXECUTION_MODE
    export M3_ADAPTER_EXECUTION_MODE=codeact
fi

# Data + demo source from the manifest: default the bundled small_train.zip; "local:<name>" means
# parity/.local/<name> (vakra-main train data converted by prepare_vakra_train.py; gitignored).
read -r M3DATA DEMODATA NOGT <<<"$(python3 - "$MAN" "$PARITY_DIR" "$ROOT" <<'PY'
import json, sys
m, parity, root = json.load(open(sys.argv[1])), sys.argv[2], sys.argv[3]
res = lambda v: f"{parity}/.local/{v[6:]}" if v.startswith("local:") else v
print(res(m.get("m3_data") or f"{root}/benchmarks/m3/data/small_train.zip"), res(m.get("demo_data") or "-"), "1" if m.get("no_ground_truth") else "0")
PY
)"
[ -e "$M3DATA" ] || { echo "data source $M3DATA missing — run: uv run --frozen python -m benchmarks.m3.parity.prepare_vakra_train --manifest $MAN --vakra-main \$VAKRA_MAIN --out <dir>" >&2; exit 2; }
BASE_ARGS=(--m3-data "$M3DATA" --capability "m3_task_$TASK_ID" --eval-key "$SUBSET" --no-policies --no-bundle)
# predictions only: eval_m3's ground-truth mode only runs the registry YAML's small_train domains
[ "$NOGT" = "1" ] && BASE_ARGS+=(--no-ground-truth)
[ "$PRESET" != "off" ] && BASE_ARGS+=(--adapter-preset "$PRESET")
[ "$PRESET" != "off" ] && [ "$DEMODATA" != "-" ] && BASE_ARGS+=(--demo-data "$DEMODATA")
echo "bash benchmarks/m3/eval.sh ${BASE_ARGS[*]} --domain <domain> $*" > "$OUT/command.txt"
echo "[$ARM] start $(date '+%F %T')  temperature=$PARITY_TEMPERATURE model=$PARITY_MODEL fc=$FC domains: $DOMS" | tee -a "$OUT/console.log"

for dom in $DOMS; do
    if [ -f "$OUT/prediction/$dom.json" ]; then
        echo "[$ARM] $dom already done (resume)" | tee -a "$OUT/console.log"; continue
    fi
    if lsof -nP -iTCP:"${REGISTRY_PORT:-8001}" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "[$ARM] registry port ${REGISTRY_PORT:-8001} still busy before $dom — waiting 30s" | tee -a "$OUT/console.log"; sleep 30
    fi
    DOM_START=$(date +%s)
    echo "[$ARM] $dom start $(date '+%T')" | tee -a "$OUT/console.log"
    (cd "$ROOT" && bash benchmarks/m3/eval.sh "${BASE_ARGS[@]}" --domain "$dom" "$@") 2>&1 | tee -a "$OUT/console.log"
    RC=${PIPESTATUS[0]}
    (cd "$ROOT" && uv run --frozen python -m benchmarks.m3.parity.snapshot snapshot-cuga-eval \
        --manifest "$MAN" --results-dir "$ROOT/benchmarks/m3/results" --since "$DOM_START" --out "$OUT" --domains "$dom") | tee -a "$OUT/snapshot.jsonl"
    echo "[$ARM] $dom done rc=$RC in $(( $(date +%s) - DOM_START ))s" | tee -a "$OUT/console.log"
    if [ "$RC" = "3" ]; then
        echo "[$ARM] environment failure at $dom (containers/daemon) — stopping this arm; re-run the same run_id to resume" | tee -a "$OUT/console.log"
        FINAL_RC=3; break
    fi
    [ "$RC" != "0" ] && FINAL_RC=$RC
done
ARM_END=$(date +%s)

_git() { git -C "$1" rev-parse --abbrev-ref HEAD 2>/dev/null; git -C "$1" rev-parse --short HEAD 2>/dev/null; git -C "$1" status --porcelain 2>/dev/null | wc -l | tr -d ' '; }
read -r AB AC AD <<<"$(_git "$ROOT" | tr '\n' ' ')"
read -r CB CC CD <<<"$(_git "${CUGA_AGENT_DIR:-$ROOT/../cuga-agent}" | tr '\n' ' ')"
DONE_DOMS=$(ls "$OUT/prediction" 2>/dev/null | sed 's/.json$//' | tr '\n' ' ')
python3 - "$OUT" <<PY
import json, sys
json.dump({
    "arm": "$ARM", "stack": "cuga-eval", "subset": "$SUBSET", "task_id": $TASK_ID, "adapter_preset": "$PRESET",
    "execution_mode": "${M3_ADAPTER_EXECUTION_MODE:-n/a}", "fc": "$FC", "policies": "off", "temperature": "$PARITY_TEMPERATURE",
    "model": "$PARITY_MODEL", "models_toml": "$AGENT_SETTING_CONFIG",
    "cuga_eval": {"branch": "$AB", "commit": "$AC", "dirty_files": "$AD"},
    "cuga_agent": {"branch": "$CB", "commit": "$CC", "dirty_files": "$CD"},
    "domains_done": "$DONE_DOMS".split(), "started": $ARM_START, "finished": $ARM_END, "eval_exit_code": $FINAL_RC,
}, open(sys.argv[1] + "/meta.json", "w"), indent=1)
PY
echo "[$ARM] done rc=$FINAL_RC in $((ARM_END-ARM_START))s (domains done: $DONE_DOMS) -> $OUT" | tee -a "$OUT/console.log"
exit $FINAL_RC
