#!/bin/zsh
# HANDBOOK integration check (2026-11-08): does the adapter run end to end on the stable code with polisys main?
# 3 public tasks (tuning set), 1 trial, CUGA alone vs the best profile, gpt-oss and Haiku 5.5. Not a gain test.
# Snapshot polisys-f88367e (polisys main after PR #3, gate tag policy/stable-v1 = 9135be1f4). Cache off (proxy 8801).
cd ~/dev/cuga-eval-policy/benchmarks/policy_eval; set -a; . ~/dev/cuga-eval/.env; set +a
S=polisys-f88367e
run() { ~/dev/cuga-agent-gate/.venv/bin/python -I harness/run.py --bench handbook --profile $2 --set handbook-public3 \
  --snapshot $S --trial 1 --run $1 --model $3 -j 2 --proxy http://127.0.0.1:8801 > /tmp/aud/$1_t1.out 2>&1; }
run hbi_A_gptoss baseline gptoss &
run hbi_P_gptoss handbook-gptoss-loop-guide-evidence gptoss &
run hbi_A_haiku55 baseline haiku55 &
run hbi_P_haiku55 experiments/handbook-haiku-graph-gate haiku55 &
wait
echo ALL_DONE
