#!/usr/bin/env bash
# Unit tests for apply_dotenv_model_overrides and apply_model_config.
# Run: bash benchmarks/helpers/tests/test_model_config.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PASS=0; FAIL=0

# assert_eq <name> <expected> <actual>
assert_eq() {
    if [[ "${2}" == "${3}" ]]; then
        echo "  PASS: ${1}"; PASS=$((PASS+1))
    else
        echo "  FAIL: ${1}"; echo "        want: ${2}"; echo "        got:  ${3}"; FAIL=$((FAIL+1))
    fi
}

# assert_contains <name> <needle> <haystack>
assert_contains() {
    if [[ "${3}" == *"${2}"* ]]; then
        echo "  PASS: ${1}"; PASS=$((PASS+1))
    else
        echo "  FAIL: ${1}"; echo "        expected to contain: ${2}"; echo "        got:                 ${3}"; FAIL=$((FAIL+1))
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
    TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
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
    TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
    printf 'MODEL_NAME="quoted-model"\nOPENAI_BASE_URL=https://x # comment\n' > "$TMP"
    apply_dotenv_model_overrides "$TMP" > /dev/null 2>&1
    echo "$MODEL_NAME|$OPENAI_BASE_URL"
)
assert_eq "strips quotes and inline comments" "quoted-model|https://x" "$result"

# handles export-prefixed lines
result=$(
    source "$SCRIPT_DIR/../common.sh"
    TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
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
    TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
    printf 'MODEL_NAME=dotenv-override\n' > "$TMP"
    export USE_DOTENV=true
    apply_model_config "gpt-oss" "$TMP" > /dev/null 2>&1
    echo "$MODEL_NAME"
)
assert_eq "USE_DOTENV=true: .env wins over profile" "dotenv-override" "$result"

# USE_DOTENV=true, .env does NOT set MODEL_NAME: profile value is kept
result=$(
    source "$SCRIPT_DIR/../common.sh"
    TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
    printf 'SOME_OTHER_VAR=x\n' > "$TMP"
    export USE_DOTENV=true
    apply_model_config "gpt-oss" "$TMP" > /dev/null 2>&1
    echo "$MODEL_NAME"
)
assert_eq "USE_DOTENV=true: profile value kept when .env omits var" "openai/gpt-oss-120b" "$result"

# USE_DOTENV=true, no profile: defaults to gpt-oss base
result=$(
    source "$SCRIPT_DIR/../common.sh"
    TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
    printf 'SOME_OTHER_VAR=x\n' > "$TMP"
    export USE_DOTENV=true
    apply_model_config "" "$TMP" > /dev/null 2>&1
    echo "$MODEL_NAME"
)
assert_eq "USE_DOTENV=true, no profile: defaults to gpt-oss" "openai/gpt-oss-120b" "$result"

# ─── _parse_env_file (shared parser) ─────────────────────────────────────────

echo "_parse_env_file"

# override=false keeps an already-set variable (profile exports win)
result=$(
    source "$SCRIPT_DIR/../common.sh"
    TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
    printf 'MODEL_NAME=from-file\n' > "$TMP"
    export MODEL_NAME=preexisting
    _parse_env_file "$TMP" false > /dev/null 2>&1
    echo "$MODEL_NAME"
)
assert_eq "_parse_env_file override=false keeps existing value" "preexisting" "$result"

# override=false sets a variable that is not already present
result=$(
    source "$SCRIPT_DIR/../common.sh"
    TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
    printf 'A_FRESH_VAR=fresh\n' > "$TMP"
    unset A_FRESH_VAR 2>/dev/null || true
    _parse_env_file "$TMP" false > /dev/null 2>&1
    echo "${A_FRESH_VAR:-unset}"
)
assert_eq "_parse_env_file override=false sets unset value" "fresh" "$result"

# override=true overwrites an already-set variable
result=$(
    source "$SCRIPT_DIR/../common.sh"
    TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
    printf 'MODEL_NAME=forced\n' > "$TMP"
    export MODEL_NAME=preexisting
    _parse_env_file "$TMP" true > /dev/null 2>&1
    echo "$MODEL_NAME"
)
assert_eq "_parse_env_file override=true overwrites" "forced" "$result"

# ─── require_single_model_for_dotenv ─────────────────────────────────────────

echo "require_single_model_for_dotenv"

# multiple models + --dotenv → rejected (nonzero)
result=$(
    source "$SCRIPT_DIR/../common.sh"
    export USE_DOTENV=true
    if require_single_model_for_dotenv gpt-oss gpt4o > /dev/null 2>&1; then echo ok; else echo rejected; fi
)
assert_eq "rejects --dotenv with multiple models" "rejected" "$result"

# single model + --dotenv → allowed
result=$(
    source "$SCRIPT_DIR/../common.sh"
    export USE_DOTENV=true
    if require_single_model_for_dotenv gpt-oss > /dev/null 2>&1; then echo ok; else echo rejected; fi
)
assert_eq "allows --dotenv with single model" "ok" "$result"

# multiple models without --dotenv → allowed
result=$(
    source "$SCRIPT_DIR/../common.sh"
    export USE_DOTENV=false
    if require_single_model_for_dotenv gpt-oss gpt4o > /dev/null 2>&1; then echo ok; else echo rejected; fi
)
assert_eq "allows multiple models without --dotenv" "ok" "$result"

# ─── build_model_envs_json honours --dotenv ──────────────────────────────────

echo "build_model_envs_json"

# With USE_DOTENV=true the per-model snapshot must reflect the .env override so
# the bundle records the model that actually ran (not the bare profile value).
result=$(
    source "$SCRIPT_DIR/../common.sh"
    TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
    printf 'MODEL_NAME=bundle-dotenv\n' > "$TMP"
    export USE_DOTENV=true
    export DOTENV_FILE="$TMP"
    build_model_envs_json "gpt-oss" 2>/dev/null
)
assert_contains "bundle snapshot reflects .env override" '"MODEL_NAME":"bundle-dotenv"' "$result"

# Without --dotenv the snapshot uses the profile value (unchanged behaviour).
result=$(
    source "$SCRIPT_DIR/../common.sh"
    export USE_DOTENV=false
    build_model_envs_json "gpt-oss" 2>/dev/null
)
assert_contains "bundle snapshot uses profile value without --dotenv" '"MODEL_NAME":"openai/gpt-oss-120b"' "$result"

# DYNACONF_* set via .env must not leak out of build_model_envs_json.
result=$(
    source "$SCRIPT_DIR/../common.sh"
    TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
    printf 'DYNACONF_TEST_LEAK=leaked\n' > "$TMP"
    export USE_DOTENV=true
    export DOTENV_FILE="$TMP"
    unset DYNACONF_TEST_LEAK 2>/dev/null || true
    build_model_envs_json "gpt-oss" > /dev/null 2>&1
    echo "${DYNACONF_TEST_LEAK:-unset}"
)
assert_eq "build_model_envs_json does not leak .env DYNACONF_*" "unset" "$result"

# A pre-existing DYNACONF_* is preserved across build_model_envs_json.
result=$(
    source "$SCRIPT_DIR/../common.sh"
    export USE_DOTENV=false
    export DYNACONF_PRESET=keepme
    build_model_envs_json "gpt-oss" > /dev/null 2>&1
    echo "${DYNACONF_PRESET:-unset}"
)
assert_eq "build_model_envs_json preserves pre-existing DYNACONF_*" "keepme" "$result"

# ─── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
