"""Policy features of every public AutomationBench task, for choosing an evaluation subset.

Reads task data only (prompt, initial state, assertion list); runs no agent. Per task it records where rule text
lives in the data, what kind of rule it is (approval, threshold, date, version), and how many checks are guardrails
(scored checks that already pass in the initial state, so the agent can only break them).

    .venv/bin/python -I policy_features.py            # writes results/policy_features.json, prints a summary
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(sys.argv[0]).resolve().parent
sys.path.insert(0, str(HERE))

RULE = re.compile(
    r"\b(polic(y|ies)|procedures?|guidelines?|rules?|SOPs?|playbooks?|handbooks?|criteria|requirements?)\b",
    re.I,
)
PROMPT_RULE = re.compile(
    r"\b(polic(y|ies)|procedures?|guidelines?|rules?|criteria|process|playbook|SOP|standards?)\b", re.I
)
VERSION = re.compile(
    r"\b(supersede[sd]?|outdated|deprecated|no longer (valid|applies|in effect)|replaced by|old (policy|version)|"
    r"previous (policy|version)|updated (policy|procedure|rules?)|revised|effective (as of|from|date))\b",
    re.I,
)
APPROVAL = re.compile(r"\b(approv(al|ed|e)|sign[- ]?off|authori[sz](ed|ation))\b", re.I)
THRESHOLD = re.compile(
    r"\b(over|above|exceed(s|ing)?|more than|at least|less than|under|below|greater than)\s+\$?\d", re.I
)
DATE_RULE = re.compile(
    r"\b(within \d+|older than|\d+\s+(business )?days|overdue|past due|expir(ed|es|y))\b", re.I
)


def strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
    elif isinstance(o, str):
        yield o


def used_before() -> set[str]:
    """Tasks already used in a run or a subset file (tuning, unseen, pilot, smoke)."""
    used = set()
    for f in (HERE / "results").glob("*/*.json"):
        if f.parent.name != "html" and f.stem.count(".") == 1:
            used.add(f.stem)
    for f in [
        HERE / "subset.json",
        HERE / "policy_pilot.json",
        *HERE.parent.glob("policy_eval/policy_eval_tasks*.json"),
    ]:
        if f.exists():
            used |= {s for s in strings(json.loads(f.read_text())) if re.fullmatch(r"[a-z]+\.[a-z0-9_]+", s)}
    return used


def main() -> None:
    from automationbench.domains import PUBLIC_DOMAINS, get_domain_dataset
    from automationbench.rubric.registry import AssertionRegistry
    from automationbench.tools import ALL_TOOLS
    from ab_env import build_world, tool_app

    app_of = {t.__name__: tool_app(t) for t in ALL_TOOLS}
    used = used_before()
    rows = []
    for dom in PUBLIC_DOMAINS:
        for row in get_domain_dataset(dom):
            info = row["info"] if isinstance(row["info"], dict) else json.loads(row["info"])
            prompt = " ".join(m["content"] for m in row["prompt"] if m["role"] == "user")
            state = info.get("initial_state", {})
            rule_apps = Counter()
            rule_text = []
            for app, data in state.items():
                for s in strings(data):
                    if RULE.search(s):
                        rule_apps[app] += 1
                        rule_text.append(s)
            text = "\n".join(rule_text)
            _, info_s, initial = build_world(info)
            from automationbench.schema.world import WorldState

            w0 = WorldState(**initial)
            guards = negs = 0
            scored = 0
            for a in info_s["assertions"]:
                if a.get("scored") is False or a.get("excluded") is True:
                    continue
                scored += 1
                neg = AssertionRegistry.is_negative(a["type"])
                negs += neg
                if a.get("excluded") is not False and AssertionRegistry.check(w0, a):
                    guards += 1
            tools = info.get("zapier_tools", [])
            rows.append(
                {
                    "task": info["task_name"],
                    "domain": dom,
                    "n_tools": len(tools),
                    "apps": sorted({app_of[t] for t in tools if t in app_of}),
                    "missing_tools": sorted(set(tools) - set(app_of)),
                    "uses_chatgpt": any(app_of.get(t) == "chatgpt" for t in tools),
                    "n_checks": scored,
                    "n_guards": guards,
                    "n_negative": negs,
                    "prompt_points_to_rules": bool(PROMPT_RULE.search(prompt)),
                    "rule_apps": sorted(rule_apps),
                    "rule_strings": sum(rule_apps.values()),
                    "versioned": bool(VERSION.search(text)),
                    "approval": bool(APPROVAL.search(text)),
                    "threshold": bool(THRESHOLD.search(text)),
                    "date_rule": bool(DATE_RULE.search(text)),
                    "used_before": info["task_name"] in used,
                }
            )
    out = HERE / "results" / "policy_features.json"
    out.write_text(json.dumps(rows, indent=1))
    n = len(rows)
    c = Counter()
    for r in rows:
        c["rule text in data"] += bool(r["rule_apps"])
        c["rule text in 2+ apps"] += len(r["rule_apps"]) >= 2
        c["prompt points to rules"] += r["prompt_points_to_rules"]
        c["versioned rules"] += r["versioned"]
        c["approval rule"] += r["approval"]
        c["threshold rule"] += r["threshold"]
        c["date rule"] += r["date_rule"]
        c["has guardrails"] += r["n_guards"] > 0
        c["used before"] += r["used_before"]
        c["uses chatgpt tool"] += r["uses_chatgpt"]
    print(f"{n} tasks -> {out}")
    for k, v in c.items():
        print(f"  {k:24} {v:4} ({100 * v / n:.0f}%)")


if __name__ == "__main__":
    main()
