#!/usr/bin/env bash
set -euo pipefail

APPWORLD_DIR="benchmarks/appworld"
APPWORLD_ENV_FILE="benchmarks/appworld/config/appworld.env"
APPWORLD_REPO_DIR="${APPWORLD_DIR}/appworld"
APPWORLD_DATA_DIR="${APPWORLD_REPO_DIR}/data"

if [ ! -d "$APPWORLD_DIR" ]; then
  echo "Error: '$APPWORLD_DIR' directory not found!"
  echo "Please clone the repository first"
  exit 1
fi

if [ ! -f "$APPWORLD_ENV_FILE" ]; then
  echo "Error: '$APPWORLD_ENV_FILE' file not found!"
  exit 1
fi

set -a
. "$APPWORLD_ENV_FILE"
set +a

if [ ! -d "$APPWORLD_REPO_DIR" ]; then
  echo "Error: '$APPWORLD_REPO_DIR' directory not found!"
  echo "Please clone the AppWorld repository into '$APPWORLD_REPO_DIR' first"
  exit 1
fi

if [ -d "$APPWORLD_DATA_DIR" ]; then
  echo "AppWorld repository already present at '$APPWORLD_REPO_DIR'."
  echo "AppWorld data already exists at '$APPWORLD_DATA_DIR'."
  printf "Would you like to reinstall AppWorld and re-download the data? [y/N] "
  read -r reinstall_appworld

  case "$reinstall_appworld" in
    y|Y|yes|YES)
      echo "Reinstalling AppWorld and downloading data..."
      ;;
    *)
      echo "Keeping existing AppWorld installation and data. Skipping setup."
      exit 0
      ;;
  esac
fi

cd "$APPWORLD_REPO_DIR"

uv pip install .
# Note: For experiment reproduction use:
uv run -m appworld.cli install

uv run appworld install --repo
uv run appworld download data

# Made with Bob
