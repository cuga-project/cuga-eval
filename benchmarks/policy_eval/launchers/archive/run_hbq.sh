#!/usr/bin/env bash
# HANDBOOK test 2 (2026-11-04): gpt-oss agent + gpt-oss gate, A / GW / GR, 3 tasks, trials 1-3 (one trial at a time).
cd /Users/samimarreed/dev/cuga-eval/benchmarks
for t in 1 2 3; do
  handbook/run_store_task_oss.sh notemsg2 hr_crestwood_university_79786c46 hbq_cw $t &
  handbook/run_store_task_oss.sh notemsg2 medical_careig_specialty_pharmacy_f5947c33 hbq_ci $t &
  handbook/run_store_task_oss.sh notemsg2 insurance_vanguard_shield_mutual_9b2f7a29 hbq_vg $t &
  wait
done
echo "hbq done $(date)"
