#!/bin/zsh
# Listing experiment (pre-registered: docs/analysis/2026-11-08-listing-preregistration.md). fresh3, Haiku 5.5, 3 trials (gpt-oss passed rules 1-3),
# cache off. Frozen: cuga-eval-policy 6f71847a, snapshot polisys-969bf8f. All arms AB_AGENT_RULES=1.
S=polisys-969bf8f
for tr in 1 2 3; do
  AB_AGENT_RULES=1 zsh /tmp/aud/oney2.sh lx_R_haiku55 baseline $S haiku55 $tr - - ab-policy-types-fresh3 &
  AB_AGENT_RULES=1 zsh /tmp/aud/oney2.sh lx_P_haiku55 automationbench-gptoss-b4tf $S haiku55 $tr - - ab-policy-types-fresh3 &
  AB_AGENT_RULES=1 zsh /tmp/aud/oney2.sh lx_L_haiku55 experiments/automationbench-gptoss-b4tf-list $S haiku55 $tr - - ab-policy-types-fresh3 &
done
wait
echo ALL_DONE
