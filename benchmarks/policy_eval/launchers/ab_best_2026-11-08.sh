#!/bin/zsh
# Workstream "AutomationBench best method": 10 arms, 10 tasks, 3 trials, Haiku 5.5, -j 1 per arm (HANDBOOK runs in parallel).
cd ~/dev/cuga-eval-policy/benchmarks/policy_eval; set -a; . ~/dev/cuga-eval/.env; set +a
export AB_AGENT_RULES=1
S=polisys-cde232a
T=(sales.linkedin_profile_enrichment hr.employee_transfer_approval_workflow finance.cash_sweep hr.asana_compliance_tasks
   sales.calendly_discovery_call finance.intercompany_transfer hr.zoom_all_hands_setup sales.form_to_crm_qualification
   marketing.utm_audit_and_fix support.freshdesk_zoho_migration)
arm() { for t in 1 2 3; do ~/dev/cuga-agent-gate/.venv/bin/python -I harness/run.py --bench automationbench --profile $2 \
  --set ab-policy-types-fresh3 --snapshot $S --trial $t --run $1 --model haiku55 -j 1 --proxy http://127.0.0.1:8801 \
  --tasks ${T[@]} > /tmp/aud/$1_t$t.out 2>&1; done; }
arm ab_base baseline &
for a in listing readback listing-readback scope actors b4tf-list b4tf-list-notracker b4tf-list-remind rules-all; do
  arm ab_${a//-/_} experiments/ab-best-$a & done
wait
echo ALL_DONE
