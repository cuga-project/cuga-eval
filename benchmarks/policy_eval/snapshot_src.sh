#!/usr/bin/env bash
# Freeze the policy-gate worktree's code for a run:  ./snapshot_src.sh [--allow-dirty] <name>
# Prints the src path to use as CUGA_SRC / PYTHONPATH. Runs then keep their code while the worktree changes
# (each task starts a new process).
#
# Snapshots live in ~/dev/cuga_snapshots/<name>/ (they survive a restart, unlike /tmp). SOURCE.txt holds two
# lines: the short commit sha and the number of uncommitted entries (git status --porcelain). A snapshot must come
# from a clean tree, so that the sha names the code exactly; a dirty tree is an error unless --allow-dirty is given
# (then SOURCE.txt records the count, and the sha alone does not describe the code).
set -euo pipefail

usage() { echo "usage: $0 [--allow-dirty] <name>" >&2; exit 2; }

allow_dirty=0
name=""
for arg in "$@"; do
  case "$arg" in
    --allow-dirty) allow_dirty=1 ;;
    -*) usage ;;
    *) [ -z "$name" ] && name="$arg" || usage ;;
  esac
done
[ -n "$name" ] || usage
[[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { echo "bad snapshot name: $name (letters, digits, . _ - only)" >&2; exit 2; }

repo="${CUGA_GATE_REPO:-$HOME/dev/cuga-agent-gate}"  # overrides exist for testing the script only
root="${CUGA_SNAPSHOT_ROOT:-$HOME/dev/cuga_snapshots}"
dest="$root/$name"

sha=$(git -C "$repo" rev-parse --short HEAD)
dirty=$(git -C "$repo" status --porcelain | wc -l | tr -d ' ')
if [ "$dirty" != "0" ] && [ "$allow_dirty" != "1" ]; then
  echo "refusing to snapshot: $repo has $dirty uncommitted entries (commit them, or pass --allow-dirty)" >&2
  git -C "$repo" status --short | head -10 >&2
  exit 1
fi

[ -e "$dest" ] && echo "replacing existing snapshot $dest" >&2
mkdir -p "$dest"
rsync -a --delete --exclude '__pycache__' --exclude '.pytest_cache' "$repo/src/" "$dest/src/"
printf '%s\n%s\n' "$sha" "$dirty" > "$dest/SOURCE.txt"
echo "$dest/src"
