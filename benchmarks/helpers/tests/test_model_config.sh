#!/usr/bin/env bash
# Unit tests for apply_dotenv_model_overrides and apply_model_config.
# Run: bash benchmarks/helpers/tests/test_model_config.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PASS=0; FAIL=0

assert_eq() {
    if [[ "${2}" == "${3}" ]]; then
        echo "  PASS: ${1}"; PASS=$((PASS+1))
    else
        echo "  FAIL: ${1}"; echo "        want: ${2}"; echo "        got:  ${3}"; FAIL=$((FAIL+1))
    fi
}

# ─── apply_dotenv_model_overrides ────────────────────────────────────────────

echo "apply_dotenv_model_overrides"

# NOTE: diagnostic output (echo lines from apply_dotenv_model_overrides /
# apply_model_profile) is redirected to /dev/null so only the final echo
# survives into $result. In the red phase (before implementation) the whole
# script will abort with "command not found" — that is the expected failure.

# overrides existing vars from a supplied env file
result=$(
    source "$SCRIPT_DIR/../common.sh"
    TMP=$(mktemp); trap "rm -f $TMP" EXIT
    printf 'MODEL_NAME=my-model\nOPENAI_BASE_URL=https://custom\n' > "$TMP"
    export MODEL_NAME=original; export OPENAI_BASE_URL=original
    apply_dotenv_model_overrides "$TMP" > /dev/null 2>&1
    echo "$MODEL_NAME|$OPENAI_BASE_URL"
)
assert_eq "overrides MODEL_NAME and OPENAI_BASE_URL" "my-model|https://custom" "$result"

# no-op when file does not exist — prints warning, does not error
result=$(
    source "$SCRIPT_DIR/../common.sh"
    export MODEL_NAME=original
    apply_dotenv_model_overrides "/no/such/file.env" > /dev/null 2>&1
    echo "$MODEL_NAME"
)
assert_eq "no-op when .env missing" "original" "$result"

# strips surrounding quotes and inline comments
result=$(
    source "$SCRIPT_DIR/../common.sh"
    TMP=$(mktemp); trap "rm -f $TMP" EXIT
    printf 'MODEL_NAME="quoted-model"\nOPENAI_BASE_URL=https://x # comment\n' > "$TMP"
    apply_dotenv_model_overrides "$TMP" > /dev/null 2>&1
    echo "$MODEL_NAME|$OPENAI_BASE_URL"
)
assert_eq "strips quotes and inline comments" "quoted-model|https://x" "$result"

# handles export-prefixed lines
result=$(
    source "$SCRIPT_DIR/../common.sh"
    TMP=$(mktemp); trap "rm -f $TMP" EXIT
    printf 'export MODEL_NAME=export-style\n' > "$TMP"
    apply_dotenv_model_overrides "$TMP" > /dev/null 2>&1
    echo "$MODEL_NAME"
)
assert_eq "handles export-prefixed lines" "export-style" "$result"

# ─── apply_model_config ───────────────────────────────────────────────────────

echo "apply_model_config"

# USE_DOTENV=false: behaves exactly like apply_model_profile, no .env re-read
result=$(
    source "$SCRIPT_DIR/../common.sh"
    export USE_DOTENV=false
    apply_model_config "gpt-oss" > /dev/null 2>&1
    echo "$MODEL_NAME"
)
assert_eq "USE_DOTENV=false: MODEL_NAME from profile" "openai/gpt-oss-120b" "$result"

# USE_DOTENV=true with profile: profile runs first, then .env overrides MODEL_NAME
result=$(
    source "$SCRIPT_DIR/../common.sh"
    TMP=$(mktemp); trap "rm -f $TMP" EXIT
    printf 'MODEL_NAME=dotenv-override\n' > "$TMP"
    export USE_DOTENV=true
    apply_model_config "gpt-oss" "$TMP" > /dev/null 2>&1
    echo "$MODEL_NAME"
)
assert_eq "USE_DOTENV=true: .env wins over profile" "dotenv-override" "$result"

# USE_DOTENV=true, .env does NOT set MODEL_NAME: profile value is kept
result=$(
    source "$SCRIPT_DIR/../common.sh"
    TMP=$(mktemp); trap "rm -f $TMP" EXIT
    printf 'SOME_OTHER_VAR=x\n' > "$TMP"
    export USE_DOTENV=true
    apply_model_config "gpt-oss" "$TMP" > /dev/null 2>&1
    echo "$MODEL_NAME"
)
assert_eq "USE_DOTENV=true: profile value kept when .env omits var" "openai/gpt-oss-120b" "$result"

# USE_DOTENV=true, no profile: defaults to gpt-oss base
result=$(
    source "$SCRIPT_DIR/../common.sh"
    TMP=$(mktemp); trap "rm -f $TMP" EXIT
    printf 'SOME_OTHER_VAR=x\n' > "$TMP"
    export USE_DOTENV=true
    apply_model_config "" "$TMP" > /dev/null 2>&1
    echo "$MODEL_NAME"
)
assert_eq "USE_DOTENV=true, no profile: defaults to gpt-oss" "openai/gpt-oss-120b" "$result"

# ─── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
