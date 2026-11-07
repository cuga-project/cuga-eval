#!/usr/bin/env python3
"""Duty replay on finished ITSM runs: which policy duties would still be open at the reply, and do they match a failed verifier.

For each run, the logged tool calls are fed in order to ``RuleSetHooks.after_tool_call`` (built from a build folder),
then the duties still open are read. An open duty "matches" when its required tool names the same record kind as a
failed verifier's table (a word other than "incident", e.g. sla, knowledge, notification). Runs that passed and still
have an open duty are possible false flags. No model calls; verifiers are read only after the replay, to score it.

  ~/dev/cuga-agent-gate/.venv/bin/python -I policy_eval/duty_replay.py --builds policy_eval/builds_v2 [--runs 'results/*/A_*.json']
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
EOG = HERE.parent / "enterpriseops_gym"
VERBS = {
    "create",
    "update",
    "link",
    "add",
    "set",
    "details",
    "new",
    "to",
    "get",
    "find",
    "send",
    "incident",
    "record",
    "by",
}


def words(name: str) -> set:
    return {w for w in re.split(r"[^a-z]+", name.lower()) if w and w not in VERBS}


def tables(verifier: dict) -> set:
    out = set()
    for q in re.findall(r'"query":\s*"(.*?)(?<!\\)"', json.dumps(verifier)):
        out |= {w for t in re.findall(r"\b(?:from|join)\s+([a-z_]+)", q, re.I) for w in words(t)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--builds", required=True)
    ap.add_argument("--runs", default="results/*/A_*.json")
    ap.add_argument("--model", default="DeepSeek")
    a = ap.parse_args()
    from cuga.policy_layer.ruleset import RuleSetHooks

    tasks = {t["task_id"]: t for t in json.loads((EOG / "tasks/itsm_oracle.json").read_text())}
    specs = json.loads((EOG / "tasks/itsm_tools.json").read_text())
    builds = {}
    stats = collections.Counter()
    rows = []
    for f in sorted(glob.glob(str(EOG / a.runs))):
        r = json.loads(Path(f).read_text())
        if a.model not in str(r.get("model")) or r["task_id"] not in tasks:
            continue
        t = tasks[r["task_id"]]
        h = t["_policy_hash"]
        if h not in builds:
            p = Path(a.builds) / f"{h}.json"
            builds[h] = json.loads(p.read_text())["rules"] if p.exists() else None
        if builds[h] is None:
            stats["no build"] += 1
            continue
        hooks = RuleSetHooks(builds[h], specs, tools_in_run=t["selected_tools"], brief=False)
        for c in r.get("tool_calls") or []:
            hooks.after_tool_call(c["tool"], c.get("args") or {}, c.get("result"))
        opened = (
            [d for d in hooks.records if d.get("outcome") == "duty_open"] if hasattr(hooks, "records") else []
        )
        open_end = [duty for _, duty in hooks.open_duties]
        vs = json.loads(t["verifiers"]) if isinstance(t["verifiers"], str) else t["verifiers"]
        failed = [
            (v["name"], tables(vs[i]) if i < len(vs) else set())
            for i, v in enumerate(r.get("verifiers") or [])
            if not v.get("passed")
        ]
        matched = [d for d in open_end if any(words(d["then"]["tool"]) & tb for _, tb in failed)]
        stats["runs"] += 1
        stats["runs passed"] += bool(r.get("passed"))
        stats["duties opened"] += len(opened)
        stats["open at reply"] += len(open_end)
        stats["failed runs with an open duty matching a failed verifier"] += bool(matched) and not r.get(
            "passed"
        )
        stats["passed runs with an open duty (possible false flag)"] += bool(open_end) and bool(
            r.get("passed")
        )
        stats["failed verifiers"] += len(failed)
        stats["failed verifiers matched by an open duty"] += sum(
            1 for _, tb in failed if any(words(d["then"]["tool"]) & tb for d in open_end)
        )
        rows.append(
            {
                "run": f.split("/results/")[1],
                "passed": r.get("passed"),
                "open": [
                    f"{d['trigger']['tool']} -> {d['then']['tool']} {d['then'].get('when') or ''} [{d.get('source', '')}]"
                    for d in open_end
                ],
                "failed": [n for n, _ in failed],
            }
        )
    out = HERE / "duty_replay" / (Path(a.builds).name + ".json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"stats": stats, "rows": rows}, indent=1, default=list))
    for k, v in stats.items():
        print(f"{v:5}  {k}")
    print("detail:", out)


if __name__ == "__main__":
    main()
