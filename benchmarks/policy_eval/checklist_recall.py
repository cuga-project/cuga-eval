#!/usr/bin/env python3
"""Phase 1 of the requirements-tracker test: does a checklist compiled from the request and the policy predict
what the grader checks?

Per task: ``requirements.compile_requirements`` (policy-layer model) makes the checklist without seeing any grader.
Then a judge model (different, stronger) maps each grader check to checklist items: full / partial / none.
Reported per benchmark and policy source:
- recall over all grader checks, and over the checks arm A failed (the upside for the agent);
- checklist items no grader check relates to (an upper bound on invented work: graders do not check everything).

Policy sources: AB "request" (request only) and "found" (request + policies the layer found in the data in arm-B
runs of the same task); ITSM "request" and "policy" (+ the system-prompt policy); HANDBOOK "policy" (+ system prompt
and the SOP file, HTML as text).

  PYTHONPATH=~/dev/cuga-agent-gate/src automationbench/.venv/bin/python policy_eval/checklist_recall.py [--bench ab,eog,hb]
"""

from __future__ import annotations

import argparse
import collections
import glob
import hashlib
import html
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
OUT = HERE / "checklist_recall"
HB = Path.home() / "dev/untrusted/handbook-sample/tasks"
sys.path.insert(0, str(BENCH))

JUDGE_SYSTEM = (
    "You compare a predicted checklist with the checks a grader runs on the finished work. Output JSON only."
)
JUDGE_USER = """Predicted checklist:
{checklist}

Grader checks:
{checks}

For each grader check, say whether the checklist covers it:
- "full": an item requires the same effect (or prohibition) with the same key values (recipient, record, field value,
  text, format, count);
- "partial": an item requires the same effect but misses or differs in a key value;
- "none": no item requires it.
Then list the checklist items that no grader check relates to.
Return {{"checks": [{{"n": <number>, "cover": "full|partial|none", "items": ["R1"]}}], "unrelated": ["R7"]}}"""


class Cached:
    def __init__(self, model, path: Path):
        self.model, self.path = model, path
        self.cache = json.loads(path.read_text()) if path.exists() else {}

    def __call__(self, system: str, user: str) -> str:
        k = hashlib.sha256(
            (str(getattr(self.model, "model_name", "")) + "\n" + system + "\n" + user).encode()
        ).hexdigest()[:24]
        if k not in self.cache:
            self.cache[k] = self.model(system, user)
            self.path.write_text(json.dumps(self.cache))
        return self.cache[k]


def html_text(path: Path) -> str:
    raw = path.read_text(errors="replace")
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", raw)
    return re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def read_data(run: dict, limit: int = 60_000) -> str:
    """What the agent read in one arm-A run: results of its non-write calls, in order."""
    from cuga.policy_layer.ruleset import is_write_tool

    parts = []
    for c in run.get("tool_calls") or []:
        if is_write_tool(c["tool"]):
            continue
        res = c.get("result")
        parts.append(
            f"{c['tool']}({json.dumps(c.get('args') or {}, default=str)[:200]}) -> "
            + (res if isinstance(res, str) else json.dumps(res, default=str))[:3000]
        )
    return "\n".join(parts)[:limit]


def hb_data(d: Path, limit: int = 60_000) -> str:
    """A HANDBOOK task's starting data (what a careful agent can read): services state and workspace sheets."""
    parts = []
    for f in sorted((d / "environment/initial_external_services").rglob("*.json")):
        parts.append(f"## {f.parent.name}/{f.name}\n{f.read_text(errors='replace')[:15000]}")
    try:
        import openpyxl

        for f in sorted((d / "environment/initial_workspace").glob("*.xlsx")):
            wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
            for ws in wb.worksheets:
                rows = [
                    "\t".join("" if v is None else str(v) for v in r)
                    for r in ws.iter_rows(values_only=True, max_row=200)
                ]
                parts.append(f"## {f.name} / {ws.title}\n" + "\n".join(rows))
    except ImportError:
        pass
    parts.append(
        "## workspace files: "
        + ", ".join(p.name for p in sorted((d / "environment/initial_workspace").iterdir()))
    )
    return "\n\n".join(parts)[:limit]


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


def ab_tasks():
    sys.path.insert(0, str(BENCH / "automationbench"))
    import ab_env as runner  # noqa: E402

    runs = collections.defaultdict(list)
    for f in glob.glob(str(BENCH / "automationbench/results/*_A_t*/*.json")):
        r = json.loads(Path(f).read_text())
        if "DeepSeek" in str(r.get("model")):
            runs[r["task"]].append(r)
    found = collections.defaultdict(dict)
    for f in glob.glob(str(BENCH / "automationbench/results/*_[BC]_t*/*.json")):
        r = json.loads(Path(f).read_text())
        for x in r.get("gate") or []:
            if isinstance(x, dict) and x.get("outcome") == "policy_found" and x.get("trust") == "trusted":
                found[r["task"]][x.get("title") or ""] = x.get("statements") or []
    for name, rs in sorted(runs.items()):
        task = runner.load_task(name)
        info = task["info"] if isinstance(task["info"], dict) else json.loads(task["info"])
        asserts = info.get("assertions") or []
        checks = [
            ("MUST NOT: " if ab_neg(a) else "") + f"{a.get('type')} {json.dumps(ab_params(a))}"
            for a in asserts
        ]
        fail = [
            sum(
                1
                for r in rs
                for x in r.get("failed") or []
                if x.get("type") == a.get("type") and x.get("params") == ab_params(a)
            )
            / len(rs)
            for a in asserts
        ]
        request = "\n\n".join(m["content"] for m in task["prompt"] if m["role"] == "user")
        pol = "\n\n".join(f"{t}:\n" + "\n".join(f"- {s}" for s in st) for t, st in found[name].items())
        yield {
            "bench": "ab",
            "task": name,
            "request": request,
            "policies": {"request": "", "found": pol},
            "data": {"found+data": (pol, read_data(rs[0]))},
            "checks": checks,
            "fail": fail,
        }


def eog_tasks():
    eog = BENCH / "enterpriseops_gym"
    tasks = {t["task_id"]: t for t in json.loads((eog / "tasks/itsm_oracle.json").read_text())}
    runs = collections.defaultdict(list)
    for f in glob.glob(str(eog / "results/*/A_*.json")):
        r = json.loads(Path(f).read_text())
        if "DeepSeek" in str(r.get("model")) and r["task_id"] in tasks:
            runs[r["task_id"]].append(r)
    for tid, rs in sorted(runs.items()):
        t = tasks[tid]
        vs = json.loads(t["verifiers"]) if isinstance(t["verifiers"], str) else t["verifiers"]
        checks = []
        for v in vs:
            q = " ".join(re.findall(r'"query":\s*"(.*?)(?<!\\)"', json.dumps(v)))[:400]
            checks.append(f"{v.get('name') or v.get('verifier_name') or ''}: {q}")
        fail = [
            sum(1 for r in rs if i < len(r.get("verifiers") or []) and not r["verifiers"][i].get("passed"))
            / len(rs)
            for i in range(len(vs))
        ]
        yield {
            "bench": "eog",
            "task": tid[-8:],
            "request": t["user_prompt"],
            "policies": {"request": "", "policy": t["system_prompt"]},
            "data": {"policy+data": (t["system_prompt"], read_data(rs[0]))},
            "checks": checks,
            "fail": fail,
        }


def hb_tasks():
    for d in sorted(p for p in HB.iterdir() if p.is_dir()):
        sop = next(iter(sorted((d / "environment/initial_workspace").glob("SOP*"))), None)
        policy = (d / "system_prompt.md").read_text() + "\n\n" + (html_text(sop) if sop else "")
        rub = json.loads((d / "tests/rubrics.json").read_text())
        rub = rub if isinstance(rub, list) else next(iter(rub.values()))
        yield {
            "bench": "hb",
            "task": d.name,
            "request": (d / "instruction.md").read_text(),
            "policies": {"policy": policy},
            "data": {"policy+data": (policy, hb_data(d))},
            "checks": [x["rubric_text"] for x in rub],
            "fail": [None] * len(rub),
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default="ab,eog,hb")
    ap.add_argument("--compiler", default="aws/gpt-oss-120b")
    ap.add_argument("--judge", default="azure/DeepSeek-V4-Pro")
    ap.add_argument("--tag", default="", help="suffix for the rows file")
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
    from cuga.policy_layer.requirements import compile_requirements, render

    OUT.mkdir(exist_ok=True)
    comp_base, judge_base = (
        openai_json_model(a.compiler, timeout=400, max_tokens=16000),
        openai_json_model(a.judge, timeout=300),
    )
    comp, judge = Cached(comp_base, OUT / "compile_cache.json"), Cached(judge_base, OUT / "judge_cache.json")
    gens = {"ab": ab_tasks, "eog": eog_tasks, "hb": hb_tasks}
    jobs = [
        (t, src)
        for b in a.bench.split(",")
        for t in gens[b]()
        for src in list(t["policies"]) + list(t.get("data") or {})
    ]

    def one(job):
        t, src = job
        try:
            pol, data = t["data"][src] if src in (t.get("data") or {}) else (t["policies"][src], "")
            cl = compile_requirements(comp, t["request"], pol, data=data)
        except Exception as e:  # noqa: BLE001
            return {"bench": t["bench"], "task": t["task"], "source": src, "error": f"compile: {e}"}
        checks = "\n".join(f"{i}. {c}" for i, c in enumerate(t["checks"], 1))
        try:
            j = parse_json(
                judge(
                    JUDGE_SYSTEM, JUDGE_USER.format(checklist=render(cl["items"]) or "(empty)", checks=checks)
                )
            )
        except Exception as e:  # noqa: BLE001
            return {
                "bench": t["bench"],
                "task": t["task"],
                "source": src,
                "error": f"judge: {e}",
                "items": cl["items"],
            }
        cover = {c.get("n"): c.get("cover", "none") for c in j.get("checks") or [] if isinstance(c, dict)}
        return {
            "bench": t["bench"],
            "task": t["task"],
            "source": src,
            "items": cl["items"],
            "dropped": len(cl["dropped"]),
            "raw": cl["raw"],
            "cover": [cover.get(i, "none") for i in range(1, len(t["checks"]) + 1)],
            "fail": t["fail"],
            "unrelated": [u for u in j.get("unrelated") or [] if isinstance(u, str)],
            "checks": t["checks"],
        }

    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(one, jobs))
    (OUT / f"rows{('_' + a.tag) if a.tag else ''}.json").write_text(json.dumps(rows, indent=1))
    agg = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        k = (r["bench"], r["source"])
        if r.get("error"):
            agg[k]["errors"] += 1
            continue
        c = agg[k]
        c["tasks"] += 1
        c["items"] += len(r["items"])
        c["dropped"] += r["dropped"]
        c["unrelated"] += len(r["unrelated"])
        for cov, f in zip(r["cover"], r["fail"]):
            c["checks"] += 1
            c[cov] += 1
            if f:
                c["failed_w"] += f
                c[f"failed_{cov}_w"] += f
    print(
        f"{'bench':5} {'source':8} {'tasks':>5} {'items/task':>10} {'unrelated':>9} {'checks':>6} {'full':>6} {'partial':>7} "
        f"{'failed checks (run-weighted)':>28}"
    )
    for (b, s), c in sorted(agg.items()):
        n = max(1, c["checks"])
        fw = c["failed_w"]
        failed = (
            f"{fw:5.1f}: full {100 * c['failed_full_w'] / fw:4.0f}% partial {100 * c['failed_partial_w'] / fw:4.0f}%"
            if fw
            else "—"
        )
        print(
            f"{b:5} {s:8} {c['tasks']:5} {c['items'] / max(1, c['tasks']):10.1f} {100 * c['unrelated'] / max(1, c['items']):8.0f}% "
            f"{c['checks']:6} {100 * c['full'] / n:5.0f}% {100 * c['partial'] / n:6.0f}%  {failed}"
            + (f"  errors {c['errors']}" if c["errors"] else "")
        )
    costs.record(
        "checklist_recall",
        a.bench,
        policy={**dict(getattr(comp_base, "usage", {}) or {}), "model": a.compiler},
    )
    costs.record(
        "checklist_recall_judge",
        a.bench,
        policy={**dict(getattr(judge_base, "usage", {}) or {}), "model": a.judge},
    )
    print(costs.line())


if __name__ == "__main__":
    main()
