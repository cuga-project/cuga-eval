#!/usr/bin/env bash
# Parity run environment — SOURCE this, do not execute:
#   source benchmarks/m3/parity/env.sh [temperature]      (default 1.0; use 0.1 only for quick smokes)
#
# Both stacks run agent AND judge on the same model through the same proxy. The
# proxy base/key are read from ~/git/appworld/.env (override with PARITY_APPWORLD_ENV)
# and are never printed. A temperature variant of cuga's settings.openai.toml is
# generated under parity/.local/ (gitignored) and AGENT_SETTING_CONFIG points at it.
_parity_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_root="$(cd "$_parity_dir/../../.." && pwd)"
export PARITY_DIR="$_parity_dir"
export PARITY_ROOT="$_root"
export PARITY_APPWORLD_ENV="${PARITY_APPWORLD_ENV:-$HOME/git/appworld/.env}"
export VAKRA_MAIN="${VAKRA_MAIN:-$HOME/git/appworld/vakra-main}"
export CUGA_AGENT_DIR="${CUGA_AGENT_DIR:-${CUGA_REPO_PATH:-$_root/../cuga-agent}}"
export PARITY_TEMPERATURE="${1:-${PARITY_TEMPERATURE:-1.0}}"
export PARITY_MODEL="${PARITY_MODEL:-azure/gpt-oss-120b}"

_parity_get() { grep -E "^$1=" "$PARITY_APPWORLD_ENV" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'"; }
_b1="$(_parity_get LITELLM_PROXY_API_BASE | sed 's#/*$##')"
_k1="$(_parity_get LITELLM_PROXY_API_KEY)"
if [ -z "$_b1" ] || [ -z "$_k1" ]; then
    echo "parity/env.sh: LITELLM_PROXY_API_BASE / LITELLM_PROXY_API_KEY not found in $PARITY_APPWORLD_ENV" >&2
    return 1 2>/dev/null || exit 1
fi
export PARITY_B1="$_b1"   # base URL without /v1; consumed by the scripts, never echoed

# this stack (cuga-eval): agent via cuga's openai platform, judge via the evaluator fork
export OPENAI_BASE_URL="$_b1" OPENAI_API_KEY="$_k1" API_KEY="$_k1" GROQ_API_KEY="$_k1"
export MODEL_NAME="$PARITY_MODEL"
export JUDGE_MODEL_NAME="$PARITY_MODEL" JUDGE_BASE_URL="$_b1" JUDGE_BACKEND=litellm
# the other stack's judge (vendor evaluator appends /v1 itself)
export JUDGE_MODEL="$PARITY_MODEL" JUDGE_ENDPOINT="$_b1"
export DYNACONF_ADVANCED_FEATURES__LANGFUSE_TRACING=false

_src="$CUGA_AGENT_DIR/src/cuga/configurations/models/settings.openai.toml"
_dst="$_parity_dir/.local/settings.openai.temp${PARITY_TEMPERATURE}.toml"
if ! (cd "$_root" && uv run --frozen python -m benchmarks.m3.parity.models --src "$_src" --dst "$_dst" --temperature "$PARITY_TEMPERATURE"); then
    echo "parity/env.sh: could not derive the temperature-$PARITY_TEMPERATURE models TOML from $_src" >&2
    return 1 2>/dev/null || exit 1
fi
export AGENT_SETTING_CONFIG="$_dst"
echo "parity env ready: model=$PARITY_MODEL temperature=$PARITY_TEMPERATURE AGENT_SETTING_CONFIG=$_dst (proxy credentials loaded from $PARITY_APPWORLD_ENV, not shown)"
unset _b1 _k1 _src _dst _parity_dir _root
