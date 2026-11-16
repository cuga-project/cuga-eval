#!/usr/bin/env bash
# The code snapshot of a run:  ./snapshot_polisys.sh <polisys repo> [cuga-agent repo]
# The CUGA code of the cuga-agent repo's HEAD, the polisys package from the polisys repo's HEAD, and cuga/policy_layer as an alias
# of polisys (the harness and its adapters import cuga.policy_layer). Neither repo may have uncommitted changes to tracked files,
# so that the two commit IDs name the code exactly. Prints the snapshot name; give it to the harness as --snapshot.
# The cuga-agent repo is the second argument, else $CUGA_AGENT_REPO, else ~/dev/cuga-agent. Snapshots go to $CUGA_SNAPSHOT_ROOT,
# else ~/dev/cuga_snapshots. SOURCE.txt: line 1 the name of the code, line 2 the number of uncommitted entries (0), line 3 the
# branches and commits of the two repos.
set -euo pipefail
polisys="${1:?polisys repo}"; agent="${2:-${CUGA_AGENT_REPO:-$HOME/dev/cuga-agent}}"
root="${CUGA_SNAPSHOT_ROOT:-$HOME/dev/cuga_snapshots}"
for repo in "$polisys" "$agent"; do
  [ -z "$(git -C "$repo" status --porcelain --untracked-files=no)" ] || { echo "$repo has uncommitted changes to tracked files" >&2; exit 1; }
done
psha=$(git -C "$polisys" rev-parse --short HEAD); asha=$(git -C "$agent" rev-parse --short HEAD)
pbranch=$(git -C "$polisys" branch --show-current); abranch=$(git -C "$agent" branch --show-current)
name="polisys-$psha-cuga-$asha"; dest="$root/$name"
rm -rf "$dest"; mkdir -p "$dest"
git -C "$agent" archive HEAD src | tar -x -C "$dest"
rm -rf "$dest/src/cuga/policy_layer"
mkdir -p "$dest/src/polisys"; git -C "$polisys" archive HEAD src/polisys | tar -x -C "$dest"
mkdir -p "$dest/src/cuga/policy_layer"
cat > "$dest/src/cuga/policy_layer/__init__.py" <<'PY'
"""Alias package: ``cuga.policy_layer.<module>`` is the module ``polisys.<module>`` (same module object)."""

import importlib
import importlib.abc
import importlib.machinery
import sys

_PREFIX = __name__ + "."


class _Alias(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, name, path=None, target=None):
        return importlib.machinery.ModuleSpec(name, self) if name.startswith(_PREFIX) else None

    def create_module(self, spec):
        return importlib.import_module("polisys." + spec.name[len(_PREFIX):])

    def exec_module(self, module):
        return None


sys.meta_path.insert(0, _Alias())
PY
printf 'poli-%s-cuga-%s\n0\ncuga-agent %s %s | polisys %s %s\n' "$psha" "$asha" "${abranch:-detached}" "$asha" "${pbranch:-detached}" "$psha" > "$dest/SOURCE.txt"
echo "$name"
