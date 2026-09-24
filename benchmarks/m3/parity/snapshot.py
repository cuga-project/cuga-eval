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


def snapshot_cuga_eval(
    manifest: Dict[str, Any], results_dir: Path, since: float, out_dir: Path
) -> Dict[str, Any]:
    """Copy this stack's predictions + native results for one arm. Returns a summary dict."""
    out_dir = Path(out_dir)
    pred_out = out_dir / "prediction"
    pred_out.mkdir(parents=True, exist_ok=True)
    summary: Dict[str, Any] = {"predictions": {}, "missing_prediction_files": [], "native_results": None}
    for domain, ids in manifest["ids_by_domain"].items():
        src = Path(results_dir) / "_vakra" / "prediction" / f"{domain}.json"
        if not src.exists() or src.stat().st_mtime < since:
            summary["missing_prediction_files"].append(domain)
            continue
        kept = _filter_records(load_json(src), {i.lower() for i in ids})
        (pred_out / f"{domain}.json").write_text(json.dumps(kept, indent=1, ensure_ascii=False))
        summary["predictions"][domain] = {"expected": len(ids), "found": len(kept)}

    candidates = [p for p in Path(results_dir).glob("m3_config_*.json") if p.stat().st_mtime >= since]
    if candidates:
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        shutil.copy2(newest, out_dir / "native_results.json")
        wanted = {u.lower() for u in manifest_uuids(manifest)}
        native: Dict[str, Any] = {}
        for rec in load_json(newest).get("results", []):
            uuid = str(rec.get("sample_id") or rec.get("uuid") or rec.get("name") or "")
            if uuid.lower() in wanted:
                native[uuid] = {
                    "success": bool(rec.get("success")),
                    "match_rate": rec.get("match_rate"),
                    "vakra": rec.get("vakra"),
                }
        (out_dir / "native_scores.json").write_text(json.dumps(native, indent=1, ensure_ascii=False))
        summary["native_results"] = {"file": newest.name, "n": len(native)}
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

    r = sub.add_parser("remap", help="rewrite prediction uuids zip -> other repo")
    r.add_argument("--map", required=True, type=Path)
    r.add_argument("--in", dest="pred_dir", required=True, type=Path)
    r.add_argument("--out", required=True, type=Path)

    g = sub.add_parser("gt-subset", help="cut the other repo's ground truth to the mapped uuids")
    g.add_argument("--map", required=True, type=Path)
    g.add_argument("--vakra-gt", required=True, type=Path)
    g.add_argument("--out", required=True, type=Path)

    args = parser.parse_args(argv)
    if args.cmd == "snapshot-cuga-eval":
        summary = snapshot_cuga_eval(load_json(args.manifest), args.results_dir, args.since, args.out)
    elif args.cmd == "remap":
        summary = remap_predictions(args.pred_dir, load_json(args.map), args.out)
    else:
        summary = build_gt_subset(load_json(args.map), args.vakra_gt, args.out)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
