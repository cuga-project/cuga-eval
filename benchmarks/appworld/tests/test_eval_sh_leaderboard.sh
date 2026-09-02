#!/usr/bin/env bash
# benchmarks/appworld/tests/test_eval_sh_leaderboard.sh
# Dry-run tests for eval.sh flag plumbing. Run: bash benchmarks/appworld/tests/test_eval_sh_leaderboard.sh
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVAL="$SCRIPT_DIR/../eval.sh"
PASS=0; FAIL=0
assert_contains() { if [[ "$3" == *"$2"* ]]; then echo "  PASS: $1"; PASS=$((PASS+1)); else echo "  FAIL: $1"; echo "    want: $2"; echo "    got:  $3"; FAIL=$((FAIL+1)); fi; }
assert_not_contains() { if [[ "$3" != *"$2"* ]]; then echo "  PASS: $1"; PASS=$((PASS+1)); else echo "  FAIL: $1"; echo "    unexpected: $2"; echo "    got: $3"; FAIL=$((FAIL+1)); fi; }

echo "eval.sh --dry-run"
out=$(bash "$EVAL" --sdk --dry-run --leaderboard cuga_v1 --eval-key test_challenge_all_b1 2>&1)
assert_contains "dispatches the SDK evaluator" "benchmarks.appworld.eval_appworld_sdk" "$out"
assert_contains "forwards --leaderboard" "--leaderboard cuga_v1" "$out"
assert_contains "forwards --eval-key" "--eval-key test_challenge_all_b1" "$out"
assert_not_contains "does not start servers" "Starting AppWorld" "$out"

out=$(bash "$EVAL" --sdk --dry-run --task a_1 b_2 c_3 2>&1)
assert_contains "forwards several task ids" "--task-id a_1 b_2 c_3" "$out"

out=$(bash "$EVAL" --sdk --dry-run --force-retry --eval-key k 2>&1)
assert_contains "forwards --force-retry" "--force-retry" "$out"

out=$(bash "$EVAL" --dry-run --leaderboard cuga_v1 --eval-key k 2>&1)
assert_contains "leaderboard implies --sdk" "eval_appworld_sdk" "$out"

out=$(bash "$EVAL" --dry-run --experiment cuga_v1_chal --eval-key test_challenge_all_b1 2>&1)
assert_contains "experiment without --sdk still dispatches SDK" "eval_appworld_sdk" "$out"
assert_not_contains "experiment dry-run is not the graph evaluator" "benchmarks.appworld.appworld_eval " "$out"

out=$(bash "$EVAL" --dry-run --experiment cuga_v1_chal --agent codeact --eval-key k 2>&1)
assert_contains "experiment+codeact still dispatches codeact" "appworld_eval_codeact" "$out"

out=$(bash "$EVAL" --dry-run --leaderboard cuga_v1 --agent codeact --eval-key k 2>&1); rc=$?
assert_contains "rejects leaderboard+codeact" "SDK-only" "$out"
[[ $rc -eq 2 ]] && { echo "  PASS: leaderboard+codeact exits 2"; PASS=$((PASS+1)); } || { echo "  FAIL: leaderboard+codeact rc=$rc"; FAIL=$((FAIL+1)); }
out=$(bash "$EVAL" --dry-run --leaderboard cuga_v1 --agent react --eval-key k 2>&1); rc=$?
assert_contains "rejects leaderboard+react" "SDK-only" "$out"
[[ $rc -eq 2 ]] && { echo "  PASS: leaderboard+react exits 2"; PASS=$((PASS+1)); } || { echo "  FAIL: leaderboard+react rc=$rc"; FAIL=$((FAIL+1)); }

# --force-retry is defined only by eval_appworld_sdk.py; the other evaluators use
# parse_args() and would exit 2 *after* booting the AppWorld and registry servers.
out=$(bash "$EVAL" --dry-run --force-retry --eval-key k 2>&1)
assert_contains "force-retry implies --sdk" "eval_appworld_sdk" "$out"
out=$(bash "$EVAL" --dry-run --force-retry --agent codeact --eval-key k 2>&1); rc=$?
assert_contains "rejects force-retry+codeact" "SDK-only" "$out"
[[ $rc -eq 2 ]] && { echo "  PASS: force-retry+codeact exits 2"; PASS=$((PASS+1)); } || { echo "  FAIL: force-retry+codeact rc=$rc"; FAIL=$((FAIL+1)); }
out=$(bash "$EVAL" --dry-run --force-retry --agent react --eval-key k 2>&1); rc=$?
assert_contains "rejects force-retry+react" "SDK-only" "$out"
[[ $rc -eq 2 ]] && { echo "  PASS: force-retry+react exits 2"; PASS=$((PASS+1)); } || { echo "  FAIL: force-retry+react rc=$rc"; FAIL=$((FAIL+1)); }

# --dry-run must print what would actually run. It used to be a second copy of
# the dispatch logic and had drifted: the live paths append --agent, DISPATCH did
# not. Both now go through build_eval_command, so assert the --agent flags show up.
out=$(bash "$EVAL" --dry-run --agent codeact --eval-key k 2>&1)
assert_contains "dry-run shows codeact --agent flag" "appworld_eval_codeact --agent codeact" "$out"
out=$(bash "$EVAL" --dry-run --agent react --eval-key k 2>&1)
assert_contains "dry-run shows react --agent flag" "appworld_eval_react --agent react" "$out"
out=$(bash "$EVAL" --dry-run --eval-key k --no-bundle 2>&1)
assert_contains "dry-run shows default --agent flag" "appworld_eval --agent cuga" "$out"

echo "pack_leaderboard.sh"
PACK="$SCRIPT_DIR/../pack_leaderboard.sh"
out=$(bash "$PACK" 2>&1); rc=$?
assert_contains "usage on missing args" "Usage:" "$out"
[[ $rc -ne 0 ]] && { echo "  PASS: non-zero exit"; PASS=$((PASS+1)); } || { echo "  FAIL: exit 0"; FAIL=$((FAIL+1)); }
out=$(bash "$PACK" nope_prefix "m" "" "l" "" https://x --only test_normal 2>&1); rc=$?
assert_contains "validate runs first and reports" "task dirs present" "$out"
[[ $rc -ne 0 ]] && { echo "  PASS: refuses incomplete"; PASS=$((PASS+1)); } || { echo "  FAIL: packed incomplete"; FAIL=$((FAIL+1)); }

echo; echo "passed=$PASS failed=$FAIL"
[[ $FAIL -eq 0 ]]
