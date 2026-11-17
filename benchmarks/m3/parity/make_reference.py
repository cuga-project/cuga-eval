"""Build a small reference subset of a VAKRA campaign train scorecard (est2 / est3).

The campaign scored its train scorecards on fixed 120-item samples
(``vakra-main/cuga_runs/est<cap>_sample_by_dom.json``) and kept every per-item verdict
(``cuga_runs/est<cap>_score_treat``). A reference subset is a deterministic slice of
that sample: stratified by the campaign's recorded outcome (so the subset keeps the
sample's pass rate) and spread across domains (at most ceil(n / domains) items per
domain, raised only when the quotas cannot otherwise be met). The manifest carries
the recorded verdicts, so every run on it is compared item by item with the campaign.

Writes ``manifests/<name>.json`` and ``manifests/uuid_map_<name>.json`` (identity: the
subset is defined in vakra-main uuids) and prints the ``eval_config.toml`` line. No
benchmark data is written — ids and pass flags only.

usage: uv run --frozen python -m benchmarks.m3.parity.make_reference --cap 3 --n 30 --name parity_est3_ref30
       ... --name parity_est3_fresh30 --exclude-subset parity_est3_ref30   # a disjoint second slice
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#: The campaign's train scorecards with per-item verdicts (paths relative to vakra-main).
SOURCES = {
    1: dict(
        capdir="capability_1_bi_apis",
        preset="cap1",
        sample="cuga_runs/estimate_sample_by_dom.json",
        scores="cuga_runs/est_score_treat",
        predictions="output/est_treat",
        train_data="data/train/capability_1_bi_apis",
        recorded=56.3,
        recipe="fc_canon + FC + re-list (cap1_estimate.sh)",
    ),
    2: dict(
        capdir="capability_2_dashboard_apis",
        preset="cap2",
        sample="cuga_runs/est2_sample_by_dom.json",
        scores="cuga_runs/est2_score_treat",
        predictions="output/est2_treat",
        train_data="data/train/capability_2_dashboard_apis",
        recorded=62.6,
        recipe="fc_canon + FC (cap_estimate.sh 2)",
    ),
    3: dict(
        capdir="capability_3_multihop_reasoning",
        preset="cap3",
        sample="cuga_runs/est3_sample_by_dom.json",
        scores="cuga_runs/est3_score_treat",
        predictions="output/est3_treat",
        train_data="data/train/capability_3_multihop_reasoning",
        recorded=56.7,
        recipe="fc_canon + FC (cap_estimate.sh 3)",
    ),
    4: dict(
        capdir="capability_4_multiturn",
        preset="cap4_v3wx",
        sample="cap4_train/full_by_dom.json",
        scores="cap4_train/scores/full_v3wx",
        predictions="cap4_train/runs/full_v3wx",
        train_data="cap4_train/data",
        recorded=47.4,
        recipe="V3WX (cap4_train full_pipeline.sh)",
    ),
}
CAPS = SOURCES  # back-compat name
MANIFESTS = Path(__file__).resolve().parent / "manifests"


def load_verdicts(score_dir: Path) -> Dict[str, bool]:
    """``{uuid: passed}`` from a directory of vendor-evaluator result files."""
    out: Dict[str, bool] = {}
    for f in sorted(glob.glob(str(score_dir / "*.json"))):
        try:
            data = json.loads(Path(f).read_text())
        except (OSError, ValueError):
            continue
        # vendor evaluator: {"domains": {d: {"dialogues": [...]}}}; cap4_train scorer: {"dialogues": [...]}
        blocks = list((data.get("domains") or {}).values()) or [data]
        for dom in blocks:
            for d in dom.get("dialogues") or []:
                out[str(d["uuid"])] = float(d.get("score") or 0) == 1.0
    return out


def _order_key(seed: int, uuid: str) -> str:
    return hashlib.sha1(f"{seed}:{uuid}".encode(), usedforsecurity=False).hexdigest()  # ordering only


def select(items: List[Tuple[str, str, bool]], n: int, seed: int = 0) -> List[Tuple[str, str, bool]]:
    """``n`` of ``(uuid, domain, passed)``: outcome quotas preserve the pass rate, domains spread."""
    if n >= len(items):
        return sorted(items)
    rate = sum(p for _, _, p in items) / len(items)
    quota = {True: round(n * rate), False: n - round(n * rate)}
    order = sorted(items, key=lambda it: _order_key(seed, it[0]))
    domains = {d for _, d, _ in items}
    cap = math.ceil(n / len(domains))
    largest = max(sum(1 for _, d, _ in items if d == dom) for dom in domains)
    picked: List[Tuple[str, str, bool]] = []
    taken = {True: 0, False: 0}
    per_domain: Dict[str, int] = {}
    while len(picked) < n and cap <= largest:
        for it in order:
            if len(picked) == n:
                break
            uuid, dom, passed = it
            if it in picked or taken[passed] >= quota[passed] or per_domain.get(dom, 0) >= cap:
                continue
            picked.append(it)
            taken[passed] += 1
            per_domain[dom] = per_domain.get(dom, 0) + 1
        cap += 1
    return picked


def build(
    cap: int,
    n: int,
    name: str,
    vakra_main: Path,
    seed: int = 0,
    extra: Optional[Dict[str, str]] = None,
    default_arms: Optional[str] = None,
    exclude: Optional[Dict[str, List[str]]] = None,
):
    """``exclude``: {subset name: its ids}; those items are left out of the pool (a disjoint slice)."""
    src = SOURCES[cap]
    capdir, preset, recorded_pct = src["capdir"], src["preset"], src["recorded"]
    by_dom = json.loads((vakra_main / src["sample"]).read_text())
    verdicts = load_verdicts(vakra_main / src["scores"])
    excluded = {u for ids in (exclude or {}).values() for u in ids}
    items = [
        (u, d, verdicts[u]) for d, us in by_dom.items() for u in us if u in verdicts and u not in excluded
    ]
    chosen = sorted(select(items, n, seed), key=lambda it: (it[1], it[0]))
    ids_by_domain: Dict[str, List[str]] = {}
    for u, d, _ in chosen:
        ids_by_domain.setdefault(d, []).append(u)
    pass_by_uuid = {"on": {u: p for u, _, p in chosen}}
    source_runs = {"on": f"vakra-main {src['scores']}"}
    for label, rel in (extra or {}).items():
        v = load_verdicts(vakra_main / rel)
        pass_by_uuid[label] = {u: v[u] for u, _, _ in chosen if u in v}
        source_runs[label] = f"vakra-main {rel}"
    pass_rate = {k: (sum(v.values()) / len(v) if v else None) for k, v in pass_by_uuid.items()}
    manifest = {
        "subset": name,
        "task_id": cap,
        "capability_dir": capdir,
        "adapter_preset": preset,
        "data_source": f"vakra-main {src['train_data']} (a slice of the campaign's cap{cap} train scorecard), "
        "converted locally by prepare_vakra_train.py",
        "vakra_train_data": src["train_data"],
        "m3_data": "local:vakra_train",
        "demo_data": "local:vakra_train",
        "no_ground_truth": True,
        "campaign_predictions": src["predictions"],
        "default_arms": default_arms or f"cuga_eval_{preset}_fc@pre_parity,cuga_eval_{preset}_fc",
        "n": len(chosen),
        "selection": {
            "from": f"vakra-main {src['sample']} ({len(items)} scored items)",
            "method": "stratified by the campaign's recorded outcome (pass rate preserved), "
            "spread across domains, sha1(seed:uuid) order",
            "seed": seed,
            **({"excluding": sorted(exclude)} if exclude else {}),
        },
        "reference": {
            "description": f"VAKRA campaign cap{cap} train scorecard ({recorded_pct}% on all {len(items)} items): "
            f"{src['recipe']}, temperature 1.0, judge azure/gpt-oss-120b via the proxy. "
            "Per-item verdicts as recorded.",
            "source_runs": source_runs,
            "pass_rate": pass_rate,
            "pass_by_uuid": pass_by_uuid,
        },
        "ids_by_domain": ids_by_domain,
    }
    uuid_map = {
        "subset": name,
        "task_id": cap,
        "capability_dir": capdir,
        "method": "identity (the subset is defined in vakra-main uuids)",
        "vakra_main_data": f"{src['train_data']}/input/<domain>.json",
        "zip_to_vakra": {u: {"vakra_uuid": u, "domain": d, "match": "identity"} for u, d, _ in chosen},
        "unmatched": [],
    }
    return manifest, uuid_map


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cap", type=int, required=True, choices=sorted(CAPS))
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--name", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--vakra-main",
        type=Path,
        default=Path(os.environ.get("VAKRA_MAIN", "~/git/appworld/vakra-main")).expanduser(),
    )
    parser.add_argument(
        "--extra-reference",
        action="append",
        default=[],
        metavar="LABEL=SCORES_DIR",
        help="another recorded campaign run to carry per item (dir relative to vakra-main), "
        "e.g. codeact_stepwise=cuga_runs/gateStruct_score_treat or soft2=cap4_train/scores/full_soft2",
    )
    parser.add_argument("--default-arms", default=None, help="the manifest's default arms (comma-separated)")
    parser.add_argument(
        "--exclude-subset",
        action="append",
        default=[],
        metavar="NAME",
        help="leave out the items of manifests/<NAME>.json (repeatable): a slice disjoint from it",
    )
    args = parser.parse_args(argv)
    extra = dict(x.split("=", 1) for x in args.extra_reference)
    exclude = {
        name: [
            u
            for us in json.loads((MANIFESTS / f"{name}.json").read_text())["ids_by_domain"].values()
            for u in us
        ]
        for name in args.exclude_subset
    }
    manifest, uuid_map = build(
        args.cap,
        args.n,
        args.name,
        args.vakra_main,
        args.seed,
        extra,
        default_arms=args.default_arms,
        exclude=exclude,
    )
    (MANIFESTS / f"{args.name}.json").write_text(json.dumps(manifest, indent=1) + "\n")
    (MANIFESTS / f"uuid_map_{args.name}.json").write_text(json.dumps(uuid_map, indent=1) + "\n")
    ids = [u for us in manifest["ids_by_domain"].values() for u in us]
    rates = ", ".join(f"{k} {v:.1%}" for k, v in manifest["reference"]["pass_rate"].items() if v is not None)
    print(
        f"{args.name}: {len(ids)} items over {len(manifest['ids_by_domain'])} domains; recorded pass rate {rates}"
    )
    print(f"eval_config.toml: {args.name} = {json.dumps(ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
