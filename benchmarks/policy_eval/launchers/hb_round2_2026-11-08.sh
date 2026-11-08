#!/bin/zsh
# HANDBOOK round 2 (docs/analysis/2026-11-08-handbook-haiku-approaches.md): 3 tasks, Haiku 5.5, 3 trials, 5 arms.
cd ~/dev/cuga-eval-policy/benchmarks/policy_eval; set -a; . ~/dev/cuga-eval/.env; set +a
S=polisys-c396487
arm() { for t in 1 2 3; do ~/dev/cuga-agent-gate/.venv/bin/python -I harness/run.py --bench handbook --profile $2 \
  --set handbook-public3 --snapshot $S --trial $t --run $1 --model haiku55 -j 2 --proxy http://127.0.0.1:8801 \
  > /tmp/aud/$1_t$t.out 2>&1; done; }
arm r2_base experiments/handbook-haiku-graph-gate &
arm r2_readback experiments/hb-r1-readback &
arm r2_all experiments/hb-r1-all &
arm r2_scope experiments/hb-r1-scope &
arm r2_advisory experiments/hb-r1-advisory &
wait
echo ALL_DONE
