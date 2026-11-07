#!/usr/bin/env python3
"""Offline check of the "read before write" reminder (``cuga.policy_layer.references``) on recorded arm-A runs.

For each task: feed the request, then every logged tool call in order (logged results, cut to 4000 characters) to a
ReferenceLedger, and note at each write whether a referred policy source is still unread (the reminder would fire).
Writes are labelled with the shadow replay (``shadow/<run>.json``): violating (a guardrail newly fails) or clean.
No model calls.

  PYTHONPATH=~/dev/cuga-agent-gate/src automationbench/.venv/bin/python policy_eval/reference_replay.py oss2_A_t1 oss2u_A_t1
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AB = HERE.parent / "automationbench"
sys.path.insert(0, str(AB))

import ab_env as runner  # noqa: E402
from cuga.policy_layer.intake import is_write_tool  # noqa: E402
from cuga.policy_layer.references import ReferenceLedger  # noqa: E402


def replay(run: str, verbose: bool) -> dict:
    shadow = {t["task"]: t for t in json.loads((HERE / "shadow" / f"{run}.json").read_text())}
    totals = {"violating": [0, 0], "clean": [0, 0], "tasks": []}  # [writes, reminder would fire]
    for path in sorted((AB / "results" / run).glob("*.json")):
        rec = json.loads(path.read_text())
        task = runner.load_task(rec["task"])
        labels = {w["i"]: w["label"] for w in shadow[rec["task"]]["writes"]}
        ledger = ReferenceLedger()
        ledger.add_from("\n".join(m["content"] for m in task["prompt"] if m["role"] == "user"), "the request")
        fired = []
        for i, call in enumerate(rec["tool_calls"]):
            write = is_write_tool(call["tool"])
            if write and i in labels:
                unread = ledger.unread()
                totals[labels[i]][0] += 1
                totals[labels[i]][1] += bool(unread)
                if unread:
                    fired.append((i, call["tool"], labels[i], [r.text for r in unread]))
            ledger.observe(call["tool"], call["args"], call["result"], write)
        totals["tasks"].append(
            (
                rec["task"],
                any(l == "violating" for l in labels.values()),
                bool(fired),
                any(fired_l == "violating" for _, _, fired_l, _ in fired),
            )
        )
        if verbose:
            viol = sum(1 for l in labels.values() if l == "violating")
            print(
                f"\n== {rec['task']}  violating writes {viol}, reminder fired before {len(fired)} of {len(labels)} writes"
            )
            print(ledger.summary() or "   (no references)")
            for f in fired[:3]:
                print(f"   fired before write {f[0]} {f[1]} [{f[2]}]: unread {f[3]}")
    return totals


def main() -> None:
    for run in sys.argv[1:]:
        t = replay(run, verbose="-q" not in sys.argv)
        print(
            f"\n## {run}: reminder fires before {t['violating'][1]} of {t['violating'][0]} violating writes, "
            f"{t['clean'][1]} of {t['clean'][0]} clean writes"
        )
        tv = [x for x in t["tasks"] if x[1]]
        tc = [x for x in t["tasks"] if not x[1]]
        print(
            f"   per task: fires in {sum(x[2] for x in tv)} of {len(tv)} tasks with a violating write "
            f"(before a violating write in {sum(x[3] for x in tv)}); fires in {sum(x[2] for x in tc)} of {len(tc)} other tasks "
            f"{[x[0] for x in tc if x[2]]}"
        )


if __name__ == "__main__":
    main()
