"""Materialize vakra-main train domains in the layout cuga-eval's M3DataLoader reads (local only).

vakra-main keeps ground truth as ``output[i].sequence``; cuga-eval's loader (the
small_train.zip layout) reads ``ground_truth[i].gold_sequence``. This writes
``<out>/<capability_dir>/{input,output}/<domain>.json`` for every domain of a
manifest — whole domain files, because the adapter draws its prose demos from
them, as the campaign did. Inputs are copied verbatim, outputs re-keyed.
The result lives under parity/.local/ (gitignored): VAKRA data is CC BY-NC-SA and
must never be committed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def convert_output_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    """vakra-main output record -> small_train.zip output record."""
    return {
        "uuid": rec["uuid"],
        "domain": rec.get("domain"),
        "ground_truth": [
            {
                "turn_id": o.get("turn_id", i),
                "query": o.get("query"),
                "answer": o.get("answer"),
                "gold_sequence": o.get("sequence") or {},
            }
            for i, o in enumerate(rec.get("output") or [])
        ],
    }


def prepare(vakra_main: Path, capability_dir: str, domains: List[str], out: Path) -> Dict[str, int]:
    src = Path(vakra_main) / "data" / "train" / capability_dir
    dst = Path(out) / capability_dir
    (dst / "input").mkdir(parents=True, exist_ok=True)
    (dst / "output").mkdir(parents=True, exist_ok=True)
    counts: Dict[str, int] = {}
    for dom in sorted(domains):
        inputs = json.loads((src / "input" / f"{dom}.json").read_text())
        outputs = json.loads((src / "output" / f"{dom}.json").read_text())
        (dst / "input" / f"{dom}.json").write_text(json.dumps(inputs, ensure_ascii=False))
        converted = [convert_output_record(r) for r in outputs]
        (dst / "output" / f"{dom}.json").write_text(json.dumps(converted, ensure_ascii=False))
        counts[dom] = len(inputs)
    return counts


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--vakra-main", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    m = json.loads(args.manifest.read_text())
    counts = prepare(args.vakra_main, m["capability_dir"], list(m["ids_by_domain"]), args.out)
    print(json.dumps({"out": str(args.out), "domains": len(counts), "items": sum(counts.values())}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
