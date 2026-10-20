"""Package test-split arms as a VAKRA leaderboard submission (the layout validate_output.py checks).

For each arm (one per capability, after its recovery merge) this writes
``<out>/<capability_dir>/<domain>.json``: one record per task of the official test input, with
``uuid, domain, status, error, duration_s`` and ``output[turn_id, query, answer, sequence.tool_call]``.

* ``status``/``error`` follow VAKRA's runner: ``error`` when the task ended without an answer, with
  the cause reduced to a short category. Raw provider messages can carry endpoint details, so they
  never go into a submission.
* ``duration_s``: cap1's runner records it. For caps 2-4 it is the task's wall time read from the
  console log of the run that produced the submitted answer (the arm, or the recovery pass that
  replaced it). Tasks with no timing in any log get 0.0 and are counted in the report.
* ``sequence.tool_response`` is dropped: the evaluator replays every tool call and overwrites it.
* Completeness: every uuid of the official test input appears exactly once, in input order. A task
  the arm never predicted gets an empty ``error`` record so the file validates, and it is counted.

usage: python -m benchmarks.m3.parity.package_submission --arm RUN_DIR/ARM [--arm ...] --out DIR
           [--vakra-main ~/git/appworld/vakra-main] [--no-validate]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from benchmarks.m3.parity.recover import _runner_records

PARITY_DIR = Path(__file__).resolve().parent
MANIFESTS = PARITY_DIR / "manifests"

_TS = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+) \|")
_START = re.compile(r"^\[\d+/\d+\] Processing sample")
_END = re.compile(r"(?:✅ Completed: |❌ ERROR in multi-turn task )([0-9A-Za-z-]+)")


def error_category(error: str) -> str:
    """A short, endpoint-free description of why a task has no answer."""
    e = error.lower()
    if not e.strip():
        return "empty answer"
    if "429" in e or "ratelimit" in e or "rate limit" in e:
        return "RateLimitError: model provider rate limit"
    if "context length" in e or "context_length" in e or "longer than the model" in e:
        return "BadRequestError: input longer than the model's context length"
    if "timeout" in e or "timed out" in e:
        return "TimeoutError: agent timed out"
    if "connection" in e:
        return "APIConnectionError: model provider unreachable"
    return "Error: agent run failed"


def console_durations(console_log: Path) -> Dict[str, float]:
    """``{uuid: seconds}`` from an eval_m3 console log: a task's first timestamped line to its end line."""
    out: Dict[str, float] = {}
    if not console_log.exists():
        return out
    waiting, start = False, None
    with open(console_log, errors="replace") as fh:
        for line in fh:
            if _START.match(line):
                waiting, start = True, None
                continue
            m = _TS.match(line)
            if not m:
                continue
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f")
            if waiting:
                waiting, start = False, ts
            end = _END.search(line)
            if end and start is not None:
                out.setdefault(end.group(1).lower(), round((ts - start).total_seconds(), 3))
                start = None
    return out


def _cap1_durations(arm_dir: Path) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for f in sorted(
        glob.glob(str(arm_dir / "raw" / "*" / "m3_task1_enterprise_2*.json")), key=os.path.getmtime
    ):
        for it in json.loads(Path(f).read_text()).get("results") or []:
            if it.get("duration_s") is not None:
                out[str(it.get("uuid") or "").lower()] = float(it["duration_s"])
    return out


def run_info(arm_dir: Path, task_id: int) -> Dict[str, Dict[str, Any]]:
    """``{uuid: {answer, error, duration}}`` for one run of an arm (the arm itself or a recovery pass)."""
    durations = _cap1_durations(arm_dir) if task_id == 1 else console_durations(arm_dir / "console.log")
    info: Dict[str, Dict[str, Any]] = {}
    for rec in _runner_records(arm_dir, task_id):
        key = str(rec.get("uuid") or "").lower()
        prev = info.get(key)
        cur = dict(answer=rec["answer"].strip(), error=rec["error"].strip(), duration=durations.get(key))
        if prev is None or (cur["answer"] and not prev["answer"]):
            info[key] = cur
    return info


def recovery_runs(arm_dir: Path) -> List[Path]:
    """The arm's recovery passes in the order they ran (``<run_id>__recover<N>/<arm>``)."""
    run_dir, arm = arm_dir.parent, arm_dir.name
    found = []
    for d in glob.glob(str(run_dir.parent / f"{run_dir.name}__recover*" / arm)):
        n = re.search(r"__recover(\d+)$", Path(d).parent.name)
        if n:
            found.append((int(n.group(1)), Path(d)))
    return [p for _, p in sorted(found)]


def _final_turn(record: Dict[str, Any]) -> Dict[str, Any]:
    turns = record.get("output") or []
    return turns[-1] if turns else {}


def _tool_calls(turn: Dict[str, Any]) -> List[Dict[str, Any]]:
    calls = (turn.get("sequence") or {}).get("tool_call") or []
    out = []
    for c in calls:
        args = c.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        out.append({"name": str(c.get("name") or ""), "arguments": args if isinstance(args, dict) else {}})
    return out


def package_arm(arm_dir: Path, inputs_dir: Path, out_root: Path) -> Dict[str, Any]:
    """Write one capability's submission files; returns counts for the report."""
    arm_dir = Path(arm_dir)
    meta = json.loads((arm_dir / "meta.json").read_text())
    manifest = json.loads((MANIFESTS / f"{meta['subset']}.json").read_text())
    task_id = int(manifest["task_id"])
    cap_dir = out_root / manifest["capability_dir"]
    cap_dir.mkdir(parents=True, exist_ok=True)

    runs = [arm_dir] + recovery_runs(arm_dir)
    infos = [run_info(r, task_id) for r in runs]
    preds: Dict[str, Dict[str, Any]] = {}
    for f in glob.glob(str(arm_dir / "prediction" / "*.json")):
        for rec in json.loads(Path(f).read_text()):
            preds[str(rec.get("uuid") or "").lower()] = rec

    counts = dict(tasks=0, answered=0, error=0, missing=0, no_duration=0, turn_id_mismatch=0, domains=0)
    for inp_file in sorted(inputs_dir.glob("*.json")):
        domain = inp_file.stem
        records = []
        for item in json.loads(inp_file.read_text()):
            uuid = str(item["uuid"])
            key = uuid.lower()
            last_in = ((item.get("dialogue") or {}).get("turns") or [{}])[-1]  # the turn to answer
            pred = preds.get(key)
            turn = _final_turn(pred) if pred else {}
            answer = str(turn.get("answer") or "").strip() if pred else ""
            # the run that produced the submitted answer: the latest one whose answer matches it
            src = next(
                (i for i in reversed(infos) if key in i and i[key]["answer"] == answer and answer), None
            )
            if src is None:
                src = next((i for i in reversed(infos) if key in i), None)
            seen = (src or {}).get(key) or {}
            duration = seen.get("duration")
            counts["tasks"] += 1
            if pred is None:
                counts["missing"] += 1
            if duration is None:
                counts["no_duration"] += 1
            status = "success" if answer else "error"
            counts["answered" if answer else "error"] += 1
            turn_id = turn.get("turn_id") if pred else None
            if turn_id is None:
                turn_id = last_in.get("turn_id", 0)
            if "turn_id" in last_in and turn_id != last_in["turn_id"]:
                counts["turn_id_mismatch"] += 1
            records.append(
                {
                    "uuid": uuid,
                    "domain": domain,
                    "status": status,
                    "error": ""
                    if answer
                    else ("Error: task not run" if pred is None else error_category(seen.get("error") or "")),
                    "duration_s": float(duration or 0.0),
                    "output": [
                        {
                            "turn_id": int(turn_id),
                            "query": str(turn.get("query") or last_in.get("query") or ""),
                            "answer": answer,
                            "sequence": {"tool_call": _tool_calls(turn)},
                        }
                    ],
                }
            )
        (cap_dir / f"{domain}.json").write_text(json.dumps(records, indent=1, ensure_ascii=False))
        counts["domains"] += 1
    unknown = set(preds) - {
        str(it["uuid"]).lower() for f in inputs_dir.glob("*.json") for it in json.loads(f.read_text())
    }
    return dict(
        arm=str(arm_dir),
        subset=meta["subset"],
        capability_dir=manifest["capability_dir"],
        recovery_runs=[str(r) for r in runs[1:]],
        cuga_agent=meta.get("cuga_agent"),
        cuga_eval=meta.get("cuga_eval"),
        adapter_preset=meta.get("adapter_preset"),
        execution_mode=meta.get("execution_mode"),
        temperature=meta.get("temperature"),
        model=meta.get("model"),
        predictions_not_in_input=len(unknown),
        **counts,
    )


def validate(vakra_main: Path, cap_dirs: List[Path]) -> Tuple[int, str]:
    """Run VAKRA's own validate_output.py on each capability directory."""
    proc = subprocess.run(  # noqa: S603 — fixed argv: this interpreter and the vakra-main validator
        [sys.executable, str(vakra_main / "validate_output.py"), *map(str, cap_dirs)],
        capture_output=True,
        text=True,
    )
    return proc.returncode, (proc.stdout + proc.stderr)[-3000:]


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--arm", action="append", required=True, type=Path, help="RUN_DIR/ARM (repeat per capability)"
    )
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--vakra-main", type=Path, default=Path(os.path.expanduser("~/git/appworld/vakra-main")))
    p.add_argument("--no-validate", action="store_true")
    args = p.parse_args(argv)
    report = []
    for arm in args.arm:
        manifest = json.loads(
            (MANIFESTS / f"{json.loads((arm / 'meta.json').read_text())['subset']}.json").read_text()
        )
        inputs = args.vakra_main / manifest["vakra_train_data"] / "input"
        report.append(package_arm(arm, inputs, args.out))
    result: Dict[str, Any] = {"arms": report}
    if not args.no_validate:
        rc, log = validate(args.vakra_main, [args.out / r["capability_dir"] for r in report])
        result["validate_output"] = {"exit_code": rc, "tail": log}
    (args.out / "package_report.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))
    return 0 if result.get("validate_output", {}).get("exit_code", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
