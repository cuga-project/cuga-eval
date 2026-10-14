"""Which CUGA this environment actually imports — the parity kit's guard against a moving checkout.

cuga-eval installs CUGA editable from a checkout, so whatever that checkout has checked out
*is* the CUGA a run uses. The cuga-agent repo's main checkout is shared: other sessions switch
its branch at any time (on 2026-10-13 one did, mid-run, and half an arm ran without function
calling). Parity runs therefore import CUGA from a linked worktree pinned to one commit; this
reports what is really imported so the kit can refuse the shared checkout and stop an arm whose
CUGA changes between domains.

usage: python -m benchmarks.m3.parity.cuga_identity [--line]
  default: JSON {package, repo, commit, branch, dirty, main_worktree}
  --line:  "repo commit branch dirty main_worktree(0|1)" for bash ``read``
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def _git(repo: str, *args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True)  # noqa: S603, S607
    except (OSError, subprocess.CalledProcessError):
        return ""
    return out.stdout.strip()


def identity(package: Optional[str] = None) -> Dict[str, Any]:
    """Describe the checkout of ``package`` (default: the importable ``cuga``, located without importing it)."""
    if package is None:
        spec = importlib.util.find_spec("cuga")
        package = str(Path(spec.origin).parent) if spec and spec.origin else ""
    repo = _git(package, "rev-parse", "--show-toplevel") if package else ""
    if not repo:
        return {
            "package": package,
            "repo": "",
            "commit": "",
            "branch": "",
            "dirty": 0,
            "main_worktree": False,
        }
    git_dir = _git(repo, "rev-parse", "--absolute-git-dir")
    common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return {
        "package": package,
        "repo": repo,
        "commit": _git(repo, "rev-parse", "--short=8", "HEAD"),
        "branch": _git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": sum(1 for line in _git(repo, "status", "--porcelain").splitlines() if line.strip()),
        # the main worktree is where the other cuga sessions work; a linked worktree is ours alone
        "main_worktree": bool(git_dir) and os.path.realpath(git_dir) == os.path.realpath(common),
    }


def as_line(ident: Dict[str, Any]) -> str:
    fields = (ident["repo"], ident["commit"], ident["branch"], ident["dirty"], int(ident["main_worktree"]))
    return " ".join(str(f) if f != "" else "-" for f in fields)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--line", action="store_true", help="one bash-readable line instead of JSON")
    args = parser.parse_args(argv)
    ident = identity()
    print(as_line(ident) if args.line else json.dumps(ident))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
