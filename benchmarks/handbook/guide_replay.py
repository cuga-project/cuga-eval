#!/usr/bin/env python3
"""Replay the procedure guide on finished HANDBOOK runs: which writes it would stop, and why (no model calls).

~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/handbook/guide_replay.py hb_A_t1 hb_A_t2 hb_A_t3
"""

import glob
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILDS = HERE.parent / "policy_eval/builds_handbook/v3"


def main() -> None:
    from cuga.policy_layer.procedure_guide import guide_from_build
    from cuga.policy_layer.ruleset import is_write_tool

    for run in sys.argv[1:]:
        for f in sorted(glob.glob(str(HERE / "results" / run / "*.json"))):
            r = json.loads(Path(f).read_text())
            b = BUILDS / f"{r['task']}.json"
            if not b.exists():
                print(run, r["task"][:20], "no build yet")
                continue
            g = guide_from_build(str(b))
            stops = []
            for i, c in enumerate(r.get("tool_calls") or []):
                if not is_write_tool(c["tool"]):
                    continue
                res = g.before_tool_call(c["tool"], c.get("args") or {})
                if res.message:
                    rec = g.records[-1]
                    stops.append(
                        f"#{i} {c['tool']} {rec['rule'].split('_')[1]} [{str(rec.get('procedure'))[:40]}] "
                        f"args={json.dumps(c.get('args'), default=str)[:90]}"
                    )
            print(
                f"{run} {r['task'][:20]} rubric {r.get('rubrics_passed')}/{r.get('rubrics_total')}: {len(stops)} stops"
            )
            for s in stops:
                print("   ", s)


if __name__ == "__main__":
    main()
