#!/bin/zsh
# HANDBOOK round 1 (docs/analysis/2026-11-08-handbook-haiku-approaches.md): Vanguard, Haiku 5.5, 3 trials, 8 arms in parallel.
cd ~/dev/cuga-eval-policy/benchmarks/policy_eval; set -a; . ~/dev/cuga-eval/.env; set +a
S=polisys-129b89b; T=insurance_vanguard_shield_mutual_9b2f7a29
arm() { for t in 1 2 3; do ~/dev/cuga-agent-gate/.venv/bin/python -I harness/run.py --bench handbook --profile $2 \
  --set handbook-public3 --snapshot $S --trial $t --run $1 --model haiku55 -j 1 --proxy http://127.0.0.1:8801 \
  --tasks $T > /tmp/aud/$1_t$t.out 2>&1; done; }
arm r1_base experiments/handbook-haiku-graph-gate &
for a in actors worksheet scope idem readback gateread all; do arm r1_$a experiments/hb-r1-$a & done
wait
echo ALL_DONE
