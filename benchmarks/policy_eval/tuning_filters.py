#!/usr/bin/env python3
"""Precision filters on compiled rules, from logged tuning-run calls (adopted from JevAct, arXiv 2610.38620).

1. Firing rate: replay every logged write call of the tuning runs (both arms, no outcome labels) through the compiled
   code rules of its policy; a rule that denies more than 10% of the calls of its tools becomes remind-only
   (``may_deny: false`` in the build).
2. Repair round: each such rule is shown to the policy model with up to 5 calls it fired on; the model may correct
   the rule's slots or mark it as advice. A corrected rule must pass ``validate.check_rule`` and fire at most 10%.

Only tuning tasks are used. Writes ``filters_report.md`` and updates the builds in ``builds/`` (a backup is kept).

  ~/dev/cuga-agent-gate/.venv/bin/python benchmarks/policy_eval/tuning_filters.py --runs tune_A_t1,tune_B_t1 [--repair]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
MAX_FIRING = 0.10
REPAIR_SYSTEM = (
    "You fix rules of an automatic policy checker that block too many correct actions. Output JSON only."
)
REPAIR_USER = """Policy statement: "{quote}"
Rule now (JSON): {rule}
Tool schema: {schema}
Write calls that this rule blocked (the agent made them while working; most were probably correct):
{calls}

If the rule misreads the statement, return the corrected rule (same JSON keys). If the statement cannot be checked
this way, return {{"advice": true}}. Return {{"rule": {{...}}}} or {{"advice": true}}."""


def logged_calls(runs: List[str]) -> List[Dict[str, Any]]:
    """(policy version, ordered calls with results) per ITSM task result in the given runs."""
    out = []
    for run in runs:
        for f in sorted((BENCH / "enterpriseops_gym/results" / run).glob("*.json")):
            rec = json.loads(f.read_text())
            out.append(
                {
                    "policy": rec.get("policy_version"),
                    "task": rec.get("task_id"),
                    "calls": rec.get("tool_calls") or [],
                }
            )
    return out


def firing(build: Dict[str, Any], specs: List[Dict[str, Any]], tasks: List[Dict[str, Any]]):
    from cuga.policy_layer.ruleset import RuleSetHooks, is_write_tool

    code = [r for r in build["rules"] if r.get("type") not in ("verify", "guidance")]
    fired: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    seen: Dict[str, int] = defaultdict(int)
    for t in tasks:
        hooks = RuleSetHooks(code, specs)
        for c in t["calls"]:
            tool, args = c.get("tool") or c.get("name"), c.get("args") or c.get("arguments") or {}
            if is_write_tool(tool):
                for chk in hooks._checks(tool, args):
                    rid = chk.rule.get("id")
                    if rid is None:
                        continue
                    seen[rid] += 1
                    if not chk.ok:
                        fired[rid].append({"tool": tool, "args": args, "task": t["task"]})
            hooks.after_tool_call(tool, args, c.get("result"))
    rates = {rid: len(fired[rid]) / n for rid, n in seen.items() if n}
    return rates, fired


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True, help="comma-separated ITSM tuning run names")
    ap.add_argument("--repair", action="store_true")
    ap.add_argument("--model", default="aws/gpt-oss-120b")
    a = ap.parse_args()
    sys.path.insert(0, str(BENCH))
    import policy_pilot_costs as costs
    from cuga.policy_layer.llm import openai_json_model, parse_json
    from cuga.policy_layer.validate import check_rule

    specs = json.loads((BENCH / "enterpriseops_gym/tasks/itsm_tools.json").read_text())
    by_name = {t["name"]: t for t in specs}
    tasks = logged_calls(a.runs.split(","))
    model = openai_json_model(a.model) if a.repair else None
    lines = ["# Tuning filters (firing rate > 10% of logged write calls of the rule's tools)", ""]
    for version in sorted({t["policy"] for t in tasks if t["policy"]}):
        path = HERE / "builds" / f"{version}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        shutil.copy(path, path.with_suffix(".before_filters.json"))
        rates, fired = firing({"rules": data["rules"]}, specs, [t for t in tasks if t["policy"] == version])
        lines.append(f"## {version}: {len(tasks)} tasks, {len(rates)} rules checked")
        for rule in data["rules"]:
            rid = rule.get("id")
            rate = rates.get(rid, 0.0)
            if rate <= MAX_FIRING:
                continue
            note = f"- `{rid}` {rule['type']} fired {rate:.0%}"
            if model is not None:
                tools = rule.get("tools") or [rule.get("tool")]
                reply = parse_json(
                    model(
                        REPAIR_SYSTEM,
                        REPAIR_USER.format(
                            quote=rule.get("quote", ""),
                            rule=json.dumps(rule),
                            schema=json.dumps(by_name.get(tools[0], {}))[:3000],
                            calls="\n".join(json.dumps(c, default=str)[:400] for c in fired[rid][:5]),
                        ),
                    )
                )
                new = reply.get("rule") if isinstance(reply.get("rule"), dict) else None
                if new and not check_rule(
                    {**new, "quote": rule.get("quote", "")}, by_name, rule.get("quote", "")
                ):
                    new = {**rule, **new, "id": rid, "repaired": True}
                    r2, _ = firing({"rules": [new]}, specs, [t for t in tasks if t["policy"] == version])
                    if r2.get(rid, 0.0) <= MAX_FIRING:
                        rule.clear()
                        rule.update(new)
                        lines.append(note + f" -> repaired (now {r2.get(rid, 0.0):.0%})")
                        continue
            rule["may_deny"] = False
            lines.append(note + " -> remind only")
        path.write_text(json.dumps(data, indent=1))
    if model is not None:
        costs.record("tuning_filters", a.runs, policy={**model.usage, "model": model.model_name})
    (HERE / "filters_report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
