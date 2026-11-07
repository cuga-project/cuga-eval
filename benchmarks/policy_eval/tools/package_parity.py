"""The package path and the old path give the same results on real data. Offline: no model call.

    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/tools/package_parity.py [store|rules|gate]

store  ``ProcedureStore`` text from each HANDBOOK graph and from its package.
rules  Every converted build, through ``RuleSetHooks`` from the old rule list and from the package file, under each setting
       below. Each rule gets one call made from its own slots that tries to break it; everything the hooks say and record
       must be equal. The rule dicts must also be equal, apart from ``level`` and from ``statement_ids``, which the hooks do
       not read and ``load_rules`` adds. A hook call that raises counts as a failure, because two equal errors compare
       nothing.
       Not every rule fires, and the tool prints how many do (2026-11-05: 1760 of 1775 that are not guidance). Guidance is
       never checked at a write. A rule stays silent when the call cannot break it: its tool is a read tool, its ``format``
       pattern accepts the value, or its condition needs a value the call does not have. Guidance and silent rules take
       part only in the comparison of the brief.
gate   ``StoreGate.from_package`` on every package with a store of its own: it builds only where the package holds rules
       to check, and raises on the others. Where it builds, the rules equal those of a gate on the graph, and opening a
       procedure on that store makes the gate call the model.

scope  ``StoreGate._rules`` on every package file under ``packages/``, for several ways of opening procedures, against the function
       the gate had before routers and expanders (``legacy_rules``, copied here, frozen). The scope comes from ``Scope``
       (``agent_opened`` with ``next_links``) and must be the same lines in the same order.

hops   ``k_hops`` on every package file under ``packages/``: how many procedure pairs have a walkable link (``refers_to``,
       ``exception_of``, ``supersedes``), and whether one hop adds a procedure to ``next_links`` for some procedure. Counts the
       packages the gate can be built on (``from_package`` accepts them) apart: a walk on a package with no pair changes nothing.

Exit code 1 if anything differs or raises.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent.parent)]

from convert_all import ARTIFACTS, AS_GRAPH, HERE, paths_of, target_of  # noqa: E402
from cuga.policy_layer.model import Verdict  # noqa: E402
from cuga.policy_layer.package import load_package, runtime_rules  # noqa: E402
from cuga.policy_layer.procedure_store import ProcedureStore  # noqa: E402
from cuga.policy_layer.ruleset import RULE_TYPES, RuleSetHooks  # noqa: E402
from cuga.policy_layer.store_gate import StoreGate  # noqa: E402
from rule_audit import load_rules  # noqa: E402

UNSEEN = "zzz unseen value"


def artifacts_of(convert: Tuple[Callable, Callable]) -> Iterator[Tuple[Path, Path]]:
    """(source artifact, package file) of the artifacts of one source format."""
    for artifacts in ARTIFACTS:
        if artifacts.convert is convert:
            for path in paths_of(artifacts):
                yield path, target_of(artifacts, path)


# -- store -------------------------------------------------------------------------------------------------------------


def store_texts(store: ProcedureStore) -> Dict[str, str]:
    ids = list(store.procs)
    texts = {"list": store.list_procedures(), "all": store.get_procedure(ids)}
    texts.update({f"get {i}": store.get_procedure([i]) for i in ids})
    return texts


def check_store() -> int:
    wrong = 0
    for path, target in artifacts_of(AS_GRAPH):
        old = store_texts(ProcedureStore.load(str(path)))
        new = store_texts(ProcedureStore.from_package(load_package(target)))
        differ = [k for k in old if old[k] != new.get(k)] + [k for k in new if k not in old]
        wrong += len(differ)
        print(
            f"{path.stem:<50} texts {len(old):>3}  chars {sum(map(len, old.values())):>7}  differ {len(differ)}"
        )
    print(f"store differences: {wrong}")
    return wrong


# -- rules -------------------------------------------------------------------------------------------------------------


class DenyAll:
    """A verifier that finds every statement broken, so verify rules reach their outcome with no model."""

    def check(self, request: str, statements: List[Dict[str, Any]], *_: Any) -> List[Verdict]:
        return [Verdict(outcome="deny", rule_id=s["rule_id"], reason="broken") for s in statements]


def settings() -> Dict[str, Dict[str, Any]]:
    def every_type(choice: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return {t: dict(choice) for t in RULE_TYPES}

    measured = json.loads((HERE / "method_choice.json").read_text())
    return {
        "no method choice": {},
        "verifier_may_deny": {"verifier_may_deny": True},
        "method_choice.json": {"method_choice": measured},
        "choice: code may not deny": {
            "method_choice": every_type({"checker": "code", "code_may_deny": False})
        },
        "choice: code may deny": {"method_choice": every_type({"checker": "code", "code_may_deny": True})},
        "choice: all to the verifier": {
            "method_choice": every_type({"checker": "verifier", "code_may_deny": False, "may_deny": True}),
            "verifier_may_deny": True,
        },
    }


def tools_of(rule: Dict[str, Any]) -> List[str]:
    return list(rule.get("tools") or []) or [
        t for t in (rule.get("tool"), (rule.get("trigger") or {}).get("tool")) if t
    ]


def breaking_call(rule: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]], Dict[str, Any]]:
    """The tool, a record read before, and arguments that break the rule, from its own slots."""
    tools = tools_of(rule)
    tool = tools[0] if tools else "update_record"
    kind, arg = rule.get("type"), rule.get("arg")
    when = (rule.get("trigger") or {}).get("when") if kind == "duty" else rule.get("when")
    args: Dict[str, Any] = {
        k: (v[0] if isinstance(v, list) and v and str(v[0]) != "*" else "given")
        for k, v in (when or {}).items()
    }
    read = None
    if kind in ("allowed_values", "format"):
        args[arg] = UNSEEN
    elif kind == "derived_value":
        key = next(iter(rule.get("table") or {}), "")
        args.update(zip(rule.get("inputs") or [], key.split("|")))
        args[arg] = UNSEEN
    elif kind == "transition":
        read = {"id": "REC-1", arg: next(iter(rule.get("edges") or {}), "new")}
        args.update({rule.get("id_arg"): "REC-1", arg: UNSEEN})
    elif kind == "reference_status":
        read = {"id": "REC-1", rule.get("field"): UNSEEN}
        args[arg] = "REC-1"
    elif kind == "membership":
        read = {"group": "GRP-1", "user": "USR-2"}
        args.update({arg: "USR-1", rule.get("group_arg"): "GRP-1"})
    elif kind == "record_condition":
        value = rule.get("value")
        read = {"id": "REC-1", rule.get("field"): value[0] if isinstance(value, list) and value else value}
        args["ref"] = "REC-1"
    elif kind == "threshold":
        args[arg] = -(10**9) if rule.get("op") in ("lt", "le") else 10**9
    elif kind in ("grounded_values", "id_provenance"):
        args.update({"ref_id": "AB-123", "option": UNSEEN})
    return tool, read, args


def said(call: Callable[[], Any]) -> Any:
    """What one hook call says, or ``{"raised": error}``, which ``check_rules`` counts as a failure."""
    try:
        result = call()
    except Exception as exc:  # noqa: BLE001
        return {"raised": repr(exc)}
    return result.message


def raised_in(case: Dict[str, Any]) -> List[str]:
    return [f"{k}: {v['raised']}" for k, v in case.items() if isinstance(v, dict) and "raised" in v]


def fired(case: Dict[str, Any], rule: Dict[str, Any]) -> bool:
    return any(r.get("rule_id") == rule.get("id") and r["outcome"] != "allow" for r in case["records"])


def one_case(hooks: RuleSetHooks, rule: Dict[str, Any]) -> Dict[str, Any]:
    tool, read, args = breaking_call(rule)
    roles = rule.get("roles") if rule.get("type") == "role_permission" else None
    hooks.principal = {"id": "USER_PARITY", "role": roles[0] if roles else "admin"}
    hooks.session_start(None)
    out = {"brief": said(lambda: hooks.before_llm_call(None))}
    if read:
        hooks.after_tool_call("read_record", {}, read)
    out["call"] = said(lambda: hooks.before_tool_call(tool, dict(args)))
    out["after"] = said(lambda: hooks.after_tool_call(tool, dict(args), {"ok": True}))
    out["reply"] = said(lambda: hooks.before_reply("done"))
    out["next brief"] = said(lambda: hooks.before_llm_call(None))
    out["records"] = list(hooks.records)
    return out


def bare(rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{k: v for k, v in r.items() if k not in ("level", "statement_ids")} for r in rules]


def check_rules() -> int:
    wrong, raised, builds, rule_total, cases = 0, 0, 0, 0, 0
    outcomes: Dict[str, collections.Counter] = {name: collections.Counter() for name in settings()}
    guidance, fire, silent = 0, 0, collections.Counter()
    for artifacts in ARTIFACTS:
        if artifacts.convert is AS_GRAPH:
            continue
        for path in paths_of(artifacts):
            pkg = load_package(target_of(artifacts, path))
            old_rules = load_rules(path)
            builds += 1
            rule_total += len(old_rules)
            if bare(runtime_rules(pkg)) != bare(old_rules):
                wrong += 1
                print(f"RULES DIFFER {target_of(artifacts, path)}")
            tools = sorted({t for r in old_rules for t in tools_of(r)} | {"update_record"})
            specs = [{"name": t} for t in tools]
            for name, setting in settings().items():
                kwargs = {"verifier": DenyAll(), "tools_in_run": tools, **setting}
                old = RuleSetHooks(old_rules, specs, **kwargs)
                new = RuleSetHooks.from_package(pkg, specs, **kwargs)
                for rule in old_rules:
                    a, b = one_case(old, rule), one_case(new, rule)
                    cases += 1
                    outcomes[name].update(r["outcome"] for r in a["records"])
                    errors = raised_in(a) + raised_in(b)
                    if errors:
                        raised += len(errors)
                        if raised < 6:
                            print(
                                f"RAISED {path.relative_to(HERE)} [{name}] {rule.get('id')}: {errors[0][:200]}"
                            )
                    if a != b:
                        wrong += 1
                        if wrong < 6:
                            print(
                                f"DIFFER {target_of(artifacts, path)} [{name}] {rule.get('id')}: {a} != {b}"
                            )
                    if name == "no method choice":
                        if rule.get("type") == "guidance":
                            guidance += 1
                        elif fired(a, rule):
                            fire += 1
                        else:
                            silent[rule.get("type")] += 1
    for name, counts in outcomes.items():
        print(f"{name:<30} " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(
        f"rules that fire under breaking_call: {fire} of {fire + sum(silent.values())} that are not guidance; "
        f"silent: {sum(silent.values())} ({', '.join(f'{k} {v}' for k, v in silent.most_common())}); "
        f"guidance, never checked: {guidance}"
    )
    print(
        f"{builds} builds, {rule_total} rules, {cases} cases, raised calls: {raised}, rule differences: {wrong}"
    )
    if not all(outcomes["no method choice"][k] for k in ("deny", "remind", "observe")):
        print("no outcome of some kind: the cases do not test the levels")
        return wrong + raised + 1
    return wrong + raised


# -- gate --------------------------------------------------------------------------------------------------------------


def check_gate() -> int:
    """A gate is only useful where it has rules, and only on the store behind the agent's tools."""
    wrong, built, refused, reasons = 0, 0, 0, collections.Counter()
    for artifacts in ARTIFACTS:
        for path in paths_of(artifacts):
            pkg = load_package(target_of(artifacts, path))
            calls: List[str] = []

            def model(system: str, user: str) -> str:
                calls.append(user)
                return '{"breaks": false}'

            store = ProcedureStore.from_package(pkg)
            try:
                gate = StoreGate.from_package(pkg, model, store=store)
            except ValueError as exc:
                refused += 1
                reasons[str(exc)] += 1
                continue
            built += 1
            if artifacts.convert is AS_GRAPH:
                old = StoreGate(ProcedureStore.load(str(path)), model)
                for one in (old, gate):
                    one.store.get_procedure(list(one.store.procs))
                if old._rules() != gate._rules():
                    wrong += 1
                    print(f"GATE RULES DIFFER {path}")
            store.get_procedure(list(store.procs))
            gate.before_tool_call("send_message", {"to": "someone"})
            if not calls:
                wrong += 1
                print(f"GATE DID NOT CALL THE MODEL {path}")
            print(
                f"{path.stem:<50} rules after opening all procedures {len(gate._rules()):>3}  model calls {len(calls)}"
            )
            if not StoreGate.from_package(pkg, model, sop_text="The SOP.")._rules():
                wrong += 1
    print(f"gates that build: {built}; packages that raise: {refused} ({dict(reasons)})")
    print(f"gate differences: {wrong}")
    return wrong


# -- scope -------------------------------------------------------------------------------------------------------------


def legacy_rules(store: ProcedureStore) -> List[str]:
    """``StoreGate._rules`` as it was before routers (gate ``fcb15283d``). Frozen: do not change it to follow the gate."""
    out: List[str] = []
    for c in store.calls:
        for pid in c.get("expanded") or []:
            p = store.procs.get(pid) or {}
            out += [f"[{pid}] MUST NOT: {m}" for m in p.get("must_not") or []]
            out += [
                f"[{pid}] DECISION {d.get('id')}: {d.get('rule')}"
                + (f"; then: {d['then']}" if d.get("then") else "")
                + f"; else: {d.get('else', '')}"
                for d in p.get("decisions") or []
            ]
    esc = (store.g.get("escalation") or {}).get("must_not") or []
    out += [f"[escalation] MUST NOT: {m}" for m in esc]
    return list(dict.fromkeys(out))


def openings(ids: List[str]) -> List[List[List[str]]]:
    """Ways an agent opens procedures: nothing, each one alone, pairs, every id in one call and in two calls, and a call
    with an id the store does not have."""
    out: List[List[List[str]]] = [[], [ids], [ids[: len(ids) // 2], ids[len(ids) // 2 :]], [["no such id"]]]
    out += [[[i]] for i in ids[:60]]
    out += [[[a], [b]] for a, b in zip(ids, ids[1:])][:60]
    out += [[[b, a]] for a, b in zip(ids, ids[1:])][:30]
    return out


def check_scope() -> int:
    wrong, packages, compared, lines = 0, 0, 0, 0
    for path in sorted((HERE / "packages").rglob("package.json")):
        pkg = load_package(path)
        store = ProcedureStore.from_package(pkg)
        gates = {"store only": StoreGate(store, lambda s, u: "{}")}
        try:
            gates["from_package"] = StoreGate.from_package(pkg, lambda s, u: "{}", store=store)
        except ValueError:
            pass  # a package with nothing to check: the gate is not built, and the direct constructor still reads the scope
        packages += 1
        for opened in openings(list(store.procs)):
            store.calls.clear()
            for ids in opened:
                store.get_procedure(ids)
            store.get_template(["1"])
            want = legacy_rules(store)
            for name, gate in gates.items():
                got = gate._rules()
                compared += 1
                lines += len(got)
                if got != want:
                    wrong += 1
                    if wrong <= 5:
                        print(f"SCOPE DIFFERS {path.relative_to(HERE)} [{name}] after {opened[:3]}")
    print(f"{packages} packages, {compared} comparisons, {lines} rule lines, scope differences: {wrong}")
    return wrong


def check_hops() -> int:
    """Where ``k_hops`` has something to walk. It never fails by itself: a package with nothing to walk is a fact the printed
    counts show, and the gate refuses ``k_hops`` there (``Expander.problem``)."""
    from cuga.policy_layer.router import make_expander, procedure_graph

    wrong, with_procedures, with_pairs, gate_ok, gate_pairs, grows = 0, 0, 0, 0, 0, 0
    nxt, walk = make_expander("next_links"), make_expander("k_hops", hops=1)
    for path in sorted((HERE / "packages").rglob("package.json")):
        pkg = load_package(path)
        if not pkg.procedures:
            continue
        with_procedures += 1
        graph = procedure_graph(pkg)
        pairs = len({frozenset((a, b)) for a, bs in graph.items() for b in bs})
        try:
            StoreGate.from_package(pkg, lambda s, u: "{}", store=ProcedureStore.from_package(pkg))
            buildable = True
        except ValueError:
            buildable = False
        gate_ok += buildable
        if not pairs:
            if walk.problem(pkg) == "":
                wrong += 1
                print(f"NO PAIR BUT NO PROBLEM {path.relative_to(HERE)}")
            continue
        with_pairs += 1
        gate_pairs += buildable
        adds = any(walk.expand([pid], pkg).procedures != nxt.expand([pid], pkg).procedures for pid in graph)
        grows += adds
        if not adds or walk.problem(pkg):
            wrong += 1
            print(f"WALK ADDS NOTHING {path.relative_to(HERE)}")
        print(
            f"{str(path.relative_to(HERE / 'packages').parent):<64} procedures {len(pkg.procedures):>3}  pairs {pairs:>3}  gate {buildable}"
        )
    print(
        f"{with_procedures} packages with procedures, {with_pairs} with a pair to walk and {grows} where one hop adds a "
        f"procedure; the gate builds on {gate_ok}, and {gate_pairs} of those have a pair; hop differences: {wrong}"
    )
    return wrong


def main() -> int:
    checks = {
        "store": check_store,
        "rules": check_rules,
        "gate": check_gate,
        "scope": check_scope,
        "hops": check_hops,
    }
    chosen = sys.argv[1:] or list(checks)
    return 1 if sum(checks[c]() for c in chosen) else 0


if __name__ == "__main__":
    sys.exit(main())
