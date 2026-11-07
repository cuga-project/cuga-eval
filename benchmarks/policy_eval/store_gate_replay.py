"""Replay the must-not write gate (StoreGate over the raw SOP / policy text, no graph) on saved runs, offline.

Each run's recorded tool calls are fed in order: before an acting call the gate is asked (as in a live run), after
every call the result becomes data the agent read. Nothing is blocked (a replay cannot change the run); the output is
what the gate would have done. Then the flags are compared with the grader:
  - EnterpriseOps-Gym ITSM (--bench eog): policy = the task's system prompt, the user request is the first data read;
    a grounded flag on a write to a table that a failed verifier reads counts as a catch.
  - HANDBOOK (--bench handbook): policy = the task's SOP file (read only, untrusted folder), today = world time.

    ~/dev/cuga-agent-gate/.venv/bin/python -I policy_eval/store_gate_replay.py --bench eog \
        --runs 'enterpriseops_gym/results/g5tA_t2/A_*.json' --gate-model aws/gpt-oss-120b --out policy_eval/store_gate_replay/x.json
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(sys.argv[0]).resolve().parent
BENCH = HERE.parent
EVAL = BENCH.parent
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "enterpriseops_gym"))


def _tables(obj: Any) -> set:
    return {t.lower() for t in re.findall(r"\b(?:FROM|JOIN|UPDATE|INTO)\s+([a-z_]+)", json.dumps(obj), re.I)}


def _tool_hits_table(tool: str, tables: set) -> bool:
    """A write tool touches a table when a word of the tool name is the table's stem (update_incident -> incident)."""
    words = set(re.findall(r"[a-z]+", tool.lower()))
    for t in tables:
        stem = re.sub(r"s$", "", t.split("_")[0])
        if stem and any(w.rstrip("s") == stem for w in words):
            return True
    return False


def eog_context(run: Dict[str, Any]) -> Dict[str, Any]:
    from eog_env import load_task

    task = load_task(run["task_id"])
    return {"sop": task["system_prompt"], "today": "", "pre": [f"user request: {task['user_prompt']}"], "task": task}


def handbook_context(run: Dict[str, Any]) -> Dict[str, Any]:
    sys.path.insert(0, str(BENCH / "handbook"))
    from hb_env import TASKS

    from handbook.sop_text import html_text, largest_sop_file

    sop = largest_sop_file(TASKS / run["task"])
    return {"sop": html_text(sop.read_text(errors="replace")), "today": (run.get("world_time") or "")[:10], "pre": []}


def replay(path: str, bench: str, model: Any) -> Dict[str, Any]:
    from cuga.policy_layer.store_gate import StoreGate

    run = json.loads(Path(path).read_text())
    ctx = eog_context(run) if bench == "eog" else handbook_context(run)
    gate = StoreGate(None, model, today=ctx["today"], sop_text=ctx["sop"])
    gate.reads += ctx["pre"]
    flags: List[Dict[str, Any]] = []
    for i, c in enumerate(run.get("tool_calls") or []):
        tool, args = c.get("tool") or "", c.get("args") or {}
        n = len(gate.records)
        msg = gate.before_tool_call(tool, args)
        if len(gate.records) > n and gate.records[-1].get("breaks"):
            r = dict(gate.records[-1])
            r.update({"i": i, "args": json.dumps(args, default=str)[:600], "would_block": bool(msg)})
            flags.append(r)
        gate.after_tool_call(tool, args, c.get("result") if c.get("result") is not None else c.get("error"))
    out = {
        "run": path,
        "checks": sum(r.get("gate") == "checked" for r in gate.records),
        "errors": sum(r.get("gate") == "error" for r in gate.records),
        "flags": flags,
        "blocks": sum(f["would_block"] for f in flags),
    }
    if bench == "eog":
        task = ctx["task"]
        failed = [
            {"name": v["name"], "tables": sorted(_tables(task["verifiers"][k]))}
            for k, v in enumerate(run.get("verifiers") or [])
            if not v.get("passed")
        ]
        out.update(
            passed=bool(run.get("passed")),
            verifiers=f"{run.get('verifiers_passed')}/{run.get('verifiers_total')}",
            failed=failed,
        )
        for f in flags:
            f["hits_failed_table"] = any(_tool_hits_table(f["tool"], set(v["tables"])) for v in failed)
    else:
        out.update(
            passed=bool(run.get("passed")),
            rubrics=f"{run.get('rubrics_passed')}/{run.get('rubrics_total')}",
            failed=[(r.get("text") or "")[:200] for r in run.get("rubrics") or [] if not r.get("pass")],
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", choices=["eog", "handbook"], required=True)
    ap.add_argument("--runs", nargs="+", required=True, help="glob(s) of result JSON files")
    ap.add_argument("--gate-model", default="aws/gpt-oss-120b")
    ap.add_argument("--out", required=True)
    ap.add_argument("-j", "--jobs", type=int, default=8)
    a = ap.parse_args()

    from dotenv import dotenv_values

    secrets = dotenv_values(EVAL / ".env")
    for k in ("OPENAI_BASE_URL", "OPENAI_API_KEY"):
        if secrets.get(k) and not os.environ.get(k):
            os.environ[k] = secrets[k]
    from cuga.policy_layer.llm import openai_json_model

    import policy_pilot_costs as costs

    model = openai_json_model(a.gate_model, timeout=180, max_tokens=16000 if "gpt-oss" in a.gate_model else 4000)
    paths = sorted({p for g in a.runs for p in glob.glob(g)})
    with ThreadPoolExecutor(a.jobs) as ex:
        results = list(ex.map(lambda p: replay(p, a.bench, model), paths))
    usage = dict(getattr(model, "usage", {}) or {})
    usage["model"] = a.gate_model
    c = costs.record("replay_store_gate", f"{a.bench}:{Path(a.out).stem}", policy=usage)
    failed_runs = [r for r in results if not r["passed"]]
    passed_runs = [r for r in results if r["passed"]]
    summary = {
        "runs": len(results),
        "checks": sum(r["checks"] for r in results),
        "errors": sum(r["errors"] for r in results),
        "flags": sum(len(r["flags"]) for r in results),
        "would_block": sum(r["blocks"] for r in results),
        "failed_runs_with_block": f"{sum(r['blocks'] > 0 for r in failed_runs)}/{len(failed_runs)}",
        "passed_runs_with_block": f"{sum(r['blocks'] > 0 for r in passed_runs)}/{len(passed_runs)}",
        "cost_usd": round(c, 4),
        "gate_model": a.gate_model,
    }
    if a.bench == "eog":
        summary["blocks_on_failed_table"] = sum(
            f["would_block"] and f.get("hits_failed_table") for r in results for f in r["flags"]
        )
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"summary": summary, "runs": results}, indent=1))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
