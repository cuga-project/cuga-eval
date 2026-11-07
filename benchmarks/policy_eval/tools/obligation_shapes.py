"""Can the ledger read the real packages? Each obligation of each ``skill_v1`` package goes through the ledger, offline.

    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/tools/obligation_shapes.py [--json OUT]

The packages were written before the ledger existed, so this is the check that their shapes fit it. No model and no agent:
``RecordingModels`` raises when called, and the binding answer is made here. For each package:

  build     ``build_runtime`` with a ledger on the package, at item level observe.
  compile   every pattern of every obligation becomes a regular expression, with all values known and with none known.
  bind      one made-up case per procedure, with every fact known, goes through a final reply with no call: every item is
            open or unknown, and an item never ``wrong``.
  perfect   one made-up call per obligation, written from its own pattern: the status must be ``met``. A row that is not met
            is a pattern the ledger cannot read as its author meant.
  produce   ``obligations_from_package``: all obligations with no case, and the ones of a case per procedure (an obligation
            with a ``scope.procedure`` only in the cases of that procedure, the others in every case).
  limits    what the skill's guidance asks for since Task 4.2 and these older packages do not have: a file obligation that names
            only the code tools although the run has a tool that writes files (``code_only_with_file_tool``), and an
            obligation whose tools are all the user's (``user_tool_only``). Counted, not changed.

It reports what the ledger cannot check, per reason (``gaps_of``), the value tests by kind, patterns with brackets the agent
would fill in, and the size of the cards. Packages are not changed here. Reads the package and the tool specs, no run and no
grader data. Exit code 1 when something raised.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from cuga.policy_layer.dry_run import RecordingModels
from cuga.policy_layer.model import Obligation
from cuga.policy_layer.obligations import (
    CODE_ARGS,
    CODE_TOOL,
    GAP,
    Case,
    ObligationLedger,
    _kind,
    _regex,
    _schema_of,
    _show,
    cards_of,
    check_calls,
    fact_id,
    gaps_of,
    plan_of,
    stated_id,
)
from cuga.policy_layer.package import load_package, obligations_from_package
from cuga.policy_layer.policy_config import PolicyConfig
from cuga.policy_layer.procedure_store import ProcedureStore
from cuga.policy_layer.runtime import RunContext, build_runtime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_all import PACKAGES, specs_of  # noqa: E402

DAY = "2026-03-05"
TODAY = "2026-03-20"
PROFILE = {
    "package": "p.json",
    "sources": {"request": True},
    "decisions": {"mode": "off"},
    "checkers": {"rules": "off", "gate": {"mode": "off"}, "verifier": {"mode": "off"}},
    "organizers": {
        "procedure_tools": "off",
        "guide": "off",
        "loop": "off",
        "sop_tracker": "off",
        "navigator": "off",
        "requirements_tracker": "off",
    },
    "obligations": {"producers": ["package"], "model": "m/bind", "item_level": "observe"},
}


def full_case(ob: Obligation, name: str = "case", procedure: str = "") -> Case:
    """A case that knows every value of this obligation. A date is used for all, so that a format can read it."""
    facts: Dict[str, Dict[str, str]] = {}
    stated: Dict[str, Dict[str, str]] = {}
    for spec in (ob.values or {}).values():
        if spec.get("from") == "case_fact":
            facts[fact_id(spec.get("field"), spec.get("record") or "")] = {"value": DAY}
        elif spec.get("from") == "request":
            stated[stated_id(spec.get("about"))] = {"value": DAY}
        elif spec.get("from") == "computed":
            for arg in spec.get("args") or []:
                facts[fact_id(arg)] = {"value": DAY}
    return Case(name=name, procedure=procedure, decision="proceed", facts=facts, stated=stated)


def perfect_call(tool: str, plan: Dict[str, Any], by_name: Dict[str, Any]) -> Dict[str, Any]:
    """The call that a careful agent makes: each argument holds the pattern's text, in the form the schema wants."""
    args: Dict[str, Any] = {}
    for arg, tokens in plan.items():
        if arg in CODE_ARGS and arg not in ((by_name.get(tool) or {}).get("inputSchema") or {}).get(
            "properties", {}
        ):
            continue
        text = _show([t if t[1] != GAP else ("x", t[1], t[2]) for t in tokens])
        if arg == "code":
            args[arg] = f'open("out.txt", "a").write("""{text}""")'
            continue
        if arg == "command":
            args[arg] = f'printf %s "{text}" >> out.txt'
            continue
        schema = _schema_of(by_name, tool, arg)
        if schema.get("type") in ("integer", "number"):
            try:
                args[arg] = float(text) if "." in text else int(text)
            except ValueError:
                args[arg] = text
        elif schema.get("type") == "boolean":
            args[arg] = text.strip().lower() == "true"
        elif schema.get("type") == "array":
            args[arg] = [text]
        elif schema.get("type") == "object":
            args[arg] = {"date": text}
        else:
            args[arg] = text
    return args


def check(bench: str, policy: str, path: Path) -> Dict[str, Any]:
    pkg = load_package(path)
    specs = specs_of(bench, policy)
    if not specs:
        raise AssertionError(f"no tool specs for {bench}/{policy}")
    by_name = {t["name"]: t for t in specs}
    cfg = PolicyConfig.from_dict(PROFILE)
    ctx = RunContext(
        task_id=path.parts[-3],
        policy_version=policy,
        request="r",
        tool_specs=specs,
        message_tool="",
        world_time=TODAY,
    )
    parts = build_runtime(cfg, pkg, ctx, models=RecordingModels())
    if "obligations" not in parts.components:
        raise AssertionError('check failed: "obligations" in parts.components')
    produced = obligations_from_package(pkg)
    if [o.id for o in produced] != [o.id for o in pkg.obligations]:
        raise AssertionError("the producer must give the package's obligations")
    per_case = {
        p.id: [o.id for o in obligations_from_package(pkg, Case(name="c", procedure=p.id))]
        for p in pkg.procedures
    }
    scoped = {o.id: (o.scope or {}).get("procedure") for o in pkg.obligations}
    for pid, ids in per_case.items():
        if not all(scoped[i] in (None, "", pid) for i in ids):
            raise AssertionError(f"{bench}/{policy}: an obligation of another procedure in {pid}")
    in_a_case = {i for ids in per_case.values() for i in ids}
    if not all(scoped[i] in (None, "") or i in in_a_case or scoped[i] not in per_case for i in scoped):
        raise AssertionError("a lost obligation")
    row: Dict[str, Any] = {"package": f"{bench}/{policy}", "obligations": len(produced)}
    code_only = [
        o
        for o in produced
        if (o.effect or {}).get("tools") and all(CODE_TOOL.search(str(t)) for t in o.effect["tools"])
    ]
    can_write_file = any(re.search(r"write_?file", t["name"], re.I) for t in specs)
    row["limits"] = {
        "code_only_with_file_tool": len(code_only) if can_write_file else 0,
        "user_tool_only": sum(
            1
            for o in produced
            if (o.effect or {}).get("tools") and all(str(t).startswith("user__") for t in o.effect["tools"])
        ),
    }
    gaps: Counter = Counter()
    kinds: Counter = Counter()
    origins: Counter = Counter()
    not_met: List[Dict[str, Any]] = []
    brackets: List[str] = []
    no_case_when: Counter = Counter()
    decisions = {str(d.get("id")) for p in pkg.procedures for d in p.decisions if isinstance(d, dict)}
    store = ProcedureStore.from_package(pkg)
    for ob in pkg.obligations:
        gaps.update(gaps_of(ob))
        for spec in (ob.values or {}).values():
            origins[spec.get("from")] += 1
        for key in (ob.scope or {}).get("when") or {}:
            no_case_when["decision_key" if key in decisions else "free_key"] += 1
        tools = [t for t in (ob.effect or {}).get("tools") or []]
        none_known = plan_of(ob, Case(name="c"), store, TODAY)
        plan = plan_of(ob, full_case(ob), store, TODAY)
        for tokens in list(none_known.values()) + list(plan.values()):
            for skeleton in (False, True):
                _regex(tokens, skeleton=skeleton)
                _regex(tokens, full=True, skeleton=skeleton)
        if not tools:
            continue
        for arg, tokens in plan.items():
            text = "".join(t[0] for t in tokens)
            for tool in tools:
                if arg in CODE_ARGS and arg not in _props_of(by_name, tool):
                    continue
                kinds[_kind(tool, arg, None, _schema_of(by_name, tool, arg))] += 1
            if "[" in text and "]" in text:
                brackets.append(ob.id)
        call = {"tool": tools[0], "args": perfect_call(tools[0], plan, by_name)}
        result = check_calls(ob, [call], plan, specs=by_name)
        if result.status != "met" and "code_tool_no_pattern" not in gaps_of(ob):
            not_met.append({"id": ob.id, "status": result.status, "reason": result.reason[:200]})
    row.update(
        gaps=dict(sorted(gaps.items())),
        value_tests=dict(sorted(kinds.items())),
        value_origins=dict(sorted(origins.items(), key=str)),
        when_keys=dict(sorted(no_case_when.items())),
        brackets=sorted(set(brackets)),
        not_met=not_met,
        levels=dict(Counter(o.level for o in pkg.obligations)),
    )
    # A final reply with one case per procedure, every value known, and no call.
    answer = {
        "cases": [
            {
                "case": f"case {p.id}",
                "keys": [],
                "evidence": "a request about this case",
                "procedure": p.id,
                "decision": {"branch": "proceed"},
            }
            for p in pkg.procedures[:12]
        ]
    }
    cards = cards_of(pkg.obligations, pkg.procedures)
    row["cards_chars"] = len(json.dumps(cards, ensure_ascii=False))
    led = ObligationLedger(
        pkg.obligations,
        lambda system, user: json.dumps(answer),
        cards=cards,
        tool_specs=specs,
        request="a request about this case",
        store=store,
        today=TODAY,
        item_level="follow_up",
    )
    message = led.before_reply("done").message
    statuses = Counter(i.status for i in led.items)
    if statuses.get("wrong"):
        raise AssertionError(f"{path}: wrong with no call")
    row["final_reply"] = {
        "items": len(led.items),
        "statuses": dict(sorted(statuses.items())),
        "follow_up_chars": len(message or ""),
    }
    return row


def _props_of(by_name: Dict[str, Any], tool: str) -> Dict[str, Any]:
    return ((by_name.get(tool) or {}).get("inputSchema") or {}).get("properties", {})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", help="write the rows to this file")
    args = parser.parse_args()
    rows, errors = [], []
    for path in sorted(PACKAGES.glob("*/*/skill_v1/package.json")):
        bench, policy = path.parts[-4], path.parts[-3]
        try:
            rows.append(check(bench, policy, path))
        except Exception as exc:  # a crash is the result this script exists to rule out
            errors.append(f"{bench}/{policy}: {type(exc).__name__}: {exc}")
    total: Counter = Counter()
    limits: Counter = Counter()
    for row in rows:
        total.update(row["gaps"])
        limits.update(row["limits"])
    out = {
        "packages": len(rows),
        "obligations": sum(r["obligations"] for r in rows),
        "gaps": dict(sorted(total.items())),
        "limits": dict(sorted(limits.items())),
        "rows": rows,
        "errors": errors,
    }
    text = json.dumps(out, indent=1, ensure_ascii=False)
    if args.json:
        Path(args.json).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
