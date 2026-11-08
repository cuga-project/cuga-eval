#!/bin/zsh
# AutomationBench fresh4 frozen run (docs/analysis/2026-11-09-automationbench-fresh4-preregistration.md).
cd ~/dev/cuga-eval-policy/benchmarks/policy_eval; set -a; . ~/dev/cuga-eval/.env; set +a
export AB_AGENT_RULES=1
S=polisys-7dc68b0
arm() { for t in 1 2 3; do ~/dev/cuga-agent-gate/.venv/bin/python -I harness/run.py --bench automationbench --profile $2 \
  --set ab-policy-types-fresh4 --snapshot $S --trial $t --run $1 --model $3 -j 2 --proxy http://127.0.0.1:8801 \
  > /tmp/aud/$1_t$t.out 2>&1; done; }
arm f4_R_haiku55 baseline haiku55 &
arm f4_B_haiku55 experiments/ab-sf-data haiku55 &
arm f4_R_gptoss baseline gptoss &
arm f4_B_gptoss experiments/ab-sf-data gptoss &
arm f4_L_gptoss experiments/automationbench-gptoss-b4tf-list gptoss &
wait
echo ALL_DONE
