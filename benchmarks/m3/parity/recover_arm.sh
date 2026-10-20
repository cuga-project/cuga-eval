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
MAN="$PARITY_DIR/manifests/$SUBSET.json"
NOGT="$(python3 -c "import json,sys;print(1 if json.load(open(sys.argv[1])).get('no_ground_truth') else 0)" "$MAN")"
if [ "$NOGT" = "1" ]; then
    # Test split (no ground truth): run_parity.sh would end in scoring, so run the arm directly.
    case "$ARM" in cuga_eval_*) ;; *) echo "test-split recovery supports cuga_eval arms only" >&2; exit 2;; esac
    case "$ARM" in *@*) echo "test-split recovery does not take variants" >&2; exit 2;; esac
    BASE="${ARM#cuga_eval_}"; FC=0; case "$BASE" in *_fc) FC=1; BASE="${BASE%_fc}";; esac
    TID="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['task_id'])" "$MAN")"
    (
        # shellcheck source=env.sh
        source "$PARITY_DIR/env.sh" "${PARITY_TEMPERATURE:-1.0}" || exit 1
        PARITY_FC="$FC" bash "$PARITY_DIR/preflight.sh" "$TID" || exit 1
        M3_EVAL_CONFIG_EXTRA="$EXTRA" PARITY_FC="$FC" PARITY_VARIANT= \
            bash "$PARITY_DIR/run_cuga_eval_arm.sh" "$REC_ID" "$SUBSET" "$BASE"
    ) || echo "[$ARM] recovery arm exited non-zero (merging whatever it answered)"
else
    M3_EVAL_CONFIG_EXTRA="$EXTRA" bash "$PARITY_DIR/run_parity.sh" --subset "$SUBSET" --arms "$ARM" \
        --temperature "${PARITY_TEMPERATURE:-1.0}" --run-id "$REC_ID"
fi

python3 - "$RUN/$ARM/meta.json" "$PARITY_DIR/runs/$REC_ID/$ARM/meta.json" <<'PY'
import json, sys
a, b = (json.load(open(p))["cuga_agent"]["commit"] for p in sys.argv[1:3])
if a != b:
    sys.exit(f"recovery ran on CUGA {b}, the arm on {a}: not merging")
PY
(cd "$ROOT" && python3 -m benchmarks.m3.parity.recover merge --run-dir "$RUN" --arm "$ARM" --from "$PARITY_DIR/runs/$REC_ID/$ARM")
[ "$NOGT" = "1" ] && { echo "[$ARM] test split: predictions merged, nothing to score"; exit 0; }
(cd "$ROOT" && python3 -m benchmarks.m3.parity.recover score --run-dir "$RUN" --arm "$ARM" --from "$PARITY_DIR/runs/$REC_ID/$ARM")
