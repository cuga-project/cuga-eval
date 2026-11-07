"""The procedure monitor of the gate repo at a base commit and as it is now, on the packages of measured profiles.

    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/tools/monitor_base_vs_head.py [base commit]

For every package with procedures that is not written from a skill (ITSM ``builds_v5``, HANDBOOK ``v3``, ``v4`` and
``claude_v1``, Telecom ``builds``, the pipeline packages), calls the tools of the steps in several sequences (each tool alone,
each procedure's tools in order and in reverse) and compares the brief, the reply message and the records of the two
monitors. Prints the number of differences; exit code 1 if there is one. Task 4.2 fix round 1: 0 of 1188 (base ``675dc1756``).
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from cuga.policy_layer import procedure_monitor as head
from cuga.policy_layer.package import load_package

GATE = Path.home() / "dev/cuga-agent-gate"
BASE = sys.argv[1] if len(sys.argv) > 1 else "675dc1756"
ROOT = Path(__file__).resolve().parents[1] / "packages"
PATTERNS = (
    "itsm/*/builds_v5/package.json",
    "itsm/*/builds_v5_norepair/package.json",
    "handbook/*/v3/package.json",
    "handbook/*/v4/package.json",
    "handbook/*/claude_v1/package.json",
    "tau2_telecom/telecom/builds/package.json",
    "*/*/pipeline_*/package.json",
)


def base_module():
    text = subprocess.run(
        ["git", "-C", str(GATE), "show", f"{BASE}:src/cuga/policy_layer/procedure_monitor.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    path = Path(tempfile.mkdtemp()) / "pm_base.py"
    path.write_text(text)
    spec = importlib.util.spec_from_file_location("cuga.policy_layer.pm_base", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run(module, pkg, seq):
    monitor = module.ProcedureMonitor(pkg.procedures)
    out = []
    for tool in seq:
        out.append(json.dumps(monitor.after_tool_call(tool, {}, {"ok": True}).details, sort_keys=True))
        out.append(monitor.before_llm_call(None).message)
    out.append(monitor.before_reply("x").message)
    out.append(json.dumps(monitor.records, sort_keys=True))
    return out


def main() -> int:
    base = base_module()
    files = [f for pattern in PATTERNS for f in sorted(ROOT.glob(pattern))]
    packages = sequences = differences = 0
    for path in files:
        pkg = load_package(path)
        if not pkg.procedures:
            continue
        packages += 1
        tools = list(dict.fromkeys(s.action for p in pkg.procedures for s in p.steps if s.action))
        seqs = [[t] for t in tools]
        for proc in pkg.procedures:
            acts = [s.action for s in proc.steps if s.action]
            seqs += [acts[:k] for k in range(2, len(acts) + 1)] + [list(reversed(acts))]
        for seq in seqs:
            sequences += 1
            if run(base, pkg, seq) != run(head, pkg, seq):
                differences += 1
                print("DIFFERENT", path.relative_to(ROOT), seq[:4])
    print(f"base {BASE}: packages {packages}, call sequences {sequences}, differences {differences}")
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())
