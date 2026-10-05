"""Move run artifacts into the parity layout (stdlib only).

Sub-commands:

* ``snapshot-cuga-eval`` — after an ``eval.sh`` arm: copy this stack's Vakra
  prediction files (``results/_vakra/prediction/<domain>.json``, written by the
  in-run scorer with live tool names) filtered to the manifest's uuids, plus the
  run's ``m3_config_*.json`` and its per-uuid native pass flags.
* ``remap`` — rewrite prediction uuids from the bundled-zip ids to the other
  repo's ids (``manifests/uuid_map_*.json``) so one evaluator + one ground truth
  can score every arm.
* ``gt-subset`` — cut the other repo's ground-truth files down to the mapped
  uuids, so the evaluator's ``n_groundtruth`` is the subset size and a missing
  prediction is visible as such.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text())


def manifest_uuids(manifest: Dict[str, Any]) -> List[str]:
    return [u for ids in manifest["ids_by_domain"].values() for u in ids]


# ---------------------------------------------------------------------------
# snapshot-cuga-eval
# ---------------------------------------------------------------------------


def _filter_records(records: Iterable[Dict[str, Any]], keep: set) -> List[Dict[str, Any]]:
    return [r for r in records if str(r.get("uuid", "")).lower() in keep]


def strip_registry_prefix(records: Iterable[Dict[str, Any]], domain: str) -> List[Dict[str, Any]]:
    """Predicted tool names ``<domain>_<tool>`` -> ``<tool>`` (the live MCP name).

    cuga's registry names tools ``<app>_<tool>`` and in eval_m3 the app is the
    domain. In ground-truth mode the in-run scorer rewrites names to the live MCP
    names before writing predictions; predictions-only mode writes them raw, and the
    vendor evaluator's live replay needs the MCP names. Copies; names without the
    prefix are left as they are.
    """
    prefix = f"{domain}_"

    def _fix(call: Any) -> Any:
        if isinstance(call, list):
            return [_fix(c) for c in call]
        if isinstance(call, dict) and str(call.get("name", "")).startswith(prefix):
            return {**call, "name": call["name"][len(prefix) :]}
        return call

    out = []
    for rec in records:
        turns = []
        for turn in rec.get("output") or []:
            seq = dict(turn.get("sequence") or {})
            seq["tool_call"] = [_fix(c) for c in seq.get("tool_call") or []]
            turns.append({**turn, "sequence": seq})
        out.append({**rec, "output": turns})
    return out


def snapshot_cuga_eval(
    manifest: Dict[str, Any],
    results_dir: Path,
    since: float,
    out_dir: Path,
    domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Copy this stack's predictions + native results for one arm. Returns a summary dict.

    With ``domains`` only those domains are collected and the native scores are
    *merged* into any existing ``native_scores.json`` — that is what lets an arm
    run and resume domain by domain.
    """
    out_dir = Path(out_dir)
    pred_out = out_dir / "prediction"
    pred_out.mkdir(parents=True, exist_ok=True)
    wanted_domains = [d for d in (domains or manifest["ids_by_domain"]) if d in manifest["ids_by_domain"]]
    summary: Dict[str, Any] = {
        "domains": wanted_domains,
        "predictions": {},
        "missing_prediction_files": [],
        "native_results": None,
    }
    for domain in wanted_domains:
        ids = manifest["ids_by_domain"][domain]
        src = Path(results_dir) / "_vakra" / "prediction" / f"{domain}.json"
        if not src.exists() or src.stat().st_mtime < since:
            summary["missing_prediction_files"].append(domain)
            continue
        kept = _filter_records(load_json(src), {i.lower() for i in ids})
        if manifest.get("no_ground_truth"):
            kept = strip_registry_prefix(kept, domain)
        (pred_out / f"{domain}.json").write_text(json.dumps(kept, indent=1, ensure_ascii=False))
        summary["predictions"][domain] = {"expected": len(ids), "found": len(kept)}

    candidates = [p for p in Path(results_dir).glob("m3_config_*.json") if p.stat().st_mtime >= since]
    if candidates and manifest.get("no_ground_truth"):
        # predictions-only mode has no in-run judge: keep the raw results, record no native scores
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        label = "-".join(wanted_domains) if domains else "all"
        shutil.copy2(newest, out_dir / f"native_results.{label}.json")
        candidates = []
    if candidates:
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        label = "-".join(wanted_domains) if domains else "all"
        shutil.copy2(newest, out_dir / f"native_results.{label}.json")
        wanted = {u.lower() for d in wanted_domains for u in manifest["ids_by_domain"][d]}
        scores_path = out_dir / "native_scores.json"
        native: Dict[str, Any] = load_json(scores_path) if scores_path.exists() else {}
        added = 0
        for rec in load_json(newest).get("results", []):
            uuid = str(rec.get("sample_id") or rec.get("uuid") or rec.get("name") or "")
            if uuid.lower() in wanted:
                native[uuid] = {
                    "success": bool(rec.get("success")),
                    "match_rate": rec.get("match_rate"),
                    "vakra": rec.get("vakra"),
                }
                added += 1
        scores_path.write_text(json.dumps(native, indent=1, ensure_ascii=False))
        summary["native_results"] = {"file": newest.name, "n_new": added, "n_total": len(native)}
    return summary


# ---------------------------------------------------------------------------
# remap / gt-subset
# ---------------------------------------------------------------------------


def remap_records(
    records: Iterable[Dict[str, Any]], zip_to_vakra: Dict[str, Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Return (records with the other repo's uuids, dropped zip uuids)."""
    lookup = {k.lower(): v["vakra_uuid"] for k, v in zip_to_vakra.items()}
    remapped, dropped = [], []
    for rec in records:
        uuid = str(rec.get("uuid", ""))
        target = lookup.get(uuid.lower())
        if target is None:
            dropped.append(uuid)
            continue
        clone = dict(rec)
        clone["uuid"] = target
        remapped.append(clone)
    return remapped, dropped


def remap_predictions(pred_dir: Path, uuid_map: Dict[str, Any], out_dir: Path) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: Dict[str, Any] = {"mapped": 0, "dropped": {}}
    for src in sorted(Path(pred_dir).glob("*.json")):
        remapped, dropped = remap_records(load_json(src), uuid_map["zip_to_vakra"])
        (out_dir / src.name).write_text(json.dumps(remapped, indent=1, ensure_ascii=False))
        summary["mapped"] += len(remapped)
        if dropped:
            summary["dropped"][src.stem] = dropped
    return summary


def gt_subset(records: Iterable[Dict[str, Any]], keep_vakra_uuids: set) -> List[Dict[str, Any]]:
    return [r for r in records if str(r.get("uuid", "")) in keep_vakra_uuids]


def build_gt_subset(uuid_map: Dict[str, Any], vakra_gt_dir: Path, out_dir: Path) -> Dict[str, int]:
    """Write ``<out_dir>/<domain>.json`` holding only the mapped uuids of each domain."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    by_domain: Dict[str, set] = {}
    for entry in uuid_map["zip_to_vakra"].values():
        by_domain.setdefault(entry["domain"], set()).add(entry["vakra_uuid"])
    counts: Dict[str, int] = {}
    for domain, keep in sorted(by_domain.items()):
        src = Path(vakra_gt_dir) / f"{domain}.json"
        kept = gt_subset(load_json(src), keep)
        (out_dir / f"{domain}.json").write_text(json.dumps(kept, indent=1, ensure_ascii=False))
        counts[domain] = len(kept)
    return counts


def campaign_recorded_arm(manifest: Dict[str, Any], vakra_main: Path, out_dir: Path) -> Dict[str, Any]:
    """The campaign's own recorded predictions as a pseudo-arm, so they are rescored
    with today's evaluator and judge next to the live arms (judge-drift control)."""
    rel = manifest["campaign_predictions"]
    src = Path(vakra_main) / rel
    out_dir = Path(out_dir)
    (out_dir / "prediction").mkdir(parents=True, exist_ok=True)
    counts: Dict[str, int] = {}
    for domain, ids in manifest["ids_by_domain"].items():
        f = src / f"{domain}.json"
        if not f.exists():
            continue
        kept = _filter_records(load_json(f), {i.lower() for i in ids})
        (out_dir / "prediction" / f"{domain}.json").write_text(json.dumps(kept, indent=1, ensure_ascii=False))
        counts[domain] = len(kept)
    meta = {
        "arm": out_dir.name,
        "stack": "vakra-main",
        "recipe": "fc_canon",
        "fc": "1",
        "source": f"recorded campaign predictions ({rel}), rescored now",
        "subset": manifest.get("subset"),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1))
    return {"domains": len(counts), "items": sum(counts.values())}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snapshot-cuga-eval", help="collect this stack's arm artifacts")
    s.add_argument("--manifest", required=True, type=Path)
    s.add_argument("--results-dir", required=True, type=Path)
    s.add_argument("--since", required=True, type=float, help="epoch seconds when the arm started")
    s.add_argument("--out", required=True, type=Path)
    s.add_argument("--domains", nargs="+", default=None, help="only these domains (merges native scores)")

    r = sub.add_parser("remap", help="rewrite prediction uuids zip -> other repo")
    r.add_argument("--map", required=True, type=Path)
    r.add_argument("--in", dest="pred_dir", required=True, type=Path)
    r.add_argument("--out", required=True, type=Path)

    g = sub.add_parser("gt-subset", help="cut the other repo's ground truth to the mapped uuids")
    g.add_argument("--map", required=True, type=Path)
    g.add_argument("--vakra-gt", required=True, type=Path)
    g.add_argument("--out", required=True, type=Path)

    c = sub.add_parser("campaign-recorded", help="the campaign's recorded predictions as a pseudo-arm")
    c.add_argument("--manifest", required=True, type=Path)
    c.add_argument("--vakra-main", required=True, type=Path)
    c.add_argument("--out", required=True, type=Path)

    args = parser.parse_args(argv)
    if args.cmd == "campaign-recorded":
        print(
            json.dumps(campaign_recorded_arm(load_json(args.manifest), args.vakra_main, args.out), indent=1)
        )
        return 0
    if args.cmd == "snapshot-cuga-eval":
        summary = snapshot_cuga_eval(
            load_json(args.manifest), args.results_dir, args.since, args.out, domains=args.domains
        )
    elif args.cmd == "remap":
        summary = remap_predictions(args.pred_dir, load_json(args.map), args.out)
    else:
        summary = build_gt_subset(load_json(args.map), args.vakra_gt, args.out)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
