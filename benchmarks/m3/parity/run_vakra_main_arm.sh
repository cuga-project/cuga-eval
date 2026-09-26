#!/usr/bin/env bash
# One parity arm on the OTHER stack (~/git/appworld/vakra-main: its cuga_v2 adapter over its own CUGA checkout).
# usage: run_vakra_main_arm.sh <run_id> <subset> <arm: base|fc_canon>
# Requires: source benchmarks/m3/parity/env.sh (and a PASSing preflight).
#   base     = VAKRA_AGENT=cuga_v2 with every VAKRA_CUGA_* flag unset (the campaign's Phase-0 re-baseline)
#   fc_canon = the submitted recipe from cuga_runs/fc_canon_test.sh (FC only when PARITY_FC=1):
#              GATES + GATES_CAPS + CONTRACT + NORMALIZE + BLUFF_MAP + DEMOS(prose,k=2)
#              + FINAL_ANSWER_CANONICALIZE, top-k 128, temperature $PARITY_TEMPERATURE,
#              policies off, MAX_STEPS 40, AGENT_TIMEOUT_SECONDS 220 (PARITY_AGENT_TIMEOUT).
#              Note: that script does NOT set VAKRA_CUGA_CAP2_VERBATIM; the cuga-eval cap2 preset does.
# Runs only the manifest's uuids (VAKRA_RETRY_UUIDS_FILE, mapped by query text) and
# snapshots predictions into parity/runs/<run_id>/vakra_main_<arm>/prediction/.
set -uo pipefail
PARITY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_ID="${1:?run_id}"; SUBSET="${2:?subset}"; ARMNAME="${3:?base|fc_canon}"
[ -n "${PARITY_B1:-}" ] || { echo "source benchmarks/m3/parity/env.sh first" >&2; exit 2; }
MAP="$PARITY_DIR/manifests/uuid_map_$SUBSET.json"; [ -f "$MAP" ] || { echo "no uuid map $MAP" >&2; exit 2; }
VAKRA_MAIN="${VAKRA_MAIN:-$HOME/git/appworld/vakra-main}"
MODEL="${PARITY_MODEL:-azure/gpt-oss-120b}"; T="${PARITY_TEMPERATURE:-1.0}"
TASK_ID=$(python3 -c "import json;print(json.load(open('$MAP'))['task_id'])")
CAPDIR=$(python3 -c "import json;print(json.load(open('$MAP'))['capability_dir'])")
ARM="vakra_main_${ARMNAME}"; OUT="$PARITY_DIR/runs/$RUN_ID/$ARM"; RAW="$OUT/raw"; mkdir -p "$RAW" "$OUT/prediction"
START=$(date +%s)

cd "$VAKRA_MAIN" || exit 2
export OPENAI_API_BASE="$PARITY_B1/v1" OPENAI_BASE_URL="$PARITY_B1/v1"   # their litellm provider wants /v1
export VAKRA_AGENT=cuga_v2 DYNACONF_POLICY__ENABLED=false VAKRA_CUGA_MAX_STEPS=40 LITELLM_REQUEST_TIMEOUT_SECONDS=150
export AGENT_TIMEOUT_SECONDS="${PARITY_AGENT_TIMEOUT:-220}"
export "CAPABILITY_${TASK_ID}_DIR=$VAKRA_MAIN/data/train/$CAPDIR" VAKRA_CURRENT_CAPABILITY="$TASK_ID"
for f in VAKRA_CUGA_GATES VAKRA_CUGA_GATES_CAPS VAKRA_CUGA_CONTRACT VAKRA_CUGA_CAP1_PROTOCOL VAKRA_CUGA_CAP2_VERBATIM \
         VAKRA_CUGA_NORMALIZE VAKRA_CUGA_BLUFF_MAP VAKRA_CUGA_DEMOS VAKRA_CUGA_DEMOS_MODE VAKRA_DEMOS_K \
         VAKRA_CUGA_STEPWISE VAKRA_CUGA_STEPWISE_STRUCT VAKRA_CUGA_REQUIRE_TOOL VAKRA_CUGA_FC VAKRA_RELIST_AFTER_SWITCH \
         VAKRA_CUGA_TOOLFINDER DYNACONF_ADVANCED_FEATURES__FINAL_ANSWER_CANONICALIZE; do unset "$f"; done
case "$ARMNAME" in
    base) ;;
    fc_canon)
        export VAKRA_CUGA_GATES=1 VAKRA_CUGA_GATES_CAPS="$TASK_ID" VAKRA_CUGA_CONTRACT=1 VAKRA_CUGA_NORMALIZE=1 \
               VAKRA_CUGA_BLUFF_MAP=1 VAKRA_CUGA_DEMOS=1 VAKRA_CUGA_DEMOS_MODE=prose VAKRA_DEMOS_K=2 \
               DYNACONF_ADVANCED_FEATURES__FINAL_ANSWER_CANONICALIZE=true
        [ "$TASK_ID" = "1" ] && export VAKRA_RELIST_AFTER_SWITCH=1 VAKRA_CUGA_CAP1_PROTOCOL=1
        [ "${PARITY_FC:-0}" = "1" ] && export VAKRA_CUGA_FC=1
        [ -n "${PARITY_VAKRA_EXTRA_FLAGS:-}" ] && for kv in $PARITY_VAKRA_EXTRA_FLAGS; do export "$kv"; done
        ;;
    *) echo "arm must be base|fc_canon" >&2; exit 2;;
esac
env | grep -E '^(VAKRA_|DYNACONF_)' | sort > "$OUT/flags.txt"

wait_proxy() {
    local ok=0 code body
    body=$(mktemp)
    while [ $ok -lt 2 ]; do
        code=$(curl -s -m 20 -o "$body" -w "%{http_code}" "$PARITY_B1/v1/chat/completions" -H "Authorization: Bearer $OPENAI_API_KEY" \
            -H "Content-Type: application/json" -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_completion_tokens\":8,\"reasoning_effort\":\"low\"}")
        if grep -qi "budget has been exceeded" "$body" 2>/dev/null; then
            echo "[$ARM] proxy=$code BUDGET EXHAUSTED — aborting the arm (ask for a budget reset / another key)" | tee -a "$OUT/console.log"
            rm -f "$body"; exit 3
        fi
        case "$code" in 200|429) ok=$((ok+1)); sleep 2;; *) echo "[$ARM] proxy=$code, waiting 120s" | tee -a "$OUT/console.log"; ok=0; sleep 120;; esac
    done
    rm -f "$body"
}
restart_ctr() {
    docker restart "$1" >/dev/null 2>&1
    for _ in $(seq 1 15); do docker logs --tail 3 "$1" 2>&1 | grep -q "ready for exec" && break; sleep 3; done; sleep 2
}
DOMS=$(python3 - "$MAP" "$RAW" <<'PY'
import json, sys
m = json.load(open(sys.argv[1])); raw = sys.argv[2]
by = {}
for e in m["zip_to_vakra"].values(): by.setdefault(e["domain"], []).append(e["vakra_uuid"])
for dom, ids in by.items(): json.dump(ids, open(f"{raw}/uuids_{dom}.json", "w"))
print(" ".join(sorted(by)))
PY
)
echo "[$ARM] start $(date '+%F %T') domains: $DOMS  temperature=$T model=$MODEL fc=${PARITY_FC:-0}" | tee -a "$OUT/console.log"
for dom in $DOMS; do
    BOUT="$RAW/$dom"; mkdir -p "$BOUT"
    if [ -f "$BOUT/$dom.json" ]; then
        echo "[$ARM] $dom already done (resume)" | tee -a "$OUT/console.log"
    else
        restart_ctr "$CAPDIR"; wait_proxy
        echo "[$ARM] $dom start $(date '+%T')" | tee -a "$OUT/console.log"
        VAKRA_RETRY_UUIDS_FILE="$RAW/uuids_$dom.json" PYTHONPATH="$VAKRA_MAIN" .venv-cuga/bin/python benchmark_runner.py \
            --capability_id "$TASK_ID" --domain "$dom" --restart --mcp-config benchmark/mcp_connection_config.yaml \
            --provider litellm --model "$MODEL" --temperature "$T" --top-k-tools 128 --output "$BOUT/" >> "$OUT/console.log" 2>&1 \
            || echo "[$ARM] $dom runner exit $?" | tee -a "$OUT/console.log"
    fi
    [ -f "$BOUT/$dom.json" ] && cp "$BOUT/$dom.json" "$OUT/prediction/$dom.json"
done
restart_ctr "$CAPDIR"
END=$(date +%s)
OC=$(.venv-cuga/bin/python -c "import cuga, os; print(os.path.dirname(os.path.dirname(cuga.__file__)))" 2>/dev/null)
python3 - "$OUT" "$OC" <<PY
import json, subprocess, sys
out, oc = sys.argv[1], sys.argv[2]
def git(*a):
    try: return subprocess.check_output(["git", "-C", oc + "/..", *a], text=True).strip()
    except Exception: return "?"
json.dump({
    "arm": "$ARM", "stack": "vakra-main", "subset": "$SUBSET", "task_id": $TASK_ID, "recipe": "$ARMNAME",
    "fc": "${PARITY_FC:-0}", "policies": "off", "temperature": "$T", "model": "$MODEL",
    "cuga_checkout": {"path": oc, "branch": git("rev-parse", "--abbrev-ref", "HEAD"), "commit": git("rev-parse", "--short", "HEAD"),
                      "dirty_files": len(git("status", "--porcelain").splitlines())},
    "started": $START, "finished": $END,
}, open(out + "/meta.json", "w"), indent=1)
PY
echo "[$ARM] done in $((END-START))s -> $OUT" | tee -a "$OUT/console.log"
