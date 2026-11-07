#!/usr/bin/env python3
"""Compare offline generators against the gold builds of the tuning policies (design §7, Task 14).

Generators:
  pipeline   build_policy_set with a small model (default aws/gpt-oss-120b), run here through the CLI;
  skill-cuga the policy compiler skill run by CUGA with gpt-oss-120b (output in gold/<policy>/skill_cuga/, if present);
  skill-claude the skill run by Claude Code = the gold build before the user's review (gold/*.prereview.json, if kept).
Scores per policy: statements covered, statement-type accuracy, rule match (type and main slots) on statements that
gold enforces, links (precision and recall on type, source, target), validation errors, time and model calls.

  ~/dev/cuga-agent-gate/.venv/bin/python benchmarks/policy_eval/compare_generators.py [--model aws/gpt-oss-120b]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
GOLD = HERE / "gold"
PY = "/Users/samimarreed/dev/cuga-agent-gate/.venv/bin/python"
SLOTS = (
    "tool",
    "tools",
    "arg",
    "args",
    "values",
    "op",
    "value",
    "field",
    "pattern",
    "then",
    "roles",
    "inputs",
    "edges",
    "allowed",
    "trigger",
)


def policies() -> List[Dict[str, Path]]:
    out = []
    for b in sorted(GOLD.glob("itsm-*.build.json")):
        pid = b.name.replace(".build.json", "")
        out.append(
            {
                "id": pid,
                "gold": b,
                "set": GOLD / f"{pid}.set.json",
                "raw_set": GOLD / "drafts" / f"{pid}.set.json",
                "tools": GOLD / "inputs" / "itsm_tools.json",
                "dir": GOLD / pid,
            }
        )
    for b in sorted(GOLD.glob("ab/*/build.json")):
        d = b.parent
        out.append(
            {
                "id": d.name,
                "gold": b,
                "set": d / "set.gold.json",
                "raw_set": d / "set.json",
                "tools": d / "tools.json",
                "dir": d,
            }
        )
    return out


def _texts(set_path: Path) -> Dict[str, str]:
    ps = json.loads(set_path.read_text())
    return {
        st["id"]: st["text"] for d in ps["documents"] for sec in d["sections"] for st in sec["statements"]
    }


def _types(set_path: Path) -> Dict[str, List[str]]:
    ps = json.loads(set_path.read_text())
    return {
        st["id"]: st.get("types") or []
        for d in ps["documents"]
        for sec in d["sections"]
        for st in sec["statements"]
    }


def _rules_by_statement(build: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in build["rules"]:
        for sid in r.get("statement_ids") or []:
            out.setdefault(sid, []).append(r["rule"])
    return out


def _sig(rule: Dict[str, Any]) -> Tuple:
    return (rule.get("type"),) + tuple(json.dumps(rule.get(k), sort_keys=True) for k in SLOTS if k in rule)


def _heading(sid: str, types: List[str], texts: Dict[str, str]) -> bool:
    """Section headings are typed `definition` by convention; type accuracy leaves them out (gold README)."""
    text = texts.get(sid, "")
    return types == ["definition"] and len(text.split()) <= 6 and not text.rstrip().endswith(".")


def score(
    gen_build: Dict[str, Any],
    gen_types: Dict[str, List[str]],
    gold_build: Dict[str, Any],
    gold_types: Dict[str, List[str]],
    texts: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    texts = texts or {}
    ids = list(gold_types)
    covered_gen = {c["statement_id"] for c in gen_build.get("coverage", [])} | set(
        _rules_by_statement(gen_build)
    )
    scored = [i for i in ids if gold_types[i] and not _heading(i, gold_types[i], texts)]
    type_ok = sum(1 for i in scored if gen_types.get(i) and gen_types[i][0] in gold_types[i])
    typed = len(scored)
    g_rules, x_rules = _rules_by_statement(gold_build), _rules_by_statement(gen_build)
    enforced = [i for i, rs in g_rules.items() if any(r["type"] not in ("guidance",) for r in rs)]
    type_match = sum(
        1 for i in enforced if {r["type"] for r in g_rules[i]} & {r["type"] for r in x_rules.get(i, [])}
    )
    exact = sum(1 for i in enforced if {_sig(r) for r in g_rules[i]} & {_sig(r) for r in x_rules.get(i, [])})
    gl = {(l["type"], l["src"], l["dst"]) for l in gold_build.get("links", []) if l["type"] != "defines"}
    xl = {(l["type"], l["src"], l["dst"]) for l in gen_build.get("links", []) if l["type"] != "defines"}
    return {
        "statements": len(ids),
        "covered": sum(i in covered_gen for i in ids) / max(len(ids), 1),
        "type_acc": type_ok / max(typed, 1),
        "enforced": len(enforced),
        "rule_type_match": type_match / max(len(enforced), 1),
        "rule_exact": exact / max(len(enforced), 1),
        "link_recall": len(gl & xl) / len(gl) if gl else None,
        "link_precision": len(gl & xl) / len(xl) if xl else None,
        "validation_errors": sum(
            1 for e in gen_build.get("validation", []) if e.get("code") != "schema_conflict"
        ),
    }


def run_pipeline(
    p: Dict[str, Path], model: str
) -> Tuple[Dict[str, Any], Dict[str, List[str]], Dict[str, Any]]:
    out_dir = p["dir"] / "pipeline"
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    proc = subprocess.run(
        [
            PY,
            "-m",
            "cuga.policy_layer.cli",
            "build",
            str(p["raw_set"]),
            "--tools",
            str(p["tools"]),
            "-o",
            str(out_dir / "build.json"),
            "--typed-set",
            str(out_dir / "set.json"),
            "--model",
            model,
            "--cache",
            str(GOLD / "drafts" / "cache"),
        ],
        capture_output=True,
        text=True,
    )
    stats = (
        json.loads(proc.stdout.strip().splitlines()[-1])
        if proc.stdout.strip()
        else {"error": proc.stderr[-300:]}
    )
    stats["seconds"] = round(time.monotonic() - t0, 1)
    return json.loads((out_dir / "build.json").read_text()), _types(out_dir / "set.json"), stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="aws/gpt-oss-120b")
    a = ap.parse_args()
    rows = []
    for p in policies():
        gold_build, gold_types = json.loads(p["gold"].read_text()), _types(p["set"])
        build, types, stats = run_pipeline(p, a.model)
        rows.append(
            {
                "policy": p["id"],
                "generator": f"pipeline {a.model}",
                **score(build, types, gold_build, gold_types, _texts(p['set'])),
                "seconds": stats.get("seconds"),
                "calls": (stats.get("usage") or {}).get("calls"),
            }
        )
        for gen, path, set_path in (
            (
                "skill-cuga gpt-oss-120b",
                p["dir"] / "skill_cuga" / "build.json",
                p["dir"] / "skill_cuga" / "set.json",
            ),
            ("skill-claude (before review)", Path(str(p["gold"]).replace(".json", ".prereview.json")), None),
        ):
            if path.exists():
                b = json.loads(path.read_text())
                t = _types(set_path) if set_path and set_path.exists() else gold_types
                rows.append(
                    {
                        "policy": p["id"],
                        "generator": gen,
                        **score(b, t, gold_build, gold_types, _texts(p['set'])),
                    }
                )
    (HERE / "generator_results.json").write_text(json.dumps(rows, indent=1))
    lines = [
        "# Generators against the gold builds (tuning policies)",
        "",
        "| Policy | Generator | Statements | Covered | Type acc. | Enforced (gold) | Rule type match | Rule exact | "
        "Link recall | Link precision | Validation errors | Seconds |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    fmt = lambda v: "" if v is None else (f"{v:.0%}" if isinstance(v, float) else str(v))  # noqa: E731
    for r in rows:
        lines.append(
            f"| {r['policy']} | {r['generator']} | {r['statements']} | {fmt(r['covered'])} | {fmt(r['type_acc'])} | "
            f"{r['enforced']} | {fmt(r['rule_type_match'])} | {fmt(r['rule_exact'])} | {fmt(r['link_recall'])} | "
            f"{fmt(r['link_precision'])} | {r['validation_errors']} | {r.get('seconds', '')} |"
        )
    (HERE / "generator_comparison.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
