#!/bin/zsh
# CSM tuning runs (2026-11-08), Haiku 5.5, 3 trials. Usage: csm_tune_2026-11-08.sh <run> <profile> <set>...
cd ~/dev/cuga-eval-policy/benchmarks/policy_eval; set -a; . ~/dev/cuga-eval/.env; set +a
export EOG_CSM_URL=http://127.0.0.1:8001 EOG_HR_URL=http://127.0.0.1:8008
S=${SNAP:-polisys-7dc68b0}; run=$1; prof=$2; shift 2
for set in "$@"; do for t in 1 2 3; do
  ~/dev/cuga-agent-gate/.venv/bin/python -I harness/run.py --bench ${BENCH:-csm} --profile $prof --set $set --snapshot $S --trial $t \
    --run ${run}_${set#*-} --model haiku55 -j 4 --proxy http://127.0.0.1:8801 > /tmp/aud/${run}_${set#*-}_t$t.out 2>&1
done; done
