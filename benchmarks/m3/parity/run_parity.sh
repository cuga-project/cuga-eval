#!/usr/bin/env bash
# Cross-repo parity run: the same train subset on THIS stack (cuga main + adapter) and on
# the OTHER stack (~/git/appworld/vakra-main), identical model/temperature/judge, sequential arms,
# one evaluator for all arms, then a per-task comparison report.
#
# usage: bash benchmarks/m3/parity/run_parity.sh --subset parity_smoke_hockey|parity_cap2_30|parity_cap3_20
#          [--arms cuga_eval_off,cuga_eval_cap2,vakra_main_base,vakra_main_fc_canon]   # default: all four for the subset
#          [--fc-ab]   # arms = <preset>, <preset>_fc, fc_canon, fc_canon_fc: the FC on/off gate, both stacks, one report
#          [--temperature 1.0] [--fc 0|1] [--run-id ID] [--skip-preflight] [--rescore-only] [--dry-run]
# An arm name ending in _fc runs with native function calling regardless of --fc
# (e.g. cuga_eval_cap3_fc, vakra_main_fc_canon_fc, cuga_eval_off_fc).
# Anchors (see README.md): smoke off=0 / cap2=1; cap2_30 off 30.0% / cap2 63.3%; cap3_20 off 20.0% / cap3 35.0%.
set -uo pipefail
PARITY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$PARITY_DIR/../../.." && pwd)"
SUBSET=""; ARMS=""; TEMP="1.0"; FC="0"; RUN_ID=""; SKIP_PRE=0; RESCORE_ONLY=0; DRY=0; FC_AB=0
while [ $# -gt 0 ]; do
    case "$1" in
        --subset) SUBSET="$2"; shift 2;;
        --arms) ARMS="$2"; shift 2;;
        --temperature) TEMP="$2"; shift 2;;
        --fc) FC="$2"; shift 2;;
        --fc-ab) FC_AB=1; shift;;
        --run-id) RUN_ID="$2"; shift 2;;
        --skip-preflight) SKIP_PRE=1; shift;;
        --rescore-only) RESCORE_ONLY=1; shift;;
        --dry-run) DRY=1; shift;;
        -h|--help) sed -n '2,10p' "$0"; exit 0;;
        *) echo "unknown flag $1" >&2; exit 2;;
    esac
done
[ -n "$SUBSET" ] || { echo "--subset is required" >&2; exit 2; }
MAN="$PARITY_DIR/manifests/$SUBSET.json"; [ -f "$MAN" ] || { echo "unknown subset $SUBSET (see manifests/)" >&2; exit 2; }
PRESET=$(python3 -c "import json;print(json.load(open('$MAN'))['adapter_preset'])")
if [ "$FC_AB" = "1" ]; then
    ARMS="cuga_eval_${PRESET},cuga_eval_${PRESET}_fc,vakra_main_fc_canon,vakra_main_fc_canon_fc"
fi
[ -n "$ARMS" ] || ARMS="cuga_eval_off,cuga_eval_${PRESET},vakra_main_base,vakra_main_fc_canon"
TAG="fc${FC}"; [ "$FC_AB" = "1" ] && TAG="fcab"
[ -n "$RUN_ID" ] || RUN_ID="$(date +%Y%m%d_%H%M%S)_${SUBSET}_t${TEMP}_${TAG}"
# arm -> "script base fc": a trailing _fc forces function calling for that arm
arm_plan() {
    local a="$1" fc="$FC"
    case "$a" in *_fc) fc=1; a="${a%_fc}";; esac
    case "$a" in
        cuga_eval_*) echo "run_cuga_eval_arm.sh ${a#cuga_eval_} $fc";;
        vakra_main_*) echo "run_vakra_main_arm.sh ${a#vakra_main_} $fc";;
        *) echo "unknown";;
    esac
}
ANY_FC="$FC"
for a in ${ARMS//,/ }; do
    read -r _s _b _f <<<"$(arm_plan "$a")"
    [ "$_s" = "unknown" ] && { echo "unknown arm $a" >&2; exit 2; }
    [ "$_f" = "1" ] && ANY_FC=1
done
export PARITY_FC="$ANY_FC"   # preflight: require native FC when any arm uses it

echo "== parity run $RUN_ID: subset=$SUBSET arms=$ARMS temperature=$TEMP fc=$FC (arms ending in _fc: FC on) =="
if [ "$DRY" = "1" ]; then
    echo "source $PARITY_DIR/env.sh $TEMP"
    echo "bash $PARITY_DIR/preflight.sh"
    for a in ${ARMS//,/ }; do
        read -r _s _b _f <<<"$(arm_plan "$a")"
        echo "PARITY_FC=$_f bash $PARITY_DIR/$_s $RUN_ID $SUBSET $_b"
    done
    echo "bash $PARITY_DIR/rescore.sh $RUN_ID $SUBSET"
    echo "uv run --frozen python -m benchmarks.m3.parity.compare --run $PARITY_DIR/runs/$RUN_ID --subset $SUBSET"
    exit 0
fi
# shellcheck source=env.sh
source "$PARITY_DIR/env.sh" "$TEMP" || exit 1
[ "$SKIP_PRE" = "1" ] || bash "$PARITY_DIR/preflight.sh" "$(python3 -c "import json;print(json.load(open('$MAN'))['task_id'])")" || exit 1
mkdir -p "$PARITY_DIR/runs/$RUN_ID"
if [ "$RESCORE_ONLY" != "1" ]; then
    for a in ${ARMS//,/ }; do
        read -r _s _b _f <<<"$(arm_plan "$a")"
        PARITY_FC="$_f" bash "$PARITY_DIR/$_s" "$RUN_ID" "$SUBSET" "$_b" || echo "arm $a exited non-zero (continuing)"
    done
fi
bash "$PARITY_DIR/rescore.sh" "$RUN_ID" "$SUBSET" || echo "rescore reported errors (see rescore.log files)"
(cd "$ROOT" && uv run --frozen python -m benchmarks.m3.parity.compare --run "$PARITY_DIR/runs/$RUN_ID" --subset "$SUBSET")
