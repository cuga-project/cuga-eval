"""Compare two VAKRA submissions task by task (e.g. ours vs the campaign's) — no ground truth involved.

For every task in either submission (matched by capability directory + uuid) it records both answers,
both tool-call sequences and both statuses, and puts the task in one category:

* ``same``          — the answers match after normalization (case, whitespace, quotes, number format)
* ``contained``     — the shorter answer appears whole inside the longer one (a value vs a sentence)
* ``same_numbers``  — the texts differ but carry the same numbers (likely the same answer, worded differently)
* ``different``     — both answered, differently
* ``only_a``        — only submission A answered (B is empty or errored)
* ``only_b``        — only submission B answered
* ``neither``       — both empty
* ``missing_a`` / ``missing_b`` — the task is absent from that submission

Outputs (in ``--out``): ``summary.txt`` (per capability and per domain counts, also printed),
``tasks.csv`` (one row per task) and ``report.html`` (a self-contained page with filters and search;
it stays local — the test queries are benchmark data).

usage: python -m benchmarks.m3.parity.compare_submissions --a OURS_DIR --b CAMPAIGN_DIR
           [--a-name ours] [--b-name campaign] [--out DIR]
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CATEGORIES = (
    "same",
    "contained",
    "same_numbers",
    "different",
    "only_a",
    "only_b",
    "neither",
    "missing_a",
    "missing_b",
)
_NUM = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")
_MONTHS = {
    m: i
    for i, m in enumerate(
        "january february march april may june july august september october november december".split(), 1
    )
}
_DATE_MDY = re.compile(r"\b(" + "|".join(_MONTHS) + r")\.? (\d{1,2})(?:st|nd|rd|th)? ?,? (\d{4})\b")
_DATE_DMY = re.compile(r"\b(\d{1,2}) (" + "|".join(_MONTHS) + r") ?,? (\d{4})\b")
_SPACES = str.maketrans(
    {"\u202f": " ", "\u00a0": " ", "\u2009": " ", "\u2011": "-", "\u2013": "-", "\u2014": "-"}
)


def load_submission(root: Path) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """``{(capability_dir, uuid): record}`` for every ``<capability_dir>/<domain>.json`` under ``root``."""
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for f in sorted(Path(root).glob("capability_*/*.json")):
        if f.name.endswith("_tools.json"):
            continue  # tool-log sidecars are not part of a submission
        for rec in json.loads(f.read_text()):
            rec.setdefault("domain", f.stem)
            out[(f.parent.name, str(rec["uuid"]))] = rec
    return out


def final_turn(rec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    turns = (rec or {}).get("output") or []
    return turns[-1] if turns else {}


def answer_of(rec: Optional[Dict[str, Any]]) -> str:
    return str(final_turn(rec).get("answer") or "").strip()


def tools_of(rec: Optional[Dict[str, Any]]) -> List[str]:
    return [str(c.get("name")) for c in (final_turn(rec).get("sequence") or {}).get("tool_call") or []]


def _number(token: str) -> str:
    plain = token.replace(",", "")
    value = float(plain)
    if not math.isfinite(value) or abs(value) >= 1e15:  # ids and long digit strings stay as written
        return plain
    return str(int(value)) if value == int(value) else repr(round(value, 6))


def numbers(text: str) -> List[str]:
    return sorted(_number(t) for t in _NUM.findall(text))


def normalize(text: str) -> str:
    """Case, whitespace, markdown bold, wrapping quotes/brackets, dates (July 1, 2013 == 2013-07-01) and numbers."""
    t = text.translate(_SPACES).replace("**", "").replace("`", "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = _DATE_MDY.sub(lambda m: f"{m.group(3)}-{_MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}", t)
    t = _DATE_DMY.sub(lambda m: f"{m.group(3)}-{_MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}", t)
    t = re.sub(r"^[\s\"'`\[\(]+|[\s\"'`\]\)\.]+$", "", t)
    t = _NUM.sub(lambda m: _number(m.group(0)), t)
    return re.sub(r"\s+", " ", t)


def categorize(a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> str:
    if a is None:
        return "missing_a"
    if b is None:
        return "missing_b"
    aa, ab = answer_of(a), answer_of(b)
    if not aa and not ab:
        return "neither"
    if not ab:
        return "only_a"
    if not aa:
        return "only_b"
    na_, nb_ = normalize(aa), normalize(ab)
    if na_ == nb_:
        return "same"
    short, long_ = sorted((na_, nb_), key=len)
    if short and re.search(r"(?<![\w.])" + re.escape(short) + r"(?![\w]|\.\d)", long_):
        return "contained"  # the shorter answer appears whole inside the longer one (value vs sentence)
    na, nb = numbers(aa), numbers(ab)
    if na and na == nb:
        return "same_numbers"
    return "different"


def compare(a_root: Path, b_root: Path) -> List[Dict[str, Any]]:
    a, b = load_submission(a_root), load_submission(b_root)
    rows = []
    for key in sorted(set(a) | set(b)):
        ra, rb = a.get(key), b.get(key)
        ta, tb = tools_of(ra), tools_of(rb)
        rows.append(
            dict(
                capability=key[0],
                domain=(ra or rb or {}).get("domain", ""),
                uuid=key[1],
                category=categorize(ra, rb),
                query=str(final_turn(ra or rb).get("query") or ""),
                answer_a=answer_of(ra),
                answer_b=answer_of(rb),
                status_a=(ra or {}).get("status", "missing"),
                status_b=(rb or {}).get("status", "missing"),
                error_a=str((ra or {}).get("error") or ""),
                error_b=str((rb or {}).get("error") or ""),
                tools_a=" > ".join(ta),
                tools_b=" > ".join(tb),
                n_tools_a=len(ta),
                n_tools_b=len(tb),
                same_tools=ta == tb,
            )
        )
    return rows


def summarize(rows: List[Dict[str, Any]], a_name: str, b_name: str) -> str:
    label = {
        "only_a": f"only_{a_name}",
        "only_b": f"only_{b_name}",
        "missing_a": f"missing_{a_name}",
        "missing_b": f"missing_{b_name}",
    }
    head = (
        ["tasks"]
        + [label.get(c, c) for c in CATEGORIES]
        + [f"answered_{a_name}", f"answered_{b_name}", "same_tools"]
    )
    lines = [f"{'':40s}" + "".join(f"{h:>16s}" for h in head)]

    def line(name: str, group: List[Dict[str, Any]]) -> str:
        c = Counter(r["category"] for r in group)
        vals = [len(group)] + [c[k] for k in CATEGORIES]
        vals += [sum(1 for r in group if r["answer_a"]), sum(1 for r in group if r["answer_b"])]
        vals += [sum(1 for r in group if r["same_tools"])]
        return f"{name:40s}" + "".join(f"{v:16d}" for v in vals)

    by_cap: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_cap[r["capability"]].append(r)
    for cap in sorted(by_cap):
        lines.append(line(cap, by_cap[cap]))
    lines.append(line("ALL", rows))
    lines.append("")
    lines.append("Per domain (domains where the answered counts differ):")
    by_dom: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_dom[(r["capability"], r["domain"])].append(r)
    for (cap, dom), group in sorted(by_dom.items()):
        if sum(1 for r in group if r["answer_a"]) != sum(1 for r in group if r["answer_b"]):
            lines.append(line(f"  {cap.split('_')[1]}/{dom}", group))
    return "\n".join(lines)


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Submission diff</title>
<style>
:root{{--bg:#fff;--fg:#1d1d1f;--mut:#6e6e73;--line:#e3e3e8;--chip:#f2f2f5;--same:#e6f4ea;--diff:#fdecea;--only:#fff4e0}}
@media (prefers-color-scheme: dark){{:root{{--bg:#141416;--fg:#ececf0;--mut:#9a9aa2;--line:#2c2c31;--chip:#222227;--same:#16301f;--diff:#3a1c1c;--only:#3a2e14}}}}
body{{margin:0;padding:16px;font:14px/1.45 -apple-system,system-ui,sans-serif;background:var(--bg);color:var(--fg)}}
h1{{font-size:20px;margin:0 0 4px}} .mut{{color:var(--mut)}}
.bar{{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0;position:sticky;top:0;background:var(--bg);padding:8px 0;z-index:2}}
select,input{{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}}
input{{flex:1;min-width:180px}}
pre{{background:var(--chip);padding:10px;border-radius:8px;overflow-x:auto;font-size:12px}}
table{{border-collapse:collapse;width:100%;table-layout:fixed}}
td,th{{border-bottom:1px solid var(--line);padding:6px;vertical-align:top;text-align:left;word-break:break-word}}
th{{font-size:12px;color:var(--mut)}} tr.same td.c,tr.same_numbers td.c{{background:var(--same)}}
tr.different td.c{{background:var(--diff)}} tr.only_a td.c,tr.only_b td.c,tr.missing_a td.c,tr.missing_b td.c{{background:var(--only)}}
.t{{font-size:11px;color:var(--mut)}} .wrap{{overflow-x:auto}}
</style></head><body>
<h1>Submission diff: {a} vs {b}</h1>
<div class="mut">{n} tasks · A = {a} ({a_root}) · B = {b} ({b_root}) · no ground truth: "same" means the two answers agree, not that they are right.</div>
<pre>{summary}</pre>
<div class="bar"><select id="cap"><option value="">all capabilities</option>{cap_opts}</select>
<select id="cat"><option value="">all categories</option>{cat_opts}</select>
<input id="q" placeholder="search domain, uuid, query, answers, tools"><span class="mut" id="cnt"></span></div>
<div class="wrap"><table><thead><tr><th style="width:9%">capability / domain</th><th style="width:7%">category</th>
<th style="width:24%">query</th><th style="width:20%">{a}</th><th style="width:20%">{b}</th><th style="width:20%">tools {a} / {b}</th></tr></thead>
<tbody id="rows">{rows}</tbody></table></div>
<script>
const rows=[...document.querySelectorAll('#rows tr')];
function f(){{const cap=document.getElementById('cap').value,cat=document.getElementById('cat').value,
q=document.getElementById('q').value.toLowerCase();let n=0;
for(const r of rows){{const ok=(!cap||r.dataset.cap===cap)&&(!cat||r.dataset.cat===cat)&&(!q||r.textContent.toLowerCase().includes(q));
r.style.display=ok?'':'none';n+=ok}}document.getElementById('cnt').textContent=n+' shown'}}
for(const id of ['cap','cat','q'])document.getElementById(id).addEventListener('input',f);f();
</script></body></html>"""


def render_html(
    rows: List[Dict[str, Any]], summary: str, a_name: str, b_name: str, a_root: Path, b_root: Path
) -> str:
    e = html.escape
    label = {
        "only_a": f"only {a_name}",
        "only_b": f"only {b_name}",
        "missing_a": f"missing in {a_name}",
        "missing_b": f"missing in {b_name}",
        "same_numbers": "same numbers",
    }
    body = []
    for r in rows:
        ans_a = e(r["answer_a"]) or f'<span class="t">{e(r["status_a"])} {e(r["error_a"])}</span>'
        ans_b = e(r["answer_b"]) or f'<span class="t">{e(r["status_b"])} {e(r["error_b"])}</span>'
        tools = f'<div>{e(r["tools_a"]) or "—"}</div><div class="t">{e(r["tools_b"]) or "—"}</div>' + (
            "" if r["same_tools"] else '<div class="t">(tool sequences differ)</div>'
        )
        body.append(
            f'<tr class="{r["category"]}" data-cap="{e(r["capability"])}" data-cat="{r["category"]}">'
            f'<td>{e(r["capability"].split("_")[1])} / {e(r["domain"])}<div class="t">{e(r["uuid"])}</div></td>'
            f'<td class="c">{e(label.get(r["category"], r["category"]))}</td><td>{e(r["query"])}</td>'
            f"<td>{ans_a}</td><td>{ans_b}</td><td>{tools}</td></tr>"
        )
    caps = sorted({r["capability"] for r in rows})
    return _PAGE.format(
        a=e(a_name),
        b=e(b_name),
        a_root=e(str(a_root)),
        b_root=e(str(b_root)),
        n=len(rows),
        summary=e(summary),
        cap_opts="".join(f'<option value="{e(c)}">{e(c)}</option>' for c in caps),
        cat_opts="".join(f'<option value="{c}">{e(label.get(c, c))}</option>' for c in CATEGORIES),
        rows="".join(body),
    )


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--a", required=True, type=Path, help="submission A (e.g. ours)")
    p.add_argument("--b", required=True, type=Path, help="submission B (e.g. the campaign's)")
    p.add_argument("--a-name", default="ours")
    p.add_argument("--b-name", default="campaign")
    p.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / ".local" / "submission_diff")
    args = p.parse_args(argv)
    rows = compare(args.a, args.b)
    summary = summarize(rows, args.a_name, args.b_name)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.txt").write_text(summary + "\n")
    with open(args.out / "tasks.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["uuid"])
        writer.writeheader()
        writer.writerows(rows)
    (args.out / "report.html").write_text(
        render_html(rows, summary, args.a_name, args.b_name, args.a, args.b)
    )
    print(summary)
    print(f"\nwrote {args.out}/summary.txt, tasks.csv, report.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
