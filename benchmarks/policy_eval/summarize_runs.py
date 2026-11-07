#!/usr/bin/env python3
"""One line per run: AutomationBench (strict pass, partial, AA-style, guardrail-break tasks, tool calls, tokens) or
ITSM (pass, verifiers). Usage: summarize_runs.py ab:<run> eog:<run>:<arm> ..."""

import glob
import json
import sys
from pathlib import Path

B = Path(__file__).resolve().parent.parent


def ab(run):
    rs = [json.load(open(f)) for f in sorted(glob.glob(str(B / f"automationbench/results/{run}/*.json")))]
    if not rs:
        return f"{run}: no results"
    tok = sum((r.get("receipt") or {}).get("input_tokens", 0) for r in rs)
    deny = sum(1 for r in rs for g in r.get("gate") or [] if g.get("outcome") == "deny")
    remind = sum(1 for r in rs for g in r.get("gate") or [] if g.get("outcome") == "remind")
    return (
        f"AB  {run:16} n={len(rs):2} pass={sum(r['pass'] for r in rs):2} partial={sum(r['partial_credit'] for r in rs) / len(rs) * 100:5.1f}% "
        f"AA={sum(r['aa_style'] for r in rs) / len(rs) * 100:5.1f}% guard_tasks={sum(bool(r.get('guard_broken')) for r in rs)} "
        f"calls={sum(len(r['tool_calls']) for r in rs):4} in_tok={tok / 1e6:5.2f}M deny={deny} remind={remind} "
        f"errors={sum(bool(r.get('error')) for r in rs)}"
    )


def eog(run, arm):
    rs = [
        json.load(open(f))
        for f in sorted(glob.glob(str(B / f"enterpriseops_gym/results/{run}/{arm}_*.json")))
    ]
    if not rs:
        return f"{run} {arm}: no results"
    deny = sum(1 for r in rs for g in r.get("gate") or [] if g.get("outcome") == "deny")
    remind = sum(1 for r in rs for g in r.get("gate") or [] if g.get("outcome") == "remind")
    return (
        f"EOG {run:12} {arm} n={len(rs):2} pass={sum(r['passed'] for r in rs):2} "
        f"verifiers={sum(r['verifiers_passed'] for r in rs)}/{sum(r['verifiers_total'] for r in rs)} "
        f"calls={sum(len(r['tool_calls']) for r in rs):4} deny={deny} remind={remind} errors={sum(bool(r['error']) for r in rs)}"
    )


for spec in sys.argv[1:]:
    kind, *rest = spec.split(":")
    print(ab(*rest) if kind == "ab" else eog(*rest))
