#!/usr/bin/env bash
set -euo pipefail

# Install the CUGA integration into an isolated tau2-bench checkout.
# Existing Tau checkouts are not reset or switched to another revision.

cd "$(dirname "${BASH_SOURCE[0]}")"

TAU_DIR="benchmarks/tau3"
TAU_ENV_FILE="${TAU_DIR}/config/tau.env"
TAU_REPO_DIR="${TAU_DIR}/tau2-bench"
TAU_GIT_URL="${TAU_GIT_URL:-https://github.com/sierra-research/tau2-bench.git}"
TAU_REF="${TAU_REF:-cf71a8070269883e38a365ffa85f78f46844c1f4}"
TAU_ENV_SRC="${TAU_ENV_SRC:-${TAU_DIR}/.tau.env}"

if [ ! -d "$TAU_DIR" ]; then
  echo "Error: '$TAU_DIR' directory not found."
  exit 1
fi

if [ -f "$TAU_ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$TAU_ENV_FILE"
  set +a
else
  echo "Warning: '$TAU_ENV_FILE' file not found."
  echo "Continuing with defaults."
fi

if ! command -v git >/dev/null 2>&1; then
  echo "Error: git is required." >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: uv is required." >&2
  exit 1
fi

# Step 1: clone upstream Tau if missing.
if [ ! -d "$TAU_REPO_DIR" ]; then
  echo "Cloning tau2-bench into '$TAU_REPO_DIR'..."
  git clone "$TAU_GIT_URL" "$TAU_REPO_DIR"
  git -C "$TAU_REPO_DIR" checkout --detach "$TAU_REF"
else
  echo "Found existing tau2-bench clone at '$TAU_REPO_DIR'."
  if [[ "$(git -C "$TAU_REPO_DIR" rev-parse HEAD)" != "$TAU_REF" ]]; then
    echo "Warning: existing Tau checkout is not at pinned revision $TAU_REF; leaving it unchanged." >&2
  fi
fi

if [ ! -f "$TAU_REPO_DIR/pyproject.toml" ]; then
  echo "Error: '$TAU_REPO_DIR' does not look like a Python project."
  echo "Missing pyproject.toml."
  exit 1
fi

if [ ! -d "$TAU_REPO_DIR/src/tau2" ]; then
  echo "Error: '$TAU_REPO_DIR/src/tau2' not found." >&2
  exit 1
fi








echo "Installing CUGA tau integration files into tau2-bench..."


TAU_AGENT_DIR="${TAU_REPO_DIR}/src/tau2/agent"

CUGA_BRIDGE_SERVER_SRC="${TAU_DIR}/integration/cuga_bridge_server.py"
CUGA_REMOTE_AGENT_SRC="${TAU_DIR}/integration/cuga_remote_agent.py"
CUGA_BRIDGE_SERVER_DST="${TAU_AGENT_DIR}/cuga_bridge_server.py"
CUGA_REMOTE_AGENT_DST="${TAU_AGENT_DIR}/cuga_remote_agent.py"
TAU_ENV_DST="${TAU_REPO_DIR}/.env"

if [[ ! -f "${CUGA_BRIDGE_SERVER_SRC}" ]]; then
  echo "Missing integration file: ${CUGA_BRIDGE_SERVER_SRC}" >&2
  exit 1
fi

if [[ ! -f "${CUGA_REMOTE_AGENT_SRC}" ]]; then
  echo "Missing integration file: ${CUGA_REMOTE_AGENT_SRC}" >&2
  exit 1
fi

mkdir -p "${TAU_AGENT_DIR}"

cp "${CUGA_BRIDGE_SERVER_SRC}" "${CUGA_BRIDGE_SERVER_DST}"
cp "${CUGA_REMOTE_AGENT_SRC}" "${CUGA_REMOTE_AGENT_DST}"
if [[ -f "$TAU_ENV_SRC" ]]; then
  cp "$TAU_ENV_SRC" "$TAU_ENV_DST"
  chmod 600 "$TAU_ENV_DST"
  echo "Copied optional Tau environment file to ${TAU_ENV_DST}."
else
  echo "No Tau environment file at ${TAU_ENV_SRC}; use exported credentials or supply TAU_ENV_SRC."
fi

echo "Copied:"
echo "  ${CUGA_BRIDGE_SERVER_DST}"
echo "  ${CUGA_REMOTE_AGENT_DST}"








echo "Patching tau2 registry..."

TAU_REGISTRY_FILE="${TAU_REPO_DIR}/src/tau2/registry.py"

"${PYTHON_BIN:-python3}" - <<PY
from pathlib import Path

registry_path = Path("${TAU_REGISTRY_FILE}")
text = registry_path.read_text()

import_line = "from tau2.agent.cuga_remote_agent import create_cuga_remote_agent\\n"
registration = '    registry.register_agent_factory(create_cuga_remote_agent, "cuga_remote")\\n'

# Remove any previous bad unindented registration line.
text = text.replace(
    'registry.register_agent_factory(create_cuga_remote_agent, "cuga_remote")\\n',
    "",
)

# Add import near other tau2.agent imports.
if import_line not in text:
    marker = "from tau2.agent.llm_agent import"
    idx = text.find(marker)
    if idx == -1:
        raise RuntimeError("Could not find tau2.agent.llm_agent import marker")
    text = text[:idx] + import_line + text[idx:]

# Add registration inside the global try block, under # Agent factories.
if 'registry.register_agent_factory(create_cuga_remote_agent, "cuga_remote")' not in text:
    marker = '    registry.register_agent_factory(create_llm_agent, "llm_agent")\\n'
    idx = text.find(marker)
    if idx == -1:
        raise RuntimeError("Could not find llm_agent registration marker")

    insert_at = idx + len(marker)
    text = text[:insert_at] + registration + text[insert_at:]

registry_path.write_text(text)
PY

if [[ "${TAU_SKIP_SYNC:-false}" == "true" ]]; then
  echo "Skipping Tau dependency sync; using the environment already installed."
else
  echo "Installing tau2-bench in its own environment..."
  (
    cd "${TAU_REPO_DIR}"
    uv sync --extra knowledge
  )
fi
