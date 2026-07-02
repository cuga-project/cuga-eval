#!/bin/bash
# Smoke-test external agents against configured LLM (no CUGA, no AppWorld servers).
#
# Usage:
#   ./smoke_external.sh
#   ./smoke_external.sh --agents deepagents,hermes
#   ./smoke_external.sh --native-sdk   # try OpenClaw/Hermes native clients
#
# Set in .env (repo root):
#   AGENT_SETTING_CONFIG=settings.openai.toml
#   OPENAI_API_KEY=...
#   OPENAI_BASE_URL=https://ete-litellm.bx.cloud9.ibm.com
#   MODEL_NAME=Azure/gpt-5.2-chat-2025-12-11

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/.env"
    set +a
fi

echo "Smoke test — external agents (no CUGA / no AppWorld)"
echo "  AGENT_SETTING_CONFIG=${AGENT_SETTING_CONFIG:-<unset>}"
echo "  MODEL_NAME=${MODEL_NAME:-<unset>}"
echo "  OPENAI_BASE_URL=${OPENAI_BASE_URL:-${LITE_LLM_URL:-<unset>}}"
echo ""

uv run --no-sync python -m benchmarks.appworld.smoke_external_agents "$@"
