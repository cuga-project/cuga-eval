"""Helper for the hand-made gold policy builds of the AutomationBench (ab) tasks.

    python -I gold_ab.py docs <task>    # policy records -> ab/<task>/docs/*.md, meta.json, tools.json
    python -I gold_ab.py show <task>    # statements of ab/<task>/set.json with their ids
    python -I gold_ab.py build <task>   # spec + set.json -> ab/<task>/set.gold.json, build.json

The record choice, trust, types, rules and links are written by hand in ``specs/<task>.py`` (DOCS and BUILD).
Record text is copied from the task input JSON, never retyped, so every document is word for word. The task data
is only read as data.
"""

from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

G = Path(__file__).resolve().parent.parent
GENERATOR = {"kind": "skill", "harness": "claude-code", "model": "claude (gold, reviewed by a person later)"}


def _spec(task: str):
    path = G / "scripts" / "specs" / f"{task.replace('.', '_')}.py"
    spec = importlib.util.spec_from_file_location(f"spec_{task.replace('.', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _inputs(task: str) -> Dict[str, Any]:
    return json.loads((G / "inputs" / "ab" / f"{task}.json").read_text())


def _find(items: List[Dict[str, Any]], key: str, value: Any) -> Dict[str, Any]:
    hits = [x for x in items if x.get(key) == value]
    if len(hits) != 1:
        raise SystemExit(f"{key}={value!r}: {len(hits)} matches")
    return hits[0]


def _sheet(state: Dict[str, Any], ss_id: str, ws_id: str):
    ss = next(
        s for s in state["google_sheets"]["spreadsheets"] if (s.get("id") or s.get("spreadsheet_id")) == ss_id
    )
    ws = next(w for w in ss["worksheets"] if (w.get("id") or w.get("worksheet_id")) == ws_id)
    return ss, ws


def _cell(v: Any) -> str:
    s = "" if v is None else str(v)
    if "|" in s or "\n" in s:
        raise SystemExit(f"cell needs escaping: {s!r}")
    return s


def _table(columns: List[str], rows: List[Dict[str, Any]]) -> str:
    out = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for r in rows:
        out.append("| " + " | ".join(_cell(r["cells"].get(c)) for c in columns) + " |")
    return "\n".join(out)


def _render(state: Dict[str, Any], d: Dict[str, Any]):
    """One policy record -> (markdown text, source record info, effective date)."""
    kind = d["kind"]
    if kind == "email":
        m = _find(state["gmail"]["messages"], "id", d["record"])
        text = f"# {m['subject']}\n\n{m['body_plain']}\n"
        return (
            text,
            {
                "system": "gmail",
                "id": m["id"],
                "from": m.get("from_"),
                "to": m.get("to"),
                "subject": m["subject"],
                "date": m.get("date"),
            },
            (m.get("date") or "")[:10] or None,
        )
    if kind == "slack":
        m = next(x for x in state["slack"]["messages"] if (x.get("id") or x.get("ts")) == d["record"])
        chan = next(
            (c["name"] for c in state["slack"].get("channels", []) if c["id"] == m.get("channel_id")),
            m.get("channel_id"),
        )
        users = {u["id"]: u.get("name") for u in state["slack"].get("users", [])}
        who = users.get(m.get("user_id")) or m.get("user_id")
        day = datetime.datetime.fromtimestamp(float(m["ts"]), datetime.timezone.utc).date().isoformat()
        text = f"# Slack message in #{chan} from {who}\n\n{m['text']}\n"
        return (
            text,
            {
                "system": "slack",
                "id": m.get("id") or m["ts"],
                "channel": chan,
                "user_id": m.get("user_id"),
                "user_name": users.get(m.get("user_id")),
                "ts": m["ts"],
                "date": day,
            },
            day,
        )
    if kind in ("tab", "row"):
        ss, ws = _sheet(state, d["spreadsheet"], d["worksheet"])
        rows = ws["rows"] if kind == "tab" else [_find(ws["rows"], "row_id", d["row_id"])]
        columns = d.get("columns") or ws.get("headers") or list(rows[0]["cells"])
        title = f"{ss['title']}: {ws['title']}" + (f", row {d['row_id']}" if kind == "row" else "")
        text = f"# {title}\n\n{_table(columns, rows)}\n"
        src = {
            "system": "google_sheets",
            "spreadsheet": d["spreadsheet"],
            "spreadsheet_title": ss["title"],
            "worksheet": d["worksheet"],
            "worksheet_title": ws["title"],
            "columns": columns,
        }
        if kind == "row":
            src["row_id"] = d["row_id"]
        return text, src, None
    raise SystemExit(f"unknown kind {kind}")


def cmd_docs(task: str) -> None:
    spec, data = _spec(task), _inputs(task)
    out = G / "ab" / task
    (out / "docs").mkdir(parents=True, exist_ok=True)
    meta: Dict[str, Any] = {}
    for d in spec.DOCS:
        text, src, day = _render(data["initial_state"], d)
        (out / "docs" / f"{d['id']}.md").write_text(text)
        m: Dict[str, Any] = {"trust": d["trust"], "trust_reason": d["trust_reason"]}
        if day and d.get("dated", True):
            m["effective_date"] = day
        if d.get("authority_rank"):
            m["authority_rank"] = d["authority_rank"]
            m["authority_reason"] = d["authority_reason"]
        m["source_record"] = src
        meta[d["id"]] = m
    (out / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
    (out / "tools.json").write_text(json.dumps(data["tools"], indent=1, ensure_ascii=False) + "\n")
    print(f"{len(spec.DOCS)} docs -> {out}")


def _statements(ps: Dict[str, Any]):
    for d in ps["documents"]:
        for sec in d["sections"]:
            for st in sec["statements"]:
                yield d, sec, st


def cmd_show(task: str) -> None:
    ps = json.loads((G / "ab" / task / "set.json").read_text())
    for d, sec, st in _statements(ps):
        print(f"{st['id']}  [{d['trust']}]  {st['text']}")


# -- build -------------------------------------------------------------------------------------------------------

CHECKER = {"role_permission": "cedar", "duty": "monitor", "guidance": "brief", "verify": "verifier"}


def _rid(*parts: Any) -> str:
    return "g_" + hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:10]


def cmd_build(task: str) -> None:
    sys.path.insert(0, str(Path("/Users/samimarreed/dev/cuga-agent-gate/src")))
    from cuga.policy_layer.documents import clean
    from cuga.policy_layer.handlers.links import drop_superseded, fold_exceptions
    from cuga.policy_layer.model import (
        CoverageItem,
        Definition,
        Link,
        LinkType,
        PolicyBuild,
        PolicySet,
        Procedure,
        Rule,
        StatementType,
        Step,
        Trust,
        from_json,
        to_json,
    )
    from cuga.policy_layer.validate import validate_build

    spec = _spec(task)
    B = spec.BUILD
    out = G / "ab" / task
    raw = json.loads((out / "set.json").read_text())
    tools = json.loads((out / "tools.json").read_text())
    meta = json.loads((out / "meta.json").read_text())
    by_id = {st["id"]: (d, sec, st) for d, sec, st in _statements(raw)}

    # 1. statement types and modality (set.gold.json)
    types = B["types"]
    unknown = set(types) - set(by_id)
    if unknown:
        raise SystemExit(f"types for unknown statements: {sorted(unknown)}")
    missing = set(by_id) - set(types)
    if missing:
        raise SystemExit(f"statements without a types entry: {sorted(missing)}")
    for sid, (tps, modality) in types.items():
        if len(tps) > 2:
            raise SystemExit(f"{sid}: more than 2 types")
        for t in tps:
            StatementType(t)
        st = by_id[sid][2]
        st["types"] = list(tps)
        st["modality"] = modality
    raw["links"] = []
    ps = from_json(PolicySet, raw)
    texts = {sid: v[2]["text"] for sid, v in by_id.items()}
    trust = {d.id: d.trust for d in ps.documents}

    def src_of(sid: str) -> Dict[str, Any]:
        return dict(by_id[sid][2]["source"])

    def joined(ids: List[str]) -> str:
        return " ".join(texts[i] for i in ids)

    def readable(ids: List[str]) -> str:
        """The statement text for the verifier: table rows get their column names in front (from the record)."""
        parts = []
        for i in ids:
            header = by_id[i][2]["source"].get("table_header")
            parts.append(f"({' | '.join(header)}) {texts[i]}" if header else texts[i])
        return " ".join(parts)

    # 2. rules
    rules: List[Rule] = []
    for spec_rule in B["rules"]:
        r = dict(spec_rule)
        ids = r.pop("ids")
        may_deny = r.pop("may_deny", True)
        for i in ids:
            if i not in by_id:
                raise SystemExit(f"rule on unknown statement {i}")
            if trust[i.split(":")[0]] == Trust.UNTRUSTED:
                raise SystemExit(f"enforcing rule on untrusted statement {i}")
        t = r["type"]
        stmt = joined(ids)
        if t == "verify":
            r.setdefault("statement", readable(ids))
            r.setdefault("quote", stmt)
            r["types"] = sorted({x for i in ids for x in types[i][0]})
        elif t == "guidance":
            r.setdefault("text", readable(ids))
            r.setdefault("quote", stmt)
        else:
            q = r.get("quote")
            if not q or clean(q).lower() not in clean(stmt).lower():
                raise SystemExit(f"quote not verbatim for {ids}: {q!r}")
        first = src_of(ids[0])
        r["source"] = f"{first['document']} §{first['section']}" + (
            f" step {first['step']}" if first.get("step") else ""
        )
        r["by"] = "skill"
        r["id"] = _rid(t, ids, {k: v for k, v in r.items() if k not in ("id", "by", "source")})
        rules.append(
            Rule(
                id=r["id"],
                type=t,
                rule=r,
                statement_ids=list(ids),
                checker=CHECKER.get(t, "code"),
                may_deny=may_deny,
                source=first,
                quote=r["quote"] if "quote" in r else stmt,
            )
        )

    # 3. links
    ids_all = (
        {d.id for d in ps.documents}
        | {f"{d.id}:{s.id}" for d in ps.documents for s in d.sections}
        | set(by_id)
    )
    links: List[Link] = []
    for typ, s, dst, quote in B.get("links", []):
        if s not in ids_all or dst not in ids_all:
            raise SystemExit(f"link end missing: {typ} {s} -> {dst}")
        if s in texts and quote and clean(quote).lower() not in clean(texts[s]).lower():
            raise SystemExit(f"link quote not in source statement: {s}: {quote!r}")
        links.append(
            Link(
                type=LinkType(typ),
                src=s,
                dst=dst,
                source=src_of(s) if s in by_id else {"document": s},
                quote=quote,
            )
        )
    ps.links = links

    # 4. procedures and definitions
    procedures: List[Procedure] = []
    for p in B.get("procedures", []):
        steps = [
            Step(
                id=x["id"],
                action=x["action"],
                required=x.get("required", True),
                condition=x.get("condition"),
                source=src_of(x["id"]),
                quote=texts[x["id"]],
            )
            for x in p["steps"]
        ]
        edges = [{"from": a.id, "to": b.id} for a, b in zip(steps, steps[1:])]
        procedures.append(
            Procedure(
                id=p["id"],
                name=p["name"],
                trigger=p.get("trigger", {}),
                steps=steps,
                edges=edges,
                source=src_of(steps[0].id),
                quote=" / ".join(s.quote for s in steps),
            )
        )
    definitions = [
        Definition(
            term=t,
            meaning=texts[sid],
            used_by=[link.dst for link in links if link.src == sid and link.type == LinkType.DEFINES],
            source={**src_of(sid), "statement": sid},
            quote=texts[sid],
        )
        for sid, t in B.get("definitions", {}).items()
    ]

    # 5. exceptions folded into the rules they change; superseded statements lose their rules
    rules = fold_exceptions(rules, links, ps)
    rules, sup_cov = drop_superseded(rules, links, ps)
    superseded = {c.statement_id for c in sup_cov}

    # 6. coverage: every statement accounted for, once per outcome
    coverage: List[CoverageItem] = []
    ruled: Dict[str, List[str]] = {}
    for r in rules:
        for i in r.statement_ids:
            ruled.setdefault(i, []).append(r.type)
    explicit = B.get("coverage", {})
    steps = {s.id for p in procedures for s in p.steps}
    for sid in by_id:
        st = by_id[sid][2]
        doc = sid.split(":")[0]
        if trust[doc] == Trust.UNTRUSTED:
            coverage.append(
                CoverageItem(
                    sid,
                    "untrusted",
                    f"untrusted source: {meta[doc]['trust_reason']}; no enforcing rule, brief only",
                    src_of(sid),
                    st["text"],
                )
            )
            continue
        if sid in superseded:
            continue  # drop_superseded's own item
        kinds = ruled.get(sid, [])
        if kinds:
            enforcing = [k for k in kinds if k not in ("verify", "guidance")]
            kind = "rule" if enforcing else ("verify" if "verify" in kinds else "guidance")
            coverage.append(
                CoverageItem(
                    sid,
                    kind,
                    f"{len(kinds)} rule(s): {', '.join(sorted(set(kinds)))}",
                    src_of(sid),
                    st["text"],
                )
            )
        if sid in steps:
            coverage.append(CoverageItem(sid, "step", "procedure step", src_of(sid), st["text"]))
        if sid in B.get("definitions", {}):
            coverage.append(CoverageItem(sid, "definition", B["definitions"][sid], src_of(sid), st["text"]))
        if sid in explicit:
            kind, reason = explicit[sid]
            coverage.append(CoverageItem(sid, kind, reason, src_of(sid), st["text"]))
        if not kinds and sid not in steps and sid not in explicit and sid not in B.get("definitions", {}):
            raise SystemExit(f"statement not accounted for: {sid}: {st['text']}")
        if kinds and sid in explicit and explicit[sid][0] not in ("dangling_link", "link", "definition"):
            raise SystemExit(f"{sid}: has rules and an explicit {explicit[sid][0]} coverage item")
    coverage += sup_cov
    for sid, kind, reason in B.get("extra_coverage", []):
        coverage.append(CoverageItem(sid, kind, reason, src_of(sid), texts[sid]))

    build = PolicyBuild(
        version=ps.version,
        rules=rules,
        procedures=procedures,
        links=links,
        definitions=definitions,
        coverage=coverage,
        generator=dict(GENERATOR),
    )
    build.validation = [vars(e) for e in validate_build(build, tools, ps)]
    kinds: Dict[str, int] = {}
    for c in coverage:
        kinds[c.kind] = kinds.get(c.kind, 0) + 1
    build.stats = {
        "documents": len(ps.documents),
        "statements": len(by_id),
        "rules": len(rules),
        "by_type": {t: sum(r.type == t for r in rules) for t in sorted({r.type for r in rules})},
        "procedures": len(procedures),
        "links": len(links),
        "links_by_type": {
            t: sum(link.type.value == t for link in links)
            for t in sorted({link.type.value for link in links})
        },
        "coverage": kinds,
        "validation_errors": len(build.validation),
        "documents_by_trust": {
            t: sum(d.trust.value == t for d in ps.documents) for t in ("trusted", "untrusted")
        },
    }
    gold_set = to_json(ps)
    (out / "set.gold.json").write_text(json.dumps(gold_set, indent=1, ensure_ascii=False) + "\n")
    (out / "build.json").write_text(json.dumps(to_json(build), indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(build.stats))
    for v in build.validation:
        print("VALIDATION", v)


if __name__ == "__main__":
    cmd, task = sys.argv[1], sys.argv[2]
    {"docs": cmd_docs, "show": cmd_show, "build": cmd_build}[cmd](task)
