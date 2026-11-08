#!/bin/zsh
# HANDBOOK round 4 on gpt-oss-120b (docs/analysis/2026-11-08-handbook-haiku-approaches.md): 3 tasks, 3 trials, 6 arms.
cd ~/dev/cuga-eval-policy/benchmarks/policy_eval; set -a; . ~/dev/cuga-eval/.env; set +a
S=polisys-cde232a
arm() { for t in 1 2 3; do ~/dev/cuga-agent-gate/.venv/bin/python -I harness/run.py --bench handbook --profile $2 \
  --set handbook-public3 --snapshot $S --trial $t --run $1 --model gptoss -j 2 --proxy http://127.0.0.1:8801 \
  > /tmp/aud/$1_t$t.out 2>&1; done; }
arm r4g_alone baseline &
arm r4g_loop handbook-gptoss-loop-guide-evidence &
arm r4g_base experiments/hb-g-base &
arm r4g_readback experiments/hb-g-readback &
arm r4g_scope experiments/hb-g-scope &
arm r4g_combo experiments/hb-g-combo-cells &
wait
echo ALL_DONE
