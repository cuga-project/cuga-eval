#!/usr/bin/env bash
set -euo pipefail

# One-stop setup for the tau2-bench (τ²) benchmark.
#
# What this script does:
#   1. Clones the standalone tau2-bench repo into benchmarks/tau2/tau2-bench
#      and checks out a PINNED commit (skipped if it's already there).
#   2. Registers it as an editable dependency in pyproject.toml under the
#      `tau2` group (via `uv add --editable --no-workspace ... --group tau2`).
#      pyproject.toml is committed without this entry so that `uv sync` works
#      on fresh checkouts; this script adds it locally.
#   3. Runs `tau2 check-data` to confirm the data dir resolves. τ² ships its
#      data inside the repo (no separate multi-GB download, unlike AppWorld/M3).
#
# After running this script:
#   - `uv sync --group tau2`  -> installs base deps + tau2
#   - `uv sync`               -> still works; reconciles to base deps (re-run
#                                with --group tau2 to put tau2 back).
#
# Re-running this script is safe: an existing clone is preserved.

TAU2_DIR="benchmarks/tau2"
TAU2_ENV_FILE="${TAU2_DIR}/config/tau2.env"
TAU2_REPO_DIR="${TAU2_DIR}/tau2-bench"
TAU2_GIT_URL="https://github.com/sierra-research/tau2-bench"

# Pinned to the exact revision every codebase fact in TAU2_CUGA_EVAL_PLAN.md was
# verified against (2026-06-10, "feat: make review model configurable (#346)").
# Bump deliberately, never implicitly — τ² has shown meaningful API drift.
TAU2_PIN="5ebebbe827b455b3ed04fcb9294235c6ef4e5fd6"

if [ ! -d "$TAU2_DIR" ]; then
  echo "Error: '$TAU2_DIR' directory not found."
  echo "Run this script from the repository root."
  exit 1
fi

if [ ! -f "$TAU2_ENV_FILE" ]; then
  echo "Error: '$TAU2_ENV_FILE' file not found."
  exit 1
fi

set -a
. "$TAU2_ENV_FILE"
set +a

# Step 1: clone the standalone repo if missing, pinned to TAU2_PIN.
if [ ! -d "$TAU2_REPO_DIR" ]; then
  echo "Cloning tau2-bench into '$TAU2_REPO_DIR' (pin ${TAU2_PIN:0:7})..."
  if ! command -v git >/dev/null 2>&1; then
    echo "Error: git is required." >&2
    exit 1
  fi
  git clone "$TAU2_GIT_URL" "$TAU2_REPO_DIR"
  git -C "$TAU2_REPO_DIR" checkout --quiet "$TAU2_PIN"
else
  echo "Found existing tau2-bench clone at '$TAU2_REPO_DIR'."
  current="$(git -C "$TAU2_REPO_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
  if [ "$current" != "$TAU2_PIN" ]; then
    echo "Warning: clone is at ${current:0:7}, not the pinned ${TAU2_PIN:0:7}."
    echo "         Remove '$TAU2_REPO_DIR' and re-run to re-pin, or checkout manually."
  fi
fi

# Step 2: register tau2 as an editable dep in the `tau2` group.
# --no-workspace: add tau2 as a plain editable source under [tool.uv.sources],
#   NOT a uv workspace member, so uv does not resolve tau2's optional extras
#   (voice/knowledge/gym/dev/experiments) into this repo's environment.
echo "Registering tau2-bench as an editable dependency (group: tau2)..."
uv add --editable --no-workspace "$TAU2_REPO_DIR" --group tau2

# Step 3: verify the data dir resolves.
echo "Checking tau2 data..."
if uv run --group tau2 tau2 check-data; then
  echo ""
  echo "tau2 setup complete."
else
  echo ""
  echo "tau2 'check-data' failed. τ² defaults to its in-repo data/ dir; if your"
  echo "clone is incomplete, set TAU2_DATA_DIR in ${TAU2_ENV_FILE} or re-clone."
  exit 1
fi

echo ""
echo "Usage:"
echo "  uv sync --group tau2   # install/refresh with tau2"
echo "  uv sync                # base deps only (tau2 removed from venv;"
echo "                         #   re-add with --group tau2)"
