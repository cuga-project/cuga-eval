"""Compare retrieval methods offline on saved acting calls (design section 11). Replaces ``sop_retrieval_eval.py``.

    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/tools/retrieval_eval.py \\
        --package 'benchmarks/policy_eval/packages/handbook/{task}/claude_v1/package.json' \\
        --router bm25 --expand next_links --runs benchmarks/policy_eval/sop_retrieval/result.json

``--package``: a package file, or a path with ``{task}``, which is filled in from the ``task`` of each saved call.
``--router`` and ``--expand``: any names registered in ``cuga.policy_layer.router`` (a method written for the gate is
measured here with no change to this file). ``--runs``: a file with ``rows``, each a saved acting call
(``task``, ``tool``, ``args``, ``context``) with the labels of the call. ``--hops``, ``--top-k``: options of ``k_hops`` and of
a router that ranks (a flag the chosen methods do not read is an error, as a profile setting is). ``--top-k`` defaults to the
router's own, 3, as in a profile. ``--model`` (``llm_cards``) and ``--ask`` (``bm25_kev``) name the models of a router that
needs one: that is a paid call for every query, and with no name given a model router stops before it asks anything.

The query of a call is ``<tool> <args> <context>``, the data the agent had read (a router that reads a prompt gets the action
``tool(args)`` and the data apart). The router and the expander run as the gate runs them, with a profile's defaults, so the
scope measured is the scope the gate would use.

Output. The procedure measures take the calls that have a procedure label:

  procedure recall@1, @3   the first labelled procedure is in the first 1, or 3, ids the router returns
  procedure in scope       it is in the scope the expander gives (what the gate would look at)

The two below take every call that has those labels, also one with ``label: []``; the line at the top says how many calls were
scored. The expander is checked on each package: where it changes nothing (``k_hops`` on a package with no link to walk) the
output says so, because a result there says nothing about the method.

  must-not recall@5        the labelled must-not rules (the rule text, in ``must_not``) that are among the rules of the
                           first 5 procedures of the scope (fixed at 5, whatever ``--top-k`` is), with the escalation rules
  exception recall         the labelled exception procedures (ids, in ``exceptions``) that are in scope
  tokens and time          model tokens and milliseconds per query (select and expand)

A metric whose labels the file does not have says "no labels", and it is never filled in. Labels are for measurement only:
nothing from a label enters a package or a router. They are the picks of a judge model (the change 106 record names
DeepSeek-V4-Pro), so recall is agreement with that model, not truth.

``--relabel`` writes new labels with a judge model from saved runs (a paid call per query; see ``--judge``). The calls come
from the saved HANDBOOK runs, all arms, with the data the agent had read.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

POLICY_EVAL = Path(__file__).resolve().parent.parent
BENCH = POLICY_EVAL.parent
EVAL = BENCH.parent
sys.path.insert(0, str(BENCH))
GRAPHS = POLICY_EVAL / "graphs_handbook" / "claude_v1"
OUT = POLICY_EVAL / "sop_retrieval"
NO_LABELS = "no labels"
READ = re.compile(r"^(get|list|search|read|find|fetch|query|view|check|describe|lookup|retrieve)", re.I)


def pct(hit: int, total: int) -> Any:
    return round(100 * hit / total, 1) if total else NO_LABELS


def norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def query_of(row: Dict[str, Any]) -> str:
    return f"{row.get('tool', '')} {row.get('args', '')} {row.get('context', '')}"


def tokens_of(*models: Any) -> int:
    total = 0
    for m in models:
        usage = getattr(m, "usage", None) or {}
        total += int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
    return total


MUST_NOT_N = (
    5  # must-not recall@5: the rules of the first 5 procedures of the scope, fixed whatever ``--top-k`` is
)


def evaluate(
    rows: List[Dict[str, Any]],
    packages: Any,
    router: Any,
    expander: Any,
    models: Any = (),
) -> Dict[str, Any]:
    """The measures of ``router`` and ``expander`` over saved calls. ``packages(task)`` gives the package of a call. ``models``:
    the objects with ``usage`` whose tokens count (a router that needs a model).

    The procedure measures take the calls that have a procedure label. Must-not and exception recall take every call that has
    those labels, also one that governs no procedure (``label: []``): a rule may bind a call that no procedure governs."""
    from cuga.policy_layer.router import Query

    pool = [
        r for r in rows if router.name != "agent_opened" or r.get("opened") is not None
    ]  # only runs with the tools
    has_label = lambda r: bool(r.get("label")) and r["label"] != ["<error>"]  # noqa: E731
    run = [r for r in pool if has_label(r) or r.get("must_not") or r.get("exceptions")]
    hit = {1: 0, 3: 0}
    in_scope = labelled = 0
    must_labels = must_hit = exc_labels = exc_hit = 0
    selected = matches = compared = 0
    seconds = 0.0
    no_effect: List[str] = []
    tokens_before = tokens_of(*models)
    for r in run:
        pkg = packages(r["task"])
        if r["task"] not in no_effect and expander.problem(pkg):
            no_effect.append(r["task"])
        started = time.perf_counter()
        action = f"{r.get('tool', '')}({r.get('args', '')})"
        ids = router.select(
            Query(query_of(r), tuple(r.get("opened") or ()), action, r.get("context") or ""), pkg
        )
        scope = expander.expand(ids, pkg)
        seconds += time.perf_counter() - started
        selected += len(ids)
        if has_label(r):
            labelled += 1
            for k in hit:
                hit[k] += r["label"][0] in ids[:k]
            in_scope += r["label"][0] in scope.procedures
            if router.name in r:  # the ranking saved with the labels, on the length both have
                n = min(len(ids), len(r[router.name]))
                compared += 1
                matches += ids[:n] == list(r[router.name])[:n]
        first = set(scope.procedures[:MUST_NOT_N])
        near = {norm(x.text) for x in scope.rules if x.owner in first or x.owner == "escalation"}
        for text in r.get("must_not") or []:
            must_labels += 1
            must_hit += norm(text) in near
        for pid in r.get("exceptions") or []:
            exc_labels += 1
            exc_hit += str(pid) in scope.procedures
    n = labelled
    return {
        "router": router.name,
        "expander": expander.name,
        "ranked": bool(getattr(router, "ranked", True)),
        "queries": len(rows),
        "with_label": n,
        "no_procedure": sum(r.get("label") == [] for r in rows),
        "scored_calls": len(run),
        "procedure_recall@1": pct(hit[1], n),
        "procedure_recall@3": pct(hit[3], n),
        "procedure_in_scope": pct(in_scope, n),
        "must_not_recall@5": pct(must_hit, must_labels) if must_labels else NO_LABELS,
        "must_not_labels": must_labels,
        "exception_recall": pct(exc_hit, exc_labels) if exc_labels else NO_LABELS,
        "exception_labels": exc_labels,
        "avg_ids_returned": round(selected / len(run), 2) if run else 0,
        "tokens_per_query": round((tokens_of(*models) - tokens_before) / len(run), 1) if run else 0,
        "ms_per_query": round(1000 * seconds / len(run), 2) if run else 0,
        "saved_ranking_matches": f"{matches} of {compared}" if compared else "no saved ranking",
        "expander_changes_nothing_on": no_effect,
    }


def show(name: str, summary: Dict[str, Any]) -> str:
    def cell(key: str) -> str:
        v = summary[key]
        return v if v == NO_LABELS else f"{v}%"

    lines = [
        f"{name}: {summary['with_label']} calls with a procedure label of {summary['queries']} "
        f"({summary['no_procedure']} govern no procedure; {summary['scored_calls']} calls scored)",
        f"  procedure recall@1  {cell('procedure_recall@1')}"
        + ("" if summary["ranked"] else " (a set, not a ranking)"),
        f"  procedure recall@3  {cell('procedure_recall@3')}"
        + ("" if summary["ranked"] else " (a set, not a ranking)"),
        f"  procedure in scope  {cell('procedure_in_scope')}",
        f"  must-not recall@5   {cell('must_not_recall@5')}"
        + (f" ({summary['must_not_labels']} labels)" if summary["must_not_labels"] else ""),
        f"  exception recall    {cell('exception_recall')}"
        + (f" ({summary['exception_labels']} labels)" if summary["exception_labels"] else ""),
        f"  ids returned        {summary['avg_ids_returned']} per query",
        f"  tokens per query    {summary['tokens_per_query']}",
        f"  time per query      {summary['ms_per_query']} ms",
        f"  saved ranking       {summary['saved_ranking_matches']}",
    ]
    if summary["expander_changes_nothing_on"]:
        lines.append(
            f"  WARNING: {summary['expander']} changes nothing on the packages of {len(summary['expander_changes_nothing_on'])} "
            f"tasks ({', '.join(summary['expander_changes_nothing_on'])}): a result with it says nothing about the method there"
        )
    lines.append("The labels are the picks of a judge model: recall is agreement with it, not truth.")
    return "\n".join(lines)


def package_loader(template: str) -> Any:
    from cuga.policy_layer.package import load_package

    cache: Dict[str, Any] = {}

    def load(task: str) -> Any:
        path = template.replace("{task}", task)
        if path not in cache:
            cache[path] = load_package(path)
        return cache[path]

    return load


def methods(args: argparse.Namespace) -> Any:
    """The router and expander of the arguments, and the model objects whose tokens are counted."""
    from cuga.policy_layer import router as R

    needs = R.router_needs(args.router)
    options: Dict[str, Any] = (
        {} if args.top_k is None else {"top_k": args.top_k}
    )  # the router's own default: 3, as in a profile
    made: List[Any] = []
    if needs == "model":
        if not args.model:
            raise SystemExit(f"the router {args.router} needs --model (a paid call for every query)")
        from cuga.policy_layer.llm import openai_json_model

        options["model"] = openai_json_model(
            args.model, timeout=240, max_tokens=16000
        )  # as the measured router
        made.append(options["model"])
    elif needs == "ask":
        if not args.ask:
            raise SystemExit(f"the router {args.router} needs --ask (a paid call for every candidate)")
        from cuga.policy_layer.detectors import systemone_questions

        options["ask"] = systemone_questions(args.ask)
        made.append(options["ask"])
    for flag, value, read in (
        ("--top-k", args.top_k, R.router_options(args.router)),
        ("--hops", args.hops, R.expander_options(args.expand)),
    ):
        if value is not None and flag.lstrip("-").replace("-", "_") not in read:
            raise SystemExit(f"{flag} is set, and {args.router} with {args.expand} does not read it")
    hops = {} if args.hops is None else {"hops": args.hops}
    return R.make_router(args.router, **options), R.make_expander(args.expand, **hops), made


# -- new labels (a paid call for each query) ------------------------------------------------------------------------------


def _acts(tool: str) -> bool:
    name = tool.split("__", 1)[-1]
    return not tool.startswith("policy__") and not READ.match(re.sub(r"([a-z])([A-Z])", r"\1_\2", name))


def cards(graph: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"id": p["id"], "name": p["name"], "applies": str(p.get("applies_when") or "")[:300]}
        for p in graph["procedures"]
    ]


def queries(per_task: int) -> List[Dict[str, Any]]:
    random.seed(20261104)
    out = []
    for gpath in sorted(GRAPHS.glob("*.json")):
        task = gpath.stem
        seen, pool = set(), []
        for f in sorted(glob.glob(str(BENCH / "handbook/results/*" / f"{task}.json"))):
            d = json.loads(Path(f).read_text())
            reads: List[str] = []
            opened: List[str] = []
            for c in d.get("tool_calls") or []:
                tool, args = c.get("tool") or "", c.get("args") or {}
                if tool == "policy__get_procedure":
                    opened += [str(x) for x in args.get("ids") or []]
                if _acts(tool):
                    key = f"{tool}:{json.dumps(args, sort_keys=True)[:400]}"
                    if key not in seen:
                        seen.add(key)
                        pool.append(
                            {
                                "task": task,
                                "run": f.split("/")[-2],
                                "tool": tool,
                                "args": json.dumps(args, default=str)[:1200],
                                "context": "\n".join(reads[-2:])[-2000:],
                                "opened": sorted(set(opened)) if "_GW_" in f else None,
                            }
                        )
                elif not tool.startswith("policy__"):
                    reads.append(f"{tool}: {str(c.get('result'))[:1500]}")
        out += random.sample(pool, min(per_task, len(pool)))
    return out


def relabel(args: argparse.Namespace) -> None:
    from dotenv import dotenv_values

    secrets = dotenv_values(EVAL / ".env")
    for k in ("OPENAI_BASE_URL", "OPENAI_API_KEY"):
        if secrets.get(k) and not os.environ.get(k):
            os.environ[k] = secrets[k]
    from cuga.policy_layer.llm import openai_json_model, parse_json
    from cuga.policy_layer.router import LLM_SYSTEM, LLM_USER

    judge = openai_json_model(args.judge, timeout=240, max_tokens=4000)
    graphs = {p.stem: json.loads(p.read_text()) for p in GRAPHS.glob("*.json")}
    qs = queries(args.per_task)

    def ask(q: Dict[str, Any]) -> List[str]:
        text = "\n".join(f"{c['id']} | {c['name']} | {c['applies']}" for c in cards(graphs[q["task"]]))
        action = f"{q['tool']}({q['args']})"
        try:
            reply = parse_json(
                judge(
                    LLM_SYSTEM,
                    LLM_USER.format(cards=text, context=q["context"] or "(none)", action=action, top=3),
                )
            )
            return [str(x) for x in reply.get("procedures") or []][:3]
        except Exception:  # noqa: BLE001
            return ["<error>"]

    with ThreadPoolExecutor(8) as ex:
        labels = list(ex.map(ask, qs))
    rows = [{**q, "label": lab, "judge": args.judge} for q, lab in zip(qs, labels)]
    Path(args.runs).parent.mkdir(parents=True, exist_ok=True)
    Path(args.runs).write_text(json.dumps({"rows": rows}, indent=1))
    print(f"{len(rows)} calls labelled by {args.judge}, written to {args.runs}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="retrieval methods on saved acting calls with labels")
    ap.add_argument("--package", help="a package file, or a path with {task}")
    ap.add_argument("--router", default="agent_opened")
    ap.add_argument("--expand", default="next_links")
    ap.add_argument("--runs", default=str(OUT / "result.json"), help="saved calls with labels (rows)")
    ap.add_argument(
        "--top-k", type=int, help="ids a ranking router returns (default: its own, 3, as in a profile)"
    )
    ap.add_argument("--hops", type=int, help="steps of k_hops (an option of that expander only)")
    ap.add_argument("--model", help="JSON model of llm_cards (paid)")
    ap.add_argument("--ask", help="narrow-question model of bm25_kev (paid)")
    ap.add_argument("--json", dest="json_out", help="also write the measures to this file")
    ap.add_argument("--relabel", action="store_true", help="write new labels to --runs with --judge (paid)")
    ap.add_argument("--judge", default="azure/DeepSeek-V4-Pro")
    ap.add_argument("--per-task", type=int, default=40)
    args = ap.parse_args(argv)
    if args.relabel:
        relabel(args)
        return 0
    if not args.package:
        ap.error("--package is required")
    router, expander, made = methods(args)
    rows = json.loads(Path(args.runs).read_text())["rows"]
    summary = evaluate(rows, package_loader(args.package), router, expander, made)
    print(show(f"{args.router} + {args.expand}", summary))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
