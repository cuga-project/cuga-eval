#!/usr/bin/env bash
# Pin the CUGA the parity kit runs, out of reach of other sessions.
# usage: bash benchmarks/m3/parity/setup_pinned_cuga.sh <cuga-agent commit or ref> [overrides.txt]
#
# The cuga-agent repo's main checkout and cuga-eval's .venv are both shared: other sessions
# switch branches in the first and re-sync (even re-lock) the second, and either change silently
# swaps the CUGA a run imports. This builds the two private pieces the kit uses instead:
#   - a linked worktree of the cuga-agent repo detached at <commit> (default ../cuga-agent-parity);
#   - a kit-only venv (parity/.local/venv, gitignored) synced from the committed uv.lock, with that
#     worktree installed editable.
# env.sh points every kit command at that venv (UV_PROJECT_ENVIRONMENT) and never re-syncs it.
# Re-run with a new commit to move the kit to another CUGA (e.g. once cuga-agent#777 merges).
# overrides.txt: exact versions installed over the lock, for a CUGA whose floors exceed it
# (venv_overrides.cuga-main-88fd3549.txt rebuilds venv-main, the CUGA main the validated runs used).
set -euo pipefail
PARITY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$PARITY_DIR/../../.." && pwd)"
COMMIT="${1:?usage: setup_pinned_cuga.sh <cuga-agent commit or ref> [overrides.txt]}"
OVERRIDES="${2:-}"
REPO="${CUGA_REPO:-$ROOT/../cuga-agent}"
WT="${PARITY_CUGA_WORKTREE:-$ROOT/../cuga-agent-parity}"
VENV="${PARITY_VENV:-$PARITY_DIR/.local/venv}"
# Both kit venvs run Python 3.12.7; without a pin uv takes the newest installed Python (3.13 on the Mac).
export UV_PYTHON="${UV_PYTHON:-3.12.7}"

if [ -e "$WT" ]; then
    [ -z "$(git -C "$WT" status --porcelain)" ] || { echo "pinned worktree $WT has local changes; refusing to move it" >&2; exit 1; }
    git -C "$WT" checkout -q --detach "$COMMIT"
else
    git -C "$REPO" worktree add -q --detach "$WT" "$COMMIT"
fi
# The venv must match the committed lock, not a lock another session rewrote in the working tree.
git -C "$ROOT" diff --quiet -- uv.lock || {
    echo "uv.lock differs from HEAD (another session re-locked?): restore it first with 'git checkout -- uv.lock'" >&2
    exit 1
}
(cd "$ROOT" && env -u VIRTUAL_ENV UV_PROJECT_ENVIRONMENT="$VENV" uv sync --frozen --group dev)
[ -z "$OVERRIDES" ] || uv pip install --python "$VENV/bin/python" --no-deps -r "$OVERRIDES"
uv pip install --python "$VENV/bin/python" --no-deps -e "$WT"
(cd "$ROOT" && env -u VIRTUAL_ENV UV_PROJECT_ENVIRONMENT="$VENV" uv run --no-sync python -m benchmarks.m3.parity.cuga_identity)
