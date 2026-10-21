"""Recovery pass: re-run an arm's tasks that died on infrastructure and merge their new predictions.

A task died on infrastructure when the runner recorded an error for it (the agent timeout, a dropped
connection, a rate limit, a 5xx) or its final answer is empty. The campaign re-ran such items for
cap1 (empty answers 12.8% -> 3.5%); on the train validation runs they were 3-20% of a cap's tasks,
mostly cap4 timeouts and proxy outages.

Flow (``recover_arm.sh`` drives it):

* ``find``  — list an arm's failed tasks per domain and write a recovery subset: a manifest and its
  uuid map in ``manifests/`` (``zz_recover_*``, removed by ``clean``) and the eval key in a TOML that
  ``M3_EVAL_CONFIG_EXTRA`` points ``eval_m3`` at, so the shared ``eval_config.toml`` stays untouched.
* the arm is re-run on that subset with the kit (same arm name -> same preset, variant, FC mode).
* ``merge`` — replace the failed tasks' records in the arm's ``prediction/`` with the re-run's
  records that now carry an answer (the originals are kept in ``prediction_pre_recover/``).
* ``score`` — the arm's pass rate with the recovered tasks' verdicts swapped in (the other tasks keep
  the verdicts they were scored with, so the judge is not re-rolled on them).
* ``clean`` — remove the recovery subset's manifest files.

usage: python -m benchmarks.m3.parity.recover find  --run-dir RUN_DIR --arm ARM
       python -m benchmarks.m3.parity.recover merge --run-dir RUN_DIR --arm ARM --from RECOVERY_ARM_DIR
       python -m benchmarks.m3.parity.recover clean --name SUBSET
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PARITY_DIR = Path(__file__).resolve().parent
MANIFESTS = PARITY_DIR / "manifests"
RECOVER_DIR = PARITY_DIR / ".local" / "recover"
PREFIX = "zz_recover_"


def _load(path: Path) -> Any:
    return json.loads(Path(path).read_text())


def _final_answer(record: Dict[str, Any]) -> str:
    turns = record.get("output") or []
    return str((turns[-1] if turns else {}).get("answer") or "")


def _runner_records(arm_dir: Path, task_id: int) -> List[Dict[str, Any]]:
    """The runner's own per-task results: uuid, error, answer (cap1 raw output; caps 2-4 native results)."""
    out: List[Dict[str, Any]] = []
    if task_id == 1:
        newest: Dict[str, Path] = {}
        for f in glob.glob(str(arm_dir / "raw" / "*" / "m3_task1_enterprise_2*.json")):
            dom = Path(f).parent.name
            if dom not in newest or Path(f).stat().st_mtime > newest[dom].stat().st_mtime:
                newest[dom] = Path(f)
        for f in newest.values():
            for it in _load(f).get("results") or []:
                out.append(
                    dict(
                        uuid=it.get("uuid"),
                        error=str(it.get("error") or ""),
                        answer=str(it.get("response") or ""),
                    )
                )
        return out
    for f in glob.glob(str(arm_dir / "native_results.*.json")):
        for it in _load(f).get("results") or []:
            turns = it.get("all_responses") or []
            answer = (turns[-1].get("response") if turns else None) or it.get("response") or ""
            out.append(dict(uuid=it.get("uuid"), error=str(it.get("error") or ""), answer=str(answer)))
    return out


def _replaced_by(arm_dir: Path) -> Dict[str, Path]:
    """uuid -> the recovery run whose record the arm's prediction holds now (the last pass that replaced it)."""
    out: Dict[str, Path] = {}
    log = Path(arm_dir) / "recover_log.jsonl"
    if log.exists():
        for line in log.read_text().splitlines():
            if line.strip():
                entry = json.loads(line)
                for uuid in entry.get("replaced") or []:
                    out[str(uuid).lower()] = Path(entry["recovered_from"])
    return out


def failed_tasks(arm_dir: Path, manifest: Dict[str, Any]) -> Dict[str, List[str]]:
    """``{domain: [uuid, ...]}`` of the manifest's tasks that errored or ended without an answer.

    A task an earlier recovery pass replaced is judged by that pass's runner record, not by the arm's
    original one (which still shows the old failure), so a second pass re-runs only what is still failing.
    """
    arm_dir = Path(arm_dir)
    task_id = int(manifest.get("task_id") or 0)
    wanted = {u.lower(): (d, u) for d, ids in manifest["ids_by_domain"].items() for u in ids}
    replaced_by = _replaced_by(arm_dir)
    bad: Dict[str, str] = {}
    sources = [(arm_dir, None)] + [(src, src) for src in dict.fromkeys(replaced_by.values())]
    for run_dir, src in sources:
        for rec in _runner_records(run_dir, task_id):
            key = str(rec.get("uuid") or "").lower()
            if key not in wanted or replaced_by.get(key) != src:
                continue  # judged by the run whose record the prediction holds
            if rec["error"].strip() or not rec["answer"].strip():
                bad[key] = rec["error"].strip() or "empty answer"
    seen = set()
    for f in glob.glob(str(arm_dir / "prediction" / "*.json")):
        for rec in _load(f):
            key = str(rec.get("uuid") or "").lower()
            seen.add(key)
            if key in wanted and (str(rec.get("error") or "").strip() or not _final_answer(rec).strip()):
                bad.setdefault(key, str(rec.get("error") or "").strip() or "empty answer")
    for key in wanted:  # a task the arm never predicted at all
        if key not in seen:
            bad.setdefault(key, "no prediction")
    out: Dict[str, List[str]] = {}
    for key in sorted(bad):
        dom, uuid = wanted[key]
        out.setdefault(dom, []).append(uuid)
    return out


def subset_name(run_id: str, arm: str) -> str:
    return PREFIX + re.sub(r"[^A-Za-z0-9]+", "_", f"{run_id}_{arm}").strip("_").lower()


def write_recovery_subset(
    run_dir: Path, arm: str, manifests: Path = MANIFESTS, local: Path = RECOVER_DIR
) -> Dict[str, Any]:
    """Write the recovery subset for one arm; returns a summary (``n`` 0 means nothing to recover)."""
    run_dir = Path(run_dir)
    meta = _load(run_dir / arm / "meta.json")
    base = meta["subset"]
    manifest = _load(manifests / f"{base}.json")
    failures = failed_tasks(run_dir / arm, manifest)
    n = sum(len(v) for v in failures.values())
    name = subset_name(run_dir.name, arm)
    summary = dict(
        run=run_dir.name,
        arm=arm,
        base_subset=base,
        subset=name,
        n=n,
        failed_by_domain={d: len(v) for d, v in failures.items()},
    )
    if not n:
        return summary
    keep = {u.lower() for ids in failures.values() for u in ids}
    sub = dict(
        manifest,
        subset=name,
        n=n,
        ids_by_domain=failures,
        data_source=f"recovery subset of {base} for {run_dir.name}/{arm}",
    )
    ref = (manifest.get("reference") or {}).get("pass_by_uuid") or {}
    if ref:
        sub["reference"] = dict(
            manifest["reference"],
            pass_by_uuid={k: {u: v for u, v in d.items() if u.lower() in keep} for k, d in ref.items()},
        )
    (manifests / f"{name}.json").write_text(json.dumps(sub, indent=1))
    umap = _load(manifests / f"uuid_map_{base}.json")
    umap = dict(
        umap,
        subset=name,
        zip_to_vakra={k: v for k, v in umap.get("zip_to_vakra", {}).items() if k.lower() in keep},
    )
    (manifests / f"uuid_map_{name}.json").write_text(json.dumps(umap, indent=1))
    local.mkdir(parents=True, exist_ok=True)
    toml = local / f"{name}.toml"
    ids = [u for d in failures for u in failures[d]]
    toml.write_text(f"{name} = [\n" + "".join(f'  "{u}",\n' for u in ids) + "]\n")
    summary["eval_config_extra"] = str(toml)
    return summary


def merge_predictions(arm_dir: Path, recovered_arm_dir: Path) -> Dict[str, Any]:
    """Replace records of ``arm_dir/prediction`` with the recovery run's records that have an answer."""
    arm_dir, recovered_arm_dir = Path(arm_dir), Path(recovered_arm_dir)
    backup = arm_dir / "prediction_pre_recover"
    replaced, kept_failed = [], []
    for f in sorted(glob.glob(str(recovered_arm_dir / "prediction" / "*.json"))):
        dom_file = arm_dir / "prediction" / Path(f).name
        new = {r["uuid"].lower(): r for r in _load(f)}
        if not dom_file.exists():
            continue
        records = _load(dom_file)
        changed = False
        for i, rec in enumerate(records):
            got = new.get(str(rec.get("uuid", "")).lower())
            if got is None:
                continue
            if _final_answer(got).strip() and not str(got.get("error") or "").strip():
                records[i] = got
                replaced.append(rec["uuid"])
                changed = True
            else:
                kept_failed.append(rec["uuid"])
        if changed:
            backup.mkdir(exist_ok=True)
            if not (backup / dom_file.name).exists():  # the first pass keeps the arm's original records
                shutil.copy2(dom_file, backup / dom_file.name)
            dom_file.write_text(json.dumps(records, indent=1, ensure_ascii=False))
    log = dict(recovered_from=str(recovered_arm_dir), replaced=replaced, still_failed=kept_failed)
    with open(arm_dir / "recover_log.jsonl", "a") as fh:
        fh.write(json.dumps(log) + "\n")
    return dict(replaced=len(replaced), still_failed=len(kept_failed))


def _domain_blocks(results: Dict[str, Any]) -> List[Dict[str, Any]]:
    doms = results.get("domains") or {}
    return list(doms.values()) if isinstance(doms, dict) else list(doms)


def pass_rate(results: Dict[str, Any]) -> Dict[str, Any]:
    """Pass rate over the scored dialogues (unscored and judge-error ones left out, as the kit does)."""
    passed = scored = 0
    for block in _domain_blocks(results):
        skip = set(block.get("unscored_uuids") or []) | set(block.get("judge_error_uuids") or [])
        for d in block.get("dialogues") or []:
            if d.get("uuid") in skip:
                continue
            scored += 1
            passed += float(d.get("score") or 0) >= 1
    return dict(passed=passed, scored=scored, rate=round(100 * passed / scored, 1) if scored else None)


def merge_verdicts(arm_dir: Path, recovered_arm_dir: Path) -> Dict[str, Any]:
    """The arm's scores with the recovered tasks' verdicts swapped in (``vendor_results.recovered.json``).

    Only the tasks ``merge`` replaced change; every other task keeps the verdict it was scored with,
    so the comparison does not re-roll the judge on the tasks that ran fine.
    """
    arm_dir, recovered_arm_dir = Path(arm_dir), Path(recovered_arm_dir)
    replaced = set()
    log = arm_dir / "recover_log.jsonl"
    if log.exists():
        for line in log.read_text().splitlines():
            replaced |= {u.lower() for u in json.loads(line).get("replaced") or []}
    original = _load(arm_dir / "vendor_results.json")
    recovered = _load(recovered_arm_dir / "vendor_results.json")
    new_dialogues: Dict[str, Dict[str, Any]] = {}
    new_skip = set()
    for block in _domain_blocks(recovered):
        new_skip |= {
            u.lower() for u in (block.get("unscored_uuids") or []) + (block.get("judge_error_uuids") or [])
        }
        for d in block.get("dialogues") or []:
            new_dialogues[str(d.get("uuid", "")).lower()] = d
    swapped = 0
    for block in _domain_blocks(original):
        for i, d in enumerate(block.get("dialogues") or []):
            key = str(d.get("uuid", "")).lower()
            if key in replaced and key in new_dialogues:
                block["dialogues"][i] = new_dialogues[key]
                swapped += 1
                for field in ("unscored_uuids", "judge_error_uuids"):
                    kept = [u for u in block.get(field) or [] if u.lower() != key]
                    if key in new_skip:
                        kept.append(d.get("uuid"))
                    block[field] = kept
    (arm_dir / "vendor_results.recovered.json").write_text(json.dumps(original, indent=1))
    return dict(
        before=pass_rate(_load(arm_dir / "vendor_results.json")), after=pass_rate(original), swapped=swapped
    )


def clean(name: str, manifests: Path = MANIFESTS) -> List[str]:
    if not name.startswith(PREFIX):
        raise ValueError(f"refusing to remove {name!r}: not a recovery subset")
    removed = []
    for p in (manifests / f"{name}.json", manifests / f"uuid_map_{name}.json"):
        if p.exists():
            p.unlink()
            removed.append(p.name)
    return removed


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find", help="list an arm's infra-failed tasks and write the recovery subset")
    f.add_argument("--run-dir", required=True, type=Path)
    f.add_argument("--arm", required=True)
    m = sub.add_parser("merge", help="merge a recovery run's predictions into the arm")
    m.add_argument("--run-dir", required=True, type=Path)
    m.add_argument("--arm", required=True)
    m.add_argument("--from", dest="src", required=True, type=Path)
    v = sub.add_parser("score", help="the arm's pass rate with the recovered tasks' verdicts swapped in")
    v.add_argument("--run-dir", required=True, type=Path)
    v.add_argument("--arm", required=True)
    v.add_argument("--from", dest="src", required=True, type=Path)
    c = sub.add_parser("clean", help="remove a recovery subset's manifest files")
    c.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "find":
        print(json.dumps(write_recovery_subset(args.run_dir, args.arm), indent=1))
    elif args.cmd == "merge":
        print(json.dumps(merge_predictions(args.run_dir / args.arm, args.src), indent=1))
    elif args.cmd == "score":
        print(json.dumps(merge_verdicts(args.run_dir / args.arm, args.src), indent=1))
    else:
        print(json.dumps(clean(args.name)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
