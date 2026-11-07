#!/usr/bin/env python3
"""Shadow replay: what the policy layer would decide on every write of a finished arm-A AutomationBench run.

For each task: rebuild the world, re-run the logged tool calls in order with their logged arguments, and before each
write ask the layer (OnlinePolicyIntake, built as arm B builds it) for its decision. The call then runs anyway, as it
did in arm A. A write is labelled ``violating`` when it makes a guardrail (negative assertion) newly fail, else
``clean``. This measures the layer on identical calls, without the agent's path changing.

Before each write, pending policy extraction is drained fully (the agent's thinking time in a real run), so the catch
rate is an upper bound for the timing.

  CUGA_ENV_FILE=cuga.gptoss.env PYTHONPATH=~/dev/cuga-agent-gate/src automationbench/.venv/bin/python \
      policy_eval/shadow_replay.py oss2_A_t1 [--tasks a,b] [-j 3]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
AB = HERE.parent / "automationbench"
sys.path.insert(0, str(AB))
sys.path.insert(0, str(HERE.parent))

import run_cuga as runner  # noqa: E402

OUT = HERE / "shadow"
DECISIONS = {"deny", "allow", "remind", "allow_after_cap"}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _failed_negatives(world, info, initial) -> set:
    res = runner.score(world, info, initial)
    return {json.dumps(f, sort_keys=True, default=str) for f in res["failed"] if f["negative"]}


def _layer(tools, today=None):
    from cuga.policy_layer.builder import openai_json_model
    from cuga.policy_layer.intake import OnlinePolicyIntake

    specs = [
        {
            "name": t.name,
            "description": t.description or "",
            "inputSchema": t.args_schema.model_json_schema() if t.args_schema else {},
        }
        for t in tools
    ]
    detector = None
    if os.environ.get("POLICY_DETECTOR", "kev") == "kev" and os.environ.get("OPENROUTER_API_KEY"):
        from cuga.policy_layer.detectors import systemone_detector

        detector = systemone_detector()
    choice = os.environ.get("POLICY_METHOD_CHOICE")
    return OnlinePolicyIntake(
        openai_json_model(os.environ.get("POLICY_MODEL_NAME") or os.environ["MODEL_NAME"]),
        detector=detector,
        tool_specs=specs,
        check_reply=False,
        method_choice=json.loads(Path(choice).read_text()) if choice else None,
        guard_code=os.environ.get("POLICY_GUARD_CODE", "remind"),
        today=today,
    )


def replay_task(run: str, name: str) -> Dict[str, Any]:
    rec = json.loads((AB / "results" / run / f"{name}.json").read_text())
    task = runner.load_task(name)
    world, info, initial = runner.build_world(task["info"])
    fns = {f.__name__: f for f in runner.toolset_functions(rec["toolset"], info)}
    tools = [runner.make_tool(f, world, []) for f in fns.values()]
    hooks = _layer(tools, today=str(rec.get("world_time") or "")[:10] or None)
    hooks.on_user_message("\n\n".join(m["content"] for m in task["prompt"] if m["role"] == "user"), None)
    failed = _failed_negatives(world, info, initial)
    writes: List[Dict[str, Any]] = []
    mismatches = 0
    for i, call in enumerate(rec["tool_calls"]):
        tool, args = call["tool"], call["args"]
        decision = None
        if hooks.is_write(tool):
            hooks._drain(120)
            n = len(hooks.records)
            res = hooks.before_tool_call(tool, args)
            new = [
                r for r in hooks.records[n:] if r.get("outcome") in DECISIONS
            ]  # not async extraction records
            outcomes = [r["outcome"] for r in new]
            decision = next(
                (d for d in ("deny", "allow_after_cap", "remind", "allow") if d in outcomes),
                "message" if res.message else "no_check",
            )
            rules = sorted(
                {
                    r.get("rule") or r.get("type") or "verifier"
                    for r in new
                    if r["outcome"] in ("deny", "remind")
                }
            )
            reasons = [str(v.get("reason", ""))[:200] for r in new for v in r.get("violations") or []]
        fn = fns[tool]
        try:  # as the runner's tool wrapper: a tool error is returned, not raised
            out = fn(world=world, **args) if "world" in fn.__code__.co_varnames else fn(**args)
        except Exception as exc:  # noqa: BLE001
            out = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        if (
            UUID.sub("", str(out))[:300] != UUID.sub("", str(call["result"]))[:300]
        ):  # invocation ids are random
            mismatches += 1
        if decision is not None:
            now = _failed_negatives(world, info, initial)
            broke = sorted(now - failed)
            failed = now
            writes.append(
                {
                    "i": i,
                    "tool": tool,
                    "args": json.dumps(args, default=str)[:300],
                    "decision": decision,
                    "label": "violating" if broke else "clean",
                    "broke": broke,
                    "reasons": reasons,
                    "rules": rules,
                    "policies": len(hooks.policies),
                    "statements": len(hooks._statements(True)),
                }
            )
        hooks.after_tool_call(tool, args, out)
    hooks._drain(120)
    usage = {**dict(getattr(hooks.model, "usage", {}) or {}), "model": getattr(hooks.model, "model_name", None)}
    return {
        "task": name,
        "run": run,
        "writes": writes,
        "result_mismatches": mismatches,
        "final_guard_broken": rec.get("guard_broken"),
        "policies": len(hooks.policies),
        "policy_titles": [p.get("title") for p in hooks.policies],
        "usage": usage,
        "statements": [
            {"title": p.get("title"), "tool": p.get("tool"), "statements": p.get("statements")}
            for p in hooks.policies
        ],
        "compiled": [
            {k: v for k, v in r.items() if k != "statement_text"}
            for r in (hooks.enforcer.rules if hooks.enforcer is not None else [])
        ],
        "detector_usage": dict(getattr(hooks.detector, "usage", {}) or {}) if hooks.detector else {},
        "guard_log": hooks.guard.log[-20:],
        "guard_codes": [
            {"statement": k[0], "tool": k[1], "code": (v or {}).get("code")}
            for k, v in hooks.guard.cache.items()
            if v
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--tasks")
    ap.add_argument("-j", "--jobs", type=int, default=3)
    a = ap.parse_args()
    os.environ.update({k: v for k, v in runner.child_env(None).items() if k not in os.environ})
    names = a.tasks.split(",") if a.tasks else sorted(p.stem for p in (AB / "results" / a.run).glob("*.json"))
    OUT.mkdir(exist_ok=True)
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        results = list(pool.map(lambda n: replay_task(a.run, n), names))
    (OUT / f"{a.run}.json").write_text(json.dumps(results, indent=1))
    import policy_pilot_costs as costs

    for r in results:
        costs.record("shadow_replay", f"{a.run}/{r['task']}", policy=r["usage"])
    rows = [w for r in results for w in r["writes"]]
    for label in ("violating", "clean"):
        sub = [w for w in rows if w["label"] == label]
        counts = {d: sum(w["decision"] == d for w in sub) for d in sorted({w["decision"] for w in sub})}
        print(f"{label:9} writes {len(sub):3}  {counts}")
    print(
        f"tasks {len(results)}  result mismatches {sum(r['result_mismatches'] for r in results)}  "
        f"{time.monotonic() - t0:.0f}s  {costs.line()}"
    )


if __name__ == "__main__":
    main()
