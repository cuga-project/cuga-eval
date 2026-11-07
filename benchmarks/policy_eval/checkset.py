#!/usr/bin/env python3
"""Check set for choosing a method per statement type (design §7). Built from the TUNING policies' gold builds only.

For each gold statement that a rule or a verify rule enforces, a generator model writes 2 compliant and 2 violating
write calls, with the records the agent would have seen. Case:
  {"id", "policy", "type", "statement", "tool", "args", "records", "label": "allow"|"deny", "origin", "why",
   "code_label"}
``code_label`` is the gold code rule's own verdict when the statement has one; a case whose generated label differs
from it is marked ``needs_check`` (hand review). The generator (Gemini 3.8 Flash) is a reference model that is never
picked as a method, so it does not favour any candidate.

  ~/dev/cuga-agent-gate/.venv/bin/python benchmarks/policy_eval/checkset.py [--per 2] [--limit N]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import policy_pilot_costs as costs  # noqa: E402

GOLD = HERE / "gold"
OUT = HERE / "checkset.jsonl"
GENERATOR = "gcp/gemini-3.8-flash"
SKIP = {"guidance", "grounded_values", "id_provenance", "duty"}

SYSTEM = "You write test cases for a policy checker. Output JSON only."
USER = """Company policy statement (type: {types}):
"{statement}"

Tools the assistant can call (name: arguments):
{tools}

Write {per} write calls that COMPLY with the statement and {per} that BREAK it. Each call uses one tool from the list,
realistic argument values, and the records the assistant would have read before (as small JSON objects; include the
fields the statement depends on). Make the breaking calls break only this statement, and the complying calls look
similar. Do not use the same record for all cases.
Return {{"cases": [{{"label": "allow|deny", "tool": "...", "args": {{...}}, "records": [{{...}}], "why": "..."}}]}}"""


def _tools_text(specs: List[Dict[str, Any]], names: Optional[List[str]] = None) -> str:
    out = []
    for t in specs:
        if names and t["name"] not in names:
            continue
        props = (t.get("inputSchema") or {}).get("properties") or {}
        out.append(f"{t['name']}({', '.join(props)})")
    return "\n".join(out[:60])


def _gold_items() -> List[Dict[str, Any]]:
    """(policy id, statement, rules, tools) from every gold build of the tuning set."""
    items = []
    builds = sorted(GOLD.glob("itsm-*.build.json")) + sorted(GOLD.glob("ab/*/build.json"))
    for bpath in builds:
        if bpath.name.endswith("set.json"):
            continue
        build = json.loads(bpath.read_text())
        if bpath.parent.name == "gold":
            policy = bpath.name.replace(".build.json", "")
            set_path = GOLD / f"{policy}.set.json"
            tools = json.loads((GOLD / "inputs" / "itsm_tools.json").read_text())
        else:
            policy = bpath.parent.name
            set_path = bpath.parent / "set.gold.json"
            tools = json.loads((bpath.parent / "tools.json").read_text())
        ps = json.loads(set_path.read_text()) if set_path.exists() else {"documents": []}
        texts = {st["id"]: st for d in ps["documents"] for sec in d["sections"] for st in sec["statements"]}
        by_stmt: Dict[str, List[Dict[str, Any]]] = {}
        for r in build["rules"]:
            if r["type"] in SKIP:
                continue
            for sid in r.get("statement_ids") or []:
                by_stmt.setdefault(sid, []).append(r["rule"])
        for sid, rules in by_stmt.items():
            st = texts.get(sid)
            if not st:
                continue
            names = sorted({n for r in rules for n in (r.get("tools") or [r.get("tool")]) if n})
            items.append(
                {
                    "policy": policy,
                    "statement_id": sid,
                    "statement": st["text"],
                    "types": st.get("types") or [],
                    "rules": rules,
                    "tools": tools,
                    "tool_names": names,
                }
            )
    return items


def _code_label(
    rules: List[Dict[str, Any]], specs: List[Dict[str, Any]], case: Dict[str, Any]
) -> Optional[str]:
    """The gold code rules' verdict on a case, or None if no code rule applies."""
    from cuga.policy_layer.ruleset import RuleSetHooks

    code = [r for r in rules if r["type"] not in ("verify", "role_permission")]
    if not code:
        return None
    hooks = RuleSetHooks(code, specs)
    hooks.after_tool_call("read_records", {}, {"records": case.get("records") or []})
    checks = [
        c
        for c in hooks._checks(case["tool"], case.get("args") or {})
        if c.rule.get("id") in {r.get("id") for r in code}
    ]
    if not checks:
        return None
    return "deny" if any(not c.ok for c in checks) else "allow"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=2)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    from cuga.policy_layer.llm import openai_json_model, parse_json

    items = _gold_items()[: a.limit] if a.limit else _gold_items()
    model = openai_json_model(GENERATOR)

    def one(it):
        prompt = USER.format(
            types=", ".join(it["types"]) or "untyped",
            statement=it["statement"],
            per=a.per,
            tools=_tools_text(it["tools"], it["tool_names"] or None),
        )
        try:
            reply = parse_json(model(SYSTEM, prompt))
        except Exception as exc:  # noqa: BLE001
            return [{"error": str(exc), "statement_id": it["statement_id"]}]
        out = []
        for c in reply.get("cases") or []:
            if not isinstance(c, dict) or c.get("label") not in ("allow", "deny") or not c.get("tool"):
                continue
            case = {
                "policy": it["policy"],
                "statement_id": it["statement_id"],
                "type": (it["types"] or ["untyped"])[0],
                "types": it["types"],
                "statement": it["statement"],
                "tool": c["tool"],
                "args": c.get("args") or {},
                "records": c.get("records") or [],
                "label": c["label"],
                "why": c.get("why", ""),
                "origin": "generated",
            }
            try:
                case["code_label"] = _code_label(it["rules"], it["tools"], case)
            except Exception:  # noqa: BLE001
                case["code_label"] = None
            case["needs_check"] = case["code_label"] is not None and case["code_label"] != case["label"]
            case["id"] = hashlib.sha256(json.dumps(case, sort_keys=True, default=str).encode()).hexdigest()[
                :12
            ]
            out.append(case)
        return out

    with ThreadPoolExecutor(max_workers=6) as pool:
        cases = [c for batch in pool.map(one, items) for c in batch]
    OUT.write_text("".join(json.dumps(c, default=str) + "\n" for c in cases))
    costs.record(
        "checkset",
        f"{len(items)} statements, {len(cases)} cases",
        policy={**model.usage, "model": model.model_name},
    )
    good = [c for c in cases if "error" not in c]
    print(
        f"{len(items)} statements -> {len(good)} cases ({sum(c['needs_check'] for c in good)} need a hand check); "
        f"{costs.line()}"
    )


if __name__ == "__main__":
    main()
