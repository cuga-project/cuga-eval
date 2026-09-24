#!/usr/bin/env bash
# Score EVERY arm of a parity run with ONE evaluator against ONE ground truth:
# the other repo's official evaluator (vakra-main/evaluator, live tool replay) and
# its data/train ground truth, cut to the subset. cuga-eval predictions are
# re-keyed to the other repo's uuids first (manifests/uuid_map_*.json).
# usage: rescore.sh <run_id> <subset>      (requires: source env.sh; containers up)
set -uo pipefail
PARITY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$PARITY_DIR/../../.." && pwd)"
RUN_ID="${1:?run_id}"; SUBSET="${2:?subset}"
[ -n "${PARITY_B1:-}" ] || { echo "source benchmarks/m3/parity/env.sh first" >&2; exit 2; }
VAKRA_MAIN="${VAKRA_MAIN:-$HOME/git/appworld/vakra-main}"
RUN="$PARITY_DIR/runs/$RUN_ID"; MAP="$PARITY_DIR/manifests/uuid_map_$SUBSET.json"; MAN="$PARITY_DIR/manifests/$SUBSET.json"
TASK_ID=$(python3 -c "import json;print(json.load(open('$MAP'))['task_id'])")
CAPDIR=$(python3 -c "import json;print(json.load(open('$MAP'))['capability_dir'])")
case "$TASK_ID" in 1) CAPNAME=capability_bi_apis;; 2) CAPNAME=capability_dashboard_apis;; 3) CAPNAME=capability_multihop_reasoning;; *) echo "unsupported task $TASK_ID" >&2; exit 2;; esac
DOMS=$(python3 -c "import json;print(' '.join(sorted(json.load(open('$MAN'))['ids_by_domain'])))")
export API_KEY="${API_KEY:?}" JUDGE_ENDPOINT="$PARITY_B1" JUDGE_MODEL="${PARITY_MODEL:-azure/gpt-oss-120b}"

GT="$RUN/gt"
(cd "$ROOT" && uv run --frozen python -m benchmarks.m3.parity.snapshot gt-subset --map "$MAP" --vakra-gt "$VAKRA_MAIN/data/train/$CAPDIR/output" --out "$GT") | tee "$RUN/gt_subset.json"
restart_ctr() { docker restart "$1" >/dev/null 2>&1; for _ in $(seq 1 15); do docker logs --tail 3 "$1" 2>&1 | grep -q "ready for exec" && break; sleep 3; done; sleep 2; }

RC=0
for ARMDIR in "$RUN"/cuga_eval_* "$RUN"/vakra_main_*; do
    [ -d "$ARMDIR" ] || continue
    ARM=$(basename "$ARMDIR")
    case "$ARM" in
        cuga_eval_*)
            PRED="$ARMDIR/prediction_vakra_ids"
            (cd "$ROOT" && uv run --frozen python -m benchmarks.m3.parity.snapshot remap --map "$MAP" --in "$ARMDIR/prediction" --out "$PRED") | tee "$ARMDIR/remap.json";;
        *) PRED="$ARMDIR/prediction";;
    esac
    [ -n "$(ls "$PRED"/*.json 2>/dev/null)" ] || { echo "[$ARM] no predictions to score" | tee -a "$ARMDIR/rescore.log"; continue; }
    [ "${PARITY_RESCORE_RESUME:-0}" = "1" ] || rm -f "$ARMDIR/vendor_results.json"   # the evaluator resumes from an existing output
    restart_ctr "$CAPDIR"
    echo "[$ARM] vendor evaluator start $(date '+%T')" | tee -a "$ARMDIR/rescore.log"
    (cd "$VAKRA_MAIN" && PYTHONPATH="$VAKRA_MAIN:$VAKRA_MAIN/evaluator" .venv/bin/python evaluator/evaluator.py \
        --capability_name "$CAPNAME" --gt_root "$GT" --pred_root "$PRED" --output "$ARMDIR/vendor_results.json" \
        --mcp-config benchmark/mcp_connection_config.yaml --domains $DOMS) >> "$ARMDIR/rescore.log" 2>&1 || { echo "[$ARM] evaluator exit $?" | tee -a "$ARMDIR/rescore.log"; RC=1; }
    echo "[$ARM] vendor evaluator done $(date '+%T')" | tee -a "$ARMDIR/rescore.log"
done
restart_ctr "$CAPDIR"
exit $RC
