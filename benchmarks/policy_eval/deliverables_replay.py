#!/usr/bin/env python3
"""Deliverables replay: what ``DeliverablesHooks`` would flag on finished arm-A runs, scored against the graders.

Per run: the request goes to ``on_user_message`` (one model call per distinct request, cached), the logged calls go
through ``before_tool_call`` (enum-word check) and ``after_tool_call`` in order, then ``missing()`` gives the
deliverables the reply check would name. Graders are read only afterwards, to score:
- a flag "matches" when one of its targets or values appears in a failed check (ITSM verifier SQL, AutomationBench
  assertion params);
- flags on runs that passed are possible false flags.

  ITSM:  PYTHONPATH=~/dev/cuga-agent-gate/src ~/dev/cuga-agent-gate/.venv/bin/python -I policy_eval/deliverables_replay.py --bench eog
  AB:    PYTHONPATH=~/dev/cuga-agent-gate/src automationbench/.venv/bin/python -I policy_eval/deliverables_replay.py --bench ab
"""

from __future__ import annotations

import argparse
import collections
import glob
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
OUT = HERE / "deliverables_replay"
sys.path.insert(0, str(BENCH))


class CachedModel:
    def __init__(self, model, path: Path):
        self.model, self.path = model, path
        self.cache = json.loads(path.read_text()) if path.exists() else {}
        self.usage = getattr(model, "usage", {})

    def __call__(self, system: str, user: str) -> str:
        k = hashlib.sha256((system + "\n" + user).encode()).hexdigest()[:24]
        if k not in self.cache:
            self.cache[k] = self.model(system, user)
            self.path.write_text(json.dumps(self.cache))
        return self.cache[k]


def eog_runs(model_filter: str):
    eog = BENCH / "enterpriseops_gym"
    tasks = {t["task_id"]: t for t in json.loads((eog / "tasks/itsm_oracle.json").read_text())}
    specs = json.loads((eog / "tasks/itsm_tools.json").read_text())
    for f in sorted(glob.glob(str(eog / "results/*/A_*.json"))):
        r = json.loads(Path(f).read_text())
        if model_filter not in str(r.get("model")) or r["task_id"] not in tasks:
            continue
        t = tasks[r["task_id"]]
        failed = [
            json.dumps(
                json.loads(t["verifiers"])[i] if isinstance(t["verifiers"], str) else t["verifiers"][i]
            ).lower()
            for i, v in enumerate(r.get("verifiers") or [])
            if not v.get("passed")
        ]
        yield f, t["user_prompt"], specs, r.get("tool_calls") or [], bool(r.get("passed")), failed


def ab_runs(model_filter: str):
    sys.path.insert(0, str(BENCH / "automationbench"))
    import ab_env as runner  # noqa: E402

    for f in sorted(glob.glob(str(BENCH / "automationbench/results/*_A_t*/*.json"))):
        r = json.loads(Path(f).read_text())
        if model_filter not in str(r.get("model")):
            continue
        task = runner.load_task(r["task"])
        world, info, _ = runner.build_world(task["info"])
        tools = [runner.make_tool(fn, world, []) for fn in runner.toolset_functions(r["toolset"], info)]
        specs = [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.args_schema.model_json_schema() if t.args_schema else {},
            }
            for t in tools
        ]
        request = "\n\n".join(m["content"] for m in task["prompt"] if m["role"] == "user")
        failed = [json.dumps(a).lower() for a in r.get("failed") or [] if not a.get("negative")]
        yield f, request, specs, r.get("tool_calls") or [], bool(r.get("pass")), failed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", choices=["eog", "ab"], required=True)
    ap.add_argument("--model-filter", default="DeepSeek")
    ap.add_argument("--policy-model", default=os.environ.get("POLICY_MODEL_NAME", "aws/gpt-oss-120b"))
    a = ap.parse_args()
    import policy_pilot_costs as costs
    from cuga.policy_layer.deliverables import DeliverablesHooks
    from cuga.policy_layer.llm import openai_json_model
    from cuga.policy_layer.ruleset import canon

    try:  # secrets as build_rules.py loads them (cuga-eval/.env); never printed
        from dotenv import dotenv_values

        for k, v in dotenv_values(BENCH.parent / ".env").items():
            if k in ("OPENAI_API_KEY", "OPENAI_BASE_URL") and v and k not in os.environ:
                os.environ[k] = v
    except ImportError:
        pass
    OUT.mkdir(exist_ok=True)
    base = openai_json_model(a.policy_model)
    model = CachedModel(base, OUT / "cache.json")
    st = collections.Counter()
    rows = []
    for f, request, specs, calls, passed, failed in (eog_runs if a.bench == "eog" else ab_runs)(
        a.model_filter
    ):
        h = DeliverablesHooks(model, specs)
        h.on_user_message(request, None)
        for c in calls:
            h.before_tool_call(c["tool"], c.get("args") or {})
            h.after_tool_call(c["tool"], c.get("args") or {}, c.get("result"))
        gaps = h.missing()
        enums = [x for x in h.records if x.get("rule") == "request_value"]

        def hit(strings):
            return any(canon(s).lower() in fc for s in strings for fc in failed)

        def app(g):  # the tool's app (gmail, slack, zendesk): matches a failed check of that app
            return [g["tool"].split("_")[0] + "_"] if a.bench == "ab" else []

        gap_hits = [g for g in gaps if hit(g["targets"] + g["values"] + list(g["args"].values()) + app(g))]
        enum_hits = [e for e in enums if hit([e["want"]])]
        st["runs"] += 1
        st["runs passed"] += passed
        st["runs with deliverables"] += bool(h.items)
        st["deliverables listed"] += len(h.items)
        st["failed runs flagged (gap or enum)"] += (not passed) and bool(gaps or enums)
        st["failed runs with a flag matching a failed check"] += (not passed) and bool(gap_hits or enum_hits)
        st["passed runs flagged (possible false flag)"] += passed and bool(gaps or enums)
        st["gaps"] += len(gaps)
        st["gaps matching a failed check"] += len(gap_hits)
        st["enum reminds"] += len(enums)
        st["enum reminds matching a failed check"] += len(enum_hits)
        st["failed checks"] += len(failed)
        st["failed checks matched"] += sum(
            1
            for fc in failed
            if any(
                canon(s).lower() in fc
                for g in gaps
                for s in g["targets"] + g["values"] + list(g["args"].values())
            )
            or any(canon(e["want"]).lower() in fc for e in enums)
        )
        rows.append(
            {"run": f.split("/results/")[1], "passed": passed, "items": h.items, "gaps": gaps, "enums": enums}
        )
    (OUT / f"{a.bench}.json").write_text(json.dumps({"stats": st, "rows": rows}, indent=1))
    costs.record(
        "deliverables_replay",
        a.bench,
        policy={**dict(getattr(base, "usage", {}) or {}), "model": a.policy_model},
    )
    for k, v in st.items():
        print(f"{v:5}  {k}")
    print(costs.line())


if __name__ == "__main__":
    main()
