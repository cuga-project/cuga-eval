"""Replay the online policy intake's write checks on a finished AutomationBench run, without the agent.

Rebuilds the task world, re-runs the logged tool calls in order (the log keeps full arguments; results are
cut to 4000 characters, so they are recomputed), feeds them to OnlinePolicyIntake, and asks the write verifier
about each logged write. Policies come from the run's own ``policy_found`` records, so extraction is not re-run.

    .venv/bin/python intake_replay.py pilot2_B operations.fire_extinguisher_inspection_schedule --repeat 3
    .venv/bin/python intake_replay.py pilot2_B operations.fire_extinguisher_inspection_schedule --facts 1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from ab_env import build_world, load_task, toolset_functions  # noqa: E402


def replay(run: str, task_name: str):
    rec = json.loads((HERE / "results" / run / f"{task_name}.json").read_text())
    task = load_task(task_name)
    world, info, _ = build_world(task["info"])
    fns = {f.__name__: f for f in toolset_functions(rec["toolset"], info)}
    user = "\n\n".join(m["content"] for m in task["prompt"] if m["role"] == "user")
    policies = [
        {
            "title": r.get("title"),
            "trust": r.get("trust"),
            "statements": r["statements"],
            "supersedes": r.get("supersedes"),
            "tool": r.get("tool"),
        }
        for r in rec["gate"]
        if r.get("outcome") == "policy_found" and isinstance(r.get("statements"), list)
    ]
    steps = []
    for call in rec["tool_calls"]:
        fn = fns[call["tool"]]
        out = fn(world=world, **call["args"]) if "world" in fn.__code__.co_varnames else fn(**call["args"])
        try:
            out = json.loads(out) if isinstance(out, str) else out
        except ValueError:
            pass
        steps.append((call["tool"], call["args"], out))
    return user, policies, steps


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("task")
    ap.add_argument("--repeat", type=int, default=1, help="verifier calls per write")
    ap.add_argument(
        "--facts", type=int, help="print the facts the verifier sees at write N (1-based) and stop"
    )
    ap.add_argument("--model", default=None)
    ap.add_argument(
        "--old-facts", action="store_true", help="verifier sees the last 8000 characters only (pilot code)"
    )
    ap.add_argument(
        "--reply", action="store_true", help="also run the check before the reply, --repeat times"
    )
    a = ap.parse_args()

    from cuga.policy_layer.builder import openai_json_model
    from cuga.policy_layer.intake import OnlinePolicyIntake

    user, policies, steps = replay(a.run, a.task)
    model = openai_json_model(a.model) if a.facts is None else (lambda s, u: '{"violations": []}')
    hooks = OnlinePolicyIntake(lambda s, u: '{"policies": []}', check_reply=False)
    hooks.on_user_message(user, None)
    hooks.policies = policies
    hooks.model = model
    if a.old_facts:
        hooks._facts_for = lambda args: hooks.facts[-8000:]
    n_write = 0
    for tool, args, out in steps:
        if hooks.is_write(tool):
            n_write += 1
            if a.facts == n_write:
                print(hooks._facts_for(args))
                return
            if a.facts is None:
                outcomes = []
                for _ in range(a.repeat):
                    hooks._denials.clear()
                    hooks.records.clear()
                    hooks.before_tool_call(tool, args)
                    r = hooks.records[-1] if hooks.records else {"outcome": "skip", "violations": []}
                    outcomes.append(r["outcome"])
                    reason = (r["violations"] or [{}])[0].get("reason", "")
                label = args.get("summary") or args.get("to") or ""
                print(f"write {n_write} {tool} [{label}]: {outcomes}  {reason[:160]}")
        hooks.after_tool_call(tool, args, out)
    if a.reply and a.facts is None:
        hooks.check_reply = True
        outcomes = []
        for _ in range(a.repeat):
            hooks._reply_checked = False
            hooks.records.clear()
            hooks.before_reply("")
            r = hooks.records[-1] if hooks.records else {"outcome": "skip", "missing": []}
            outcomes.append(r["outcome"])
            missing = (r.get("missing") or [{}])[0].get("action", "")
        print(f"before_reply: {outcomes}  {missing[:200]}")
    if a.facts is None:
        usage = getattr(model, "usage", {})
        print("usage:", json.dumps(usage))
        sys.path.insert(0, str(HERE.parent))
        import policy_pilot_costs as costs

        costs.record(
            "replay",
            f"{a.run}/{a.task}" + (" old-facts" if a.old_facts else ""),
            policy={**usage, "model": getattr(model, "model_name", None)},
        )
        print(costs.line())


if __name__ == "__main__":
    main()
