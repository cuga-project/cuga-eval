"""SOP long-document discovery, offline test on HANDBOOK.md (no agent runs).

Hypothesis: for a strong agent, the policy system should find the SOP parts each case needs in a long document
(retrieve the procedure, follow its links) and show them as a checklist, instead of driving the agent case by case.

Per task: index the SOP build (procedures, statements, links); per case found by the agents in recorded runs
(sop_loop plan phase): retrieve procedures by BM25, re-rank the top 5 with one Kev question each; expand the chosen
procedure (its section, preconditions, exceptions, escalations, template text, statements one link away, general
rules that match the case). Scored with the task's rubric (used for scoring only): each rubric item is mapped to its
deciding SOP statement (BM25), and to the cases whose keys it names.

  L0  the loop's recorded procedure choice + its section and attachments (what the agent was shown)
  B1  BM25 top-1 + section and attachments
  R1  BM25 top-5 re-ranked by Kev, top-1 + section and attachments
  R2  R1 + one-hop links + template text + matching general rules
  R3  R2 for the top-2 procedures

    PYTHONPATH=<cuga src> ../automationbench/.venv/bin/python sop_discovery.py --runs hbg38_L_t1,hbg38_L_t2,hbh_L_t1
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(sys.argv[0]).resolve().parent
BENCH = HERE.parent
STOP = set(
    "the and for with that this from must have has are not any all each into your when then than there their which "
    "been also only per its may can should shall will a an of to in on or by be is as at it if".split()
)
KEV_Q = "Does this SOP procedure apply to this case, given the case summary? Answer yes only if it is the procedure to follow."


def toks(t: str) -> list:
    t = (t or "").lower()
    special = re.findall(r"\[[a-z_ -]+\]|[\w.-]+@[\w.-]+|[\w-]+\.(?:xlsx|csv|json|docx|pdf|md)|#[\w-]+", t)
    return [w for w in re.findall(r"[a-z][a-z0-9_-]{2,}", t) if w not in STOP] + special


class BM25:
    def __init__(self, docs: list, k1: float = 1.5, b: float = 0.75):
        self.docs = [toks(d) for d in docs]
        self.avg = sum(map(len, self.docs)) / max(len(self.docs), 1)
        self.df = Counter(w for d in self.docs for w in set(d))
        self.n, self.k1, self.b = len(self.docs), k1, b
        self.tf = [Counter(d) for d in self.docs]

    def scores(self, query: str) -> list:
        q = toks(query)
        out = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for w in q:
                if w in tf:
                    idf = math.log(1 + (self.n - self.df[w] + 0.5) / (self.df[w] + 0.5))
                    s += (
                        idf
                        * tf[w]
                        * (self.k1 + 1)
                        / (tf[w] + self.k1 * (1 - self.b + self.b * len(self.docs[i]) / self.avg))
                    )
            out.append(s)
        return out


def proc_text(p: dict) -> str:
    parts = [p.get("name", "")] + [s.get("quote", "") for s in p.get("steps") or []]
    for k in ("preconditions", "exceptions", "escalations", "templates"):
        parts += [str(x.get("quote") or x.get("condition") or x.get("when") or "") for x in p.get(k) or []]
    return "\n".join(parts)


def load_task(task: str):
    data = json.load(open(BENCH / f"policy_eval/builds_handbook/v3/{task}.json"))
    b, ps = data["build"], data["policy_set"]
    sts = [s for d in ps["documents"] for sec in d["sections"] for s in sec["statements"]]
    secs = {f"{d['id']}:{sec['id']}": sec for d in ps["documents"] for sec in d["sections"]}
    parent = {k: (f"{k.split(':')[0]}:{v['parent']}" if v.get("parent") else None) for k, v in secs.items()}
    return b, sts, secs, parent


def sec_of(s: dict) -> str:
    return f"{s['source']['document']}:{s['source'].get('section')}"


def ancestors(sid, parent):
    out = []
    while sid:
        out.append(sid)
        sid = parent.get(sid)
    return out


def expand(p: dict, sts, secs, parent, links, general, case_q, one_hop: bool) -> set:
    """Statement ids of the checklist for one procedure."""
    psec = {f"{p['source']['document']}:{p['source'].get('section')}"} | {
        f"{st['source']['document']}:{st['source'].get('section')}" for st in p.get("steps") or []
    }
    ids = {s["id"] for s in sts if any(a in psec for a in ancestors(sec_of(s), parent))}
    quotes = [
        str(x.get("quote") or "")
        for k in ("preconditions", "exceptions", "escalations", "templates")
        for x in p.get(k) or []
    ]
    ids |= {s["id"] for s in sts if any(q and (s["text"][:60] in q or q[:60] in s["text"]) for q in quotes)}
    if not one_hop:
        return ids
    E = ids | psec
    by_sec = defaultdict(list)
    for s in sts:
        by_sec[sec_of(s)].append(s["id"])
    for lk in links:
        for a, bb in ((lk["src"], lk["dst"]), (lk["dst"], lk["src"])):
            if a in E:
                ids |= {bb} if bb not in secs else set(by_sec.get(bb, []))
    names = set(re.findall(r"Template\s+[A-Z]?-?\d+", proc_text(p)))  # template text by name
    for k, sec in secs.items():
        if any(n.lower() in sec["title"].lower() for n in names):
            ids |= set(by_sec.get(k, []))
    if general:  # general rules that match the case
        g = (
            (general.get("preconditions") or [])
            + (general.get("exceptions") or [])
            + (general.get("escalations") or [])
        )
        gq = [str(x.get("quote") or "") for x in g]
        if gq:
            sc = BM25(gq).scores(case_q)
            for q, s in sorted(zip(gq, sc), key=lambda x: -x[1])[:5]:
                if s > 0:
                    ids |= {st["id"] for st in sts if q and (st["text"][:60] in q or q[:60] in st["text"])}
    return ids


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="hbg38_L_t1,hbg38_L_t2,hbh_L_t1,hbh_L_t2,hbh_L_t3")
    ap.add_argument("--no-kev", action="store_true")
    args = ap.parse_args()
    ask = None
    if not args.no_kev:
        from dotenv import dotenv_values

        os.environ.setdefault(
            "OPENROUTER_API_KEY", dotenv_values(BENCH.parent / ".env").get("OPENROUTER_API_KEY") or ""
        )
        from cuga.policy_layer.detectors import systemone_questions

        ask = systemone_questions()
    tasks = [
        "hr_crestwood_university_79786c46",
        "insurance_vanguard_shield_mutual_9b2f7a29",
        "medical_careig_specialty_pharmacy_f5947c33",
    ]
    totals = defaultdict(lambda: Counter())
    for task in tasks:
        b, sts, secs, parent = load_task(task)
        procs = [p for p in b["procedures"] if p.get("steps")]
        general = next((p for p in b["procedures"] if not p.get("steps")), None)
        links = b.get("links") or []
        pindex = BM25([proc_text(p) for p in procs])
        sindex = BM25([s["text"] for s in sts])
        rubric = {}
        cases = []  # (run, case dict, loop's chosen procedure name)
        for run in args.runs.split(","):
            for f in glob_one(run, task):
                r = json.load(open(f))
                for it in r.get("rubrics") or []:
                    rubric[it["id"]] = it["text"]
                chosen = {
                    e.get("case"): e.get("procedure")
                    for e in r.get("sop_loop") or []
                    if e.get("phase") == "case"
                }
                for e in r.get("sop_loop") or []:
                    if e.get("phase") == "plan":
                        cases += [
                            (run, c, chosen.get(c.get("case"))) for c in e.get("cases") or [] if c.get("case")
                        ]
        deciding = {}
        for iid, text in rubric.items():  # rubric item -> its deciding SOP statement
            sc = sindex.scores(text)
            i = max(range(len(sc)), key=sc.__getitem__)
            deciding[iid] = sts[i]["id"] if sc[i] > 8 else None
        for run, c, loop_choice in cases:
            keys = [k for k in c.get("keys") or [] if len(k) >= 3]
            mine = [
                iid
                for iid, t in rubric.items()
                if deciding.get(iid) and any(k.lower() in t.lower() for k in keys)
            ]
            if not mine:
                continue
            q = f"{c['case']}. {c.get('summary', '')}"
            sc = pindex.scores(q)
            order = sorted(range(len(procs)), key=lambda i: -sc[i])
            gold_ids = {deciding[i] for i in mine}
            cover = [len(expand(p, sts, secs, parent, links, general, q, True) & gold_ids) for p in procs]
            best = max(
                range(len(procs)), key=lambda i: cover[i]
            )  # procedure that holds most of the case's items
            kev_rank = order[:5]
            if ask is not None:
                ps_ = []
                for i in order[:5]:
                    p = procs[i]
                    a = ask(
                        f"Case: {c['case']}\nSummary: {c.get('summary', '')}\n\nSOP procedure: {p['name']}\nFirst steps: "
                        + " / ".join(s.get("quote", "")[:120] for s in (p.get("steps") or [])[:4]),
                        {"applies": KEV_Q},
                    ).get("applies")
                    ps_.append((a if a is not None else -1, -order.index(i), i))
                kev_rank = [i for _, _, i in sorted(ps_, reverse=True)]
            loop_i = next((i for i, p in enumerate(procs) if p["name"] == loop_choice), None)
            variants = {
                "L0 loop's recorded choice": ([loop_i] if loop_i is not None else [], False),
                "B1 BM25 top-1": ([order[0]], False),
                "R1 BM25 + Kev top-1": ([kev_rank[0]], False),
                "R2 R1 + links, templates, general rules": ([kev_rank[0]], True),
                "R3 R2 for top-2": (kev_rank[:2], True),
            }
            t = totals
            t["cases"]["n"] += 1
            t["cases"]["items"] += len(gold_ids)
            for name, (chosen_i, hop) in variants.items():
                ids = set()
                for i in chosen_i:
                    ids |= expand(procs[i], sts, secs, parent, links, general, q, hop)
                t[name]["right_procedure"] += int(best in chosen_i)
                t[name]["items_covered"] += len(ids & gold_ids)
                t[name]["checklist_statements"] += len(ids)
                t[name]["checklist_chars"] += sum(len(s["text"]) for s in sts if s["id"] in ids)
    n, items = totals["cases"]["n"], totals["cases"]["items"]
    print(f"cases {n} (from runs {args.runs}), rubric items mapped to cases {items}")
    print(
        f"{'variant':44} {'right procedure':>16} {'checklist recall':>17} {'statements/case':>16} {'chars/case':>11}"
    )
    for name in [k for k in totals if k != "cases"]:
        v = totals[name]
        print(
            f"{name:44} {100 * v['right_procedure'] / n:15.0f}% {100 * v['items_covered'] / items:16.0f}% {v['checklist_statements'] / n:16.1f} {v['checklist_chars'] / n:11.0f}"
        )
    if ask is not None:
        print("Kev:", dict(getattr(ask, "usage", {})))


def glob_one(run: str, task: str):
    import glob

    return glob.glob(str(BENCH / f"handbook/results/{run}/{task}.json"))


if __name__ == "__main__":
    main()
