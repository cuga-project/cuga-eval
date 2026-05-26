#!/usr/bin/env bash
# Block commits that include the locally-injected AppWorld entries in
# pyproject.toml. setup_appworld.sh adds these via `uv add --editable
# --no-workspace benchmarks/appworld/appworld --group appworld`; they point
# at a path that exists only on machines where the script has run, so
# committing them would break `uv sync` on fresh checkouts (CI, other
# contributors).
#
# Bypass with `git commit --no-verify` only if you genuinely intend to commit
# the appworld dependency (e.g. switching to a shipped editable layout).

set -euo pipefail

# Only run when pyproject.toml is among the files being committed.
if ! git diff --cached --name-only | grep -qx 'pyproject.toml'; then
  exit 0
fi

staged_pyproject=$(git show ":pyproject.toml" 2>/dev/null || true)

if [ -z "$staged_pyproject" ]; then
  exit 0
fi

bad=0

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

if [ "$bad" -ne 0 ]; then
  cat >&2 <<'MSG'

These entries are added locally by ./setup_appworld.sh and must not be
committed — they point at benchmarks/appworld/appworld, which only exists
on machines that have run the setup script. Committing them re-breaks
`uv sync` for everyone who hasn't.

To unstage them:
  git restore --staged pyproject.toml
Then re-stage only the changes you actually want to commit.
MSG
  exit 1
fi

exit 0
