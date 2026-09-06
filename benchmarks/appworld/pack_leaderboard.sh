#!/bin/bash
# Validate, officially evaluate, pack and verify both AppWorld leaderboard splits.
# `evaluate` writes AppWorld evaluations/<split>.json (required to pack). It does
# not update a cuga-eval workspace report.md — that is skill step 5 (`evaluate
# … --bundle-dir …`).
# Usage: ./pack_leaderboard.sh <prefix> "<method>" "<method tooltip>" "<llm>" "<llm tooltip>" <url> [--allow-low-interactions] [--only SPLIT] [--re-evaluate]
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

if [[ $# -lt 6 ]]; then
    echo "Usage: $0 <prefix> \"<method>\" \"<method tooltip>\" \"<llm>\" \"<llm tooltip>\" <url> [--allow-low-interactions] [--only test_normal|test_challenge] [--re-evaluate]" >&2
    exit 2
fi
PREFIX="$1"; METHOD="$2"; METHOD_TIP="$3"; LLM="$4"; LLM_TIP="$5"; URL="$6"; shift 6
EXTRA=(); SPLITS=(test_normal test_challenge)
while [[ $# -gt 0 ]]; do
    case "$1" in
        --allow-low-interactions) EXTRA+=(--allow-low-interactions); shift ;;
        --only) SPLITS=("$2"); shift 2 ;;
        --re-evaluate) RE_EVALUATE=true; shift ;;
        *) echo "unknown flag $1" >&2; exit 2 ;;
    esac
done

LB=(uv run --no-sync python -m benchmarks.appworld.leaderboard)
ROOT_DIR="${APPWORLD_ROOT:-$SCRIPT_DIR/appworld}"
BUNDLES=()
for split in "${SPLITS[@]}"; do
    # Validate first: it only stats files, and it fails cleanly on a missing or
    # incomplete experiment instead of letting `evaluate` die deep inside
    # AppWorld. (`pack` validates again internally — that one is the guarantee.)
    echo "== $split: validate"
    "${LB[@]}" validate "$PREFIX" --split "$split" "${EXTRA[@]+"${EXTRA[@]}"}" || exit 1
    # `evaluate` loads the start/end DBs of every task — tens of minutes on
    # test_challenge — so skip it when evaluations/<split>.json is already newer
    # than the newest task output. Force a re-run with --re-evaluate.
    EVAL_JSON="$ROOT_DIR/experiments/outputs/${PREFIX}_${split}/evaluations/${split}.json"
    NEWER=$(find "$ROOT_DIR/experiments/outputs/${PREFIX}_${split}/tasks" -newer "$EVAL_JSON" -print -quit 2>/dev/null || true)
    if [[ "${RE_EVALUATE:-false}" != "true" && -f "$EVAL_JSON" && -z "$NEWER" ]]; then
        echo "== $split: official evaluate — up to date, skipping (--re-evaluate to force)"
    else
        echo "== $split: official evaluate"
        "${LB[@]}" evaluate "${PREFIX}_${split}" --split "$split" || exit 1
    fi
    echo "== $split: pack + verify"
    out=$("${LB[@]}" pack "$PREFIX" --split "$split" --method "$METHOD" --method-tooltip "$METHOD_TIP" \
          --llm "$LLM" --llm-tooltip "$LLM_TIP" --url "$URL" "${EXTRA[@]+"${EXTRA[@]}"}") || { echo "$out"; exit 1; }
    echo "$out"
    BUNDLES+=("$(echo "$out" | sed -n 's/^Bundle verified: //p')")
done

APPWORLD_REF=$(git -C benchmarks/appworld/appworld rev-parse --short HEAD 2>/dev/null || echo "<appworld version>")
PY=$(uv run --no-sync python -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo
echo "Bundles:"; printf '  %s\n' "${BUNDLES[@]}"
echo
echo "Next: copy each bundle to appworld-leaderboard/experiments/outputs/<experiment>/leaderboard.bundle,"
echo "open a PR on https://github.com/StonyBrookNLP/appworld-leaderboard and comment:"
echo "  /add-to-leaderboard --python $PY --appworld git+https://github.com/stonybrooknlp/appworld.git@$APPWORLD_REF $PREFIX"
