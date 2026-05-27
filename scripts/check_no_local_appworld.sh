#!/usr/bin/env bash
# Block commits that include the locally-injected AppWorld entries in
# pyproject.toml or uv.lock. setup_appworld.sh runs `uv add --editable
# --no-workspace benchmarks/appworld/appworld --group appworld`, which writes
# to BOTH files; the entries point at a path that exists only on machines
# where the script has run, so committing either re-breaks `uv sync` on
# fresh checkouts (CI, other contributors).
#
# Bypass with `git commit --no-verify` only if you genuinely intend to commit
# the appworld dependency (e.g. switching to a shipped editable layout).

set -euo pipefail

staged_files=$(git diff --cached --name-only)
bad=0

# --- pyproject.toml -------------------------------------------------------
if printf '%s\n' "$staged_files" | grep -qx 'pyproject.toml'; then
  staged_pyproject=$(git show ":pyproject.toml" 2>/dev/null || true)
  if [ -n "$staged_pyproject" ]; then
    # Source entry written by `uv add --editable benchmarks/appworld/appworld`.
    # Uses POSIX bracket expressions (BSD grep on macOS doesn't grok PCRE \s).
    if printf '%s\n' "$staged_pyproject" | grep -Eq '^[[:space:]]*appworld[[:space:]]*=[[:space:]]*\{[^}]*path[[:space:]]*=[[:space:]]*"benchmarks/appworld/appworld"'; then
      echo "error: staged pyproject.toml contains the local AppWorld editable source" >&2
      echo "       (appworld = { path = \"benchmarks/appworld/appworld\", ... })." >&2
      bad=1
    fi

    # Dependency group entry: `appworld = [...]` under `[dependency-groups]`.
    # Uses POSIX bracket classes; standard awk doesn't grok \s either.
    if printf '%s\n' "$staged_pyproject" | awk '
      /^[[:space:]]*\[/ { in_group = ($0 ~ /^[[:space:]]*\[dependency-groups\][[:space:]]*$/); next }
      in_group && /^[[:space:]]*appworld[[:space:]]*=/ { found = 1 }
      END { exit found ? 0 : 1 }
    '; then
      echo "error: staged pyproject.toml contains the local [dependency-groups].appworld entry." >&2
      bad=1
    fi
  fi
fi

# --- uv.lock --------------------------------------------------------------
# `uv add --editable` also rewrites uv.lock with a [[package]] block for
# appworld. Even if pyproject.toml is clean, a stale uv.lock with that block
# re-introduces the bad reference on the next `uv sync`.
if printf '%s\n' "$staged_files" | grep -qx 'uv.lock'; then
  staged_lock=$(git show ":uv.lock" 2>/dev/null || true)
  if [ -n "$staged_lock" ] && printf '%s\n' "$staged_lock" | grep -Eq '^name[[:space:]]*=[[:space:]]*"appworld"'; then
    echo "error: staged uv.lock contains the local 'appworld' package block." >&2
    bad=1
  fi
fi

if [ "$bad" -ne 0 ]; then
  cat >&2 <<'MSG'

These entries are added locally by ./setup_appworld.sh and must not be
committed — they point at benchmarks/appworld/appworld, which only exists
on machines that have run the setup script. Committing them re-breaks
`uv sync` for everyone who hasn't.

To unstage them:
  git restore --staged pyproject.toml uv.lock
Then re-stage only the changes you actually want to commit.
MSG
  exit 1
fi

exit 0
