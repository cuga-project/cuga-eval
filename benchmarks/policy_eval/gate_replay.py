#!/usr/bin/env python3
"""Phase 2 of the requirements-tracker test: would the completion gate have flagged what the grader failed?

For every finished arm-A run (DeepSeek agent): compile the checklist from the request, the policy and the data that
run read (``requirements.compile_requirements``); give the gate that run's successful writes
(``requirements.gate``); then (graders read only now) a judge maps grader checks to checklist items. Per grader check:
- caught: the check failed in this run and an item covering it was flagged missing or wrong;
- false flag: the check passed and an item covering it was flagged.
Per run: a follow-up would be sent when any item is flagged; on runs that passed that is a needless follow-up.

  PYTHONPATH=~/dev/cuga-agent-gate/src automationbench/.venv/bin/python policy_eval/gate_replay.py --bench ab,eog
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BENCH))
import checklist_recall as cr  # noqa: E402

OUT = HERE / "gate_replay"


def ab_params(a: dict) -> dict:
    """Task files keep assertion parameters at the top level; result files put them under "params"."""
    return (
        a.get("params")
        if isinstance(a.get("params"), dict)
        else {k: v for k, v in a.items() if k not in ("type", "negative")}
    )


def ab_neg(a: dict) -> bool:
    import re as _re

    return bool(a.get("negative")) or bool(_re.search(r"(^|_)not(_|$)|_no_", str(a.get("type"))))


def ab_runs():
    sys.path.insert(0, str(BENCH / "automationbench"))
    import ab_env as runner  # noqa: E402
    from cuga.policy_layer.ruleset import is_write_tool

    found = collections.defaultdict(dict)
    for f in glob.glob(str(BENCH / "automationbench/results/*_[BC]_t*/*.json")):
        r = json.loads(Path(f).read_text())
        for x in r.get("gate") or []:
            if isinstance(x, dict) and x.get("outcome") == "policy_found" and x.get("trust") == "trusted":
                found[r["task"]][x.get("title") or ""] = x.get("statements") or []
    tasks = {}
    for f in sorted(glob.glob(str(BENCH / "automationbench/results/*_A_t*/*.json"))):
        r = json.loads(Path(f).read_text())
        if "DeepSeek" not in str(r.get("model")):
            continue
        if r["task"] not in tasks:
            t = runner.load_task(r["task"])
            info = t["info"] if isinstance(t["info"], dict) else json.loads(t["info"])
            tasks[r["task"]] = (t, info.get("assertions") or [])
        t, asserts = tasks[r["task"]]
        failed = [
            any(
                x.get("type") == a.get("type") and x.get("params") == ab_params(a)
                for x in r.get("failed") or []
            )
            for a in asserts
        ]
        pol = "\n\n".join(f"{k}:\n" + "\n".join(f"- {s}" for s in st) for k, st in found[r["task"]].items())
        writes = [
            c for c in r.get("tool_calls") or [] if is_write_tool(c["tool"]) and not _err(c.get("result"))
        ]
        yield {
            "bench": "ab",
            "run": f.split("/results/")[1],
            "request": "\n\n".join(m["content"] for m in t["prompt"] if m["role"] == "user"),
            "policy": pol,
            "data": cr.read_data(r),
            "writes": writes,
            "passed": bool(r.get("pass")),
            "checks": [
                ("MUST NOT: " if ab_neg(a) else "") + f"{a.get('type')} {json.dumps(ab_params(a))}"
                for a in asserts
            ],
            "failed": failed,
        }


def eog_runs():
    import re

    from cuga.policy_layer.ruleset import is_write_tool

    eog = BENCH / "enterpriseops_gym"
    tasks = {t["task_id"]: t for t in json.loads((eog / "tasks/itsm_oracle.json").read_text())}
    for f in sorted(glob.glob(str(eog / "results/*/A_*.json"))):
        r = json.loads(Path(f).read_text())
        if "DeepSeek" not in str(r.get("model")) or r["task_id"] not in tasks:
            continue
        t = tasks[r["task_id"]]
        vs = json.loads(t["verifiers"]) if isinstance(t["verifiers"], str) else t["verifiers"]
        checks = [
            f"{v.get('name') or ''}: "
            + " ".join(re.findall(r'"query":\s*"(.*?)(?<!\\)"', json.dumps(v)))[:400]
            for v in vs
        ]
        failed = [
            i < len(r.get("verifiers") or []) and not r["verifiers"][i].get("passed") for i in range(len(vs))
        ]
        writes = [
            c for c in r.get("tool_calls") or [] if is_write_tool(c["tool"]) and not _err(c.get("result"))
        ]
        yield {
            "bench": "eog",
            "run": f.split("/results/")[1],
            "request": t["user_prompt"],
            "policy": t["system_prompt"],
            "data": cr.read_data(r),
            "writes": writes,
            "passed": bool(r.get("passed")),
            "checks": checks,
            "failed": failed,
        }


def _err(res) -> bool:
    if isinstance(res, str):
        try:
            res = json.loads(res)
        except ValueError:
            return res.lower().startswith("error")
    return isinstance(res, dict) and ("error" in res or res.get("success") is False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default="ab,eog")
    ap.add_argument("--compiler", default="aws/gpt-oss-120b")
    ap.add_argument("--judge", default="azure/DeepSeek-V4-Pro")
    ap.add_argument("--limit", type=int, default=0, help="runs per benchmark (0 = all)")
    ap.add_argument("--gate-model", default="", help="model for the gate (default: the compiler)")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    try:
        from dotenv import dotenv_values

        for k, v in dotenv_values(BENCH.parent / ".env").items():
            if k in ("OPENAI_API_KEY", "OPENAI_BASE_URL") and v and k not in os.environ:
                os.environ[k] = v
    except ImportError:
        pass
    import policy_pilot_costs as costs
    from cuga.policy_layer.llm import openai_json_model, parse_json
    from cuga.policy_layer.requirements import compile_requirements, gate, render

    OUT.mkdir(exist_ok=True)
    comp_base = openai_json_model(a.compiler, timeout=400, max_tokens=16000)
    judge_base = openai_json_model(a.judge, timeout=400)
    comp, judge = (
        cr.Cached(comp_base, OUT / "compile_cache.json"),
        cr.Cached(judge_base, OUT / "judge_cache.json"),
    )
    gate_base = openai_json_model(a.gate_model, timeout=400, max_tokens=16000) if a.gate_model else comp_base
    gate_m = cr.Cached(gate_base, OUT / "gate_cache.json")
    runs = []
    for b in a.bench.split(","):
        rs = list({"ab": ab_runs, "eog": eog_runs}[b]())
        runs += rs[: a.limit] if a.limit else rs

    def one(r):
        try:
            cl = compile_requirements(comp, r["request"], r["policy"], data=r["data"])
            st = gate(
                gate_m,
                cl["items"],
                [{"tool": w["tool"], "args": w.get("args"), "result": w.get("result")} for w in r["writes"]],
            )
            checks = "\n".join(f"{i}. {c}" for i, c in enumerate(r["checks"], 1))
            j = parse_json(
                judge(
                    cr.JUDGE_SYSTEM,
                    cr.JUDGE_USER.format(checklist=render(cl["items"]) or "(empty)", checks=checks),
                )
            )
        except Exception as e:  # noqa: BLE001
            return {"bench": r["bench"], "run": r["run"], "error": str(e)[:200]}
        cover = {c.get("n"): c for c in j.get("checks") or [] if isinstance(c, dict)}
        flagged = {i for i, s in st.items() if s["status"] in ("missing", "wrong")}
        per = []
        for n, fail in enumerate(r["failed"], 1):
            c = cover.get(n) or {}
            items = (
                [x for x in c.get("items") or [] if isinstance(x, str)]
                if c.get("cover") in ("full", "partial")
                else []
            )
            per.append({"failed": fail, "covered": bool(items), "flagged": bool(set(items) & flagged)})
        return {
            "bench": r["bench"],
            "run": r["run"],
            "passed": r["passed"],
            "items": len(cl["items"]),
            "flagged": sorted(flagged),
            "status": st,
            "per_check": per,
            "checklist": cl["items"],
        }

    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(one, runs))
    (OUT / f"rows{('_' + a.tag) if a.tag else ''}.json").write_text(json.dumps(rows, indent=1))
    for b in a.bench.split(","):
        rr = [r for r in rows if r["bench"] == b and not r.get("error")]
        pc = [p for r in rr for p in r["per_check"]]
        fails = [p for p in pc if p["failed"]]
        oks = [p for p in pc if not p["failed"]]
        passed = [r for r in rr if r["passed"]]
        failed_runs = [r for r in rr if not r["passed"]]
        print(
            f"\n{b}: {len(rr)} runs ({len(passed)} passed), {sum(r['items'] for r in rr) / max(1, len(rr)):.1f} items/run, "
            f"errors {sum(1 for r in rows if r['bench'] == b and r.get('error'))}"
        )
        print(
            f"  failed grader checks {len(fails)}: covered {sum(p['covered'] for p in fails)}, caught (covered and flagged) "
            f"{sum(p['flagged'] for p in fails)} ({100 * sum(p['flagged'] for p in fails) / max(1, len(fails)):.0f}%)"
        )
        print(
            f"  passed grader checks {len(oks)}: wrongly flagged {sum(p['flagged'] for p in oks)} "
            f"({100 * sum(p['flagged'] for p in oks) / max(1, len(oks)):.0f}%)"
        )
        print(
            f"  follow-up sent: failed runs {sum(bool(r['flagged']) for r in failed_runs)}/{len(failed_runs)}, "
            f"passed runs {sum(bool(r['flagged']) for r in passed)}/{len(passed)}"
        )
    costs.record(
        "gate_replay", a.bench, policy={**dict(getattr(comp_base, "usage", {}) or {}), "model": a.compiler}
    )
    costs.record(
        "gate_replay_judge",
        a.bench,
        policy={**dict(getattr(judge_base, "usage", {}) or {}), "model": a.judge},
    )
    if a.gate_model:
        costs.record(
            "gate_replay_gate",
            a.bench,
            policy={**dict(getattr(gate_base, "usage", {}) or {}), "model": a.gate_model},
        )
    print(costs.line())


if __name__ == "__main__":
    main()
