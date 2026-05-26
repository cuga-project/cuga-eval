#!/usr/bin/env bash
set -euo pipefail

# One-stop setup for the AppWorld benchmark.
#
# What this script does:
#   1. Clones the upstream AppWorld repo into benchmarks/appworld/appworld
#      (skipped if it's already there).
#   2. Registers it as an editable dependency in pyproject.toml under the
#      `appworld` group (via `uv add --editable ... --group appworld`).
#      pyproject.toml is committed without this entry so that `uv sync`
#      works on fresh checkouts; this script adds it locally.
#   3. Runs `appworld install --repo` and `appworld download data` to set up
#      the repo layout and download the benchmark dataset.
#
# After running this script:
#   - `uv sync --group appworld`  -> installs base deps + appworld
#   - `uv sync`                    -> still works; reconciles to base deps
#                                     (re-run with --group appworld to put
#                                     appworld back).
#
# Re-running this script is safe: existing clone/data are preserved unless
# you opt in to a reinstall when prompted.

APPWORLD_DIR="benchmarks/appworld"
APPWORLD_ENV_FILE="${APPWORLD_DIR}/config/appworld.env"
APPWORLD_REPO_DIR="${APPWORLD_DIR}/appworld"
APPWORLD_DATA_DIR="${APPWORLD_REPO_DIR}/data"
APPWORLD_GIT_URL="https://github.com/StonyBrookNLP/appworld"

if [ ! -d "$APPWORLD_DIR" ]; then
  echo "Error: '$APPWORLD_DIR' directory not found."
  echo "Run this script from the repository root."
  exit 1
fi

if [ ! -f "$APPWORLD_ENV_FILE" ]; then
  echo "Error: '$APPWORLD_ENV_FILE' file not found."
  exit 1
fi

set -a
. "$APPWORLD_ENV_FILE"
set +a

# Step 1: clone the upstream repo if missing.
if [ ! -d "$APPWORLD_REPO_DIR" ]; then
  echo "Cloning AppWorld into '$APPWORLD_REPO_DIR'..."
  if ! command -v git >/dev/null 2>&1; then
    echo "Error: git is required." >&2
    exit 1
  fi
  if ! command -v git-lfs >/dev/null 2>&1; then
    echo "Warning: git-lfs not found. AppWorld's data files use LFS; install"
    echo "         it (e.g. 'brew install git-lfs && git lfs install') if the"
    echo "         clone or data download fails."
  fi
  git clone "$APPWORLD_GIT_URL" "$APPWORLD_REPO_DIR"
else
  echo "Found existing AppWorld clone at '$APPWORLD_REPO_DIR'."
fi

# Decide whether to redo the data download.
reinstall_data="yes"
if [ -d "$APPWORLD_DATA_DIR" ]; then
  echo "AppWorld data already exists at '$APPWORLD_DATA_DIR'."
  printf "Re-download data and re-run install? [y/N] "
  read -r answer
  case "$answer" in
    y|Y|yes|YES) reinstall_data="yes" ;;
    *) reinstall_data="no" ;;
  esac
fi

# Step 2: register appworld as an editable dep in the `appworld` group.
# `uv add` is idempotent: re-running updates the entry in place.
#
# --no-workspace: add appworld as a plain editable source under
#   [tool.uv.sources], NOT as a uv workspace member. As a workspace member,
#   uv would resolve the upstream's `[all]` extras (which pin ruff==0.8.0)
#   and collide with this repo's ruff>=0.14.3 dev pin.
echo "Registering AppWorld as an editable dependency (group: appworld)..."
uv add --editable --no-workspace "$APPWORLD_REPO_DIR" --group appworld

if [ "$reinstall_data" = "no" ]; then
  echo "Skipping data download. AppWorld is installed and ready."
  exit 0
fi

# Step 3: set up the repo layout and download data. These commands write into
# the current working directory, so we run them from the clone.
cd "$APPWORLD_REPO_DIR"

echo "Setting up AppWorld repository layout..."
uv run python -m appworld.cli install --repo

echo "Downloading AppWorld data..."
uv run python -m appworld.cli download data

cd - > /dev/null

echo ""
echo "AppWorld setup complete."
echo ""
echo "Usage:"
echo "  uv sync --group appworld   # install/refresh with AppWorld"
echo "  uv sync                    # base deps only (AppWorld will be removed"
echo "                             #   from the venv; re-add with --group)"
