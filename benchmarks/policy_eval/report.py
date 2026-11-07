#!/usr/bin/env python3
"""Evaluation report: arm A (CUGA alone) vs arm B (CUGA + policy layer), per benchmark, over trials.

Manifest (``runs.json`` next to this file):
  {"set": "unseen", "automationbench": {"A": ["run_A_t1", ...], "B": [...]}, "itsm": {"A": [...], "B": [...]}}
Run names are directories under ``benchmarks/automationbench/results`` and ``benchmarks/enterpriseops_gym/results``.

Primary metrics (fixed 2026-11-01): AutomationBench AA-style score (a guardrail break scores 0); ITSM task pass
rate. A result whose error is an infrastructure error (gateway, timeout of the environment) is not scored; it is
listed so it can be re-run. Changes made after tuning runs are read from ``changes.md``.

  python3 benchmarks/policy_eval/report.py [--manifest runs.json] [-o report.md]
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
INFRA = (
    "APIConnectionError",
    "Connection error",
    "gateway",
    "502",
    "503",
    "504",
    "server not ready",
    "ECONNREFUSED",
    "RemoteProtocolError",
)


def _infra(rec: Dict[str, Any]) -> bool:
    err = str(rec.get("error") or "")
    return any(m in err for m in INFRA)


def load(bench: str, runs: List[str]) -> List[Dict[str, Any]]:
    root = BENCH / ("automationbench/results" if bench == "automationbench" else "enterpriseops_gym/results")
    out = []
    for trial, run in enumerate(runs, 1):
        for f in sorted((Path(run) if Path(run).is_absolute() else root / run).glob("*.json")):
            rec = json.loads(f.read_text())
            rec["_run"], rec["_trial"] = run, trial
            rec["_task"] = rec.get("task") or rec.get("task_id")
            out.append(rec)
    return out


def score(bench: str, rec: Dict[str, Any]) -> Dict[str, float]:
    if bench == "automationbench":
        return {
            "primary": float(rec.get("aa_style") or 0.0),
            "strict": float(bool(rec.get("pass"))),
            "partial": float(rec.get("partial_credit") or 0.0),
            "guard_broken": float(bool(rec.get("guard_broken"))),
        }
    total = rec.get("verifiers_total") or 0
    return {
        "primary": float(bool(rec.get("passed"))),
        "verifiers": (rec.get("verifiers_passed") or 0) / total if total else 0.0,
    }


def gate_counts(rec: Dict[str, Any]) -> Dict[str, int]:
    gate = rec.get("gate") or []
    denies = [g for g in gate if g.get("outcome") == "deny"]
    executed = [c.get("tool") for c in rec.get("tool_calls") or []]
    # a deny whose tool was called again later: the agent obeyed with other arguments, or went around a false deny
    overridden = sum(1 for d in denies if d.get("tool") in executed)
    return {
        "denies": len(denies),
        "denies_overridden": overridden,
        "reminders": sum(g.get("outcome") == "remind" for g in gate),
        "followups": sum(g.get("outcome") == "followup" for g in gate),
    }


def summarize(bench: str, arms: Dict[str, List[str]]) -> Dict[str, Any]:
    res: Dict[str, Any] = {"arms": {}, "tasks": defaultdict(dict), "infra": []}
    for arm, runs in arms.items():
        recs = load(bench, runs)
        scored = [r for r in recs if not _infra(r)]
        res["infra"] += [
            f"{arm} {r['_run']} {r['_task']}: {str(r.get('error'))[:80]}" for r in recs if _infra(r)
        ]
        metrics = defaultdict(list)
        per_task = defaultdict(list)
        gates = {"denies": 0, "denies_overridden": 0, "reminders": 0, "followups": 0}
        for r in scored:
            s = score(bench, r)
            for k, v in s.items():
                metrics[k].append(v)
            per_task[r["_task"]].append(s["primary"])
            for k, v in gate_counts(r).items():
                gates[k] += v
        res["arms"][arm] = {
            "results": len(scored),
            **{k: statistics.mean(v) for k, v in metrics.items()},
            **gates,
            "policy_calls": sum((r.get("policy_usage") or {}).get("calls", 0) for r in scored),
        }
        for t, v in per_task.items():
            res["tasks"][t][arm] = statistics.mean(v)
    return res


def render(manifest: Dict[str, Any]) -> str:
    lines = [f"# Policy layer evaluation: {manifest.get('set', '')} set", ""]
    for bench in ("automationbench", "itsm"):
        if bench not in manifest:
            continue
        s = summarize(bench, manifest[bench])
        lines += [
            f"## {bench}",
            "",
            "| Arm | Results | Primary | "
            + ("Strict | Partial | Guardrail breaks" if bench == "automationbench" else "Verifiers")
            + " | Denies | Denied tool called later | Reminders | Follow-ups | Policy calls |",
            "|---|---|---|"
            + ("---|---|---|" if bench == "automationbench" else "---|")
            + "---|---|---|---|---|",
        ]
        for arm, m in s["arms"].items():
            extra = (
                f"{m.get('strict', 0):.1%} | {m.get('partial', 0):.1%} | {m.get('guard_broken', 0):.1%}"
                if bench == "automationbench"
                else f"{m.get('verifiers', 0):.1%}"
            )
            lines.append(
                f"| {arm} | {m['results']} | {m.get('primary', 0):.1%} | {extra} | {m['denies']} | "
                f"{m['denies_overridden']} | {m['reminders']} | {m['followups']} | {m['policy_calls']} |"
            )
        lines += ["", "| Task | A | B | B − A |", "|---|---|---|---|"]
        for t, v in sorted(s["tasks"].items()):
            a, b = v.get("A"), v.get("B")
            diff = f"{b - a:+.2f}" if a is not None and b is not None else ""
            lines.append(
                f"| {t} | {'' if a is None else f'{a:.2f}'} | {'' if b is None else f'{b:.2f}'} | {diff} |"
            )
        if s["infra"]:
            lines += ["", "Not scored (infrastructure errors; re-run):", *[f"- {x}" for x in s["infra"]]]
        lines.append("")
    changes = HERE / "changes.md"
    lines += [
        "## Changes made after seeing tuning runs",
        "",
        changes.read_text() if changes.exists() else "(none recorded)",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(HERE / "runs.json"))
    ap.add_argument("-o", "--output", default=str(HERE / "report.md"))
    a = ap.parse_args()
    text = render(json.loads(Path(a.manifest).read_text()))
    Path(a.output).write_text(text)
    print(text[:3000])


if __name__ == "__main__":
    main()
