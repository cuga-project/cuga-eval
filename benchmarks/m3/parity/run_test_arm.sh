#!/usr/bin/env bash
# One capability on the VAKRA test split (inputs only; the organizers score it): the arm with the shipped
# preset, then up to TEST_RECOVER_PASSES recovery passes (recover_arm.sh re-runs tasks that died on
# infrastructure and merges what they answer). Predictions land in runs/<run_id>/<arm>/prediction_vakra_ids;
# package them with package_submission.py (README.md, "Test split").
#
# usage: PARITY_KEY=<slot> PARITY_VENV=<abs venv> [PARITY_REGISTRY_PORT=<port>] [PARITY_CONTAINER=<cap1 container>] \
#          bash benchmarks/m3/parity/run_test_arm.sh [--check] <cap 1-4> [run_id]
#   --check            everything but the agent: manifest, eval keys, converted data, env, preflight (no LLM call)
#   TEST_SUBSET        manifest to run (default test_cap<N>; test_cap<N>_smoke = one task)
#   TEST_RECOVER_PASSES  recovery passes after the arm (default 2; 0 = none)
#   PARITY_SWITCH_TIMEOUT  cap1 universe-switch timeout in seconds (default 150; heavy test domains need 600)
# Prerequisites (once): make_test_manifests.py, then prepare_vakra_train.py into .local/vakra_test.
set -euo pipefail
PARITY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$PARITY_DIR/../../.." && pwd)"
CHECK=0; [ "${1:-}" = "--check" ] && { CHECK=1; shift; }
CAP="${1:?usage: run_test_arm.sh [--check] <cap 1-4> [run_id]}"
case "$CAP" in
    1|2|3) BASE="cap$CAP"; FC=1; ARM="cuga_eval_cap${CAP}_fc" ;;
    4) BASE="cap4"; FC=0; ARM="cuga_eval_cap4" ;;
    *) echo "capability must be 1-4" >&2; exit 2 ;;
esac
SUBSET="${TEST_SUBSET:-test_cap$CAP}"
RUN_ID="${2:-${SUBSET}_$(date +%Y%m%d_%H%M)_k${PARITY_KEY:-1}}"
MAN="$PARITY_DIR/manifests/$SUBSET.json"
export M3_EVAL_CONFIG_EXTRA="${M3_EVAL_CONFIG_EXTRA:-$PARITY_DIR/.local/test_eval_keys.toml}"

die() { echo "error: $*" >&2; exit 2; }
[ -f "$MAN" ] || die "no $MAN — run: uv run --frozen python -m benchmarks.m3.parity.make_test_manifests --caps $CAP"
[ -f "$M3_EVAL_CONFIG_EXTRA" ] || die "no eval keys at $M3_EVAL_CONFIG_EXTRA (make_test_manifests writes them)"
python3 - "$MAN" "$M3_EVAL_CONFIG_EXTRA" "$PARITY_DIR/.local" <<'PY' || exit 2
import json, sys, tomllib
from pathlib import Path
m = json.load(open(sys.argv[1]))
keys = tomllib.loads(Path(sys.argv[2]).read_text())
ids = [u for us in m["ids_by_domain"].values() for u in us]
missing = [u for u in ids if u not in set(keys.get(m["subset"], []))]
if missing:
    sys.exit(f"error: eval key {m['subset']!r} lacks {len(missing)} of the manifest's ids (re-run make_test_manifests)")
data = Path(sys.argv[3]) / m["m3_data"].split(":", 1)[1] / m["capability_dir"]
if not data.is_dir():
    sys.exit(f"error: no converted test data at {data} — run prepare_vakra_train --manifest {sys.argv[1]} "
             f"--out {data.parent}")
demo = Path(sys.argv[3]) / m["demo_data"].split(":", 1)[1]
if not demo.is_dir():
    sys.exit(f"error: no demo (train) source at {demo}")
print(f"ok    {m['subset']}: {len(ids)} tasks over {len(m['ids_by_domain'])} domains; data {data}")
PY

mkdir -p "$PARITY_DIR/runs"
LOG="$PARITY_DIR/runs/$RUN_ID.log"
[ "$CHECK" = 1 ] && LOG=/dev/null
{
    echo "== test run $RUN_ID: subset=$SUBSET arm base=$BASE fc=$FC key=${PARITY_KEY:-1} $(date '+%Y-%m-%d %H:%M:%S')"
    echo "   cuga-eval $(git -C "$ROOT" rev-parse --short HEAD) dirty_files=$(git -C "$ROOT" status --porcelain -- benchmarks/m3 | grep -vc '^??' || true)"
    rc=0
    (
        # shellcheck source=env.sh
        source "$PARITY_DIR/env.sh" "${PARITY_TEMPERATURE:-1.0}" || exit 1
        PARITY_FC="$FC" bash "$PARITY_DIR/preflight.sh" "$CAP" || exit 1
        [ "$CHECK" = 1 ] && { echo "check passed: $SUBSET is ready to run as $RUN_ID (nothing was run)"; exit 0; }
        PARITY_FC="$FC" PARITY_VARIANT= bash "$PARITY_DIR/run_cuga_eval_arm.sh" "$RUN_ID" "$SUBSET" "$BASE"
    ) || rc=$?
    [ "$CHECK" = 1 ] && exit "$rc"
    echo "done rc=$rc $(date '+%Y-%m-%d %H:%M:%S')"
    for _ in $(seq 1 "${TEST_RECOVER_PASSES:-2}"); do
        bash "$PARITY_DIR/recover_arm.sh" "$RUN_ID" "$ARM" || echo "recovery pass failed (continuing)"
    done
    echo "predictions: $PARITY_DIR/runs/$RUN_ID/$ARM/prediction_vakra_ids"
} 2>&1 | tee -a "$LOG"
exit "${PIPESTATUS[0]}"
