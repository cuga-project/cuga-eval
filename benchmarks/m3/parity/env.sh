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
# Run in the kit's own venv (setup_pinned_cuga.sh), never the shared .venv: other sessions
# re-sync that one, and the lockfile's ../cuga-agent is a checkout they switch branches in.
# UV_NO_SYNC keeps `uv run` from re-syncing the kit venv back to that checkout.
export UV_FROZEN=1 UV_NO_SYNC=1
export PARITY_VENV="${PARITY_VENV:-$_parity_dir/.local/venv}"
# The kit's own registry port: eval.sh KILLS whatever listens on its registry port, and other
# sessions/projects run registries in the 80xx range (8001 default, 8011...). Default to a high
# port and move to the next free one; PARITY_REGISTRY_PORT pins it.
_port="${PARITY_REGISTRY_PORT:-18001}"
if [ -z "${PARITY_REGISTRY_PORT:-}" ]; then
    while lsof -nP -iTCP:"$_port" -sTCP:LISTEN >/dev/null 2>&1; do _port=$((_port + 1)); done
fi
export REGISTRY_PORT="$_port"
if [ -x "$PARITY_VENV/bin/python" ]; then
    export UV_PROJECT_ENVIRONMENT="$PARITY_VENV"
    unset VIRTUAL_ENV
else
    echo "parity/env.sh: no kit venv at $PARITY_VENV — run: bash benchmarks/m3/parity/setup_pinned_cuga.sh <commit>" >&2
fi
# The checkout this environment really imports (cuga_identity.py), not a guessed path.
_cuga_repo="$(cd "$_root" && uv run --frozen python -m benchmarks.m3.parity.cuga_identity --line 2>/dev/null | cut -d' ' -f1)"
[ "$_cuga_repo" = "-" ] && _cuga_repo=""
export CUGA_AGENT_DIR="${_cuga_repo:-${CUGA_AGENT_DIR:-${CUGA_REPO_PATH:-$_root/../cuga-agent}}}"
export PARITY_TEMPERATURE="${1:-${PARITY_TEMPERATURE:-1.0}}"
[ -n "${PARITY_MODEL:-}" ] && export PARITY_MODEL_SET=1
export PARITY_MODEL="${PARITY_MODEL:-azure/gpt-oss-120b}"

# Key slot: PARITY_KEY=1 reads LITELLM_PROXY_API_BASE/KEY, PARITY_KEY=2 reads the _2 variants, etc.
# (the same convention as vakra-main/cuga_runs/*.sh). Switch slots when a key's budget is exhausted.
export PARITY_KEY="${PARITY_KEY:-1}"
_sfx=""; [ "$PARITY_KEY" != "1" ] && _sfx="_$PARITY_KEY"
_parity_get() { grep -E "^$1=" "$PARITY_APPWORLD_ENV" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'"; }
_b1="$(_parity_get "LITELLM_PROXY_API_BASE$_sfx" | sed 's#/*$##')"
_k1="$(_parity_get "LITELLM_PROXY_API_KEY$_sfx")"
_m1="$(_parity_get "LITELLM_PROXY_MODEL$_sfx")"
if [ -z "$_b1" ] || [ -z "$_k1" ]; then
    echo "parity/env.sh: LITELLM_PROXY_API_BASE$_sfx / LITELLM_PROXY_API_KEY$_sfx not found in $PARITY_APPWORLD_ENV" >&2
    return 1 2>/dev/null || exit 1
fi
[ -n "$_m1" ] && [ -z "${PARITY_MODEL_SET:-}" ] && export PARITY_MODEL="$_m1"   # a slot may pin its own model name
export PARITY_B1="$_b1"   # base URL without /v1; consumed by the scripts, never echoed

# this stack (cuga-eval): agent via cuga's openai platform, judge via the evaluator fork
export OPENAI_BASE_URL="$_b1" OPENAI_API_KEY="$_k1" API_KEY="$_k1" GROQ_API_KEY="$_k1"
export MODEL_NAME="$PARITY_MODEL"
export JUDGE_MODEL_NAME="$PARITY_MODEL" JUDGE_BASE_URL="$_b1" JUDGE_BACKEND=litellm
# the other stack's judge (vendor evaluator appends /v1 itself)
export JUDGE_MODEL="$PARITY_MODEL" JUDGE_ENDPOINT="$_b1"
export DYNACONF_ADVANCED_FEATURES__LANGFUSE_TRACING=false
# eval.sh's helpers (benchmarks/helpers/common.sh) call bare `uv run`, which re-resolves uv.lock against
# whatever ../cuga-agent has checked out; keep the lockfile untouched during kit runs.
export UV_FROZEN=1

_src="$CUGA_AGENT_DIR/src/cuga/configurations/models/settings.openai.toml"
_dst="$_parity_dir/.local/settings.openai.temp${PARITY_TEMPERATURE}.toml"
if ! (cd "$_root" && uv run --frozen python -m benchmarks.m3.parity.models --src "$_src" --dst "$_dst" --temperature "$PARITY_TEMPERATURE"); then
    echo "parity/env.sh: could not derive the temperature-$PARITY_TEMPERATURE models TOML from $_src" >&2
    return 1 2>/dev/null || exit 1
fi
export AGENT_SETTING_CONFIG="$_dst"
echo "parity env ready: key_slot=$PARITY_KEY model=$PARITY_MODEL temperature=$PARITY_TEMPERATURE AGENT_SETTING_CONFIG=$_dst (proxy credentials loaded from $PARITY_APPWORLD_ENV, not shown)"
unset _b1 _k1 _m1 _sfx _src _dst _parity_dir _root
