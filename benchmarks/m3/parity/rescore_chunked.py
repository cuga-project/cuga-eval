"""Score one parity arm with the vendor evaluator in small chunks (the campaign's protocol).

The campaign scored its scorecards with ``vakra-main/cuga_runs/score_chunk_cap.py``: chunks of
5 items, each in its own evaluator process with a 300 s timeout after a fresh container
restart, because a single evaluator run can wedge on one item's groundedness replay (the
2026-10-12 cap3 gate rescore lost ~5 h to two such hangs). This does the same and merges the
chunks into one evaluator-format results file. A chunk that still fails after its retries is
listed under ``unscored_uuids`` (the campaign skipped such chunks) — never silently dropped.

usage: python -m benchmarks.m3.parity.rescore_chunked --vakra-main DIR --capability-name NAME \
         --container NAME --gt-root DIR --pred-root DIR --out FILE --work DIR --domains D1 D2 ...
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

CHUNK = 5  # score_chunk_cap.py default, as the campaign ran it
TIMEOUT = 300  # seconds per chunk (cap_estimate.sh: score_chunk_cap.py ... 5 300)


def restart_container(name: str) -> None:
    subprocess.run(["docker", "restart", name], capture_output=True)  # noqa: S603, S607  (docker CLI, fixed args)
    for _ in range(20):
        logs = subprocess.run(  # noqa: S603  (docker CLI, fixed args)
            ["docker", "logs", "--tail", "3", name],  # noqa: S607
            capture_output=True,
            text=True,
        )
        if "ready for exec" in (logs.stdout + logs.stderr):
            break
        time.sleep(3)
    time.sleep(2)


def run_evaluator(
    vakra_main: Path,
    capability_name: str,
    gt: Path,
    pred: Path,
    out: Path,
    mcp: str,
    domain: str,
    timeout: int,
) -> bool:
    """One evaluator process over one chunk; killed (with its children) at ``timeout``."""
    env = {**os.environ, "PYTHONPATH": f"{vakra_main}:{vakra_main}/evaluator"}
    cmd = [
        str(vakra_main / ".venv" / "bin" / "python"),
        "evaluator/evaluator.py",
        "--capability_name", capability_name,
        "--gt_root", str(gt),
        "--pred_root", str(pred),
        "--output", str(out),
        "--mcp-config", mcp,
        "--domains", domain,
    ]  # fmt: skip
    sys.stdout.flush()
    proc = subprocess.Popen(cmd, cwd=vakra_main, env=env, start_new_session=True)  # noqa: S603  (vakra-main evaluator)
    try:
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        print(f"  evaluator timed out after {timeout}s (killed)", flush=True)
        return False
    return rc == 0 and out.exists()


def has_judge_error(dialogue: Dict[str, Any]) -> bool:
    """The vendor judge reports an exception as an explanation ("Judge Error ...") with score 0."""
    return "Judge Error" in json.dumps(dialogue.get("details") or {}, default=str)


def _load_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return data if isinstance(data, list) else []


def score_domain(
    domain: str,
    gt_root: Path,
    pred_root: Path,
    work: Path,
    evaluate: Callable[[Path, Path, Path], bool],
    restart: Callable[[], None],
    chunk: int = CHUNK,
    retries: int = 1,
) -> Dict[str, Any]:
    """Evaluator-format domain block built from chunked runs (``evaluate(gt, pred, out)``)."""
    gt_recs = _load_list(gt_root / f"{domain}.json")
    preds = {str(r.get("uuid")): r for r in _load_list(pred_root / f"{domain}.json")}
    uuids = [str(r["uuid"]) for r in gt_recs]
    gt_by = {str(r["uuid"]): r for r in gt_recs}
    block: Dict[str, Any] = {
        "domain": domain,
        "n_groundtruth": len(uuids),
        "n_prediction": sum(1 for u in uuids if u in preds),
        "missing_prediction_uuids": [u for u in uuids if u not in preds],
        "extra_prediction_uuids": sorted(set(preds) - set(uuids)),
        "unscored_uuids": [],
        "judge_error_uuids": [],
        "dialogues": [],
    }
    scorable = [u for u in uuids if u in preds]
    for ci in range(0, len(scorable), chunk):
        part = scorable[ci : ci + chunk]
        cdir = work / f"{domain}_{ci // chunk}"
        shutil.rmtree(cdir, ignore_errors=True)
        (cdir / "gt").mkdir(parents=True)
        (cdir / "pred").mkdir(parents=True)
        (cdir / "gt" / f"{domain}.json").write_text(json.dumps([gt_by[u] for u in part]))
        (cdir / "pred" / f"{domain}.json").write_text(json.dumps([preds[u] for u in part]))
        out = cdir / "results.json"
        dialogues: List[Dict[str, Any]] = []
        ok = False
        for attempt in range(1 + retries):
            out.unlink(missing_ok=True)
            restart()
            if not evaluate(cdir / "gt", cdir / "pred", out):
                print(f"  {domain} chunk {ci // chunk}: attempt {attempt + 1} failed", flush=True)
                continue
            ok = True
            res = json.loads(out.read_text())
            dialogues = ((res.get("domains") or {}).get(domain) or {}).get("dialogues") or []
            if not any(has_judge_error(d) for d in dialogues) or attempt == retries:
                break
            print(
                f"  {domain} chunk {ci // chunk}: judge errors on attempt {attempt + 1}; retrying", flush=True
            )
        if not ok:
            block["unscored_uuids"] += part
            continue
        # A judge call that raised is not a verdict: never let it count as a failed task.
        errored = [d for d in dialogues if has_judge_error(d)]
        block["judge_error_uuids"] += [str(d.get("uuid")) for d in errored]
        block["dialogues"] += [d for d in dialogues if not has_judge_error(d)]
        print(
            f"  {domain} chunk {ci // chunk}: {len(dialogues) - len(errored)}/{len(part)} scored"
            + (f", {len(errored)} judge errors" if errored else ""),
            flush=True,
        )
    block["n_paired"] = len(block["dialogues"])
    return block


def merge(
    capability_name: str, gt_root: Path, pred_root: Path, blocks: List[Dict[str, Any]]
) -> Dict[str, Any]:
    dialogues = [d for b in blocks for d in b["dialogues"]]
    scores = [float(d.get("score") or 0) for d in dialogues]
    return {
        "capability_name": capability_name,
        "groundtruth_dir": str(gt_root),
        "prediction_dir": str(pred_root),
        "domains": {b["domain"]: b for b in blocks},
        "summary": {
            "n_domains": len(blocks),
            "n_samples": len(dialogues),
            "n_correct": sum(1 for s in scores if s == 1.0),
            "mean_dialogue_score": (sum(scores) / len(scores)) if scores else None,
            "n_missing_predictions": sum(len(b["missing_prediction_uuids"]) for b in blocks),
            "n_unscored": sum(len(b["unscored_uuids"]) for b in blocks),
            "n_judge_errors": sum(len(b.get("judge_error_uuids") or []) for b in blocks),
        },
        "chunking": {
            "chunk": CHUNK,
            "timeout_s": TIMEOUT,
            "protocol": "vakra-main cuga_runs/score_chunk_cap.py",
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--vakra-main", required=True, type=Path)
    p.add_argument("--capability-name", required=True)
    p.add_argument("--container", required=True)
    p.add_argument("--gt-root", required=True, type=Path)
    p.add_argument("--pred-root", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path)
    p.add_argument("--mcp-config", default="benchmark/mcp_connection_config.yaml")
    p.add_argument("--chunk", type=int, default=CHUNK)
    p.add_argument("--timeout", type=int, default=TIMEOUT)
    p.add_argument("--retries", type=int, default=1)
    p.add_argument("--domains", nargs="+", required=True)
    a = p.parse_args(argv)
    blocks = []
    for dom in a.domains:
        print(f"[{dom}] scoring in chunks of {a.chunk} ({a.timeout}s each)", flush=True)
        blocks.append(
            score_domain(
                dom,
                a.gt_root,
                a.pred_root,
                a.work,
                lambda g, pr, o, d=dom: run_evaluator(
                    a.vakra_main, a.capability_name, g, pr, o, a.mcp_config, d, a.timeout
                ),
                lambda: restart_container(a.container),
                chunk=a.chunk,
                retries=a.retries,
            )
        )
    merged = merge(a.capability_name, a.gt_root, a.pred_root, blocks)
    merged["chunking"].update(chunk=a.chunk, timeout_s=a.timeout, retries=a.retries)
    a.out.write_text(json.dumps(merged, indent=1))
    s = merged["summary"]
    print(
        f"scored {s['n_samples']} ({s['n_correct']} pass), unscored {s['n_unscored']}, "
        f"judge errors {s['n_judge_errors']}, missing {s['n_missing_predictions']}"
    )
    return 0 if s["n_unscored"] == 0 and s["n_judge_errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
