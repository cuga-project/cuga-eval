#!/usr/bin/env python3
"""Run τ² arms at the same time on the same tasks, 1 worker per process (τ² limit), N shards per arm.
Arm A = CUGA alone; arm T = CUGA + SOP tracker (SOP_TRACKER=1); arm N = CUGA + SOP navigator (hand-off check);
arm TN = both. Same snapshot, agent and simulator for all arms.

  python3 policy_eval/tau2/launch_paired.py --tasks-file policy_eval/tau2/telecom_dev20.json --tag dev1 \
      --snapshot ~/dev/cuga_snapshots/sop_trk1/src [--arms A,T] [--shards 4] [--split test]
Logs: policy_eval/tau2/<tag>_<arm>_s<i>.log; τ² results: ~/dev/cuga-eval-tau2/benchmarks/tau2/logging_<tag>_<arm>_s<i>/
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WT = Path.home() / "dev/cuga-eval-tau2"
ARMS = {
    "A": {},
    "T": {"SOP_TRACKER": "1"},
    "N": {"SOP_NAVIGATOR": "1", "POLICY_BUILD": str(HERE / "builds/telecom.json")},
    "TN": {"SOP_TRACKER": "1", "SOP_NAVIGATOR": "1", "POLICY_BUILD": str(HERE / "builds/telecom.json")},
}

ap = argparse.ArgumentParser()
ap.add_argument("--tasks-file")
ap.add_argument("--split")
ap.add_argument("--domain", default="telecom")
ap.add_argument("--tag", required=True)
ap.add_argument("--arms", default="A,T")
ap.add_argument("--shards", type=int, default=4)
ap.add_argument("--snapshot", required=True)
ap.add_argument("--agent-model", default="azure/DeepSeek-V4-Pro")
ap.add_argument("--user-sim", default="openai/Azure/gpt-4.1")
a = ap.parse_args()
a.snapshot = str(Path(a.snapshot).expanduser())
if not Path(a.snapshot).is_dir():  # every shard would fail alone, with the message only in its log file
    raise SystemExit(f"no snapshot {a.snapshot}")
if a.tasks_file:
    ids = json.loads(Path(a.tasks_file).read_text())
else:
    ids = list(
        json.loads(
            (WT / f"benchmarks/tau2/tau2-bench/data/tau2/domains/{a.domain}/split_tasks.json").read_text()
        )[a.split]
    )
procs = []
for arm in a.arms.split(","):
    for i in range(a.shards):
        shard = ids[i :: a.shards]
        if not shard:
            continue
        log = open(HERE / f"{a.tag}_{arm}_s{i}.log", "w")
        procs.append(
            subprocess.Popen(
                [
                    sys.executable,
                    str(HERE / "run_arm_a.py"),
                    "--agent-model",
                    a.agent_model,
                    "--domain",
                    a.domain,
                    "--tag",
                    f"{a.tag}_{arm}_s{i}",
                    "--user-sim",
                    a.user_sim,
                    "--snapshot",
                    a.snapshot,
                    "--task",
                    *shard,
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                env={**os.environ, **ARMS[arm]},
            )
        )
print(len(procs), "processes", flush=True)
for p in procs:
    p.wait()
print("done", flush=True)
