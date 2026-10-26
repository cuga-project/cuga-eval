"""Build the test-split manifests (local only): every vakra-main test task of a capability.

The test split has inputs only (the organizers score it), so a test manifest lists every task id per
domain and carries no reference verdicts. Writes, for each capability asked:

- ``manifests/test_cap<N>.json`` and ``manifests/uuid_map_test_cap<N>.json`` (identity map);
- with ``--smoke``, ``test_cap<N>_smoke``: the first task of the first domain (a one-task check);
- ``.local/test_eval_keys.toml``: the ``--eval-key`` id lists eval_m3 reads through
  ``M3_EVAL_CONFIG_EXTRA`` (run_test_arm.sh exports it), so ``eval_config.toml`` stays untouched.

Task ids are derived at run time from vakra-main and never committed (they are gitignored).
Then convert the inputs once: ``prepare_vakra_train --manifest manifests/test_cap<N>.json
--vakra-main $VAKRA_MAIN --out benchmarks/m3/parity/.local/vakra_test``.

usage: uv run --frozen python -m benchmarks.m3.parity.make_test_manifests [--caps 1,2,3,4] [--smoke]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

PARITY = Path(__file__).resolve().parent
MANIFESTS = PARITY / "manifests"
LOCAL = PARITY / ".local"
CAPDIRS = {
    1: "capability_1_bi_apis",
    2: "capability_2_dashboard_apis",
    3: "capability_3_multihop_reasoning",
    4: "capability_4_multiturn",
}
ARMS = {1: "cuga_eval_cap1_fc", 2: "cuga_eval_cap2_fc", 3: "cuga_eval_cap3_fc", 4: "cuga_eval_cap4"}


def test_ids(vakra_main: Path, cap: int) -> Dict[str, List[str]]:
    """``{domain: [uuid, ...]}`` of the capability's test inputs, in file order."""
    src = vakra_main / "data" / "test" / CAPDIRS[cap] / "input"
    if not src.is_dir():
        raise FileNotFoundError(f"no test inputs at {src}")
    out: Dict[str, List[str]] = {}
    for f in sorted(src.glob("*.json")):
        ids = [str(r["uuid"]) for r in json.loads(f.read_text())]
        if ids:
            out[f.stem] = ids
    return out


def build(cap: int, name: str, ids_by_domain: Dict[str, List[str]]) -> tuple:
    capdir = CAPDIRS[cap]
    manifest = {
        "subset": name,
        "task_id": cap,
        "capability_dir": capdir,
        "adapter_preset": f"cap{cap}",
        "data_source": f"vakra-main data/test/{capdir} (inputs only; scored by the organizers)",
        "vakra_train_data": f"data/test/{capdir}",
        "m3_data": "local:vakra_test",
        "demo_data": "local:vakra_train",
        "no_ground_truth": True,
        "default_arms": ARMS[cap],
        "n": sum(len(v) for v in ids_by_domain.values()),
        "ids_by_domain": ids_by_domain,
    }
    uuid_map = {
        "subset": name,
        "task_id": cap,
        "capability_dir": capdir,
        "method": "identity (the subset is defined in vakra-main uuids)",
        "vakra_main_data": f"data/test/{capdir}/input/<domain>.json",
        "zip_to_vakra": {
            u: {"vakra_uuid": u, "domain": d, "match": "identity"}
            for d, us in ids_by_domain.items()
            for u in us
        },
        "unmatched": [],
    }
    return manifest, uuid_map


def toml_lists(lists: Dict[str, List[str]]) -> str:
    return "".join(f"{k} = [\n" + "".join(f'  "{u}",\n' for u in v) + "]\n" for k, v in lists.items())


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--caps", default="1,2,3,4", help="comma-separated capabilities (default: all four)")
    parser.add_argument("--smoke", action="store_true", help="also write test_cap<N>_smoke (one task)")
    parser.add_argument(
        "--vakra-main",
        type=Path,
        default=Path(os.environ.get("VAKRA_MAIN", "~/git/appworld/vakra-main")).expanduser(),
    )
    parser.add_argument("--manifests", type=Path, default=MANIFESTS)
    parser.add_argument("--keys-out", type=Path, default=LOCAL / "test_eval_keys.toml")
    args = parser.parse_args(argv)

    lists: Dict[str, List[str]] = {}
    for cap in (int(c) for c in args.caps.split(",") if c.strip()):
        ids = test_ids(args.vakra_main, cap)
        subsets = {f"test_cap{cap}": ids}
        if args.smoke:
            first = next(iter(ids))
            subsets[f"test_cap{cap}_smoke"] = {first: ids[first][:1]}
        for name, by_dom in subsets.items():
            manifest, uuid_map = build(cap, name, by_dom)
            args.manifests.mkdir(parents=True, exist_ok=True)
            (args.manifests / f"{name}.json").write_text(json.dumps(manifest, indent=1) + "\n")
            (args.manifests / f"uuid_map_{name}.json").write_text(json.dumps(uuid_map, indent=1) + "\n")
            lists[name] = [u for us in by_dom.values() for u in us]
            print(f"{name}: {manifest['n']} tasks over {len(by_dom)} domains")
    args.keys_out.parent.mkdir(parents=True, exist_ok=True)
    # Merge with lists already there (other capabilities written by an earlier call).
    existing = {}
    if args.keys_out.exists():
        import tomllib  # noqa: PLC0415  (py3.11+)

        existing = tomllib.loads(args.keys_out.read_text())
    args.keys_out.write_text(toml_lists({**existing, **lists}))
    print(f"eval keys -> {args.keys_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
