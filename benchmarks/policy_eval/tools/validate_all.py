"""Validate every converted policy package with ``validate_package`` (legacy mode) and count the findings.

    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/tools/validate_all.py [--findings FILE.json]

Reads benchmarks/policy_eval/packages/<bench>/<id>/<source>/package.json. The tool specs of a package come from the
benchmark's own spec file (``specs_of``); a package with none is checked without the tool checks and listed at the end.
``legacy=True`` (every source except ``COMPLETE_SOURCES``, the packages made with the skill or by the pipeline of task 3.5): gaps in coverage and rules with no trigger tool are warnings. The run never changes a package. Exit
code 0 when every package was read and checked (findings are the result, not a failure), 1 when one could not be.
``--findings FILE.json`` writes every finding, for reading by hand. ``--strict`` checks every package as a new one.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from cuga.policy_layer.package import load_package
from cuga.policy_layer.validate import validate_package

HERE = Path(__file__).resolve().parent.parent
BENCH = HERE.parent
PACKAGES = HERE / "packages"
COMPLETE_SOURCES = {"skill_v1", "pipeline_gptoss", "pipeline_dsv4"}  # made with the skill or by the pipeline (task 3.5): checked as new packages, not as converted ones


def specs_of(bench: str, policy_id: str) -> Optional[List[Dict[str, Any]]]:
    """The tool specs of one policy, or None if no spec file is known for it. Nothing is made up."""
    path = {
        "itsm": BENCH / "enterpriseops_gym" / "tasks" / "itsm_tools.json",
        "automationbench": HERE / "gold" / "ab" / policy_id / "tools.json",
        "handbook": BENCH / "handbook" / "tools" / f"{policy_id}.json",
        "tau2_telecom": HERE / "tau2" / "telecom_tools.json",
        "tau2_airline": HERE / "tau2" / "airline_tools.json",
        "tau2_retail": HERE / "tau2" / "retail_tools.json",
    }.get(bench)
    if path is None or not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("tools", [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--findings", help="write every finding to this JSON file")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="check every package as a new one (legacy=False): coverage gaps and rules with no trigger tool are errors, "
        "and the text checks of a new package show (quote_not_verbatim)",
    )
    args = ap.parse_args()
    paths = sorted(PACKAGES.glob("*/*/*/package.json"))
    if not paths:
        print(f"NO PACKAGES under {PACKAGES}")
        return 1
    total: Counter = Counter()
    findings: List[Dict[str, Any]] = []
    unchecked: List[str] = []
    for path in paths:
        bench, policy_id, source = path.parts[-4:-1]
        name = f"{bench}/{policy_id}/{source}"
        try:
            package = load_package(path)
            specs = specs_of(bench, policy_id)
            # a package made with the skill must be complete: no legacy reading of its coverage
            found = validate_package(
                package, specs, legacy=not args.strict and source not in COMPLETE_SOURCES
            )
        except Exception as exc:  # a crash is the result this script exists to rule out
            print(f"CRASH {name}: {type(exc).__name__}: {exc}")
            return 1
        if specs is None:
            unchecked.append(name)
        count = Counter((f.code, f.severity) for f in found)
        total.update(count)
        findings += [{"package": name, **vars(f)} for f in found]
        shown = ", ".join(f"{code} {sev} {n}" for (code, sev), n in sorted(count.items())) or "none"
        print(f"{name:<80} rules={len(package.rules):<4} {shown}")
    print(f"\n{len(paths)} packages. Findings by code and severity:")
    for (code, severity), n in sorted(total.items()):
        print(f"  {code:<22} {severity:<8} {n}")
    if unchecked:
        print("\nNo tool spec file, tool checks skipped:", ", ".join(unchecked))
    if args.findings:
        Path(args.findings).write_text(json.dumps(findings, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
