"""Join the arms of a parity run into one report (stdlib only).

Per arm: pass rate under the shared vendor evaluator (``vendor_results.json``),
this stack's native in-run judge where present (``native_scores.json``), and
per-domain rates. Between arms: per-task agreement on the tasks both produced.
Against the manifest: the 2026-09-10 reference outcomes per uuid.

A task passes when its dialogue score is 1.0 (caps 1-3 are single-turn, so the
score is 0/1). Judge variance is real: with n < 30, or a delta under 3 points,
treat the difference as noise (README.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PASS_THRESHOLD = 0.999
NOISE_N = 30
NOISE_DELTA_PTS = 3.0


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text())


def vendor_scores(results: Dict[str, Any]) -> Dict[str, float]:
    """``{uuid: dialogue score}`` from a vendor evaluator results.json."""
    out: Dict[str, float] = {}
    for domain in (results.get("domains") or {}).values():
        for d in domain.get("dialogues") or []:
            out[str(d["uuid"])] = float(d["score"])
    return out


def pass_rate(scores: Dict[str, float]) -> Tuple[int, int, Optional[float]]:
    """(passed, n, rate) — rate is None for n == 0."""
    n = len(scores)
    passed = sum(1 for s in scores.values() if s >= PASS_THRESHOLD)
    return passed, n, (passed / n if n else None)


def agreement(a: Dict[str, float], b: Dict[str, float]) -> Dict[str, Any]:
    """Per-task agreement over the uuids present in both arms."""
    common = sorted(set(a) & set(b))
    both_pass = [u for u in common if a[u] >= PASS_THRESHOLD and b[u] >= PASS_THRESHOLD]
    both_fail = [u for u in common if a[u] < PASS_THRESHOLD and b[u] < PASS_THRESHOLD]
    only_a = [u for u in common if a[u] >= PASS_THRESHOLD > b[u]]
    only_b = [u for u in common if b[u] >= PASS_THRESHOLD > a[u]]
    agree = len(both_pass) + len(both_fail)
    return {
        "n_common": len(common),
        "agree": agree,
        "agree_rate": (agree / len(common)) if common else None,
        "both_pass": both_pass,
        "both_fail": both_fail,
        "only_a": only_a,
        "only_b": only_b,
    }


def noise_note(n: int, delta_pts: Optional[float]) -> str:
    notes = []
    if n < NOISE_N:
        notes.append(f"n={n}<{NOISE_N}")
    if delta_pts is not None and abs(delta_pts) < NOISE_DELTA_PTS:
        notes.append(f"|Δ|={abs(delta_pts):.1f}<{NOISE_DELTA_PTS:.0f}pt")
    return "noise-level (" + ", ".join(notes) + ")" if notes else "above noise"


def is_fc(meta: Dict[str, Any]) -> bool:
    """An arm ran native function calling (cuga-eval: fc=1 / execution_mode; vakra-main: fc=1)."""
    return str(meta.get("fc", "0")) == "1" or meta.get("execution_mode") == "function_calling"


def fc_pairs(arm_names: List[str]) -> List[Tuple[str, str]]:
    """(X, X_fc) pairs present in a run — the same recipe with FC off and on."""
    names = set(arm_names)
    return [(n, n + "_fc") for n in arm_names if not n.endswith("_fc") and n + "_fc" in names]


def variant_pairs(arm_names: List[str]) -> List[Tuple[str, str]]:
    """(X@variant, X) pairs present in a run — a variant against the preset as shipped."""
    names = set(arm_names)
    return [(n, n.split("@", 1)[0]) for n in arm_names if "@" in n and n.split("@", 1)[0] in names]


def _paired_delta(
    a: Dict[str, float], b: Dict[str, float]
) -> Tuple[Dict[str, Any], Optional[float], Optional[float]]:
    """Agreement of a vs b plus both pass rates over their common tasks."""
    ag = agreement(a, b)
    common = ag["both_pass"] + ag["both_fail"] + ag["only_a"] + ag["only_b"]
    _, _, ra = pass_rate({u: a[u] for u in common})
    _, _, rb = pass_rate({u: b[u] for u in common})
    return ag, ra, rb


def _pct(rate: Optional[float]) -> str:
    return "  n/a" if rate is None else f"{100 * rate:5.1f}%"


def load_run(run_dir: Path, manifest: Dict[str, Any], uuid_map: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Load every arm under ``run_dir``; scores are keyed by the bundled-zip uuid."""
    vakra_to_zip = {v["vakra_uuid"]: k for k, v in uuid_map["zip_to_vakra"].items()}
    domain_of = {u: d for d, ids in manifest["ids_by_domain"].items() for u in ids}
    arms: Dict[str, Dict[str, Any]] = {}
    for arm_dir in sorted(p for p in Path(run_dir).iterdir() if p.is_dir() and p.name != "gt"):
        arm: Dict[str, Any] = {
            "meta": load_json(arm_dir / "meta.json") if (arm_dir / "meta.json").exists() else {}
        }
        vr = arm_dir / "vendor_results.json"
        if vr.exists():
            results = load_json(vr)
            raw = vendor_scores(results)
            arm["vendor"] = {vakra_to_zip.get(u, u): s for u, s in raw.items()}
            blocks = (results.get("domains") or {}).values()
            arm["unscored"] = [u for b in blocks for u in b.get("unscored_uuids") or []]
            arm["missing"] = [u for b in blocks for u in b.get("missing_prediction_uuids") or []]
        ns = arm_dir / "native_scores.json"
        if ns.exists():
            arm["native"] = {u: (1.0 if v.get("success") else 0.0) for u, v in load_json(ns).items()}
        arm["domain_of"] = domain_of
        arms[arm_dir.name] = arm
    return arms


def render_report(
    subset: str, manifest: Dict[str, Any], uuid_map: Dict[str, Any], arms: Dict[str, Dict[str, Any]]
) -> str:
    lines: List[str] = [f"# Parity report — {subset}", ""]
    n_total = manifest["n"]
    n_mapped = len(uuid_map["zip_to_vakra"])
    lines.append(
        f"Subset: {n_total} tasks on this stack, {n_mapped} of them mapped to the other repo "
        f"({n_total - n_mapped} cuga-eval-only, listed at the end). Pass = vendor dialogue score 1.0."
    )
    ref = manifest.get("reference", {})
    if ref:
        rates = " / ".join(f"{k} {100 * v:.1f}%" for k, v in ref.get("pass_rate", {}).items())
        lines.append(f"Reference ({ref.get('description', '')}): {rates}.")
    lines += [
        "",
        "## Arms",
        "",
        "| arm | stack | recipe | n scored | vendor pass | native pass | cuga commit |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, arm in arms.items():
        meta = arm.get("meta", {})
        p, n, r = pass_rate(arm.get("vendor", {}))
        pn, nn, rn = pass_rate(arm.get("native", {}))
        recipe = (meta.get("adapter_preset") or meta.get("recipe") or "?") + (" +FC" if is_fc(meta) else "")
        recipe += f" @{meta['variant']}" if meta.get("variant") else ""
        cuga = meta.get("cuga_agent") or meta.get("cuga_checkout") or {}
        if not cuga and meta.get("source"):
            cuga = {"branch": "recorded", "commit": meta["source"].split(" (")[0], "dirty_files": "0"}
        commit = f"{cuga.get('branch', '?')}@{cuga.get('commit', '?')}" + (
            f" (+{cuga.get('dirty_files')} dirty)"
            if str(cuga.get("dirty_files", "0")) not in ("0", "")
            else ""
        )
        native = f"{_pct(rn)} ({pn}/{nn})" if nn else "—"
        lines.append(
            f"| {name} | {meta.get('stack', '?')} | {recipe} | {n} | {_pct(r)} ({p}/{n}) | {native} | {commit} |"
        )

    gaps = [(n, len(a.get("unscored") or []), len(a.get("missing") or [])) for n, a in arms.items()]
    gaps = [g for g in gaps if g[1] or g[2]]
    if gaps:
        lines += [
            "",
            "Left out of the pass rates above (as the campaign's scorer left them out): "
            + "; ".join(
                f"{n}: {u} unscored (scoring failed after its retry), {m} without a prediction"
                for n, u, m in gaps
            )
            + ".",
        ]

    lines += ["", "## Per-domain vendor pass (passed/n)", ""]
    domains = sorted(manifest["ids_by_domain"])
    lines.append("| domain | " + " | ".join(arms) + " |")
    lines.append("|---|" + "---|" * len(arms))
    for dom in domains:
        cells = []
        for arm in arms.values():
            sc = {u: s for u, s in arm.get("vendor", {}).items() if arm["domain_of"].get(u) == dom}
            p, n, _ = pass_rate(sc)
            cells.append(f"{p}/{n}" if n else "—")
        lines.append(f"| {dom} | " + " | ".join(cells) + " |")

    lines += ["", "## Per-task agreement (vendor judge, tasks scored in both arms)", ""]
    names = list(arms)
    pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1 :]]
    if pairs:
        lines.append("| A | B | common | agree | A-only pass | B-only pass | Δ(A−B) | verdict |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for a, b in pairs:
            ag = agreement(arms[a].get("vendor", {}), arms[b].get("vendor", {}))
            _, _, ra = pass_rate(
                {
                    u: arms[a]["vendor"][u]
                    for u in ag["both_pass"] + ag["both_fail"] + ag["only_a"] + ag["only_b"]
                }
                if ag["n_common"]
                else {}
            )
            _, _, rb = pass_rate(
                {
                    u: arms[b]["vendor"][u]
                    for u in ag["both_pass"] + ag["both_fail"] + ag["only_a"] + ag["only_b"]
                }
                if ag["n_common"]
                else {}
            )
            delta = None if ra is None or rb is None else 100 * (ra - rb)
            lines.append(
                f"| {a} | {b} | {ag['n_common']} | {ag['agree']} ({_pct(ag['agree_rate']).strip()}) | {len(ag['only_a'])} | {len(ag['only_b'])} | "
                f"{'n/a' if delta is None else f'{delta:+.1f}pt'} | {noise_note(ag['n_common'], delta)} |"
            )

    pairs_fc = fc_pairs(list(arms))
    if pairs_fc:
        lines += ["", "## FC effect (same recipe, native function calling off → on; vendor judge)", ""]
        lines.append("| recipe arm | FC off | FC on | common | Δ(on−off) | gained | lost | verdict |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for off_name, on_name in pairs_fc:
            off_sc, on_sc = arms[off_name].get("vendor", {}), arms[on_name].get("vendor", {})
            ag = agreement(on_sc, off_sc)
            common = ag["both_pass"] + ag["both_fail"] + ag["only_a"] + ag["only_b"]
            _, _, r_on = pass_rate({u: on_sc[u] for u in common})
            _, _, r_off = pass_rate({u: off_sc[u] for u in common})
            delta = None if r_on is None or r_off is None else 100 * (r_on - r_off)
            lines.append(
                f"| {off_name} | {_pct(r_off)} | {_pct(r_on)} | {ag['n_common']} | "
                f"{'n/a' if delta is None else f'{delta:+.1f}pt'} | {len(ag['only_a'])} | {len(ag['only_b'])} | "
                f"{noise_note(ag['n_common'], delta)} |"
            )

    pairs_variant = variant_pairs(list(arms))
    if pairs_variant:
        lines += ["", "## Variant effect (variant → preset as shipped, same tasks; vendor judge)", ""]
        lines.append(
            "| shipped arm | variant arm | variant | shipped | common | Δ(shipped−variant) | gained | lost | verdict |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for var_name, base_name in pairs_variant:
            ag, r_base, r_var = _paired_delta(
                arms[base_name].get("vendor", {}), arms[var_name].get("vendor", {})
            )
            delta = None if r_base is None or r_var is None else 100 * (r_base - r_var)
            lines.append(
                f"| {base_name} | {var_name} | {_pct(r_var)} | {_pct(r_base)} | {ag['n_common']} | "
                f"{'n/a' if delta is None else f'{delta:+.1f}pt'} | {len(ag['only_a'])} | {len(ag['only_b'])} | "
                f"{noise_note(ag['n_common'], delta)} |"
            )

    if ref.get("pass_by_uuid"):
        lines += [
            "",
            "## Against the manifest reference (per task; reference flags as recorded, vendor judge now)",
            "",
        ]
        lines.append("| arm | reference arm | common | agree | Δ(now−ref) | verdict |")
        lines.append("|---|---|---|---|---|---|")
        for name, arm in arms.items():
            meta = arm.get("meta") or {}
            recipe = meta.get("adapter_preset") or meta.get("recipe")
            if recipe is None:
                continue
            # baseline arms compare with the recorded baseline; adapter arms with every recorded recipe
            ref_arms = (
                ["off"] if recipe in ("off", "base") else [k for k in ref["pass_by_uuid"] if k != "off"]
            )
            for ref_arm in ref_arms:
                if ref_arm not in ref["pass_by_uuid"]:
                    continue
                ref_scores = {u: (1.0 if v else 0.0) for u, v in ref["pass_by_uuid"][ref_arm].items()}
                ag = agreement(arm.get("vendor", {}), ref_scores)
                both = set(arm.get("vendor", {})) & set(ref_scores)
                _, _, r_now = pass_rate({u: arm["vendor"][u] for u in both})
                _, _, r_ref = pass_rate({u: ref_scores[u] for u in both})
                delta = None if r_now is None or r_ref is None else 100 * (r_now - r_ref)
                lines.append(
                    f"| {name} | {ref_arm} | {ag['n_common']} | {ag['agree']} ({_pct(ag['agree_rate']).strip()}) | "
                    f"{'n/a' if delta is None else f'{delta:+.1f}pt'} | {noise_note(ag['n_common'], delta)} |"
                )

    unmatched = uuid_map.get("unmatched") or []
    if unmatched:
        lines += ["", "## cuga-eval-only tasks (no query-text counterpart in the other repo)", ""]
        for u in unmatched:
            lines.append(f"- {u['zip_uuid']} ({u['domain']}, best similarity {u['best_similarity']})")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", required=True, type=Path, help="parity/runs/<run_id>")
    parser.add_argument("--subset", required=True, help="manifest name, e.g. parity_cap2_30")
    parser.add_argument("--manifests", type=Path, default=Path(__file__).resolve().parent / "manifests")
    args = parser.parse_args(argv)
    manifest = load_json(args.manifests / f"{args.subset}.json")
    uuid_map = load_json(args.manifests / f"uuid_map_{args.subset}.json")
    arms = load_run(args.run, manifest, uuid_map)
    if not arms:
        print(f"no arms under {args.run}", file=sys.stderr)
        return 1
    report = render_report(args.subset, manifest, uuid_map, arms)
    (args.run / "REPORT.md").write_text(report)
    print(report)
    print(f"-> {args.run / 'REPORT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
