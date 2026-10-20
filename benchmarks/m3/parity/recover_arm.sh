#!/usr/bin/env bash
# Recovery pass for one arm: re-run the tasks that died on infrastructure (errors, timeouts, empty
# answers) with the arm's exact settings, merge the answered ones into the arm's predictions, and
# report the arm's score with the recovered tasks' verdicts swapped in (recover.py has the details).
#
# usage: PARITY_KEY=<slot> [PARITY_REGISTRY_PORT=<port>] [PARITY_VENV=<venv>] \
#          bash benchmarks/m3/parity/recover_arm.sh <run_id> <arm>
# The re-run lands in runs/<run_id>__recover<N>/ and must use the CUGA the arm ran on (checked).
set -euo pipefail
PARITY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$PARITY_DIR/../../.." && pwd)"
RUN_ID="${1:?run_id}"; ARM="${2:?arm}"
RUN="$PARITY_DIR/runs/$RUN_ID"
[ -f "$RUN/$ARM/meta.json" ] || { echo "no arm $RUN/$ARM (meta.json missing: did the arm finish?)" >&2; exit 2; }

summary="$(cd "$ROOT" && python3 -m benchmarks.m3.parity.recover find --run-dir "$RUN" --arm "$ARM")"
echo "$summary"
field() { python3 -c "import json,sys; print(json.loads(sys.argv[1]).get(sys.argv[2]) or '')" "$summary" "$1"; }
N="$(field n)"; SUBSET="$(field subset)"; EXTRA="$(field eval_config_extra)"
[ "$N" != "0" ] || { echo "[$ARM] nothing to recover"; exit 0; }

i=1; while [ -e "$PARITY_DIR/runs/${RUN_ID}__recover$i" ]; do i=$((i + 1)); done
REC_ID="${RUN_ID}__recover$i"
cleanup() { (cd "$ROOT" && python3 -m benchmarks.m3.parity.recover clean --name "$SUBSET" >/dev/null); }
trap cleanup EXIT

echo "[$ARM] re-running $N task(s) as $REC_ID"
M3_EVAL_CONFIG_EXTRA="$EXTRA" bash "$PARITY_DIR/run_parity.sh" --subset "$SUBSET" --arms "$ARM" \
    --temperature "${PARITY_TEMPERATURE:-1.0}" --run-id "$REC_ID"

python3 - "$RUN/$ARM/meta.json" "$PARITY_DIR/runs/$REC_ID/$ARM/meta.json" <<'PY'
import json, sys
a, b = (json.load(open(p))["cuga_agent"]["commit"] for p in sys.argv[1:3])
if a != b:
    sys.exit(f"recovery ran on CUGA {b}, the arm on {a}: not merging")
PY
(cd "$ROOT" && python3 -m benchmarks.m3.parity.recover merge --run-dir "$RUN" --arm "$ARM" --from "$PARITY_DIR/runs/$REC_ID/$ARM")
(cd "$ROOT" && python3 -m benchmarks.m3.parity.recover score --run-dir "$RUN" --arm "$ARM" --from "$PARITY_DIR/runs/$REC_ID/$ARM")
