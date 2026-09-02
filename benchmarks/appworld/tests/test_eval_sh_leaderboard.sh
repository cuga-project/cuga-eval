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

echo; echo "passed=$PASS failed=$FAIL"
[[ $FAIL -eq 0 ]]
