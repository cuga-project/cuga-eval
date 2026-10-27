"""Combine N runs of one capability into one arm: per task, one run's complete record (answer + its own trace).

The scorer replays the submitted tool calls (exact match) and judges the answer against their outputs
(groundedness), so a submission never pairs a voted answer with another run's trace: every rule below
picks a run and copies its record as it is.

Rules (all deterministic):

* ``majority`` — the answer most runs gave (normalized; at least 2 runs), then, among the runs that gave
  it, the trace that supports it best: every answer value in its last 20 tool results, no failed call,
  fewest calls, earliest run. No majority: the best-supported valid answer by the same order.
* ``evidence`` — evidence first: only runs whose answer is fully supported by their own trace and that
  have no failed call; among those the most common answer, then fewest calls, earliest run. When no run
  qualifies, ``majority``.
* ``first`` — the ``majority`` answer with the earliest run that gave it (no trace preference); no
  majority: run 1. A baseline that isolates what the trace choice adds.

A valid answer is non-empty and not working notes; a refusal is valid only for capability 4 (some of
its tasks expect it).

usage: python -m benchmarks.m3.parity.vote_runs --cap 1 --rule majority --out RUN/ARM@vote_majority \
           --arm RUN1/ARM --arm RUN2/ARM --arm RUN3/ARM
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from benchmarks.m3.adapter.final_answer import canonicalize_final_answer, is_giveup
from benchmarks.m3.adapter.guards import looks_like_plan_text, unsupported_values

#: The evaluator reads the last N tool responses (vakra-main evaluator/judge.py N_TOOL_CALLS_PER_TURN).
JUDGE_WINDOW = 20
RULES = ("majority", "evidence", "first")
_NUM = re.compile(r"^-?\d+(?:\.\d+)?$")


def normalize(answer: str) -> Optional[frozenset]:
    """The answer as a set of normalized items (``"5.0"`` = ``"5"``, quotes, brackets and case ignored)."""
    text = canonicalize_final_answer(str(answer or "")).strip()
    if not text:
        return None
    items = set()
    for raw in re.split(r"\s*[,;\n]\s*", text):
        item = raw.strip().strip("[](){}\"'`").strip().lower()
        if not item:
            continue
        if _NUM.match(item):
            f = float(item)
            item = str(int(f)) if f == int(f) else f"{f:.6g}"
        items.add(item)
    return frozenset(items) or None


class Run:
    """One run's record of a task, with what the rules need."""

    def __init__(self, index: int, record: dict, calls: List[Tuple[str, str]], cap: int):
        self.index, self.record = index, record
        turn = record["output"][-1]
        self.answer = str(turn.get("answer") or "")
        self.query = str(turn.get("query") or "")
        self.n_calls = len(calls)
        self.failed = any(r.startswith("Error") for _, r in calls) or bool(record.get("error"))
        ok = [r for _, r in calls if not r.startswith("Error")][-JUDGE_WINDOW:]
        refusal = is_giveup(self.answer)
        self.valid = (
            bool(self.answer.strip()) and not looks_like_plan_text(self.answer) and (cap == 4 or not refusal)
        )
        self.key = ("<refusal>",) if refusal else normalize(self.answer)
        self.supported = self.valid and (
            refusal or not unsupported_values(self.answer, self.query + " " + " ".join(ok))
        )

    def trace_order(self) -> tuple:
        return (not self.supported, self.failed, self.n_calls, self.index)


def _majority(runs: List[Run]) -> Optional[List[Run]]:
    counts = collections.Counter(r.key for r in runs if r.valid and r.key)
    if not counts:
        return None
    key, n = max(counts.items(), key=lambda kv: (kv[1], -min(r.index for r in runs if r.key == kv[0])))
    return [r for r in runs if r.key == key] if n >= 2 else None


def choose(runs: List[Run], rule: str) -> Tuple[Run, str]:
    """The run whose record is submitted, and why."""
    if rule == "evidence":
        good = [r for r in runs if r.supported and not r.failed]
        if good:
            counts = collections.Counter(r.key for r in good)
            best = max(counts.values())
            pool = [r for r in good if counts[r.key] == best]
            return min(pool, key=lambda r: (r.n_calls, r.index)), f"evidence ({best}/{len(runs)} agree)"
        rule = "majority"
    group = _majority(runs)
    if group is not None:
        if rule == "first":
            return min(group, key=lambda r: r.index), f"majority {len(group)}/{len(runs)}, earliest"
        return min(group, key=Run.trace_order), f"majority {len(group)}/{len(runs)}"
    if rule == "first":
        return runs[0], "no majority, run 1"
    valid = [r for r in runs if r.valid] or runs
    return min(valid, key=Run.trace_order), "no majority, best supported"


def _cap1_calls(arm: Path) -> Dict[str, List[Tuple[str, str]]]:
    """cap1 prediction records keep calls without results: read them from the runner's raw files."""
    out: Dict[str, List[Tuple[str, str]]] = {}
    for f in sorted(glob.glob(str(arm / "raw" / "*" / "m3_task1_enterprise_2*.json")), key=os.path.getmtime):
        for it in json.loads(Path(f).read_text()).get("results") or []:
            out[str(it["uuid"])] = [
                (
                    c.get("name"),
                    str(c.get("result")) if c.get("error") in (None, "") else f"Error: {c['error']}",
                )
                for c in it.get("tool_calls") or []
            ]
    return out


def load_arm(arm: Path, cap: int) -> Dict[str, Tuple[str, dict, List[Tuple[str, str]]]]:
    """``{uuid: (prediction file name, record, [(tool, result), ...])}``."""
    cap1 = _cap1_calls(arm) if cap == 1 else {}
    out = {}
    for f in sorted((arm / "prediction").glob("*.json")):
        for rec in json.loads(f.read_text()):
            uid = str(rec["uuid"])
            if cap == 1:
                calls = cap1.get(uid, [])
            else:
                seq = rec["output"][-1].get("sequence") or {}
                calls = [
                    (c.get("name"), str(r))
                    for c, r in zip(seq.get("tool_call") or [], seq.get("tool_response") or [])
                ]
            out[uid] = (f.name, rec, calls)
    return out


def vote(arms: List[Path], cap: int, rule: str, out: Path) -> Dict[str, Any]:
    if rule not in RULES:
        raise ValueError(f"rule must be one of {RULES}")
    loaded = [load_arm(a, cap) for a in arms]
    uuids = sorted(set().union(*loaded))
    files: Dict[str, List[dict]] = collections.defaultdict(list)
    log, stats = [], collections.Counter()
    for uid in uuids:
        runs = [Run(i, d[uid][1], d[uid][2], cap) for i, d in enumerate(loaded) if uid in d]
        run, why = choose(runs, rule)
        fname = next(d[uid][0] for d in loaded if uid in d)
        files[fname].append(run.record)
        stats[why] += 1
        log.append(
            {"uuid": uid, "chosen_run": run.index, "why": why, "answers": [r.answer[:120] for r in runs]}
        )
    if out.exists():
        raise FileExistsError(out)
    (out / "prediction").mkdir(parents=True)
    for fname, recs in files.items():
        (out / "prediction" / fname).write_text(json.dumps(recs, ensure_ascii=False))
    meta = json.loads((arms[0] / "meta.json").read_text())
    meta.update(arm=out.name, variant=f"vote_{rule}", voted_from=[str(a) for a in arms])
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    for extra in ("remap.json",):
        if (arms[0] / extra).exists():
            shutil.copy(arms[0] / extra, out / extra)
    summary = {"rule": rule, "tasks": len(uuids), "runs": len(arms), "choices": dict(stats)}
    (out / "vote_log.json").write_text(
        json.dumps({"summary": summary, "tasks": log}, indent=1, ensure_ascii=False)
    )
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--arm", action="append", required=True, type=Path, help="one run's arm dir (repeat, >= 2)"
    )
    p.add_argument("--cap", type=int, required=True, choices=(1, 2, 3, 4))
    p.add_argument("--rule", choices=RULES, default="majority")
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args(argv)
    print(json.dumps(vote(args.arm, args.cap, args.rule, args.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
