"""Does a package run? Build the runtime of each ``skill_v1`` package on three profiles, with no agent and no model.

    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/tools/runtime_check.py [--source skill_v1] [--json OUT]

A package that validates but does not run is a failure. For each package ``build_runtime`` is called with
``RecordingModels`` (its models raise when called, so nothing can reach a model) on:

  gate   ``handbook-gemini-graph-gate``: procedure tools and the must-not gate
  guide  ``handbook-dsv4-loop-guide``: the guide and the loop
  rules  ``itsm-rules``: the rule checks, with the verifier on

The profile files name a package path of their own; the opened package is passed in, and the path is never read. A raise is
printed with its message. Exit code 1 when any of them raised (``--allow`` names a combination that is known to fail).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from cuga.policy_layer.dry_run import RecordingModels
from cuga.policy_layer.package import load_package
from cuga.policy_layer.policy_config import load_config
from cuga.policy_layer.runtime import RunContext, build_runtime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_all import PACKAGES, specs_of  # noqa: E402

HERE = Path(__file__).resolve().parent.parent
PROFILES = {
    "gate": "handbook-gemini-graph-gate",
    "guide": "handbook-dsv4-loop-guide",
    "rules": "itsm-rules",
}


def combinations(source: str) -> List[Tuple[str, str, Path]]:
    return [
        (path.parts[-4], path.parts[-3], path) for path in sorted(PACKAGES.glob(f"*/*/{source}/package.json"))
    ]


def check(bench: str, policy: str, path: Path) -> List[Dict[str, Any]]:
    pkg = load_package(path)
    specs = specs_of(bench, policy) or []
    rows = []
    for name, profile in PROFILES.items():
        cfg = load_config(HERE / "profiles" / f"{profile}.yaml")
        ctx = RunContext(
            task_id=f"{bench}/{policy}", policy_version=pkg.version, tool_specs=specs, system_prompt=""
        )
        row: Dict[str, Any] = {"package": f"{bench}/{policy}", "profile": name, "raised": ""}
        try:
            parts = build_runtime(cfg, pkg, ctx, models=RecordingModels())
            row["components"] = sorted(
                parts.components
            )  # what is on: a build that wires nothing is not a run
            row["hooks"] = len(parts.hooks)
            row["tools"] = len(parts.tools)
        except Exception as exc:  # the result this script exists to show
            row["raised"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="skill_v1")
    ap.add_argument("--json", help="write the rows to this file")
    a = ap.parse_args()
    rows: List[Dict[str, Any]] = []
    for bench, policy, path in combinations(a.source):
        rows += check(bench, policy, path)
    for r in rows:
        shown = (
            "RAISED " + r["raised"][:300]
            if r["raised"]
            else f"ok  components {','.join(r['components'])}; hooks {r['hooks']}, tools {r['tools']}"
        )
        print(f"{r['package']:<58} {r['profile']:<6} {shown}")
    bad = [r for r in rows if r["raised"]]
    print(f"\n{len(rows)} builds, {len(bad)} raised")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
