#!/bin/zsh
# HANDBOOK recheck with the loop fix (polisys 44259fa) and the obligation ledger; plan in
# docs/analysis/2026-11-08-handbook-integration.md. 3 trials per arm, run one trial after another inside each arm.
cd ~/dev/cuga-eval-policy/benchmarks/policy_eval; set -a; . ~/dev/cuga-eval/.env; set +a
S=polisys-44259fa
arm() { for t in 1 2 3; do ~/dev/cuga-agent-gate/.venv/bin/python -I harness/run.py --bench handbook --profile $2 \
  --set handbook-public3 --snapshot $S --trial $t --run $1 --model $3 -j 2 --proxy http://127.0.0.1:8801 \
  > /tmp/aud/$1_t$t.out 2>&1; done; }
arm hbr_A_haiku55 baseline haiku55 &
arm hbr_G_haiku55 experiments/handbook-haiku-graph-gate haiku55 &
arm hbr_L_haiku55 experiments/handbook-haiku-loop-guide haiku55 &
arm hbr_LO_haiku55 experiments/handbook-haiku-loop-guide-ledger haiku55 &
arm hbr_A_gptoss baseline gptoss &
arm hbr_L_gptoss handbook-gptoss-loop-guide-evidence gptoss &
wait
echo ALL_DONE
