#!/usr/bin/env python3
"""Side-by-side page of one HANDBOOK task: CUGA alone vs CUGA + procedure guide (same trial number).

Per arm: the rubric result, the timeline of writes (reads are counted, not listed), the guide's stops with the agent's
next words. Built from the runner's result files and CUGA trajectories only.

  python3 benchmarks/handbook/render_side_by_side.py <task> <trial> <out.html> [--extra-task <task> --extra-trial <n>]
"""

import argparse
import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
READ = ("read", "get", "list", "search", "find", "query", "fetch", "download")
e = html.escape


def is_read(tool: str) -> bool:
    name = tool.split("__", 1)[-1].lower()
    return name.startswith(READ) or "read" in name


def load(run: str, task: str):
    r = json.loads((RES / run / f"{task}.json").read_text())
    traj = json.loads(Path(r["trajectory"]).read_text())["steps"]
    return r, traj


def narration(prompts) -> str:
    """The last thing the agent wrote before this model call (its previous turn's text)."""
    for m in reversed(prompts or []):
        if str(m.get("role", "")).lower() in ("assistant", "ai") and str(m.get("value", "")).strip():
            return str(m["value"]).strip()
    return ""


def items(step):
    """A step's data as a list of dicts (some steps store it as a JSON string)."""
    data = step.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return []
    out = []
    for x in data if isinstance(data, list) else []:
        if isinstance(x, str):
            try:
                x = json.loads(x)
            except ValueError:
                continue
        if isinstance(x, dict):
            out.append(x)
    return out


def timeline(r, traj):
    """Writes in order, read counts between them, guide stops with the agent's next words."""
    ai = [s for s in traj if s.get("name") == "Assistant_tool_calls"]
    results = [s for s in traj if s.get("name") == "Tool_results"]
    stops = {}
    for s in results:
        for x in items(s):
            c = str(x.get("content", ""))
            if "SOP CHECK" in c or "SOP TEMPLATE" in c:
                stops[x.get("tool_call_id")] = c[c.find("SOP ") :][:1200]
    rows, reads = [], 0
    for k, s in enumerate(ai):
        for call in items(s):
            tool, args = call.get("name", ""), call.get("args") or {}
            if (
                is_read(tool)
                or tool.endswith(("executePython", "executeBash"))
                and not stops.get(call.get("id"))
            ):
                reads += 1
                continue
            if reads:
                rows.append(("reads", f"{reads} read call(s)"))
                reads = 0
            stop = stops.get(call.get("id"))
            if stop:
                nxt = narration(ai[k + 1]["prompts"]) if k + 1 < len(ai) else ""
                rows.append(("stop", tool, args, stop, nxt))
            else:
                rows.append(("write", tool, args))
    if reads:
        rows.append(("reads", f"{reads} read call(s)"))
    return rows


def short_args(args) -> str:
    keep = {
        k: v
        for k, v in args.items()
        if k
        in (
            "to",
            "subject",
            "summary",
            "channel",
            "channel_id",
            "text",
            "assignee",
            "project_key",
            "issue_key",
            "title",
            "file_path",
            "code",
        )
    }
    s = json.dumps(keep or args, ensure_ascii=False)
    return s[:230] + ("…" if len(s) > 230 else "")


def column(title, r, rows) -> str:
    out = [
        f'<div class="col"><h3>{e(title)}</h3><div class="score">{r.get("rubrics_passed")} of {r.get("rubrics_total")} '
        f'rubric items</div><ol class="tl">'
    ]
    for row in rows:
        if row[0] == "reads":
            out.append(f'<li class="reads">{e(row[1])}</li>')
        elif row[0] == "write":
            out.append(
                f'<li class="write"><code>{e(row[1])}</code><div class="args">{e(short_args(row[2]))}</div></li>'
            )
        else:
            _, tool, args, stop, nxt = row
            out.append(
                f'<li class="stop"><div class="tag">Guide stopped this call</div><code>{e(tool)}</code>'
                f'<div class="args">{e(short_args(args))}</div><pre>{e(stop)}</pre>'
                + (f'<div class="next"><b>Agent, next:</b> {e(nxt[:700])}</div>' if nxt else "")
                + '</li>'
            )
    out.append("</ol></div>")
    return "".join(out)


def rubric_table(ra, rg) -> str:
    rows = []
    for a, g in zip(ra["rubrics"], rg["rubrics"]):
        pa, pg = bool(a.get("pass")), bool(g.get("pass"))
        cls = "up" if pg and not pa else ("down" if pa and not pg else "")
        rows.append(
            f'<tr class="{cls}"><td>{e(a.get("text", "")[:220])}</td><td class="c">{"pass" if pa else "fail"}</td>'
            f'<td class="c">{"pass" if pg else "fail"}</td></tr>'
        )
    return (
        '<div class="tw"><table><tr><th>Rubric item (grader, read after the run)</th><th>Alone</th><th>+ guide</th></tr>'
        + "".join(rows)
        + "</table></div>"
    )


def section(task: str, trial: int, note: str) -> str:
    ra, ta = load(f"hbg_A_t{trial}", task)
    rg, tg = load(f"hbg_G_t{trial}", task)
    tdir = Path.home() / "dev/untrusted/handbook-sample/tasks" / task
    instr = (tdir / "instruction.md").read_text().strip()
    return (
        f'<section class="slide"><h2>{e(task.rsplit("_", 1)[0].replace("_", " "))} — trial {trial}</h2>'
        f'<p class="sub">{e(note)}</p><details><summary>Task instruction</summary><p>{e(instr)}</p></details>'
        f'<div class="cols">{column("CUGA alone", ra, timeline(ra, ta))}{column("CUGA + procedure guide", rg, timeline(rg, tg))}</div>'
        f'<h3>Rubric items</h3>{rubric_table(ra, rg)}</section>'
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("trial", type=int)
    ap.add_argument("out")
    ap.add_argument("--note", default="")
    ap.add_argument("--extra-task")
    ap.add_argument("--extra-trial", type=int)
    ap.add_argument("--extra-note", default="")
    a = ap.parse_args()
    body = section(a.task, a.trial, a.note)
    if a.extra_task:
        body += section(a.extra_task, a.extra_trial, a.extra_note)
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>HANDBOOK: CUGA alone vs CUGA + procedure guide</title><style>
:root{{--ink:#111827;--ink2:#374151;--muted:#6b7280;--line:#e5e7eb;--good:#047857;--bad:#b91c1c;--warn:#b45309}}
*{{box-sizing:border-box}}body{{margin:0;background:#f3f4f6;color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
.wrap{{max-width:1150px;margin:0 auto;padding:24px 16px 64px}}h1{{font-size:26px;margin:0 0 6px}}.lead{{color:var(--ink2);margin:0 0 18px}}
.slide{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:22px 24px;margin-bottom:20px}}h2{{margin:0 0 4px;font-size:21px}}
.sub{{color:var(--ink2);margin:0 0 10px}}details{{margin:0 0 14px;color:var(--ink2);font-size:14px}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}@media(max-width:800px){{.cols{{grid-template-columns:1fr}}}}
.col{{border:1px solid var(--line);border-radius:10px;padding:12px 14px;background:#fafafa;min-width:0}}h3{{margin:4px 0 6px;font-size:16px}}
.score{{font-weight:700;margin-bottom:8px}}ol.tl{{list-style:none;padding:0;margin:0}}ol.tl li{{margin:6px 0;padding:7px 9px;border-radius:7px;font-size:13px;overflow-wrap:anywhere}}
.reads{{color:var(--muted);font-size:12.5px;padding:2px 9px!important}}.write{{background:#fff;border:1px solid var(--line)}}
.stop{{background:#fffbeb;border-left:3px solid var(--warn)}}.tag{{font-weight:700;color:var(--warn);font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
.args{{color:var(--ink2);font-size:12px;margin-top:2px}}code{{font:12px ui-monospace,Menlo,monospace}}
pre{{white-space:pre-wrap;font:12px/1.45 ui-monospace,Menlo,monospace;background:#fff;border:1px solid #fde68a;border-radius:6px;padding:8px;margin:6px 0}}
.next{{font-size:12.5px;background:#eff6ff;border-radius:6px;padding:6px 8px}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:6px}}th{{text-align:left;font-size:11.5px;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--line);padding:0 8px 6px 0}}
td{{padding:7px 8px 7px 0;border-bottom:1px solid #f1f3f5;vertical-align:top}}td.c{{white-space:nowrap}}tr.up td{{background:#ecfdf5}}tr.down td{{background:#fef2f2}}.tw{{overflow-x:auto}}
</style></head><body><div class="wrap"><h1>HANDBOOK: CUGA alone vs CUGA + procedure guide</h1>
<p class="lead">Same task and trial number, both arms run at the same time. The guide uses only the SOP (offline intake);
the grader is read only after the run. Green rows: passed only with the guide; red rows: passed only without it.</p>
{body}</div></body></html>'''
    Path(a.out).write_text(page)
    print("written", a.out, len(page))


if __name__ == "__main__":
    main()
