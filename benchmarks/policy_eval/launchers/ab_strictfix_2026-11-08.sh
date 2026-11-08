#!/bin/zsh
# AutomationBench strict fixes round (docs/analysis/2026-11-08-automationbench-best-method.md): 5 arms, 10 tasks, 3 trials, Haiku.
cd ~/dev/cuga-eval-policy/benchmarks/policy_eval; set -a; . ~/dev/cuga-eval/.env; set +a
export AB_AGENT_RULES=1
S=polisys-7dc68b0
T=(sales.linkedin_profile_enrichment hr.employee_transfer_approval_workflow finance.cash_sweep hr.asana_compliance_tasks
   sales.calendly_discovery_call finance.intercompany_transfer hr.zoom_all_hands_setup sales.form_to_crm_qualification
   marketing.utm_audit_and_fix support.freshdesk_zoho_migration)
arm() { for t in 1 2 3; do ~/dev/cuga-agent-gate/.venv/bin/python -I harness/run.py --bench automationbench --profile $2 \
  --set ab-policy-types-fresh3 --snapshot $S --trial $t --run $1 --model haiku55 -j 2 --proxy http://127.0.0.1:8801 \
  --tasks ${T[@]} > /tmp/aud/$1_t$t.out 2>&1; done; }
arm sf_base baseline &
arm sf_lr experiments/ab-best-listing-readback &
arm sf_readfirst experiments/ab-sf-readfirst &
arm sf_data experiments/ab-sf-data &
arm sf_both experiments/ab-sf-both &
wait
echo ALL_DONE
