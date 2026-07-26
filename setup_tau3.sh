#!/usr/bin/env bash
set -euo pipefail

# One-stop setup for the Tau / tau2-bench benchmark.
#
# What this script does:
# 1. Clones the upstream tau2-bench repo into benchmarks/tau/tau2-bench
#    unless it is already there.
# 2. Registers it as an editable dependency in pyproject.toml under the
#    `tau` group via `uv add --editable ... --group tau`.
#    pyproject.toml should be committed without this local entry so fresh
#    cuga-eval checkouts still work without Tau.
# 3. Syncs the tau dependency group.
# 4. Verifies the tau2 import and tau2 CLI.
#
# Re-running this script is safe: the existing clone is preserved.

TAU_DIR="benchmarks/tau3"
TAU_ENV_FILE="${TAU_DIR}/config/tau.env"
TAU_REPO_DIR="${TAU_DIR}/tau2-bench"
TAU_GIT_URL="${TAU_GIT_URL:-https://github.com/sierra-research/tau2-bench.git}"
TAU_GROUP="${TAU_GROUP:-tau}"

if [ ! -d "$TAU_DIR" ]; then
  echo "Error: '$TAU_DIR' directory not found."
  echo "Create the benchmark directory first:"
  echo "  mkdir -p benchmarks/tau/config"
  echo "Run this script from the cuga-eval repository root."
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
else
  echo "Found existing tau2-bench clone at '$TAU_REPO_DIR'."
fi

if [ ! -f "$TAU_REPO_DIR/pyproject.toml" ]; then
  echo "Error: '$TAU_REPO_DIR' does not look like a Python project."
  echo "Missing pyproject.toml."
  exit 1
fi

if [ ! -d "$TAU_REPO_DIR/src/tau2" ]; then
  echo "Warning: '$TAU_REPO_DIR/src/tau2' not found."
  echo "Continuing, but verify this is the expected tau2-bench checkout."
fi








echo "Installing CUGA tau integration files into tau2-bench..."


TAU_AGENT_DIR="${TAU_REPO_DIR}/src/tau2/agent"

CUGA_BRIDGE_SERVER_SRC="${TAU_DIR}/integration/cuga_bridge_server.py"
CUGA_REMOTE_AGENT_SRC="${TAU_DIR}/integration/cuga_remote_agent.py"
TAU_ENV_SRC="${TAU_DIR}/.tau.env"

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
cp "${TAU_ENV_SRC}" "${TAU_ENV_DST}"

echo "Copied:"
echo "  ${CUGA_BRIDGE_SERVER_DST}"
echo "  ${CUGA_REMOTE_AGENT_DST}"








echo "Patching tau2 registry..."

TAU_REGISTRY_FILE="${TAU_REPO_DIR}/src/tau2/registry.py"

"${PYTHON_BIN:-python3}" - <<PY
from pathlib import Path
import re

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

# Step 3: sync the optional group.
#echo "Syncing uv group: ${TAU_GROUP}..."
#uv sync --group "$TAU_GROUP"

echo "Installing tau2-bench in its own environment..."
(
  cd "${TAU_REPO_DIR}"
  uv sync
  uv sync --extra knowledge
)
