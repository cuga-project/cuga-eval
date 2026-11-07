#!/usr/bin/env bash
# HANDBOOK, Gemini 3.8: A (alone) vs GW (procedure graph tools + must-not gate), same time.
# Usage: run_store_task.sh <snapshot> <task> <run prefix> <trial>...
set -u
SNAP=$1 TASK=$2 PFX=$3; shift 3
SRC=$HOME/dev/cuga_snapshots/$SNAP/src
[ -d "$SRC" ] || { echo "no snapshot $SRC" >&2; exit 1; }  # else cuga would resolve to the live tree
cd /Users/samimarreed/dev/cuga-eval/benchmarks
export OPENAI_API_KEY=$(automationbench/.venv/bin/python -I enterpriseops_gym/pick_key.py 034bb8)
export CUGA_SRC=$SRC CUGA_ENV_FILE=cuga.fc.gemini38.env
PY=~/dev/cuga-agent-gate/.venv/bin/python
STORE=$PWD/policy_eval/graphs_handbook/claude_v1
for t in "$@"; do
  $PY -I handbook/run_cuga_handbook.py --tasks $TASK --run ${PFX}_A_t$t --arm A --trial $t -j 1 > handbook/${PFX}_A_t${t}_parent.log 2>&1 &
  POLICY_STORE_DIR=$STORE POLICY_STORE_GATE=1 $PY -I handbook/run_cuga_handbook.py --tasks $TASK --run ${PFX}_GW_t$t --arm GW --trial $t -j 1 > handbook/${PFX}_GW_t${t}_parent.log 2>&1 &
done
wait; echo "$PFX trials $* done $(date)"
