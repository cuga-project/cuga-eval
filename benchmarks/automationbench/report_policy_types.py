"""Report for the policy-types evaluation (run_policy_types.sh): one table per question, pooled over trials.

    .venv/bin/python -I report_policy_types.py [--base A-F]     # prints markdown, writes results/policy_types_report.md

Statistics count each task once: per task the mean over trials, then a two-sided sign test on better / worse tasks.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(sys.argv[0]).resolve().parent
RES = HERE / "results"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from policy_eval.harness.report import sign_p  # noqa: E402  (one place for the statistics)

CELLS = {"AO": "A-O", "AF": "A-F", "BF": "B-F", "TF": "T-F", "BTF": "BT-F", "DF": "D-F", "B3F": "B3-F", "B3TF": "B3T-F", "B4TF": "B4T-F", "B4TFM": "B4T-FM", "B5TF": "B5T-F", "B5aTF": "B5aT-F"}
LABEL = {
    "A-O": "CUGA alone, oracle tools",
    "A-F": "CUGA alone, 549 tools + dynamic binding",
    "B-F": "+ policy layer",
    "T-F": "+ requirements tracker",
    "BT-F": "+ policy layer + tracker",
    "D-F": "+ deliverables checklist",
    "B3-F": "+ policy layer with discovery + newer rule wins",
    "B3T-F": "+ B3 + tracker",
    "B4T-F": "+ B3T + decision checks, block once, skip after cap",
    "B4T-FM": "B4T-F with hook text as the newest message (not the system prompt)",
    "B5T-F": "+ B4T + record checks, hold on recheck",
    "B5aT-F": "+ B4T + record checks, no hold",
}


def app_of_tool() -> dict:
    from automationbench.tools import ALL_TOOLS
    from ab_env import tool_app

    return {t.__name__: tool_app(t) for t in ALL_TOOLS}


def load(trial=None, prefix="pt") -> dict:
    out = defaultdict(list)  # cell -> records
    for d in sorted(RES.glob(f"{prefix}_*_t{trial}" if trial else f"{prefix}_*_t*")):
        if not d.is_dir():
            continue
        cell = CELLS.get(d.name.split("_")[1])
        for f in d.glob("*.json"):
            r = json.loads(f.read_text())
            if isinstance(r, dict) and "partial_credit" in r:
                out[cell].append(r)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="A-F")
    ap.add_argument("--trial", help="only this trial (e.g. 2)")
    ap.add_argument("--prefix", default="pt", help="run prefix (pt = test subset, ph = held-out)")
    ap.add_argument("--subset", default="policy_types_subset.json")
    args = ap.parse_args()
    subset = json.loads((HERE / args.subset).read_text())
    ptype = {t["task"]: t["type"] for t in subset["tasks"]}
    types = list(subset["types"])
    data = load(args.trial, args.prefix)
    cells = [c for c in LABEL if data.get(c)]
    app_of = app_of_tool()
    lines = ["# Policy-types evaluation (gpt-oss-120b, function calling)", ""]

    lines += [
        "## Overall (all runs pooled)",
        "",
        "| Cell | Runs | Pass | Partial | AA | Runs breaking a guardrail | Guardrails broken | Needed app never used | Tool calls | Input tokens |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in cells:
        rs = data[c]
        n = len(rs)
        with_guards = [r for r in rs if r.get("n_guards")]
        broke = sum(bool(r.get("guards_broken")) for r in with_guards)
        missed = 0
        for r in rs:
            used = {app_of.get(x["tool"]) for x in r.get("tool_calls") or []}
            missed += bool(set(r.get("task_apps") or []) - used)
        tin = st.mean((r.get("receipt") or {}).get("input_tokens", 0) for r in rs)
        lines.append(
            f"| {c} {LABEL[c]} | {n} | {100 * st.mean(bool(r['pass']) for r in rs):.1f}% "
            f"| {100 * st.mean(r['partial_credit'] for r in rs):.1f}% | {100 * st.mean(r.get('aa', 0) for r in rs):.1f}% "
            f"| {broke}/{len(with_guards)} | {sum(r.get('guards_broken', 0) for r in rs)} | {missed}/{n} "
            f"| {st.mean(len(r.get('tool_calls') or []) for r in rs):.0f} | {tin:,.0f} |"
        )

    lines += ["", "## Partial score by policy type (mean over runs)", ""]
    lines += ["| Type | " + " | ".join(cells) + " |", "|---|" + "---|" * len(cells)]
    for t in types:
        row = []
        for c in cells:
            v = [r["partial_credit"] for r in data[c] if ptype.get(r["task"]) == t]
            row.append(f"{100 * st.mean(v):.1f}%" if v else "-")
        lines.append(f"| {t} | " + " | ".join(row) + " |")
    lines += ["", "## Runs breaking a guardrail, by policy type", ""]
    lines += ["| Type | " + " | ".join(cells) + " |", "|---|" + "---|" * len(cells)]
    for t in types:
        row = []
        for c in cells:
            v = [r for r in data[c] if ptype.get(r["task"]) == t and r.get("n_guards")]
            row.append(f"{sum(bool(r.get('guards_broken')) for r in v)}/{len(v)}" if v else "-")
        lines.append(f"| {t} | " + " | ".join(row) + " |")

    def per_task(c, key):
        by = defaultdict(list)
        for r in data[c]:
            by[r["task"]].append(float(r.get(key) or 0))
        return {k: st.mean(v) for k, v in by.items()}

    lines += [
        "",
        f"## Paired vs {args.base} (each task once: mean over trials)",
        "",
        "| Cell | Tasks | Partial diff | Better / worse / same | Sign test p | AA diff | Guardrails broken, diff per task |",
        "|---|---|---|---|---|---|---|",
    ]
    if data.get(args.base):
        base_p, base_a, base_g = (
            per_task(args.base, "partial_credit"),
            per_task(args.base, "aa"),
            per_task(args.base, "guards_broken"),
        )
        for c in cells:
            if c == args.base:
                continue
            p, a, g = per_task(c, "partial_credit"), per_task(c, "aa"), per_task(c, "guards_broken")
            common = sorted(set(p) & set(base_p))
            if not common:
                continue
            d = [p[t] - base_p[t] for t in common]
            better, worse = sum(x > 1e-9 for x in d), sum(x < -1e-9 for x in d)
            lines.append(
                f"| {c} | {len(common)} | {100 * st.mean(d):+.1f} pts | {better} / {worse} / {len(d) - better - worse} "
                f"| {sign_p(better, better + worse):.3f} | {100 * st.mean(a[t] - base_a[t] for t in common):+.1f} pts "
                f"| {st.mean(g[t] - base_g[t] for t in common):+.2f} per task |"
            )
    text = "\n".join(lines) + "\n"
    (RES / "policy_types_report.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
