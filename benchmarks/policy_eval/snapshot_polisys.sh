#!/usr/bin/env bash
# A code snapshot that runs standalone polisys under the harness:  ./snapshot_polisys.sh <polisys repo> [gate tag]
# The gate's CUGA code at the tag, the polisys package from the repo's HEAD, and cuga/policy_layer as an alias of polisys
# (the harness and its adapters import cuga.policy_layer). The repo must be clean. Prints the snapshot name.
set -euo pipefail
repo="${1:?polisys repo}"; tag="${2:-policy/stable-v1}"
gate="${CUGA_GATE_REPO:-$HOME/dev/cuga-agent-gate}"; root="${CUGA_SNAPSHOT_ROOT:-$HOME/dev/cuga_snapshots}"
[ -z "$(git -C "$repo" status --porcelain)" ] || { echo "polisys repo has uncommitted entries" >&2; exit 1; }
sha=$(git -C "$repo" rev-parse --short HEAD); gsha=$(git -C "$gate" rev-parse --short "$tag")
name="polisys-$sha"; dest="$root/$name"
rm -rf "$dest"; mkdir -p "$dest"
git -C "$gate" archive "$tag" src | tar -x -C "$dest"
rm -rf "$dest/src/cuga/policy_layer"
mkdir -p "$dest/src/polisys"; git -C "$repo" archive HEAD src/polisys | tar -x -C "$dest"
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
printf 'poli-%s-gate-%s\n0\n' "$sha" "$gsha" > "$dest/SOURCE.txt"
echo "$name"
