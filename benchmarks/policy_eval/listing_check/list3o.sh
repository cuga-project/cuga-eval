#!/bin/zsh
# Listing experiment (pre-registered: docs/analysis/2026-11-08-listing-preregistration.md). fresh3, gpt-oss, 3 trials,
# cache off. Frozen: cuga-eval-policy 6f71847a, snapshot polisys-969bf8f. All arms AB_AGENT_RULES=1.
S=polisys-969bf8f
for tr in 1 2 3; do
  AB_AGENT_RULES=1 zsh /tmp/aud/oney2.sh lx_R_gptoss baseline $S gptoss $tr - - ab-policy-types-fresh3 &
  AB_AGENT_RULES=1 zsh /tmp/aud/oney2.sh lx_P_gptoss automationbench-gptoss-b4tf $S gptoss $tr - - ab-policy-types-fresh3 &
  AB_AGENT_RULES=1 zsh /tmp/aud/oney2.sh lx_L_gptoss experiments/automationbench-gptoss-b4tf-list $S gptoss $tr - - ab-policy-types-fresh3 &
done
wait
echo ALL_DONE
