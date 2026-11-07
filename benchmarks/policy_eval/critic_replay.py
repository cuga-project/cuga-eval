"""Offline replay of an end-state critic on finished AutomationBench runs (no agent runs).

The critic sees the request (system + user message), the data the agent read and the writes it made, and lists
required effects that are missing or wrong. Step A (a model) lists the required effects; step B checks each one
against the writes. Variants:
  C1  A = Gemini 3.8 Flash,  B = Gemini 3.8 Flash
  C2  A = gpt-oss-120b,      B = code (literal targets) + Kev-4B (one yes/no question per item)
  C3  A = gpt-oss-120b,      B = gpt-oss-120b
Scored against the grader's failed checks of each run: precision = flagged items that match a failed check,
recall = failed checks matched by a flagged item; flags on fully passed runs are false alarms.
The grader is only used for scoring here, never shown to the critic.

    OPENAI_API_KEY=<key with Gemini access> ~/dev/cuga-agent-gate/.venv/bin/python -I critic_replay.py \
        --runs ../automationbench/results/pg_AF_t1 --variants C1,C2,C3
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(sys.argv[0]).resolve().parent
EVAL = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "automationbench"))
READ = re.compile(r"get|find|list|search|read|lookup|fetch|query|retrieve|view")
DATA_CHARS, WRITES_CHARS = 24000, 12000

SYSTEM = "You check finished work against what was asked. Output JSON only."
LIST_USER = """Instructions the assistant was given:
<<<
{system}
>>>

Work request:
<<<
{request}
>>>

Data the assistant read (may be cut):
<<<
{data}
>>>

List every concrete effect the request (and any rules in the data that apply) requires in the systems: each message,
email, comment, record, update or post, with its target (recipient, channel, record) and the values it must contain.
Include effects that must NOT happen when the request or rules say so. Do not invent requirements.
Return {{"effects": [{{"id": <number>, "action": "...", "target": "...", "values": ["..."], "must_not": false}}]}}"""
CHECK_USER = """Required effects:
{effects}

Writes the assistant made (tool and arguments):
<<<
{writes}
>>>

For each required effect, is it done correctly by the writes (right target and the required values), missing, or
wrong? For a must-not effect, "done" means it did not happen. Return {{"status": [{{"id": <number>,
"status": "done|missing|wrong", "why": "..."}}]}}"""
KEV_Q = (
    "Do the listed writes include this required effect, with the right target and the required values? For an effect "
    "that must not happen, answer yes if it did not happen."
)


def parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


def inputs(rec: dict) -> dict:
    from ab_env import load_task

    task = load_task(rec["task"])
    system = "\n\n".join(m["content"] for m in task["prompt"] if m["role"] == "system")
    request = "\n\n".join(m["content"] for m in task["prompt"] if m["role"] == "user")
    reads, writes = [], []
    for c in rec.get("tool_calls") or []:
        line = f"{c['tool']}({json.dumps({k: v for k, v in (c.get('args') or {}).items() if v not in (None, '', [], {})}, default=str)})"
        if READ.search(c["tool"]):
            reads.append(f"{line} -> {str(c.get('result'))[:2500]}")
        else:
            writes.append(f"{line} -> {str(c.get('result'))[:200]}")
    return {
        "system": system[:4000],
        "request": request[:6000],
        "data": "\n".join(reads)[-DATA_CHARS:],
        "writes": "\n".join(writes)[:WRITES_CHARS] or "(no writes)",
    }


def literal_done(effect: dict, writes: str) -> bool | None:
    """Code check: the target written literally (an address, #channel or ID) must appear in the writes."""
    target = str(effect.get("target") or "")
    lits = re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+|#[\w-]+|\b[A-Za-z]+[-_][A-Za-z0-9_-]*\d[\w-]*\b", target)
    if not lits:
        return None
    hit = all(x.lower() in writes.lower() for x in lits)
    if effect.get("must_not"):
        return not hit
    return hit if not hit else None  # a present target still needs the values checked by Kev


def run_variant(variant: str, rec: dict, models: dict, ask) -> list:
    x = inputs(rec)
    lister = models["gemini"] if variant == "C1" else models["oss"]
    effects = parse(lister(SYSTEM, LIST_USER.format(**x))).get("effects") or []
    effects = [e for e in effects if isinstance(e, dict)][:30]
    if not effects:
        return []
    flagged = []
    if variant in ("C1", "C3"):
        checker = models["gemini"] if variant == "C1" else models["oss"]
        st = (
            parse(
                checker(
                    SYSTEM,
                    CHECK_USER.format(effects=json.dumps(effects, ensure_ascii=False), writes=x["writes"]),
                )
            ).get("status")
            or []
        )
        by_id = {e.get("id"): e for e in effects}
        for s in st:
            if isinstance(s, dict) and s.get("status") in ("missing", "wrong") and s.get("id") in by_id:
                flagged.append({**by_id[s["id"]], "status": s["status"], "why": s.get("why")})
        return flagged
    for e in effects:  # C2: code first, then Kev
        lit = literal_done(e, x["writes"])
        if lit is False:
            flagged.append({**e, "status": "missing", "why": "target not in any write (code)"})
            continue
        p = ask(
            f"Writes the assistant made:\n{x['writes'][:6000]}\n\nRequired effect: {json.dumps(e, ensure_ascii=False)}",
            {"done": KEV_Q},
        ).get("done")
        if p is not None and p < 0.5:
            flagged.append({**e, "status": "missing", "why": f"Kev p={p:.2f}"})
    return flagged


def check_values(f: dict) -> list:
    keys = (
        "to",
        "channel",
        "channel_id",
        "channel_name",
        "ticket_id",
        "record_id",
        "text_contains",
        "content_contains",
        "subject_contains",
        "body_contains",
        "summary",
        "name",
        "email",
        "subject",
        "title",
        "value",
    )
    vals = [str(v) for k, v in (f.get("params") or {}).items() if any(k == x or k.endswith(x) for x in keys)]
    return [v.lower() for v in vals if len(v) >= 3]


def matches(item: dict, failed: dict) -> bool:
    text = json.dumps(item, ensure_ascii=False).lower()
    vals = check_values(failed)
    return bool(vals) and any(v in text for v in vals)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--variants", default="C1,C2,C3")
    ap.add_argument("--out", default=str(HERE / "critic_replay_results.json"))
    args = ap.parse_args()
    from dotenv import dotenv_values

    os.environ.setdefault("OPENAI_BASE_URL", dotenv_values(EVAL / ".env").get("OPENAI_BASE_URL") or "")
    os.environ.setdefault("OPENROUTER_API_KEY", dotenv_values(EVAL / ".env").get("OPENROUTER_API_KEY") or "")
    from cuga.policy_layer.detectors import systemone_questions
    from cuga.policy_layer.llm import openai_json_model

    models = {
        "gemini": openai_json_model("gcp/gemini-3.8-flash", timeout=180, max_tokens=16000),
        "oss": openai_json_model("aws/gpt-oss-120b", timeout=180, max_tokens=16000),
    }
    ask = systemone_questions()
    recs = [json.loads(p.read_text()) for p in sorted(Path(args.runs).glob("*.json"))]
    recs = [r for r in recs if isinstance(r, dict) and "failed" in r]
    out = {}
    for v in args.variants.split(","):
        with ThreadPoolExecutor(6) as pool:
            flagged = list(pool.map(lambda r: run_variant(v, r, models, ask), recs))
        n_flag = n_true = n_failed = n_found = false_on_pass = 0
        for r, fl in zip(recs, flagged):
            failed = [f for f in r["failed"] if check_values(f)]
            n_failed += len(failed)
            n_found += sum(1 for f in failed if any(matches(i, f) for i in fl))
            n_flag += len(fl)
            n_true += sum(1 for i in fl if any(matches(i, f) for f in failed))
            if r["pass"]:
                false_on_pass += len(fl)
        out[v] = {
            "runs": len(recs),
            "flagged": n_flag,
            "precision": round(n_true / n_flag, 3) if n_flag else None,
            "recall": round(n_found / n_failed, 3) if n_failed else None,
            "failed_checks": n_failed,
            "flags_on_passed_runs": false_on_pass,
            "passed_runs": sum(bool(r["pass"]) for r in recs),
            "usage": {k: dict(getattr(m, "usage", {}) or {}) for k, m in models.items()},
            "kev": dict(getattr(ask, "usage", {}) or {}),
            "per_run": [
                {"task": r["task"], "pass": r["pass"], "flagged": fl} for r, fl in zip(recs, flagged)
            ],
        }
        print(
            v,
            {
                k: out[v][k]
                for k in (
                    "runs",
                    "flagged",
                    "precision",
                    "recall",
                    "failed_checks",
                    "flags_on_passed_runs",
                    "passed_runs",
                )
            },
        )
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
