"""Render one AutomationBench run of CUGA as a self-contained HTML page.

    .venv/bin/python render_trajectory.py results/<run>/<task>.json [-o out.html]

Shows the task given to the agent, the score, the failed checks, every model turn with its tool calls and
results, and the final answer. Write calls that match a failed check (its target, and its text if it has one) are marked red. If the same
task and trial exists in another arm of the same run family (e.g. u3p_A_t1 and u3p_T_t1), its score is shown too.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
READ_WORDS = ("get", "find", "list", "search", "read", "lookup", "fetch", "query", "retrieve", "view")
ID_KEYS = ("id", "to", "email", "channel", "recipient", "address", "phone", "user", "row")


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def load_prompt(task: str) -> tuple[str, str]:
    try:
        import sys

        sys.path.insert(0, str(HERE))
        from ab_env import load_task

        t = load_task(task)
        system = "\n\n".join(m["content"] for m in t["prompt"] if m["role"] == "system")
        user = "\n\n".join(m["content"] for m in t["prompt"] if m["role"] == "user")
        return system, user
    except Exception as exc:  # noqa: BLE001 - the page still renders without the prompt
        return "", f"(task prompt not available: {type(exc).__name__})"


def is_read(tool: str) -> bool:
    words = re.split(r"[_\W]+", tool.lower())
    return any(w in READ_WORDS for w in words)


def check_text(f: dict) -> str:
    words = f["type"].replace("_", " ")
    params = ", ".join(f"{k} = {v}" for k, v in f["params"].items())
    return f"{words} ({params})"


def id_values(params: dict) -> list[str]:
    out = []
    for k, v in params.items():
        if isinstance(v, str) and len(v) >= 3 and any(w in k.lower() for w in ID_KEYS):
            out.append(v)
    return out


def text_values(params: dict) -> list[str]:
    """Content a check looks for (e.g. body_contains), lower-cased: a write must carry it to be the cause."""
    return [v.lower() for k, v in params.items() if isinstance(v, str) and v and "contain" in k.lower()]


GENERIC = {
    "not",
    "has",
    "with",
    "contains",
    "contain",
    "equals",
    "field",
    "exists",
    "is",
    "to",
    "in",
    "by",
    "of",
    "the",
    "and",
    "or",
    "count",
    "ticket",
    "message",
    "row",
    "record",
    "event",
    "item",
}


def action_overlap(check_type: str, tool: str) -> bool:
    """Does the tool name share the check's action word (e.g. 'comment'), beyond the app prefix and generic words?"""
    a, b = check_type.lower().split("_"), tool.lower().split("_")
    k = 0
    while k < min(len(a), len(b)) and a[k] == b[k]:
        k += 1
    return bool((set(a[k:]) & set(b[k:])) - GENERIC)


def related(f: dict, name: str, blob: str) -> bool:
    ids, texts = id_values(f["params"]), text_values(f["params"])
    if is_read(name) or not ids or not any(v in blob for v in ids):
        return False
    return not texts or any(t in blob.lower() for t in texts)


def turns_from(traj: dict) -> list[dict]:
    """One entry per model turn: its tool calls with results, or a text message."""
    turns, pending = [], None
    for s in traj.get("steps", []):
        name, data = s.get("name"), s.get("data") or ""
        if name == "Assistant_tool_calls":
            try:
                calls = json.loads(data)
            except ValueError:
                calls = []
            pending = {
                "kind": "calls",
                "calls": [{"name": c.get("name"), "args": c.get("args"), "id": c.get("id")} for c in calls],
            }
            turns.append(pending)
        elif name == "Tool_results" and pending:
            try:
                res = {r.get("tool_call_id"): r for r in json.loads(data)}
            except ValueError:
                res = {}
            for c in pending["calls"]:
                r = res.get(c["id"]) or {}
                c["status"], c["result"] = r.get("status"), r.get("content")
            pending = None
        elif name == "Assistant_nl":
            turns.append({"kind": "text", "text": data})
    return turns


def sibling_scores(rec_path: Path, rec: dict) -> list[str]:
    run = rec_path.parent.name
    m = re.match(r"(.+)_([A-Za-z]+)_(t\d+)$", run)
    if not m:
        return []
    out = []
    for d in sorted(rec_path.parent.parent.glob(f"{m.group(1)}_*_{m.group(3)}")):
        if d.name == run or not (d / rec_path.name).exists():
            continue
        o = json.loads((d / rec_path.name).read_text())
        n = o.get("n_scored") or 0
        ok = round((o.get("partial_credit") or 0) * n)
        out.append(
            f"<b>{esc(d.name)}</b>: {'PASS' if o.get('pass') else 'FAIL'}, {ok}/{n} checks, "
            f"{len(o.get('tool_calls') or [])} tool calls, guardrail broken: {'yes' if o.get('guard_broken') else 'no'}"
        )
    return out


CSS = """
:root{--ink:#111827;--ink2:#374151;--muted:#6b7280;--line:#e5e7eb;--plane:#f3f4f6;--ours:#1d4ed8;--good:#047857;--warn:#b45309;--bad:#b91c1c}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:980px;margin:0 auto;padding:24px 16px 64px}
.card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:22px 24px;margin-bottom:16px}
h1{font-size:24px;margin:0 0 4px;letter-spacing:-.01em;overflow-wrap:anywhere}
h2{font-size:17px;margin:0 0 12px}
.meta{color:var(--muted);font-size:13px;overflow-wrap:anywhere}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:16px}
.kpi{border:1px solid var(--line);border-radius:10px;padding:12px 14px;background:#fafafa}
.kpi .k{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:700}
.kpi .v{font-size:24px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
.v.bad{color:var(--bad)}.v.good{color:var(--good)}
.prompt{white-space:pre-wrap;background:#f8fafc;border-left:3px solid var(--ours);padding:12px 14px;border-radius:0 8px 8px 0;font-size:14px;overflow-wrap:anywhere}
details{margin-top:8px}summary{cursor:pointer;color:var(--ours);font-size:13px;padding:6px 0}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;background:#f9fafb;border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:6px 0 0;max-height:420px;overflow:auto}
.fail{border-left:3px solid var(--bad);background:#fef2f2;padding:8px 12px;border-radius:0 8px 8px 0;margin:6px 0;font-size:14px;overflow-wrap:anywhere}
.tag{display:inline-block;font-size:11px;font-weight:700;border-radius:999px;padding:1px 8px;margin-right:6px;vertical-align:1px}
.t-neg{background:#fee2e2;color:var(--bad)}.t-pos{background:#e0e7ff;color:var(--ours)}
.turn{display:flex;gap:12px;margin:14px 0}
.num{flex:0 0 34px;height:34px;border-radius:50%;background:#eef2ff;color:var(--ours);font-weight:700;display:flex;align-items:center;justify-content:center;font-size:13px}
.body{flex:1;min-width:0}
.call{border:1px solid var(--line);border-left:4px solid #9ca3af;border-radius:8px;padding:10px 12px;margin-bottom:8px;background:#fff}
.call.write{border-left-color:var(--ours)}.call.hit{border-left-color:var(--bad);background:#fffafa}
.call .name{font:600 13.5px ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}
.chip{font-size:11px;color:var(--muted);border:1px solid var(--line);border-radius:6px;padding:0 6px;margin-left:6px;font-family:system-ui}
.args{margin:6px 0 0;font-size:13px;color:var(--ink2);overflow-wrap:anywhere}
.args b{color:var(--ink)}
.status{font-size:12px;margin-left:6px}.ok{color:var(--good)}.err{color:var(--bad)}
.note{font-size:12.5px;color:var(--bad);margin-top:4px}
.text{white-space:pre-wrap;background:#f8fafc;border:1px solid var(--line);border-radius:8px;padding:10px 12px;font-size:14px;overflow-wrap:anywhere}
.legend{font-size:12.5px;color:var(--muted);margin-top:4px}
.legend span{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px -1px 10px}
@media (max-width:640px){.card{padding:16px}h1{font-size:20px}.num{flex-basis:28px;height:28px}}
"""


def render(rec_path: Path) -> str:
    rec = json.loads(rec_path.read_text())
    traj_path = Path(rec["trajectory"]) if rec.get("trajectory") else None
    traj = json.loads(traj_path.read_text()) if traj_path and traj_path.exists() else {"steps": []}
    system, user = load_prompt(rec["task"])
    failed = rec.get("failed") or []
    n = rec.get("n_scored") or 0
    passed = round((rec.get("partial_credit") or 0) * n)
    turns = turns_from(traj)
    apps = sorted(rec.get("apps") or [], key=len, reverse=True)
    # per failed check, the write calls that match it; keep the ones named like the check's action when there are any
    cause: dict[int, set] = {}
    for i, f in enumerate(failed):
        cands = [
            (k, j)
            for k, t in enumerate(turns)
            if t["kind"] == "calls"
            for j, c in enumerate(t["calls"])
            if related(f, c["name"] or "", json.dumps(c["args"] or {}, ensure_ascii=False))
        ]
        named = [kj for kj in cands if action_overlap(f["type"], turns[kj[0]]["calls"][kj[1]]["name"] or "")]
        cause[i] = set(named or cands)
    ncalls = sum(len(t["calls"]) for t in turns if t["kind"] == "calls")
    nwrites = sum(
        1 for t in turns if t["kind"] == "calls" for c in t["calls"] if not is_read(c["name"] or "")
    )

    h = [
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{esc(rec['task'])} · {esc(rec_path.parent.name)}</title><style>{CSS}</style></head><body><div class='wrap'>"
    ]
    h.append("<div class='card'>")
    h.append(f"<h1>{esc(rec['task'])}</h1>")
    h.append(
        f"<div class='meta'>Run <b>{esc(rec_path.parent.name)}</b> · arm {esc(rec.get('arm'))} · {esc(rec.get('model'))} · "
        f"toolset {esc(rec.get('toolset'))} · apps: {esc(', '.join(rec.get('apps') or []))} · {esc(rec.get('wall_s'))} s · "
        f"world time {esc(str(rec.get('world_time') or '')[:16])}</div>"
    )
    res_cls = "good" if rec.get("pass") else "bad"
    h.append(
        "<div class='grid'>"
        f"<div class='kpi'><div class='k'>Result</div><div class='v {res_cls}'>{'PASS' if rec.get('pass') else 'FAIL'}</div></div>"
        f"<div class='kpi'><div class='k'>Checks passed</div><div class='v'>{passed} / {n}</div></div>"
        f"<div class='kpi'><div class='k'>Guardrail broken</div><div class='v {'bad' if rec.get('guard_broken') else 'good'}'>{'yes' if rec.get('guard_broken') else 'no'}</div></div>"
        f"<div class='kpi'><div class='k'>Tool calls</div><div class='v'>{ncalls}</div><div class='meta'>{nwrites} writes · {len(turns)} model turns</div></div>"
        "</div>"
    )
    sib = sibling_scores(rec_path, rec)
    if sib:
        h.append(
            "<div class='meta' style='margin-top:12px'>Same task, same trial, other arms: "
            + " · ".join(sib)
            + "</div>"
        )
    h.append("</div>")

    h.append("<div class='card'><h2>Task given to the agent</h2>")
    h.append(f"<div class='prompt'>{esc(user)}</div>")
    if system:
        h.append(
            f"<details><summary>System message ({len(system):,} characters)</summary><pre>{esc(system)}</pre></details>"
        )
    h.append("</div>")

    h.append(f"<div class='card'><h2>Failed checks ({len(failed)})</h2>")
    if not failed:
        h.append("<div class='meta'>None: every scored check passed.</div>")
    for i, f in enumerate(failed, 1):
        tag = (
            "<span class='tag t-neg'>must not happen</span>"
            if f.get("negative")
            else "<span class='tag t-pos'>required</span>"
        )
        h.append(f"<div class='fail'><b>#{i}</b> {tag}{esc(check_text(f))}</div>")
    h.append(
        "<div class='legend'>Checks that already held before the agent acted, and still hold, are not scored.</div></div>"
    )

    h.append(
        "<div class='card'><h2>What the agent did</h2><div class='legend'>"
        "<span style='background:#9ca3af'></span>read<span style='background:#1d4ed8'></span>write"
        "<span style='background:#b91c1c'></span>write that broke a failed check</div>"
    )
    for k, t in enumerate(turns, 1):
        h.append(f"<div class='turn'><div class='num'>{k}</div><div class='body'>")
        if t["kind"] == "text":
            h.append(f"<div class='text'>{esc(t['text'])}</div>")
        else:
            for c in t["calls"]:
                name = c["name"] or "?"
                args = c["args"] or {}
                hits = [i + 1 for i in cause if (k - 1, t['calls'].index(c)) in cause[i]]
                cls = "call hit" if hits else ("call" if is_read(name) else "call write")
                app = next((x for x in apps if name.startswith(x + "_")), name.split("_", 1)[0])
                st = c.get("status")
                st_html = f"<span class='status {'ok' if st == 'success' else 'err'}'>{esc(st or 'no result')}</span>"
                h.append(
                    f"<div class='{cls}'><span class='name'>{esc(name)}</span><span class='chip'>{esc(app)}</span>{st_html}"
                )
                if args:
                    parts = []
                    for a, v in args.items():
                        sv = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                        parts.append(f"<b>{esc(a)}</b>: {esc(sv if len(sv) < 300 else sv[:300] + ' …')}")
                    h.append("<div class='args'>" + "<br>".join(parts) + "</div>")
                if hits:
                    h.append(
                        f"<div class='note'>Likely cause of failed check {', '.join('#' + str(x) for x in hits)}</div>"
                    )
                result = c.get("result")
                if result:
                    try:
                        result = json.dumps(json.loads(result), indent=2, ensure_ascii=False)
                    except (TypeError, ValueError):
                        pass
                    result = str(result)
                    short = result if len(result) <= 6000 else result[:6000] + "\n… (cut)"
                    h.append(
                        f"<details><summary>Result ({len(result):,} characters)</summary><pre>{esc(short)}</pre></details>"
                    )
                h.append("</div>")
        h.append("</div></div>")
    h.append("</div>")

    h.append(f"<div class='card'><h2>Final answer</h2><div class='text'>{esc(rec.get('answer'))}</div></div>")
    h.append(f"<div class='meta'>Source: {esc(rec_path)} · trajectory: {esc(traj_path)}</div>")
    h.append("</div></body></html>")
    return "".join(h)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("record", type=Path, help="results/<run>/<task>.json")
    ap.add_argument("-o", "--out", type=Path, help="output HTML (default results/html/<run>__<task>.html)")
    a = ap.parse_args()
    rec = a.record.resolve()
    out = a.out or HERE / "results" / "html" / f"{rec.parent.name}__{rec.stem}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(rec), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
