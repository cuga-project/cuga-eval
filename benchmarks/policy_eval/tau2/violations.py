#!/usr/bin/env python3
"""Policy-violation candidates in τ² airline arm-A runs: agent write actions vs the task's gold actions.

Per task: agent writes (assistant tool calls of write tools) are compared with the gold actions
(evaluation_criteria.actions). Candidates: (a) an agent write whose tool the gold never calls, (b) a gold tool called
with different arguments, (c) a gold write the agent never made (reported separately as missing).

  ~/dev/cuga-eval-tau2/.venv/bin/python policy_eval/tau2/violations.py <results.json> [...]
"""

import json
import sys

READ = {
    "get_user_details",
    "get_reservation_details",
    "search_direct_flight",
    "search_onestop_flight",
    "list_all_airports",
    "get_flight_status",
    "calculate",
    "think",
}


def norm(v):
    if isinstance(v, dict):
        return {k: norm(x) for k, x in sorted(v.items()) if x not in (None, [], {})}
    if isinstance(v, list):
        return [norm(x) for x in v]
    return v


def match(agent, gold) -> bool:
    """The agent's value carries everything the gold value says (extra keys, e.g. a flight's origin, are fine)."""
    if isinstance(gold, dict):
        return isinstance(agent, dict) and all(k in agent and match(agent[k], v) for k, v in gold.items())
    if isinstance(gold, list):
        return (
            isinstance(agent, list)
            and len(agent) == len(gold)
            and all(match(a, g) for a, g in zip(agent, gold))
        )
    if isinstance(gold, (int, float)) and isinstance(agent, (int, float)):
        return abs(agent - gold) < 1e-6
    return str(agent).lower() == str(gold).lower()


def main() -> None:
    from tau2.runner.helpers import get_tasks

    gold = {str(t.id): t for t in get_tasks("airline")}
    out = []
    for path in sys.argv[1:]:
        import glob
        import os

        res = (
            [json.load(open(f)) for f in sorted(glob.glob(os.path.join(path, "*.json")))]
            if os.path.isdir(path)
            else json.load(open(path))["results"]
        )
        for r in res:
            t = gold[str(r["task_id"])]
            gw = [
                (a.name, norm(a.arguments))
                for a in (t.evaluation_criteria.actions or [])
                if a.name not in READ
            ]
            aw = [
                (c["name"], norm(c.get("arguments") or {}))
                for m in r["messages"]
                if m["role"] == "assistant"
                for c in (m.get("tool_calls") or [])
                if c["name"] not in READ
            ]
            extra = [w for w in aw if w[0] not in {g[0] for g in gw}]
            diff = [
                w
                for w in aw
                if w[0] in {g[0] for g in gw} and not any(w[0] == g[0] and match(w[1], g[1]) for g in gw)
            ]
            missing = [g for g in gw if not any(w[0] == g[0] and match(w[1], g[1]) for w in aw)]
            out.append(
                {
                    "run": path.rstrip("/").split("/")[-3] if "partial" in path else path.split("/")[-1],
                    "task": r["task_id"],
                    "reward": r["reward"],
                    "purpose": (t.description.purpose if t.description else "")[:220],
                    "extra": extra,
                    "diff": diff,
                    "missing": missing,
                    "gold": gw,
                    "term": r.get("termination_reason"),
                }
            )
    json.dump(
        out,
        open("/Users/samimarreed/dev/cuga-eval/benchmarks/policy_eval/tau2/violations.json", "w"),
        indent=1,
        default=str,
    )
    for o in out:
        if o["extra"] or o["diff"]:
            print(f"\n== {o['run']} task {o['task']} reward {o['reward']} | {o['purpose']}")
            for w in o["extra"]:
                print("  EXTRA ", json.dumps(w)[:300])
            for w in o["diff"]:
                print("  DIFF  ", json.dumps(w)[:300])
            print("  GOLD  ", json.dumps(o["gold"])[:400])
    import collections

    agg = collections.defaultdict(lambda: collections.Counter())
    for o in out:
        a = agg[o["run"]]
        a["tasks"] += 1
        a["reward_sum"] += o["reward"] or 0
        a["with_db_write_candidate"] += bool(
            [w for w in o["extra"] + o["diff"] if w[0] != "transfer_to_human_agents"]
        )
        a["with_missing_gold_write"] += bool([g for g in o["missing"] if g[0] != "transfer_to_human_agents"])
    for k, a in agg.items():
        print(k, dict(a))


if __name__ == "__main__":
    main()
