#!/usr/bin/env python3
"""Render one SOP's intake build as a page: each procedure with its steps (and the tool for each), preconditions,
exceptions, templates and escalations, plus the sections it refers to. Generated from the build JSON, so it works for
any SOP the intake has processed.

  python3 benchmarks/handbook/render_sop_graph.py <build.json> <out.html>
"""

import html
import json
import sys
from collections import defaultdict

b = json.load(open(sys.argv[1]))
build, ps, stats = b["build"], b["policy_set"], b["stats"]
doc = ps["documents"][0]
by_id = {s["id"]: s for s in doc["sections"]}


def _title(
    s,
):  # a subsection heading may have been parsed as its first statement: parent title + that heading
    if s.get("title"):
        return s["title"]
    first = (s.get("statements") or [{}])[0].get("text", "")
    parent = (by_id.get(s.get("parent") or "") or {}).get("title") or ""
    head = first if 0 < len(first) <= 80 else ""
    return " — ".join(x for x in (parent, head) if x)


titles = {f"{doc['id']}:{s['id']}": _title(s) for s in doc["sections"]}
st_sec = {st["id"]: f"{doc['id']}:{sec['id']}" for sec in doc["sections"] for st in sec["statements"]}
refs = defaultdict(set)
for link in build.get("links") or []:
    if str(link.get("type")) in ("refers_to", "LinkType.REFERS_TO"):
        a, z = st_sec.get(link["src"], link["src"]), st_sec.get(link["dst"], link["dst"])
        if a != z:
            refs[a].add(z)
e = html.escape


def sec_label(key):
    return f"§{key.split(':', 1)[1]} {titles.get(key, '')}".strip()


cards = []
for p in build.get("procedures") or []:
    key = p["id"]
    tpl_by_step = defaultdict(list)
    for t in p.get("templates") or []:
        step = str(t.get("step") or "0").strip()
        tpl_by_step[int(step) if step.isdigit() else 0].append(
            t
        )  # a template with no step number is shown under the steps
    pre = "".join(
        f'<li class="pre"><b>Must hold:</b> {e(str(x.get("condition", "")))}'
        f'<span class="tag">if not: {e(str(x.get("if_not", "")))}</span></li>'
        for x in p.get("preconditions") or []
    )
    exc = "".join(
        f'<li class="exc"><b>If</b> {e(str(x.get("when", "")))} <b>then</b> {e(str(x.get("then", "")))}</li>'
        for x in p.get("exceptions") or []
    )
    esc = "".join(
        f'<li class="esc"><b>Escalate</b> when {e(str(x.get("when", "")))} → {e(str(x.get("notify", "")))}'
        f' {e(str(x.get("channel", "") or ""))}</li>'
        for x in p.get("escalations") or []
    )
    steps = []
    for i, s in enumerate(p.get("steps") or [], 1):
        tool = f'<span class="tool">{e(s.get("action") or "no tool")}</span>'
        tpls = "".join(
            f'<div class="tpl">{e(str(t.get("artifact", "")))}: <code>{e(str(t.get("template", "")))}</code></div>'
            for t in tpl_by_step.get(i, [])
        )
        steps.append(
            f'<li class="step"><span class="n">{i}</span><div>{e(s.get("quote", "")[:220])} {tool}{tpls}</div></li>'
        )
    loose = "".join(
        f'<div class="tpl">{e(str(t.get("artifact", "")))}: <code>{e(str(t.get("template", "")))}</code></div>'
        for t in tpl_by_step.get(0, [])
    )
    links = ", ".join(e(sec_label(k)) for k in sorted(refs.get(key, set())))
    cards.append(f'''<section class="card"><h3>{e(sec_label(key) or p.get("name", ""))}</h3>
<ul class="rules">{pre}{exc}{esc}</ul><ol class="steps">{"".join(steps)}</ol>{loose}
{f'<div class="refs">Refers to: {links}</div>' if links else ''}</section>''')

counts = {
    k: sum(len(p.get(k) or []) for p in build.get("procedures") or [])
    for k in ("preconditions", "exceptions", "templates", "escalations")
}
page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SOP graph: {e(stats.get("sop", ""))}</title><style>
:root{{--ink:#111827;--muted:#6b7280;--line:#e5e7eb;--pre:#b45309;--exc:#b91c1c;--esc:#6d28d9;--tpl:#1d4ed8}}
*{{box-sizing:border-box}}body{{margin:0;background:#f3f4f6;color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
.wrap{{max-width:1100px;margin:0 auto;padding:24px 16px 64px}}h1{{font-size:26px;margin:0 0 6px}}.sub{{color:var(--muted);margin:0 0 18px}}
.legend span{{display:inline-block;margin:0 14px 8px 0;font-size:13px}}.legend i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:16px}}
.card{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px 18px}}h3{{margin:0 0 10px;font-size:16px}}
ul.rules{{list-style:none;padding:0;margin:0 0 8px}}ul.rules li{{font-size:13px;padding:6px 8px;border-radius:6px;margin:4px 0}}
.pre{{background:#fffbeb;border-left:3px solid var(--pre)}}.exc{{background:#fef2f2;border-left:3px solid var(--exc)}}.esc{{background:#f5f3ff;border-left:3px solid var(--esc)}}
.tag{{color:var(--muted);margin-left:6px}}ol.steps{{list-style:none;padding:0;margin:0}}
.step{{display:flex;gap:10px;padding:6px 0;border-top:1px solid #f1f3f5;font-size:13.5px}}.n{{flex:0 0 22px;height:22px;border-radius:50%;background:#111827;color:#fff;font-size:12px;display:flex;align-items:center;justify-content:center}}
.tool{{display:inline-block;font:12px ui-monospace,Menlo,monospace;background:#f3f4f6;border-radius:4px;padding:0 5px;color:#374151}}
.tpl{{font-size:12.5px;color:var(--tpl);margin-top:3px}}code{{font:12px ui-monospace,Menlo,monospace;background:#eff6ff;padding:1px 4px;border-radius:4px}}
.refs{{font-size:12.5px;color:var(--muted);margin-top:8px}}
</style></head><body><div class="wrap">
<h1>SOP graph: {e(stats.get("sop", ""))}</h1>
<p class="sub">Offline intake (gpt-oss-120b, {stats.get("seconds")} s): {stats.get("sections")} sections, {stats.get("statements")} statements,
{len(build.get("procedures") or [])} procedures with {stats.get("procedure_steps")} steps ({stats.get("steps_with_tool")} mapped to a tool);
{counts["preconditions"]} preconditions, {counts["exceptions"]} exceptions, {counts["templates"]} templates, {counts["escalations"]} escalations.
Every item comes with a verbatim quote from the SOP.</p>
<div class="legend"><span><i style="background:var(--pre)"></i>Must hold before starting</span><span><i style="background:var(--exc)"></i>Exception / stop / hold</span>
<span><i style="background:var(--esc)"></i>Escalation</span><span><i style="background:var(--tpl)"></i>Template for a step's output</span></div>
<div class="grid">{"".join(cards)}</div></div></body></html>'''
open(sys.argv[2], "w").write(page)
print("written", sys.argv[2], len(page))
