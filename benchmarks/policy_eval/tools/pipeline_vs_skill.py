"""Pipeline against skill (stabilization task 3.5): can the open-model pipeline replace the Claude skill today?

    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/tools/pipeline_vs_skill.py run   --doc tau2_retail/retail --model gpt-oss
    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/tools/pipeline_vs_skill.py measure [--doc ...] [--judge azure/DeepSeek-V4-Pro]
    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/tools/pipeline_vs_skill.py render --md benchmarks/policy_eval/packages/PIPELINE_VS_SKILL.md

``run``      builds one package from the policy text and the tool schemas of one document with one model: ``builder.build_policy_set``
             (with its repairs) for the rules and ``procedure_compiler.compile_sop`` for the procedures and must-not rules. The
             input is the converted policy set that the skill package was made from (same statement ids, so the blind decision
             tests apply) and, for the compiler, the original file as markdown. Output: ``packages/<bench>/<id>/pipeline_<tag>/``
             with ``package.json`` (the builder's package; it holds no tests: `measure` reads the skill's blind tests from the skill package),
             ``compiled_graph.json`` (the compiler's graph) and ``run.json`` (calls, tokens, cost, time). Calls are metered and
             written to the ledger as they happen; the run stops when the total of this task reaches ``CAP``.
``measure``  the metrics of design section 9 for each document and model, against the skill package, on the same blind tests
             and saved runs, one denominator per row. Judge calls (must-not and procedure recall) are metered the same way and
             saved in ``pipeline_vs_skill.json`` next to the tables. Nothing here changes a package.
``render``   the tables of ``PIPELINE_VS_SKILL.md`` from ``pipeline_vs_skill.json`` (no model call, so the numbers cannot drift).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import warnings
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent.parent
BENCH = HERE.parent
EVAL = BENCH.parent
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

PACKAGES = HERE / "packages"
RESULT = PACKAGES / "pipeline_vs_skill.json"
START, END = "<!-- tables:start (tools/pipeline_vs_skill.py) -->", "<!-- tables:end -->"

BASELINE = 1625.1326  # ledger total before this task (the limit counts from here)
CAP = 8.0  # dollars for the whole task
FLUSH_EVERY = 10  # calls between ledger lines of one run

MODELS = {"gptoss": "aws/gpt-oss-120b", "dsv4": "azure/DeepSeek-V4-Pro"}
TYPE_MODEL = "azure/DeepSeek-V4-Pro"  # sorts statements by the kind of check they need
JUDGE_MODEL = "aws/gpt-oss-120b"  # cheap; its error is measured on a hand-checked sample
# the documents, in the order of the report; the original file(s) are what the skill read
DOCS = [
    "tau2_retail/retail",
    "tau2_airline/airline",
    "tau2_telecom/telecom",
    "itsm/e2891a7b98",
    "handbook/hr_crestwood_university_79786c46",
    "handbook/insurance_vanguard_shield_mutual_9b2f7a29",
    "handbook/medical_careig_specialty_pharmacy_f5947c33",
]
TAU2_DOMAINS = Path.home() / "dev/cuga-eval-tau2/benchmarks/tau2/tau2-bench/data/tau2/domains"
HANDBOOK_SAMPLE = Path.home() / "dev/untrusted/handbook-sample/tasks"


class BudgetStop(BaseException):
    """Raised when the ledger shows the task's cap. A BaseException, so that a ``except Exception`` of the pipeline does not hide it."""


# -- originals ------------------------------------------------------------------------------------------------------------


def originals(doc: str) -> List[Tuple[str, str]]:
    """``(document id, markdown)`` of the original file(s) of a document, as the skill read them."""
    bench, policy = doc.split("/")
    if bench == "handbook":
        from cuga.policy_layer.documents import _pages_markdown

        files = sorted((HANDBOOK_SAMPLE / policy / "environment" / "initial_workspace").glob("*.html"))
        return [("policy", "\n".join(md for _, md in _pages_markdown(files[0])))]
    if bench == "itsm":
        tasks = json.loads((BENCH / "enterpriseops_gym/tasks/itsm_oracle.json").read_text())
        return [("policy", next(t["system_prompt"] for t in tasks if t["_policy_hash"] == policy))]
    if bench == "tau2_telecom":
        return [
            (n, (TAU2_DOMAINS / "telecom" / f"{n}.md").read_text())
            for n in ("main_policy", "tech_support_manual")
        ]
    return [("policy", (TAU2_DOMAINS / policy / "policy.md").read_text())]


def doc_inputs(doc: str) -> Tuple[str, List[str], List[str]]:
    import coverage_matrix

    return coverage_matrix._inputs()[f"{doc}/skill_v1"]


def package_dir(doc: str, source: str) -> Path:
    bench, policy = doc.split("/")
    return PACKAGES / bench / policy / source


# -- metered model --------------------------------------------------------------------------------------------------------


def spent_here() -> float:
    import policy_pilot_costs as costs

    return costs.spent() - BASELINE


def metered(
    model_name: str,
    label: str,
    max_tokens: int = 16000,
    timeout: float = 75.0,
    kind: str = "pipeline_vs_skill",
):
    """The gateway call with a read timeout and retries, counting tokens and writing them to the ledger every few calls."""
    import policy_pilot_costs as costs
    from cuga.policy_layer.llm import openai_json_model

    inner = openai_json_model(model_name, timeout=timeout, max_tokens=max_tokens)
    seen = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    lock = threading.Lock()
    stats = {"failed_calls": 0}

    def flush() -> None:
        with lock:
            snap = {
                k: inner.usage[k] for k in seen
            }  # one reading: a call that ends meanwhile is in the next one
            delta = {k: snap[k] - seen[k] for k in seen}
            if delta["calls"]:
                costs.record(kind, label, policy={**delta, "model": model_name})
                seen.update(snap)

    def call(system: str, user: str) -> str:
        if spent_here() >= CAP:
            flush()
            raise BudgetStop(f"the task's cap of ${CAP} is reached: {costs.line()}")
        last: Optional[Exception] = None
        for attempt in range(4):
            try:
                out = inner(system, user)
                break
            except Exception as exc:  # noqa: BLE001 - gateway hangs and 5xx: wait and ask again
                last = exc
                time.sleep(3 * (attempt + 1))
        else:
            stats["failed_calls"] += 1
            flush()
            raise last  # type: ignore[misc]
        if inner.usage["calls"] - seen["calls"] >= FLUSH_EVERY:
            flush()
        return out

    call.model_name = model_name  # type: ignore[attr-defined]
    call.usage = inner.usage  # type: ignore[attr-defined]
    call.flush = flush  # type: ignore[attr-defined]
    call.stats = stats  # type: ignore[attr-defined]
    return call


def cost_of(model_name: str, usage: Dict[str, Any]) -> float:
    import policy_pilot_costs as costs

    return costs.usage_cost(model_name, usage)


def _env() -> None:
    from dotenv import dotenv_values

    secrets = dotenv_values(EVAL / ".env")
    for k in ("OPENAI_BASE_URL", "OPENAI_API_KEY"):
        if secrets.get(k) and not os.environ.get(k):
            os.environ[k] = secrets[k]


# -- run ------------------------------------------------------------------------------------------------------------------


def merge_graphs(graphs: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """The graphs of several documents of one policy as one: procedure ids get the document id in front."""
    if len(graphs) == 1:
        return graphs[0][1]
    out: Dict[str, Any] = {
        "id": "+".join(n for n, _ in graphs),
        "version": "compiled",
        "procedures": [],
        "templates": {},
    }
    for name, g in graphs:
        for p in g.get("procedures") or []:
            out["procedures"].append({**p, "id": f"{name}:{p['id']}", "src": f"{name} {p.get('src', '')}"})
        for k, v in (g.get("templates") or {}).items():
            out["templates"][f"{name}:{k}"] = v
        for k in ("global_rules", "definitions", "routing"):
            if g.get(k):
                cur = out.get(k)
                if isinstance(g[k], list):
                    out[k] = (cur or []) + g[k]
                else:
                    out[k] = {**(cur or {}), **g[k]}
        for k in ("triage", "housekeeping", "priority", "escalation"):
            if g.get(k) and not out.get(k):
                out[k] = g[k]
    out["built_by"] = graphs[0][1].get("built_by")
    return out


def run(
    doc: str, tag: str, stages: Iterable[str] = ("build", "compile"), replace: bool = False
) -> Dict[str, Any]:
    _env()
    from cuga.policy_layer.builder import build_policy_set
    from cuga.policy_layer.model import PolicySet, from_json, to_json
    from cuga.policy_layer.package import from_build, load_package, save_package
    from cuga.policy_layer.procedure_compiler import compile_sop
    from cuga.policy_layer.validate import validate_package

    model_name = MODELS[tag]
    bench, policy = doc.split("/")
    skill_dir = package_dir(doc, "skill_v1")
    out = package_dir(doc, f"pipeline_{tag}")
    kept = {"build": "package.json", "compile": "compiled_graph.json"}
    for stage in stages:
        if (out / kept[stage]).exists() and not replace:
            raise SystemExit(f"{out / kept[stage]}: exists (use --replace); nothing is overwritten")
    out.mkdir(parents=True, exist_ok=True)
    tools_path = doc_inputs(doc)[0]
    specs = json.loads(Path(tools_path).read_text())
    specs = specs if isinstance(specs, list) else specs.get("tools", [])
    skill = load_package(skill_dir / "package.json")
    info: Dict[str, Any] = {
        "doc": doc,
        "tag": tag,
        "model": model_name,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    existing = out / "run.json"
    if existing.exists():
        info = {**json.loads(existing.read_text()), **{"resumed": time.strftime("%Y-%m-%d %H:%M:%S")}}
    label = f"{doc}:pipeline_{tag}"

    if "build" in stages:
        m = metered(model_name, label + ":build")
        t0 = time.time()
        ps = from_json(PolicySet, json.loads((skill_dir / "set.json").read_text()))
        try:
            b = build_policy_set(ps, specs, m, cache_dir=out / "cache", repair=True)
        finally:
            m.flush()
        raw = {
            "policy_hash": skill.policy_hash,
            "rules": [r.rule for r in b.rules],
            "procedures": to_json(b.procedures),
            "build": to_json(b),
            "policy_set": to_json(ps),
        }
        pkg = from_build(raw)
        save_package(pkg, out / "package.json")
        usage = dict(m.usage)
        found = Counter(f.code for f in validate_package(pkg, specs, legacy=False))
        info["build"] = {
            "usage": usage,
            "cost": round(cost_of(model_name, usage), 4),
            "seconds": round(time.time() - t0),
            "failed_calls": m.stats["failed_calls"],
            "stats": {k: v for k, v in b.stats.items() if k != "usage"},
            "validate_legacy_false": dict(found),
        }
        print(
            label, "build", json.dumps({k: v for k, v in info["build"].items() if k != "stats"}), flush=True
        )

    if "compile" in stages:
        m = metered(model_name, label + ":compile")
        t0 = time.time()
        graphs = []
        try:
            for doc_id, text in originals(doc):
                graphs.append((doc_id, compile_sop(text, m, doc_id=doc_id)))
        finally:
            m.flush()
        graph = merge_graphs(graphs)
        (out / "compiled_graph.json").write_text(json.dumps(graph, indent=1, ensure_ascii=False))
        usage = dict(m.usage)
        info["compile"] = {
            "usage": usage,
            "cost": round(cost_of(model_name, usage), 4),
            "seconds": round(time.time() - t0),
            "failed_calls": m.stats["failed_calls"],
            "checks": [g.get("checks") for _, g in graphs],
            "procedures": len(graph.get("procedures") or []),
        }
        print(label, "compile", json.dumps(info["compile"]), flush=True)
    info["cost"] = round(sum(info[s]["cost"] for s in ("build", "compile") if s in info), 4)
    existing.write_text(json.dumps(info, indent=1))
    return info


# -- text helpers ---------------------------------------------------------------------------------------------------------

FOLD = str.maketrans(
    {"–": "-", "—": "-", "‑": "-", "−": "-", "’": "'", "‘": "'", "“": '"', "”": '"', " ": " "}
)


def norm(text: Any) -> str:
    """Case, spacing, dashes and quotes folded, no final full stop: the form two texts are compared in."""
    return re.sub(r"\s+", " ", str(text or "").translate(FOLD)).strip().lower().rstrip(". ")


def words(text: Any) -> set:
    return set(re.findall(r"[a-z0-9$%]{3,}", norm(text)))


def rank(ref: str, pool: List[Dict[str, Any]], k: int) -> List[Dict[str, Any]]:
    """The ``k`` items of ``pool`` that share most words with ``ref`` (only to choose what the judge reads; the judge decides)."""
    a = words(ref)
    scored = []
    for item in pool:
        b = words(item["text"])
        if a and b and a & b:
            scored.append((len(a & b) / (len(a) * len(b)) ** 0.5, item))
    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:k]]


# -- the judge -------------------------------------------------------------------------------------------------------------

JUDGE_SYSTEM = "You compare statements of a company policy. Answer with JSON only."
MUST_NOT_USER = """Reference prohibition, from a policy:
<<<{ref}>>>

Candidates, from a machine-made procedure:
{candidates}

Stated rule: a candidate matches when it forbids the reference's action in the reference's situation, with the same values
and limits. It may be worded more generally, or leave out a lead-in that only names the context. It does not match when it
forbids only a part of the case (narrower), has other values or limits, covers another case, or says the opposite. Decide by
meaning, not by shared words.
Return {{"match": <number of the best matching candidate, or null>, "why": "<one short sentence>"}}"""
PROC_USER = """Reference procedure, from a policy:
name: {name}
applies when: {applies}
steps:
{steps}

Candidate procedures, from a machine-made graph:
{candidates}

Stated rule: a candidate matches when it covers the same workflow (the same trigger and the same case). Then say which
steps of the reference procedure the candidate also holds: a step is held when the candidate has a step that does the same
action on the same thing, with the same value, template or deadline, in other words or as a part of a longer step.
Return {{"match": <number of the best matching candidate, or null>, "steps_held": [<numbers of the reference steps held>], "why": "<one short sentence>"}}"""


class Judge:
    """A model that answers JSON. Answers are kept in a file by the hash of the prompt, so a re-run costs nothing."""

    def __init__(
        self, call: Optional[Callable[[str, str], str]], cache: Optional[Path] = None, name: str = JUDGE_MODEL
    ):
        self.call, self.name, self.path = call, name, cache
        self.cache: Dict[str, Any] = json.loads(cache.read_text()) if cache and cache.exists() else {}
        self.hits = self.asked = 0

    def ask(self, system: str, user: str) -> Dict[str, Any]:
        import hashlib

        from cuga.policy_layer.llm import parse_json

        key = hashlib.sha256(f"{self.name}|{system}|{user}".encode()).hexdigest()[:20]
        if key in self.cache:
            self.hits += 1
            return self.cache[key]["answer"]
        if self.call is None:
            raise RuntimeError("the judge has no model and the answer is not in the cache")
        answer = parse_json(self.call(system, user))
        self.asked += 1
        self.cache[key] = {"model": self.name, "answer": answer}
        if self.path:
            self.path.write_text(json.dumps(self.cache, indent=1, ensure_ascii=False))
        return answer


def _pick(answer: Dict[str, Any], n: int) -> Optional[int]:
    m = answer.get("match")
    return m - 1 if isinstance(m, int) and 1 <= m <= n else None


# -- must-not and procedure recall -----------------------------------------------------------------------------------------


def skill_must_nots(pkg: Any) -> List[str]:
    """The must-not texts of the skill package's procedures, each once (the same sentence in two procedures counts once)."""
    seen: Dict[str, str] = {}
    for p in pkg.procedures:
        for text in p.must_not or []:
            seen.setdefault(norm(text), text)
    return list(seen.values())


def _texts(items: Any, *keys: str) -> List[str]:
    return [str(x.get(k)) for x in items or [] if isinstance(x, dict) for k in keys if x.get(k)]


def pipeline_pools(
    pkg: Any, graph: Optional[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Where a pipeline keeps a prohibition. Pool A is the place the skill puts it: the ``must_not`` of a procedure (the
    compiler's, and the builder's), the escalation's ``must_not``, and the builder's procedure exceptions and preconditions
    (each with the verbatim statement). Pool B adds every other text of the package that could state it: the compiler's
    global rules and steps, the builder's steps and the quote of every rule."""
    a: List[Dict[str, Any]] = []
    b: List[Dict[str, Any]] = []

    def add(pool: List[Dict[str, Any]], texts: Iterable[str], where: str) -> None:
        pool += [{"text": t, "where": where} for t in texts if t]

    graph = graph or {}
    for p in graph.get("procedures") or []:
        add(a, [x for x in p.get("must_not") or [] if isinstance(x, str)], f"compiled {p['id']} must_not")
        add(b, [x for x in p.get("steps") or [] if isinstance(x, str)], f"compiled {p['id']} step")
    esc = graph.get("escalation") or {}
    add(a, [x for x in esc.get("must_not") or [] if isinstance(x, str)], "compiled escalation must_not")
    for g in graph.get("global_rules") or []:
        add(b, [g.get("rule") if isinstance(g, dict) else str(g)], "compiled global rule")
    for p in pkg.procedures:
        add(a, p.must_not or [], f"builder {p.id} must_not")
        add(a, _texts(p.exceptions, "quote"), f"builder {p.id} exception")
        add(a, _texts(p.preconditions, "quote"), f"builder {p.id} precondition")
        add(b, [s.text or s.action or s.quote for s in p.steps], f"builder {p.id} step")
    for r in pkg.rules:
        add(b, [r.quote], f"builder rule {r.id}")

    def dedupe(pool: List[Dict[str, Any]], seen: set) -> List[Dict[str, Any]]:
        out = []
        for it in pool:
            key = norm(it["text"])
            if key and key not in seen:
                seen.add(key)
                out.append(it)
        return out

    seen: set = set()
    a = dedupe(a, seen)
    return a, a + dedupe(b, seen)


def _match(ref: str, pool: List[Dict[str, Any]], judge: Judge, k: int = 8) -> Dict[str, Any]:
    """One reference text against a pool: verbatim (the pool text holds the reference), else the judge on the best candidates."""
    r = norm(ref)
    for it in pool:
        if r and r in norm(it["text"]):
            return {"how": "verbatim", "match": it["text"], "where": it["where"]}
    cands = rank(ref, pool, k)
    if not cands:
        return {"how": "none", "match": None}
    listing = "\n".join(f"[{i}] {c['text']}" for i, c in enumerate(cands, 1))
    ans = judge.ask(JUDGE_SYSTEM, MUST_NOT_USER.format(ref=ref, candidates=listing))
    i = _pick(ans, len(cands))
    if i is None:
        return {"how": "none", "match": None, "why": ans.get("why", ""), "judged": [c["text"] for c in cands]}
    return {"how": "judge", "match": cands[i]["text"], "where": cands[i]["where"], "why": ans.get("why", "")}


def recall_must_nots(
    refs: List[str], pool_a: List[Dict[str, Any]], pool_b: List[Dict[str, Any]], judge: Judge
) -> Dict[str, Any]:
    items = []
    only_b = [it for it in pool_b if it not in pool_a]
    for ref in refs:
        a = _match(ref, pool_a, judge)
        b = a if a["match"] is not None else _match(ref, only_b, judge)
        items.append({"ref": ref, "A": a, "B": b})
    return {
        "skill": len(refs),
        "A": sum(i["A"]["match"] is not None for i in items),
        "B": sum(i["B"]["match"] is not None for i in items),
        "judged": sum(i["A"]["how"] == "judge" or i["B"]["how"] == "judge" for i in items),
        "items": items,
    }


def must_not_sources(recall: Dict[str, Any], pool_a: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Where the matched must-nots of pool ``A`` come from. ``compiler``: a ``must_not`` list of the compiler's graph (procedures and
    escalation). ``builder``: the builder's procedures (exceptions, preconditions, ``must_not``), which often hold the statement's
    verbatim quote. A skill text is counted once, under the source of the text it matched. A verbatim match takes the first pool
    text that holds it, and the compiler's texts come first; a judge match takes the text the judge named. So the compiler's
    share is a floor: the judge may name a builder text when a compiler text also fits."""

    def source(where: str) -> str:
        return "compiler" if where.startswith("compiled") else "builder"

    matched = {"compiler": 0, "builder": 0}
    texts: Dict[str, set] = {"compiler": set(), "builder": set()}
    for it in recall["items"]:
        a = it["A"]
        if a["match"] is not None:
            matched[source(a["where"])] += 1
            texts[source(a["where"])].add(norm(a["match"]))
    pool = {"compiler": 0, "builder": 0}
    for it in pool_a:
        pool[source(it["where"])] += 1
    return {
        "recalled": matched,
        "pool": pool,
        "pool_matched": {k: len(v) for k, v in texts.items()},
        "pool_matching_no_skill_text": {k: pool[k] - len(texts[k]) for k in pool},
    }


def skill_procedures(pkg: Any) -> List[Dict[str, Any]]:
    return [
        {
            "id": p.id,
            "name": p.name,
            "applies_when": p.applies_when or "",
            "steps": [s.text or s.action or s.quote for s in p.steps],
            "step_ids": [s.id for s in p.steps if s.id],
        }
        for p in pkg.procedures
    ]


def compiled_procedures(graph: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "id": p["id"],
            "name": p.get("name") or "",
            "applies_when": p.get("applies_when") or "",
            "steps": [x for x in p.get("steps") or [] if isinstance(x, str)],
        }
        for p in (graph or {}).get("procedures") or []
    ]


def _proc_text(p: Dict[str, Any]) -> str:
    return " ".join([p["name"], p["applies_when"]] + p["steps"])


def recall_procedures_judged(
    skill: List[Dict[str, Any]], pool: List[Dict[str, Any]], judge: Judge, k: int = 5
) -> Dict[str, Any]:
    """Each skill procedure against the compiler's procedures (they carry no statement ids): the judge names the covering procedure
    and the steps it holds. A procedure is recalled when a candidate covers it and holds at least half of its steps."""
    items = []
    for sp in skill:
        scored = rank(_proc_text(sp), [{"text": _proc_text(p), "p": p} for p in pool], k)
        cands = [c["p"] for c in scored]
        held: List[int] = []
        match = None
        why = ""
        if cands:
            steps = "\n".join(f"{i}. {t[:240]}" for i, t in enumerate(sp["steps"], 1)) or "(no steps)"
            listing = "\n".join(
                f"[{i}] {c['name']} | applies when: {c['applies_when'][:160]}\n"
                + "\n".join(f"    - {t[:160]}" for t in c["steps"][:14])
                for i, c in enumerate(cands, 1)
            )
            ans = judge.ask(
                JUDGE_SYSTEM,
                PROC_USER.format(
                    name=sp["name"], applies=sp["applies_when"], steps=steps, candidates=listing
                ),
            )
            i = _pick(ans, len(cands))
            why = ans.get("why", "")
            if i is not None:
                match = cands[i]["id"]
                held = sorted(
                    {
                        n
                        for n in ans.get("steps_held") or []
                        if isinstance(n, int) and 1 <= n <= len(sp["steps"])
                    }
                )
        items.append(
            {
                "id": sp["id"],
                "steps": len(sp["steps"]),
                "match": match,
                "held": len(held),
                "why": why,
                "asked": bool(cands),
            }
        )
    return _proc_totals(items)


def recall_procedures_by_ids(skill: List[Dict[str, Any]], pkg: Any) -> Dict[str, Any]:
    """Each skill procedure against the builder's procedures by statement id: the builder procedure that holds most of the skill
    procedure's step statements; recalled when it holds at least half of them."""
    items = []
    for sp in skill:
        ids = set(sp["step_ids"])
        best, best_n = None, 0
        for p in pkg.procedures:
            n = len(ids & {s.id for s in p.steps})
            if n > best_n:
                best, best_n = p.id, n
        items.append(
            {"id": sp["id"], "steps": len(ids) or len(sp["steps"]), "match": best, "held": best_n, "why": ""}
        )
    return _proc_totals(items)


def _proc_totals(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "skill": len(items),
        "recalled": sum(i["match"] is not None and i["held"] * 2 >= i["steps"] for i in items),
        "steps": sum(i["steps"] for i in items),
        "steps_held": sum(i["held"] for i in items if i["match"] is not None),
        "items": items,
    }


# -- the rule side: the same blind tests and saved runs for every package ---------------------------------------------------


def _severity(finding: Any) -> str:
    return getattr(finding, "severity", "error")


def validation_counts(pkg: Any, specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    from cuga.policy_layer.validate import validate_package

    found = validate_package(pkg, specs, legacy=False)
    errors = Counter(f.code for f in found if _severity(f) != "warning")
    warns = Counter(f.code for f in found if _severity(f) == "warning")
    return {
        "errors": sum(errors.values()),
        "warnings": sum(warns.values()),
        "error_codes": dict(sorted(errors.items())),
        "warning_codes": dict(sorted(warns.items())),
    }


def is_fragment(text: str) -> bool:
    """A statement that is not a whole sentence: fewer than 5 words, or it starts with a lower-case letter."""
    t = text.strip()
    return len(t.split()) < 5 or t[:1].islower()


def fragments_typed_must(pkg: Any) -> Dict[str, Any]:
    from cuga.policy_layer.validate import statement_outcomes

    outcomes = statement_outcomes(pkg)
    typed = [
        st
        for d in pkg.documents
        for st in d.statements
        if str(getattr(st.modality, "value", st.modality)) in ("must", "must_not")
    ]
    frag = [st for st in typed if is_fragment(st.text)]
    return {
        "typed_must": len(typed),
        "fragments": len(frag),
        "fragments_without_outcome": sum(1 for st in frag if not outcomes.get(st.id)),
        "examples": [st.text[:60] for st in frag[:3]],
    }


def lost_checks(skill: Any, pipe: Any) -> Dict[str, Any]:
    """Statements that the skill enforces with a hard (code) rule, and the pipeline made a procedure step only: no rule, no
    obligation, no question names them. The step carries a checkable value and nothing enforces it."""
    from cuga.policy_layer.validate import statement_outcomes

    wanted = sorted({sid for r in skill.rules if r.cls == "hard" for sid in r.statement_ids})
    outcomes = statement_outcomes(pipe)
    lost = [sid for sid in wanted if outcomes.get(sid) == ["procedure_step"]]
    bare = [sid for sid in wanted if not outcomes.get(sid)]
    return {"skill_hard_statements": len(wanted), "step_only": lost, "no_outcome": bare}


def rule_side(
    spec: str, tools: str, runs: List[str], roles: List[str], tests: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """The rules of one package on the blind tests (``tests``, or the package's own) and the saved runs."""
    import tempfile

    import coverage_matrix as cm
    import rule_audit as ra

    t = ra.load_target(spec)
    specs = ra.read_specs(tools)
    cases = tests if tests is not None else t.pkg.tests
    tests_file = ""
    if tests is not None:
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(tests, handle)
        handle.close()
        tests_file = handle.name
    tr = ra.tests_run(t, specs, tests_file, save=False) if cases else {"status": "no tests"}
    out: Dict[str, Any] = {
        "package": spec,
        "label": list(__import__("audit_report").basis_of(t.bench, t.policy, t.build)),
        "tests": cm._test_numbers(tr),
        "replay": cm._replay_numbers(ra.replay(t, specs, runs, roles, save=False))
        if runs
        else {"status": "no runs"},
        "validate": validation_counts(t.pkg, specs),
        "procedures": len(t.pkg.procedures),
        "must_nots": len(skill_must_nots(t.pkg)),
        "rules": len(t.pkg.rules),
        "verify_rules": sum(1 for r in t.pkg.rules if r.type == "verify"),
        "rule_types": dict(sorted(Counter(r.type for r in t.pkg.rules).items())),
        "false_deny_types": false_deny_types(tr),
        "threshold_on_text": threshold_on_text(t.pkg, specs, ra),
    }
    return out


def false_deny_types(tr: Dict[str, Any]) -> Dict[str, int]:
    """The rule types that denied the allow tests (schema-accepted): each denied test counts once for every type that fired."""
    found: Counter = Counter()
    for row in tr.get("rows") or []:
        if row["case"]["expected"] == "allow" and not row.get("schema") and row["decision"] == "deny":
            found.update({f["type"] for f in row.get("fired") or [] if f.get("outcome") == "deny"})
    return dict(sorted(found.items()))


def threshold_on_text(pkg: Any, specs: List[Dict[str, Any]], ra: Any) -> int:
    """Threshold rules whose argument the tool schema types as a string: a number read out of an id or a name."""
    kinds = {s["name"]: ra.schema_of(s).get("properties") or {} for s in specs}
    return sum(
        1
        for r in pkg.rules
        if r.type == "threshold"
        and (kinds.get(r.rule.get("tool"), {}).get(r.rule.get("arg")) or {}).get("type") == "string"
    )


def skill_of(doc: str) -> Any:
    from cuga.policy_layer.package import load_package

    return load_package(package_dir(doc, "skill_v1") / "package.json")


def measure_doc(doc: str, judge: Judge, tags: Iterable[str]) -> Dict[str, Any]:
    from cuga.policy_layer.package import load_package

    bench, policy = doc.split("/")
    tools, runs, roles = doc_inputs(doc)
    skill_pkg = load_package(package_dir(doc, "skill_v1") / "package.json")
    res: Dict[str, Any] = {"skill": rule_side(f"{doc}/skill_v1", tools, runs, roles), "pipelines": {}}
    refs = skill_must_nots(skill_pkg)
    sprocs = skill_procedures(skill_pkg)
    for tag in tags:
        folder = package_dir(doc, f"pipeline_{tag}")
        if not (folder / "package.json").exists():
            continue
        pkg = load_package(folder / "package.json")
        graph = (
            json.loads((folder / "compiled_graph.json").read_text())
            if (folder / "compiled_graph.json").exists()
            else None
        )
        info = json.loads((folder / "run.json").read_text()) if (folder / "run.json").exists() else {}
        side = rule_side(f"{doc}/pipeline_{tag}", tools, runs, roles, list(skill_pkg.tests))
        a, b = pipeline_pools(pkg, graph)
        side["must_not_recall"] = recall_must_nots(refs, a, b, judge)
        side["must_not_sources"] = must_not_sources(side["must_not_recall"], a)
        side["procedure_recall"] = {
            "compiled": recall_procedures_judged(sprocs, compiled_procedures(graph), judge)
            if graph
            else None,
            "builder": recall_procedures_by_ids(sprocs, pkg),
            "made": {
                "compiled": len(compiled_procedures(graph)) if graph else 0,
                "builder": len([p for p in pkg.procedures if p.steps]),
            },
        }
        side["defects"] = {
            "quote_not_verbatim": side["validate"]["error_codes"].get("quote_not_verbatim", 0),
            "lost_checks": lost_checks(skill_pkg, pkg),
            "fragments": fragments_typed_must(pkg),
            "threshold_on_text": side["threshold_on_text"],
        }
        side["cost"] = {
            "build": (info.get("build") or {}).get("cost"),
            "compile": (info.get("compile") or {}).get("cost"),
            "total": info.get("cost"),
            "seconds": sum((info.get(s) or {}).get("seconds", 0) for s in ("build", "compile")),
            "calls": sum(
                ((info.get(s) or {}).get("usage") or {}).get("calls", 0) for s in ("build", "compile")
            ),
            "failed_calls": sum((info.get(s) or {}).get("failed_calls", 0) for s in ("build", "compile")),
            "model": info.get("model"),
        }
        res["pipelines"][tag] = side
    return res


def section_detection(doc: str) -> Dict[str, Any]:
    """What ``compile_sop`` would take as a procedure, offline (no model): the sections it selects as the file is, with a leading
    ``**`` removed from each line, and with a ``*`` bullet also read as ``-``. Also the characters of the general sections that
    the call over them drops (``general_text[:40000]``). The two readings are not changes to the compiler."""
    from cuga.policy_layer.procedure_compiler import _is_procedure, split_sections, templates_of

    def count(text: str) -> Tuple[int, int]:
        secs = split_sections(text)
        tsec = {t["section"] for t in templates_of(secs).values()}
        picked = [
            x
            for x in secs
            if not (x["id"] in tsec or (x["children"] and not x["body"].strip()) or not _is_procedure(x))
        ]
        general = "\n".join(
            f"## {x['title']}\n{x['body']}" for x in secs if x["id"] not in tsec and not _is_procedure(x)
        )
        return len(picked), max(0, len(general) - 40000)

    def no_stars(text: str) -> str:
        return "\n".join(re.sub(r"^(\s*)\*\*", r"\1", ln) for ln in text.split("\n"))

    def bullets(text: str) -> str:
        return "\n".join(re.sub(r"^(\s*)\*\s+", r"\1- ", ln) for ln in no_stars(text).split("\n"))

    out = {"as_is": 0, "stars_removed": 0, "bullets_too": 0, "general_chars_cut": 0}
    for _, text in originals(doc):
        out["as_is"] += count(text)[0]
        out["stars_removed"] += count(no_stars(text))[0]
        out["bullets_too"] += count(bullets(text))[0]
        out["general_chars_cut"] += count(text)[1]
    return out


# -- the bar of design section 9 ---------------------------------------------------------------------------------------------


def pct(n: float, d: float) -> float:
    return 100.0 * n / d if d else 0.0


def bar(skill: Dict[str, Any], pipe: Dict[str, Any]) -> Dict[str, Any]:
    """The three conditions: catches not more than 5 points below the skill, false denies not higher, must-not recall at least 80%."""
    s, p = skill["tests"], pipe["tests"]
    s_pct, p_pct = (
        pct(s["caught_by_rules"], s["clean_deny_cases"]),
        pct(p["caught_by_rules"], p["clean_deny_cases"]),
    )
    recall = pipe["must_not_recall"]
    r_pct = pct(recall["A"], recall["skill"]) if recall["skill"] else None
    return {
        "catches": {
            "skill": s_pct,
            "pipeline": p_pct,
            "ok": p_pct >= s_pct - 5.0,  # one-sided: not more than 5 points below the skill
            "cannot_fail": s_pct - 5.0
            <= 0,  # the skill is under 5%: the threshold is zero or less, an empty package passes
            "allow_denied": pct(p["false_deny"], p["clean_allow_cases"]),
            "skill_allow_denied": pct(s["false_deny"], s["clean_allow_cases"]),
        },
        "false_denies": {
            "skill": s["false_deny"],
            "pipeline": p["false_deny"],
            "of": p["clean_allow_cases"],
            "ok": p["false_deny"] <= s["false_deny"],
        },
        "must_not": {"recall": r_pct, "ok": r_pct is None or r_pct >= 80.0},
        "validate_errors": pipe["validate"]["errors"],  # not one of the three conditions; shown beside them
    }


def all_met(b: Dict[str, Any]) -> bool:
    return all(b[k]["ok"] for k in ("catches", "false_denies", "must_not"))


BENCH_OF = {
    "handbook": "HANDBOOK (SOPs)",
    "itsm": "ITSM (EnterpriseOps-Gym)",
    "tau2_telecom": "tau2 Telecom",
    "tau2_airline": "tau2 airline",
    "tau2_retail": "tau2 retail",
}
BENCH_ORDER = ["tau2_retail", "tau2_airline", "tau2_telecom", "itsm", "handbook"]


def failures(b: Dict[str, Any]) -> List[str]:
    out = []
    if not b["catches"]["ok"]:
        out.append(f"catches {b['catches']['pipeline']:.1f}% against {b['catches']['skill']:.1f}%")
    if not b["false_denies"]["ok"]:
        out.append(f"false denies {b['false_denies']['pipeline']} against {b['false_denies']['skill']}")
    if not b["must_not"]["ok"]:
        out.append(f"must-not recall {b['must_not']['recall']:.0f}%")
    return out


def verdicts(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One row per benchmark. A model can replace the skill for a benchmark when every document of the benchmark that was run
    with it meets all three conditions; the row says no otherwise, with the conditions the best model missed."""
    rows = []
    for bench in BENCH_ORDER:
        docs = {d: r for d, r in result["docs"].items() if d.split("/")[0] == bench}
        if not docs:
            continue
        per_model: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
        for d, r in docs.items():
            for tag, side in r["pipelines"].items():
                per_model.setdefault(tag, []).append((d, bar(r["skill"], side)))
        scored = []
        for tag, items in per_model.items():
            miss = [(d.split("/")[1][:14], f) for d, b in items for f in failures(b)]
            scored.append((len(miss), tag, miss, len(items)))
        scored.sort(key=lambda x: (x[0], x[1]))
        if not scored:
            rows.append({"bench": bench, "docs": 0, "answer": "not measured", "reason": "no pipeline run"})
            continue
        best = scored[0]
        yes = [s for s in scored if s[0] == 0]
        if yes:
            tags = ", ".join(MODEL_LABEL[s[1]] for s in yes)
            broken = [
                f"{d.split('/')[1][:14]} {b['validate_errors']}"
                for d, r in docs.items()
                for tag, side in r["pipelines"].items()
                if tag in {s[1] for s in yes}
                for b in [bar(r["skill"], side)]
                if b["validate_errors"]
            ]
            rows.append(
                {
                    "bench": bench,
                    "docs": best[3],
                    "answer": f"yes ({tags})",
                    "reason": "all three conditions met on every document run with it"
                    + (f"; `validate` errors of the package: {', '.join(broken)}" if broken else ""),
                }
            )
        else:
            why = "; ".join(f"{d}: {f}" for d, f in best[2][:3]) + (" ..." if len(best[2]) > 3 else "")
            rows.append(
                {
                    "bench": bench,
                    "docs": best[3],
                    "answer": "no",
                    "reason": f"best model {MODEL_LABEL[best[1]]}, missed {len(best[2])}: {why}",
                }
            )
    return rows


MODEL_LABEL = {"gptoss": "gpt-oss-120b", "dsv4": "DeepSeek-V4-Pro"}


# -- the evidence on missing rule types --------------------------------------------------------------------------------------

WANTED_TYPES = {
    "text_match": "the rule checks whether a text argument (a message body, a field, a name) contains or does not contain given words, a phrase, or a kind of content that a fixed pattern can find (bank details, an attachment mention, a template name)",
    "when_prefix": "the case in which the rule applies depends on an argument text that starts with a given prefix (a subject that starts with a reply marker, an id that starts with a code)",
    "forbid_tool": "a tool must not be called at all, or not for a case that the call's own arguments or the conversation name, with nothing to read first (no data condition)",
    "array": "the rule checks the number of items in a list argument, or each item of a list argument (passengers, items, bags, payment methods)",
    "record_compare": "the rule compares an argument with a field of a stored record that must be read first, by a comparison and not by equality to a fixed value (a balance covers a total, a stored date is before another, a field of the record is not empty, the new item has the same product as the old one)",
}
TYPE_SYSTEM = "You sort statements of company policies by the kind of automatic check they would need. Answer with JSON only."
TYPE_TAIL = """

Statements:
{statements}

Return {{"answers": [{{"n": <number>, "kinds": ["<name>", ...]}}]}}"""
# Two readings of the same question. A model sorts these statements with different errors under each: the loose one names a kind
# for statements that also need judgment, the strict one leaves out statements that a check of the kind would nearly decide.
# A kind named by both is counted as wanted; a kind named by one is counted as possible. A sample is checked by hand.
TYPE_USER = {
    "loose": """Kinds of check that are NOT available as a rule type today:
{kinds}

For each statement, list the kinds above that an automatic check of one tool call would need in order to enforce it. A
statement may need several kinds, or none (it needs judgment about meaning, a sequence of calls, or another kind of check). Use
only the names above."""
    + TYPE_TAIL,
    "strict": """Kinds of check that are NOT available as a rule type today:
{kinds}

For each statement, list the kinds above that a check of ONE tool call would need in order to decide the statement. Name a kind
only when a check of that kind would be enough to decide the statement for a call. When the statement also needs judgment
about meaning (the sentiment of a message, whether an e-mail is a legal threat, whether a request is in scope), a sequence of
calls, a computed value, or a role, answer an empty list. Use only the names above."""
    + TYPE_TAIL,
}
MISSING_BAR = 2  # spec section 4: a new rule type needs statements from at least this many benchmarks
BENCHMARK_OF = {
    "tau2_telecom": "tau2",
    "tau2_airline": "tau2",
    "tau2_retail": "tau2",
    "handbook": "handbook",
    "itsm": "itsm",
    "automationbench": "automationbench",
}


def verify_statements(packages: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    """The ``verify`` rules of the packages, one per statement and benchmark (the 9 ITSM versions share their text)."""
    seen: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for key, pkgs in packages.items():
        for pkg in pkgs:
            for r in pkg.rules:
                statement = str(r.rule.get("statement") or r.quote or "").strip()
                if r.type == "verify" and statement:
                    seen.setdefault(
                        (BENCHMARK_OF[key], norm(statement)),
                        {"bench": BENCHMARK_OF[key], "source": key, "rule": r.id, "statement": statement},
                    )
    return list(seen.values())


def type_demand(
    items: List[Dict[str, Any]],
    judge: Judge,
    batch: int = 20,
    corrections: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """For each missing type, the ``verify`` statements that need it, over all benchmarks. The model reads the definitions above and
    sorts the statements twice (``TYPE_USER``); its answers are kept, and a sample is checked by hand. A kind named by both
    readings is ``wanted``; a kind named by one only is ``possible``."""
    kinds = "\n".join(f"- {k}: {v}" for k, v in WANTED_TYPES.items())
    for reading, prompt in TYPE_USER.items():
        for start in range(0, len(items), batch):
            chunk = items[start : start + batch]
            listing = "\n".join(f"{i}. {c['statement'][:300]}" for i, c in enumerate(chunk, 1))
            ans = judge.ask(TYPE_SYSTEM, prompt.format(kinds=kinds, statements=listing))
            got = {a.get("n"): a.get("kinds") or [] for a in ans.get("answers") or [] if isinstance(a, dict)}
            for i, c in enumerate(chunk, 1):
                c[reading] = [k for k in got.get(i, []) if k in WANTED_TYPES]
    for fix in corrections or []:  # a statement the sorter misread, found by hand: the kinds are taken off it
        for c in items:
            if c["rule"] == fix["rule"]:
                for reading in ("loose", "strict"):
                    c[reading] = [k for k in c[reading] if k not in fix["remove"]]
    for c in items:
        c["kinds"] = [k for k in WANTED_TYPES if k in c["loose"] and k in c["strict"]]
        c["possible"] = [k for k in WANTED_TYPES if (k in c["loose"]) != (k in c["strict"])]
    out: Dict[str, Any] = {
        "verify_statements": len(items),
        "by_benchmark": dict(sorted(Counter(i["bench"] for i in items).items())),
        "by_type": {},
    }
    for name in WANTED_TYPES:
        wanted = [i for i in items if name in i["kinds"]]
        either = [i for i in items if name in i["kinds"] or name in i["possible"]]
        out["by_type"][name] = {
            "wanted": len(wanted),
            "either": len(either),
            "per_benchmark": dict(sorted(Counter(i["bench"] for i in wanted).items())),
            "per_benchmark_either": dict(sorted(Counter(i["bench"] for i in either).items())),
            "benchmarks": len({i["bench"] for i in wanted}),
            "benchmarks_either": len({i["bench"] for i in either}),
            "examples": [
                {"bench": i["bench"], "rule": i["rule"], "text": i["statement"][:120]}
                for i in sorted(wanted, key=lambda x: (x["bench"], x["rule"]))[:4]
            ],
        }
        t = out["by_type"][name]
        t["meets_bar"] = t["benchmarks"] >= MISSING_BAR
        t["possible_bar"] = t["benchmarks_either"] >= MISSING_BAR
    out["corrections"] = list(corrections or [])
    out["none_of_them"] = sum(1 for i in items if not i["kinds"] and not i["possible"])
    out["items"] = [
        {k: i[k] for k in ("bench", "rule", "kinds", "possible", "loose", "strict")}
        | {"text": i["statement"][:200]}
        for i in items
    ]
    return out


# -- measure ---------------------------------------------------------------------------------------------------------------


def measure(
    docs: List[str], tags: List[str], judge_model: str, type_model: str = TYPE_MODEL, out: Path = RESULT
) -> Dict[str, Any]:
    _env()
    call = metered(judge_model, "judge", max_tokens=8000, kind="pipeline_vs_skill_judge")
    judge = Judge(call, PACKAGES / "pipeline_vs_skill_judge.json", judge_model)
    type_call = metered(type_model, "types", max_tokens=8000, kind="pipeline_vs_skill_judge")
    type_judge = Judge(type_call, PACKAGES / "pipeline_vs_skill_judge.json", type_model)
    result = json.loads(out.read_text()) if out.exists() else {"docs": {}}
    try:
        for doc in docs:
            result["docs"][doc] = measure_doc(doc, judge, tags)
            print(doc, "measured", flush=True)
    finally:
        call.flush()
    from cuga.policy_layer.package import load_package as load

    packages: Dict[str, List[Any]] = {}
    for d in DOCS:
        packages.setdefault(d.split("/")[0], []).append(load(package_dir(d, "skill_v1") / "package.json"))
    for p in sorted(PACKAGES.glob("itsm/*/skill_v1/package.json")):
        packages["itsm"].append(load(p))
    for p in sorted(PACKAGES.glob("automationbench/*/gold/package.json")):
        packages.setdefault("automationbench", []).append(load(p))
    try:
        hand = json.loads(HAND.read_text()) if HAND.exists() else {}
        result["type_demand"] = type_demand(
            verify_statements(packages), type_judge, corrections=hand.get("type_corrections")
        )
    finally:
        type_call.flush()
    result["compiler_detection"] = {
        d: {**section_detection(d), "skill_procedures": len(skill_procedures(skill_of(d)))} for d in DOCS
    }
    matrix = json.loads((PACKAGES / "coverage_matrix.json").read_text())["rows"]
    result["skill_causes"] = {
        d: row["causes"]
        for d in DOCS
        for row in matrix
        if row["package"] == f"{d}/skill_v1" and "causes" in row
    }
    kept = Counter(
        v["model"] for v in judge.cache.values()
    )  # every question ever asked is kept: a re-run asks nothing
    result["judge"] = {
        "model": judge_model,
        "type_model": type_model,
        "answers": {judge_model: kept[judge_model], type_model: kept[type_model]},
    }
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    return result


# -- render ----------------------------------------------------------------------------------------------------------------


def frac(n: Any, d: Any) -> str:
    return f"{n} of {d} ({pct(n, d):.1f}%)" if d else "-"


def _row(cells: List[Any]) -> str:
    return "| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in cells) + " |"


def _table(head: List[str], rows: List[List[Any]]) -> List[str]:
    return [_row(head), _row(["---"] * len(head))] + [_row(r) for r in rows]


def short(doc: str) -> str:
    bench, policy = doc.split("/")
    return {
        "handbook": f"HANDBOOK {policy.split('_')[1] if policy.startswith(('hr_', 'medical_', 'insurance_')) else policy}"
    }.get(bench, f"{BENCH_OF[bench].split(' (')[0]}" + (f" {policy[:10]}" if bench == "itsm" else ""))


SIDES = ["skill", "gptoss", "dsv4"]
SIDE_LABEL = {"skill": "skill_v1", "gptoss": "pipeline_gptoss", "dsv4": "pipeline_dsv4"}


def _sides(r: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    yield "skill", r["skill"]
    for tag in ("gptoss", "dsv4"):
        if tag in r["pipelines"]:
            yield tag, r["pipelines"][tag]


def _tests_cells(side: Dict[str, Any]) -> List[Any]:
    t = side["tests"]
    return [
        frac(t["caught_by_rules"], t["clean_deny_cases"]) + f" (deny {t['caught_deny']})",
        frac(t["false_deny"], t["clean_allow_cases"]),
        t["false_remind"],
        f"{t['schema_deny']} deny, {t['schema_allow']} allow",
    ]


def _replay_cells(side: Dict[str, Any]) -> List[Any]:
    r = side["replay"]
    if r.get("status") != "ok":
        return ["no runs", "no runs"]
    if not r["passed_runs"]:
        return [f"no passed run in {r['runs']}", f"no passed run in {r['runs']}"]
    return [
        f"{r['passed_runs_with_deny']} of {r['passed_runs']}",
        f"{r['passed_runs_with_remind']} of {r['passed_runs']}",
    ]


def _recall_cells(side: Dict[str, Any]) -> List[Any]:
    if "must_not_recall" not in side:
        return [f"{side['must_nots']} (reference)", f"{side['procedures']} (reference)"]
    m, p = side["must_not_recall"], side["procedure_recall"]
    comp, build = p["compiled"], p["builder"]
    made = p.get("made") or {}
    procs = frac(comp["recalled"], comp["skill"]) if comp else "no graph"
    steps = f"steps {comp['steps_held']} of {comp['steps']}" if comp else ""
    return [
        (
            f"{m['A']} of {m['skill']} ({pct(m['A'], m['skill']):.0f}%); anywhere {m['B']}"
            if m["skill"]
            else "no must-not in the skill"
        ),
        f"compiler {procs}, {steps} (made {made.get('compiled', '?')}); builder {build['recalled']} of {build['skill']} (made {made.get('builder', '?')})",
    ]


def _empty_catches(result: Dict[str, Any]) -> str:
    """Names the documents on which the catches condition cannot fail: the skill's catches are under 5%, so the threshold is zero or less."""
    empty = [
        short(d)
        for d, r in result["docs"].items()
        if r["pipelines"]
        and pct(r["skill"]["tests"]["caught_by_rules"], r["skill"]["tests"]["clean_deny_cases"]) < 5.0
    ]
    return (
        f"The catches condition (not more than 5 points below the skill) cannot fail on {', '.join(empty)}: the skill's catches are under 5%, so an empty package passes it. On those documents the verdict rests on the other two conditions."
        if empty
        else ""
    )


def render_tables(result: Dict[str, Any], hand: Optional[Dict[str, Any]] = None) -> str:
    out: List[str] = []
    docs = result["docs"]
    spent = sum(s["cost"]["total"] or 0 for r in docs.values() for s in r["pipelines"].values())

    out += ["## 1. Can the pipeline replace the skill today?", ""]
    out += _table(
        ["Benchmark", "Documents run", "Replace the skill today?", "Reason"],
        [[BENCH_OF[v["bench"]], v["docs"], v["answer"], v["reason"]] for v in verdicts(result)],
    )
    out += [
        "",
        "A model passes a document when all three conditions of the spec's bar hold on it (table 2). Nothing switches automatically. "
        + _empty_catches(result),
        "",
    ]

    out += ["## 2. The bar, per document and model", ""]
    rows = []
    for doc, r in docs.items():
        for tag, side in r["pipelines"].items():
            b = bar(r["skill"], side)
            rows.append(
                [
                    short(doc),
                    r["skill"]["label"][0],
                    MODEL_LABEL[tag],
                    f"{b['catches']['pipeline']:.1f}% against {b['catches']['skill']:.1f}% ("
                    + (
                        "met; cannot fail, the skill is under 5%"
                        if b["catches"]["cannot_fail"]
                        else ("met" if b["catches"]["ok"] else "missed")
                    )
                    + ")",
                    f"{b['catches']['allow_denied']:.1f}% against {b['catches']['skill_allow_denied']:.1f}%",
                    f"{b['catches']['pipeline'] - b['catches']['allow_denied']:+.1f}",
                    f"{b['false_denies']['pipeline']} against {b['false_denies']['skill']} of {b['false_denies']['of']} ({'met' if b['false_denies']['ok'] else 'missed'})",
                    (
                        f"{b['must_not']['recall']:.0f}% ({'met' if b['must_not']['ok'] else 'missed'})"
                        if b["must_not"]["recall"] is not None
                        else "n/a"
                    ),
                    "yes" if all_met(b) else "no",
                    b["validate_errors"],
                ]
            )
    out += _table(
        [
            "Document",
            "Basis of the numbers",
            "Model",
            "Catches, pipeline against skill (condition: not more than 5 points below the skill)",
            "Allow tests denied, pipeline against skill (percent of the allow tests)",
            "Catches minus allow tests denied (points; near 0: the rules do not tell the two apart)",
            "False denies, pipeline against skill (condition: not higher)",
            "Must-not recall (at least 80%)",
            "All three",
            "`validate` errors (beside the bar)",
        ],
        rows,
    )
    out += [""]

    out += ["## 3. All measures, one denominator per column", ""]
    out += [
        "Catches and false denies are on the skill's blind decision tests that the tool schema accepts (the same tests for every row of a document). "
        "Passed runs are the saved arm-A runs of the policy; a deny on a passed run is a conflict with the grader. Must-not recall is of the skill's must-not texts "
        "(each once): `A` counts the places the skill puts them (procedure must-not lists, exceptions, preconditions), `anywhere` also counts steps, global rules and rule quotes.",
        "",
    ]
    rows = []
    for doc, r in docs.items():
        for tag, side in _sides(r):
            rows.append(
                [short(doc), SIDE_LABEL[tag]] + _tests_cells(side) + _replay_cells(side) + _recall_cells(side)
            )
    out += _table(
        [
            "Document",
            "Source",
            "Deny tests caught (deny or remind)",
            "False denies (allow tests)",
            "False reminders",
            "Rejected by the tool schema (apart, not in the columns before)",
            "Passed runs denied",
            "Passed runs reminded",
            "Must-not recall",
            "Procedure recall",
        ],
        rows,
    )
    out += [""]

    out += ["## 3a. Must-not recall by source", ""]
    out += [
        "Pool `A` mixes two sources. `compiler`: the `must_not` lists of `procedure_compiler.py` (procedures and escalation). `builder`: the builder's procedure exceptions, "
        "preconditions and `must_not`, which often repeat the statement's own quote. A skill text counts under the source of the text it matched. The compiler share is a floor: "
        "a verbatim match takes the compiler's text first, but a judge match takes the text the judge named, and it may name a builder text when a compiler text also fits. "
        "The last two columns count pipeline must-nots that match no skill text.",
        "",
    ]
    rows = []
    for doc, r in docs.items():
        for tag, side in r["pipelines"].items():
            src, m = side.get("must_not_sources"), side["must_not_recall"]
            if not src or not m["skill"]:
                continue
            rows.append(
                [
                    short(doc),
                    SIDE_LABEL[tag],
                    f"{m['A']} of {m['skill']}",
                    f"{src['recalled']['compiler']} (floor)",
                    src["recalled"]["builder"],
                    f"{src['pool']['compiler']} ({src['pool_matched']['compiler']} matched)",
                    f"{src['pool']['builder']} ({src['pool_matched']['builder']} matched)",
                    src["pool_matching_no_skill_text"]["compiler"],
                    src["pool_matching_no_skill_text"]["builder"],
                ]
            )
    out += _table(
        [
            "Document",
            "Source",
            "Recall `A`",
            "Matched through a compiler `must_not` list",
            "Matched through a builder text",
            "Compiler must-nots (matched a skill text)",
            "Builder texts in the pool (matched a skill text)",
            "Compiler must-nots that match no skill text",
            "Builder texts that match no skill text",
        ],
        rows,
    )
    out += [""]

    causes = result.get("skill_causes") or {}
    if causes:
        names = [
            "code rule",
            "verify",
            "obligation or step",
            "guidance, duty or global rule",
            "definition",
            "question only",
            "no outcome",
            "statement id not in the package",
        ]
        out += ["## 3b. Why the skill's own deny tests are not caught by rules", ""]
        out += [
            "The deny tests that the tool schema accepts, by what the tested statement became in the skill package (`COVERAGE.md` table 3, from `coverage_matrix.json`). Each cell is caught of tests. "
            "A rule on one call cannot catch a deny test on an obligation, a step or a statement with no outcome: that is most of HANDBOOK and Telecom. "
            "The stored ITSM tests carry statement ids of an older split, so they cannot be placed.",
            "",
        ]
        rows = []
        for doc, c in causes.items():
            total = sum(v["tests"] for v in c.values())
            rows.append(
                [short(doc), total]
                + [f"{c[n]['caught']} of {c[n]['tests']}" if n in c else "-" for n in names]
            )
        out += _table(["Document", "Deny tests"] + names, rows)
        out += [""]

    out += ["## 4. Cost per document and validate errors", ""]
    rows = []
    for doc, r in docs.items():
        for tag, side in _sides(r):
            v = side["validate"]
            if tag == "skill":
                rows.append(
                    [
                        short(doc),
                        SIDE_LABEL[tag],
                        "made by an agent; not measured",
                        "-",
                        "-",
                        f"{v['errors']} / {v['warnings']}",
                        _codes(v["error_codes"]),
                    ]
                )
                continue
            c = side["cost"]
            rows.append(
                [
                    short(doc),
                    SIDE_LABEL[tag],
                    f"${c['total']:.3f} (rules ${c['build']:.3f}, procedures ${c['compile']:.3f})",
                    f"{c['calls']} calls, {c['seconds']} s",
                    c["failed_calls"],
                    f"{v['errors']} / {v['warnings']}",
                    _codes(v["error_codes"]),
                ]
            )
    out += _table(
        [
            "Document",
            "Source",
            "Cost of the build",
            "Calls, time",
            "Failed calls",
            "validate errors / warnings (`legacy=False`)",
            "Error codes",
        ],
        rows,
    )
    out += ["", f"Cost of the builds in this table: ${spent:.2f}. Judge calls are counted in section 8."]
    out += [""]

    out += ["## 5. Known pipeline defects, per version", ""]
    rows = []
    for doc, r in docs.items():
        for tag, side in r["pipelines"].items():
            d = side["defects"]
            lost, frag = d["lost_checks"], d["fragments"]
            rows.append(
                [
                    short(doc),
                    SIDE_LABEL[tag],
                    d["quote_not_verbatim"],
                    f"{len(lost['step_only'])} of {lost['skill_hard_statements']}"
                    + (
                        f" ({', '.join(x.split(':', 1)[-1] for x in lost['step_only'][:3])})"
                        if lost["step_only"]
                        else ""
                    ),
                    f"{len(lost['no_outcome'])} of {lost['skill_hard_statements']}",
                    f"{frag['fragments']} of {frag['typed_must']} ({frag['fragments_without_outcome']} with no outcome)",
                    d.get("threshold_on_text", 0),
                    ", ".join(f"{k} {v}" for k, v in side.get("false_deny_types", {}).items()) or "-",
                ]
            )
    out += _table(
        [
            "Document",
            "Source",
            "`quote_not_verbatim` errors",
            "Checks lost to a step (skill hard-rule statements the pipeline made a step only)",
            "Skill hard-rule statements with no outcome in the pipeline",
            "Fragments typed `must` (fewer than 5 words, or starting in lower case)",
            "Threshold rules on a text argument (a number read out of an id or a name)",
            "Rule types that denied the allow tests (tests denied, by type)",
        ],
        rows,
    )
    out += [""]
    det = result.get("compiler_detection") or {}
    if det:
        out += ["## 5a. What `compile_sop` takes as a procedure, offline", ""]
        out += [
            "The compiler picks a section as a procedure when at least two of its lines start like `Step 1`, `1.`, `If`, `When`, `Day 1` or `- ` (`STEP_LINE`). "
            "It has no pattern for `**Step 1:**` (a bold line start) or for a `*` bullet. The table counts the sections it selects as the file is, with a leading `**` removed from each line, "
            "and with `*` bullets also read as `-` (no model call; these two readings are not changes to the compiler). The last column is the characters of the general sections that the call over them "
            "drops (`general_text[:40000]`). The first column is what the measures above used; its procedure counts for Crestwood, ITSM and CareIG are tool defects, not what a model can do.",
            "",
        ]
        rows = [
            [
                short(d),
                v["skill_procedures"],
                v["as_is"],
                v["stars_removed"],
                v["bullets_too"],
                v["general_chars_cut"],
            ]
            for d, v in det.items()
        ]
        out += _table(
            [
                "Document",
                "Skill procedures",
                "As the file is",
                "Leading `**` removed",
                "`*` bullets also read as `-`",
                "General text cut (characters)",
            ],
            rows,
        )
        out += [""]

    out += ["## 6. Tuning status of the documents", ""]
    rows = []
    for doc, r in docs.items():
        for tag, side in r["pipelines"].items():
            rows.append([short(doc), SIDE_LABEL[tag], side["label"][0], side["label"][1]])
    out += _table(["Document", "Source", "Basis", "Why (`audit_report.basis_of`)"], rows)
    out += [""]

    td = result.get("type_demand")
    if td:
        out += ["## 7. Rule types the skill authors asked for", ""]
        out += [
            f"{td['verify_statements']} `verify` statements of the packages (one per statement and benchmark; benchmarks: "
            + ", ".join(f"{k} {v}" for k, v in td["by_benchmark"].items())
            + "; the three tau2 domains count as one benchmark; AutomationBench is the hand-made gold builds). "
            "A model sorted them twice with two readings of one question (section 8 gives its error against a hand check). "
            "A kind named by both readings is `wanted`; a kind named by either one is `possible`. A statement can need more than one kind; "
            f"{td['none_of_them']} are named by neither reading for any kind (they need judgment, a sequence of calls, a role or another check). "
            f"Spec section 4 allows a new type only with statements from at least {MISSING_BAR} benchmarks.",
            "",
        ]
        for fix in td.get("corrections") or []:
            out += [
                f"Hand correction: `{fix['rule']}` is taken off {', '.join(f'`{k}`' for k in fix['remove'])}. {fix['note']}",
                "",
            ]
        rows = []
        for name, v in td["by_type"].items():
            rows.append(
                [
                    name,
                    v["wanted"],
                    ", ".join(f"{k} {n}" for k, n in v["per_benchmark"].items()) or "-",
                    "yes" if v["meets_bar"] else "no",
                    f"{v['either']} ({', '.join(f'{k} {n}' for k, n in v['per_benchmark_either'].items()) or '-'})",
                    "yes" if v["possible_bar"] else "no",
                    "<br>".join(f"{e['bench']} `{e['rule']}`: {e['text']}" for e in v["examples"][:2]),
                ]
            )
        out += _table(
            [
                "Missing type",
                "Wanted (both readings)",
                "By benchmark",
                "Meets the bar",
                "Possible (either reading)",
                "Could meet the bar",
                "Examples of wanted",
            ],
            rows,
        )
        out += [""]

    out += ["## 8. The judge and its error", ""]
    j = result.get("judge") or {}
    out += [
        f"Recall judge: `{j.get('model', '-')}` ({(j.get('answers') or {}).get(j.get('model'), 0)} answers kept). Type sorter: `{j.get('type_model', '-')}` ({(j.get('answers') or {}).get(j.get('type_model'), 0)} answers kept). Their cost is in the ledger under `pipeline_vs_skill_judge`; the answers are in `pipeline_vs_skill_judge.json`, so a re-run asks nothing.",
        "",
    ]
    if hand:
        checked = hand["cases"]
        recall = [c for c in checked if not c["kind"].startswith("kinds")]
        agree = sum(1 for c in recall if _same(c["judge"], c["hand"]))
        by_kind: Dict[str, List[int]] = {}
        for c in checked:
            by_kind.setdefault(c["kind"], [0, 0])[0] += 1
            by_kind[c["kind"]][1] += _same(c["judge"], c["hand"])
        out += [
            f"Hand-checked sample: {hand.get('method', '')}",
            "",
            f"Recall verdicts (must-not and procedure): {len(recall)} read, the judge agreed with the hand verdict on {agree} ({pct(agree, len(recall)):.0f}%), error {len(recall) - agree} of {len(recall)}.",
            "",
        ]
        out += _table(
            ["Kind", "Checked", "Agreed", "Error"],
            [[k, v[0], v[1], f"{pct(v[0] - v[1], v[0]):.0f}%"] for k, v in sorted(by_kind.items())],
        )
        pairs: Dict[str, Dict[str, set]] = {}
        for c in checked:
            if c["kind"].startswith("kinds"):
                names = {x.strip() for x in c["judge"].split(",")} - {"none"}
                one = pairs.setdefault(
                    c["ref"], {"hand": {x.strip() for x in c["hand"].split(",")} - {"none"}}
                )
                one[c["kind"][7:-1]] = names
        if pairs:
            both = [
                (p["loose"] & p["strict"], p["hand"])
                for p in pairs.values()
                if "loose" in p and "strict" in p
            ]
            either = [
                (p["loose"] | p["strict"], p["hand"])
                for p in pairs.values()
                if "loose" in p and "strict" in p
            ]
            for name, rows in (
                ("both readings (`wanted`)", both),
                ("either reading (`possible` and `wanted`)", either),
            ):
                named, right, hand_n = (
                    sum(len(a) for a, _ in rows),
                    sum(len(a & h) for a, h in rows),
                    sum(len(h) for _, h in rows),
                )
                out += [
                    "",
                    f"Kinds named by {name}: {right} of {named} also named by hand (precision {pct(right, named):.0f}%); {right} of {hand_n} kinds named by hand were found (recall {pct(right, hand_n):.0f}%), on {len(rows)} statements.",
                ]
        wrong = [c for c in checked if not _same(c["judge"], c["hand"])]
        if wrong:
            out += ["", "Disagreements:", ""] + [
                f"- {c['kind']} {c['doc']} {c['tag']}: {c['ref'][:90]} | judge {c['judge']}, hand {c['hand']}. {c.get('note', '')}"
                for c in wrong
            ]
    return "\n".join(out) + "\n"


def _same(a: str, b: str) -> bool:
    """Two verdicts agree: equal, or equal as sets of names (``a, b`` and ``b, a``)."""
    return a == b or {x.strip() for x in a.split(",")} == {x.strip() for x in b.split(",")}


def _codes(codes: Dict[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in codes.items()) or "-"


def render(md: Path, result_path: Path = RESULT, hand_path: Optional[Path] = None) -> str:
    result = json.loads(result_path.read_text())
    hand = json.loads(hand_path.read_text()) if hand_path and hand_path.exists() else None
    tables = render_tables(result, hand)
    text = md.read_text() if md.exists() else f"{START}\n{END}\n"
    head, _, rest = text.partition(START)
    _, _, tail = rest.partition(END)
    new = f"{head}{START}\n{tables}{END}{tail}"
    md.write_text(new)
    return new


HAND = PACKAGES / "pipeline_vs_skill_handcheck.json"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--doc", required=True, choices=DOCS)
    r.add_argument("--model", required=True, choices=sorted(MODELS))
    r.add_argument("--stages", default="build,compile")
    r.add_argument("--replace", action="store_true")
    m = sub.add_parser("measure")
    m.add_argument("--doc", action="append", choices=DOCS)
    m.add_argument("--judge", default=JUDGE_MODEL)
    m.add_argument("--type-model", default=TYPE_MODEL)
    m.add_argument(
        "--only-types",
        action="store_true",
        help="sort the verify statements again and keep the rest of the result",
    )
    m.add_argument("--models", default="gptoss,dsv4")
    d = sub.add_parser("render")
    d.add_argument("--md", default=str(PACKAGES / "PIPELINE_VS_SKILL.md"))
    h = sub.add_parser("handsample", help="write the sample of judge verdicts to check by hand")
    h.add_argument("--n", type=int, default=24)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        run(a.doc, a.model, a.stages.split(","), a.replace)
    elif a.cmd == "measure":
        measure(a.doc or ([] if a.only_types else DOCS), a.models.split(","), a.judge, a.type_model)
    elif a.cmd == "render":
        render(Path(a.md), RESULT, HAND)
    elif a.cmd == "handsample":
        handsample(a.n)
    return 0


def handsample(n: int) -> None:
    """Judge verdicts spread over the result, one JSON file to fill in by hand (``hand`` = ``match`` or ``no_match``)."""
    result = json.loads(RESULT.read_text())
    cases = []
    for doc, r in result["docs"].items():
        for tag, side in r["pipelines"].items():
            for it in side["must_not_recall"]["items"]:
                for pool in ("A", "B"):
                    m = it[pool]
                    if m["how"] == "judge" or (m["how"] == "none" and m.get("judged")):
                        cases.append(
                            {
                                "kind": "must-not",
                                "doc": doc,
                                "tag": tag,
                                "ref": it["ref"],
                                "candidate": m.get("match") or m.get("judged"),
                                "judge": "match" if m["match"] else "no_match",
                                "why": m.get("why", ""),
                                "hand": "",
                                "note": "",
                            }
                        )
                        break
            for it in (side["procedure_recall"]["compiled"] or {}).get("items", []):
                if not it.get("asked"):
                    continue  # no candidate procedure: nothing was judged
                cases.append(
                    {
                        "kind": "procedure",
                        "doc": doc,
                        "tag": tag,
                        "ref": it["id"],
                        "candidate": it["match"],
                        "judge": "match" if it["match"] else "no_match",
                        "why": it["why"],
                        "hand": "",
                        "note": "",
                    }
                )
    step = max(1, len(cases) // n)
    sample = cases[::step][:n]
    for it in result["type_demand"]["items"][::6][:22]:  # the verify statements: both readings of the sorter
        for reading in ("loose", "strict"):
            sample.append(
                {
                    "kind": f"kinds ({reading})",
                    "doc": it["bench"],
                    "tag": "",
                    "ref": f"{it['rule']}: {it['text']}",
                    "candidate": None,
                    "judge": ", ".join(it[reading]) or "none",
                    "why": "",
                    "hand": "",
                    "note": "",
                }
            )
    (PACKAGES / "pipeline_vs_skill_handsample.json").write_text(
        json.dumps(sample, indent=1, ensure_ascii=False)
    )
    print(len(cases), "judged,", len(sample), "in the sample")


if __name__ == "__main__":
    sys.exit(main())
