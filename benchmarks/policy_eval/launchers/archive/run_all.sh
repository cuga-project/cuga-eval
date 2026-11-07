#!/usr/bin/env bash
# Run CUGA, then the plain-model baseline, on subset.json — one task at a time,
# through retry_proxy.py (must already be running on :8799). Resumable: CUGA skips
# finished tasks; rerun this script after an interruption.
set -euo pipefail
cd "$(dirname "$0")"

RUN=${RUN:-glm53flash_api}
MODEL=${MODEL:-azure/FW-GLM-5.3-Flash}
TASKS=$(python3 -c 'import json; d=json.load(open("subset.json")); print(",".join(n for v in d["tasks"].values() for n in v))')

echo "== CUGA ($RUN) $(date)"
.venv/bin/python run_cuga.py --subset subset.json --run "cuga_$RUN" -j 1 --timeout 14400

echo "== baseline auto-bench ($RUN) $(date)"
mkdir -p "results/baseline_$RUN"
set -a; source ../../.env; set +a
(cd AutomationBench && uv run auto-bench --model "$MODEL" --base-url http://127.0.0.1:8799/v1 \
  --toolset api --tasks "$TASKS" --max-concurrent 1 \
  --export-json "../results/baseline_$RUN/results.json")
echo "== done $(date)"
