#!/usr/bin/env bash
# Policy-types evaluation (2026-11-03): gpt-oss-120b, function calling, 35-task subset (policy_types_subset.json).
# All cells of one trial start at the same time from one frozen code snapshot.
#
#   ./run_policy_types.sh <snapshot> <trial> [jobs per cell]
#
# Cells: A-O  CUGA alone, oracle tools (limited_zapier)
#        A-F  CUGA alone, all 549 tools + find_tools + dynamic binding by app
#        B-F  + policy layer (online intake + verifier, reminders; final1 configuration)
#        T-F  + requirements tracker (follow-up on missing items)
#        BT-F + policy layer and tracker together
#        D-F  + deliverables checklist (request actions checked at the reply)
#        B3-F + policy layer with policy discovery and newer-rule-wins (added in trial 2)
#        B3T-F + B3 and tracker together (added in trial 2)
#        B4T-F + B3T-F with decision-model write checks, block-once verdicts, skip after cap (POLICY_V4)
set -euo pipefail
cd "$(dirname "$0")"
SNAP=${1:?snapshot name under /tmp/cuga_snapshots}
TRIAL=${2:?trial number}
JOBS=${3:-5}
SRC=/tmp/cuga_snapshots/$SNAP/src
[ -d "$SRC" ] || { echo "no snapshot $SRC"; exit 1; }
SUBSET=${SUBSET:-policy_types_subset.json}  # SUBSET=policy_types_holdout.json PREFIX=ph for the held-out draw
PREFIX=${PREFIX:-pt}
TASKS=$(python3 -c 'import json,sys; print(",".join(t["task"] for t in json.load(open(sys.argv[1]))["tasks"]))' "$SUBSET")
export CUGA_ENV_FILE=cuga.gptoss.fc.dyn.env CUGA_SRC=$SRC POLICY_MODEL_NAME=aws/gpt-oss-120b POLICY_TRACKER_MODEL=aws/gpt-oss-120b

want() { [ -z "${ONLY:-}" ] || [[ " $ONLY " == *" $1 "* ]]; }  # ONLY="A-F B3-F": run just these cells

cell() {  # cell label, run prefix, extra env (space-separated K=V or -), runner args...
  local label=$1 run=${PREFIX}_$2_t$TRIAL extra=$3; shift 3
  [ "$extra" = "-" ] && extra=""
  want "$label" || return 0
  echo "== $label -> results/$run"
  env POLICY_EVAL_CELL="$label" $extra .venv/bin/python run_cuga.py --tasks "$TASKS" --run "$run" --trial "$TRIAL" -j "$JOBS" "$@" \
    > "results/$run.out" 2>&1
}

cell A-O AO - --toolset limited_zapier &
cell A-F AF - --toolset full &
cell B-F BF - --toolset full --arm B &
cell T-F TF POLICY_TRACKER=1 --toolset full &
cell BT-F BTF POLICY_TRACKER=1 --toolset full --arm B &
[ "${SKIP_D:-}" = 1 ] || cell D-F DF POLICY_DELIVERABLES=1 --toolset full &
cell B4T-F B4TF "POLICY_SUPERSEDES=1 POLICY_DISCOVER=1 POLICY_TRACKER=1 POLICY_V4=1" --toolset full --arm B &
if [ "${WITH_B3:-1}" = 1 ]; then
  cell B3-F B3F "POLICY_SUPERSEDES=1 POLICY_DISCOVER=1" --toolset full --arm B &
  cell B3T-F B3TF "POLICY_SUPERSEDES=1 POLICY_DISCOVER=1 POLICY_TRACKER=1" --toolset full --arm B &
fi
wait
echo "== trial $TRIAL done $(date)"
