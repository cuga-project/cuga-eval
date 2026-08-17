#!/usr/bin/env bash
set -Eeuo pipefail

# =============================================================================
# PR Regression Testing VM Bootstrap
#
# Modes:
#   REPO_MODE=fork      -> use temporary AnkitaNaik forks (default for now)
#   REPO_MODE=upstream  -> use cuga-project upstream repositories
#
# Final layout:
#
#   ~/pr-regression-testing/
#   ├── cuga-agent/
#   ├── cuga-eval/
#   │   └── scripts/
#   │       └── run-eval.sh
#   └── github-runner/
#       └── _work/
#
# Required VM prerequisites:
#   git curl tar python3 git-lfs
#
# Required environment variables:
#   GITHUB_REPO_URL
#   GITHUB_RUNNER_TOKEN
#
# Optional:
#   REPO_MODE=fork|upstream
#   ROOT_DIR
#   RUNNER_NAME
#   RUNNER_LABELS
#   CUGA_AGENT_BRANCH
#   CUGA_EVAL_BRANCH
#   RUNNER_VERSION
# =============================================================================

REPO_MODE="${REPO_MODE:-fork}"
ROOT_DIR="${ROOT_DIR:-$HOME/pr-regression-testing}"

RUNNER_NAME="${RUNNER_NAME:-$(hostname)}"
RUNNER_LABELS="${RUNNER_LABELS:-run-eval}"

CUGA_AGENT_BRANCH="${CUGA_AGENT_BRANCH:-main}"
CUGA_EVAL_BRANCH="${CUGA_EVAL_BRANCH:-main}"

case "${REPO_MODE}" in
  fork)
    DEFAULT_CUGA_AGENT_REPO_URL="https://github.com/AnkitaNaik/cuga-agent.git"
    DEFAULT_CUGA_EVAL_REPO_URL="https://github.com/AnkitaNaik/cuga-eval.git"
    ;;
  upstream)
    DEFAULT_CUGA_AGENT_REPO_URL="https://github.com/cuga-project/cuga-agent.git"
    DEFAULT_CUGA_EVAL_REPO_URL="https://github.com/cuga-project/cuga-eval.git"
    ;;
  *)
    echo "ERROR: REPO_MODE must be 'fork' or 'upstream'." >&2
    exit 2
    ;;
esac

CUGA_AGENT_REPO_URL="${CUGA_AGENT_REPO_URL:-$DEFAULT_CUGA_AGENT_REPO_URL}"
CUGA_EVAL_REPO_URL="${CUGA_EVAL_REPO_URL:-$DEFAULT_CUGA_EVAL_REPO_URL}"

CUGA_AGENT_DIR="${ROOT_DIR}/cuga-agent"
CUGA_EVAL_DIR="${ROOT_DIR}/cuga-eval"
GH_RUNNER_DIR="${ROOT_DIR}/github-runner"

RUN_EVAL_SCRIPT="${CUGA_EVAL_DIR}/scripts/run-pr-regression-eval.sh"
x
log() {
  printf '\n[%s] %s\n' "$(date -u +"%Y-%m-%d %H:%M:%S UTC")" "$*"
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command '$1' is missing."
}

clone_or_update() {
  local repo_url="$1"
  local branch="$2"
  local dest="$3"
  local name="$4"

  if [[ -d "${dest}/.git" ]]; then
    log "Updating ${name}"
    git -C "${dest}" fetch --all --prune
    git -C "${dest}" checkout "${branch}"
    git -C "${dest}" pull --ff-only origin "${branch}"
  else
    log "Cloning ${name}"
    git clone --branch "${branch}" "${repo_url}" "${dest}"
  fi
}

: "${GITHUB_REPO_URL:?Set GITHUB_REPO_URL, e.g. https://github.com/OWNER/REPO}"
: "${GITHUB_RUNNER_TOKEN:?Set GITHUB_RUNNER_TOKEN to the temporary runner token}"

log "Repository mode: ${REPO_MODE}"
echo "cuga-agent: ${CUGA_AGENT_REPO_URL}"
echo "cuga-eval:  ${CUGA_EVAL_REPO_URL}"

log "Checking VM prerequisites"
need_cmd git
need_cmd curl
need_cmd tar
need_cmd python3
need_cmd git-lfs

python3 - <<'PY'
import sys
if not ((3, 12) <= sys.version_info[:2] < (3, 14)):
    raise SystemExit(
        f"ERROR: Python 3.12 or 3.13 is required; found "
        f"{sys.version_info.major}.{sys.version_info.minor}"
    )
PY

if ! command -v uv >/dev/null 2>&1; then
  log "Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
fi
need_cmd uv

mkdir -p "${ROOT_DIR}"

clone_or_update \
  "${CUGA_AGENT_REPO_URL}" \
  "${CUGA_AGENT_BRANCH}" \
  "${CUGA_AGENT_DIR}" \
  "cuga-agent"

clone_or_update \
  "${CUGA_EVAL_REPO_URL}" \
  "${CUGA_EVAL_BRANCH}" \
  "${CUGA_EVAL_DIR}" \
  "cuga-eval"

log "Running cuga-eval/setup_cuga.sh"
cd "${CUGA_EVAL_DIR}"
chmod u+x ./setup_cuga.sh
bash ./setup_cuga.sh

log "Creating/syncing cuga-eval environment"
uv venv
uv sync

log "Setting up AppWorld"
git lfs install
chmod u+x ./setup_appworld.sh
bash ./setup_appworld.sh
uv sync --group appworld

log "Checking run-eval.sh"
if [[ ! -f "${RUN_EVAL_SCRIPT}" ]]; then
  cat >&2 <<EOF

ERROR: expected evaluation entrypoint was not found:

  ${RUN_EVAL_SCRIPT}

Repository mode:
  ${REPO_MODE}

cuga-eval repository:
  ${CUGA_EVAL_REPO_URL}

If running in temporary fork mode, ensure your fork contains:
  scripts/run-eval.sh

If switching to upstream later, either:
  1. ensure upstream contains scripts/run-eval.sh, or
  2. override RUN_EVAL_SCRIPT logic in this bootstrap.

EOF
  exit 1
fi

chmod u+x "${RUN_EVAL_SCRIPT}"

mkdir -p "${GH_RUNNER_DIR}"
cd "${GH_RUNNER_DIR}"

if [[ ! -x "${GH_RUNNER_DIR}/config.sh" ]]; then
  ARCH="$(uname -m)"

  case "${ARCH}" in
    x86_64|amd64) RUNNER_ARCH="x64" ;;
    aarch64|arm64) RUNNER_ARCH="arm64" ;;
    *) die "Unsupported CPU architecture: ${ARCH}" ;;
  esac

  if [[ -z "${RUNNER_VERSION:-}" ]]; then
    log "Resolving latest GitHub Actions runner version"
    RUNNER_VERSION="$(
      python3 - <<'PY'
import json
import urllib.request

req = urllib.request.Request(
    "https://api.github.com/repos/actions/runner/releases/latest",
    headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "pr-regression-bootstrap"
    },
)

with urllib.request.urlopen(req) as response:
    data = json.load(response)

print(data["tag_name"].lstrip("v"))
PY
    )"
  fi

  RUNNER_ARCHIVE="actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz"
  RUNNER_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${RUNNER_ARCHIVE}"

  log "Downloading GitHub Actions runner ${RUNNER_VERSION}"
  curl -fL -o "${RUNNER_ARCHIVE}" "${RUNNER_URL}"
  tar xzf "${RUNNER_ARCHIVE}"
  rm -f "${RUNNER_ARCHIVE}"
fi

if [[ ! -f "${GH_RUNNER_DIR}/.runner" ]]; then
  log "Registering GitHub runner"

  ./config.sh \
    --url "${GITHUB_REPO_URL}" \
    --token "${GITHUB_RUNNER_TOKEN}" \
    --name "${RUNNER_NAME}" \
    --labels "${RUNNER_LABELS}" \
    --work "_work" \
    --unattended
else
  log "Runner already registered; skipping registration"
fi

if pgrep -f "${GH_RUNNER_DIR}/bin/Runner.Listener" >/dev/null 2>&1; then
  log "Runner already running"
else
  log "Starting runner in background"

  nohup ./run.sh > "${GH_RUNNER_DIR}/runner.log" 2>&1 &
  echo $! > "${GH_RUNNER_DIR}/runner.pid"
fi

sleep 3

if ! pgrep -f "${GH_RUNNER_DIR}/bin/Runner.Listener" >/dev/null 2>&1; then
  echo "ERROR: Runner did not remain active." >&2
  tail -n 50 "${GH_RUNNER_DIR}/runner.log" 2>/dev/null || true
  exit 1
fi

echo
echo "======================================================================"
echo "PR regression testing VM is ready"
echo "======================================================================"
echo
echo "Repository mode:"
echo "  ${REPO_MODE}"
echo
echo "Layout:"
echo "  ${ROOT_DIR}/"
echo "  ├── cuga-agent/"
echo "  ├── cuga-eval/"
echo "  │   └── scripts/run-eval.sh"
echo "  └── github-runner/"
echo "      └── _work/"
echo
echo "Repos:"
echo "  cuga-agent: ${CUGA_AGENT_REPO_URL}"
echo "  cuga-eval:  ${CUGA_EVAL_REPO_URL}"
echo
echo "Runner logs:"
echo "  tail -f ${GH_RUNNER_DIR}/runner.log"
echo
echo "Workflow target:"
echo "  runs-on: [self-hosted, linux, ${RUNNER_LABELS}]"
echo
echo "Workflow script:"
echo "  bash \"${RUN_EVAL_SCRIPT}\" \"\${COMMENT_BODY}\""
