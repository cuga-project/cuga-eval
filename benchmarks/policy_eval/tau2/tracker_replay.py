#!/usr/bin/env python3
"""Replay the SOP tracker offline on a recorded τ² conversation: the note it would give before agent turns k1, k2, ...
~/dev/cuga-agent-gate/.venv/bin/python policy_eval/tau2/tracker_replay.py <run tag> <task substring> [--at 4,8,12]"""

import argparse
import glob
import json
import os
import sys
from pathlib import Path

T2 = Path.home() / "dev/cuga-eval-tau2/benchmarks/tau2"
ap = argparse.ArgumentParser()
ap.add_argument("tag")
ap.add_argument("task")
ap.add_argument("--at", default="3,6,9,12")
ap.add_argument("--model", default="aws/gpt-oss-120b")
ap.add_argument("--src", default=str(Path.home() / "dev/cuga-agent-gate/src"))
a = ap.parse_args()
sys.path.insert(0, a.src)
from dotenv import dotenv_values  # noqa: E402

for k, v in dotenv_values(Path.home() / "dev/cuga-eval/.env").items():
    if k in ("OPENAI_API_KEY", "OPENAI_BASE_URL") and v:
        os.environ.setdefault(k, v)
from cuga.policy_layer.llm import openai_json_model  # noqa: E402
from cuga.policy_layer.sop_tracker import SopTracker  # noqa: E402

rows = {}
for f in glob.glob(str(T2 / f"logging_{a.tag}*/results/*.json")):
    j = json.load(open(f))
    for r in j.get("results") if isinstance(j, dict) else j:
        rows[r["task_id"]] = r
tid = next(t for t in rows if a.task in t)
turns, starts = [], []
for m in rows[tid]["messages"]:
    if m["role"] == "user" and (m.get("content") or "").strip():
        starts.append(len(turns))
        turns.append({"role": "customer", "text": m["content"]})
    elif m["role"] == "assistant":
        for tc in m.get("tool_calls") or []:
            turns.append({"role": "tool", "name": tc.get("name"), "args": tc.get("arguments"), "result": ""})
        if (m.get("content") or "").strip():
            turns.append({"role": "agent", "text": m["content"]})
    elif m["role"] == "tool" and turns and turns[-1].get("role") == "tool":
        turns[-1]["result"] = (m.get("content") or "")[:300]
policy = (Path(__file__).resolve().parent / "telecom_policy.md").read_text()
tr = SopTracker(policy, openai_json_model(a.model, timeout=120, max_tokens=8000))
print(tid, "| customer turns:", len(starts), "| reward", rows[tid].get("reward"))
for k in [int(x) for x in a.at.split(",") if int(x) <= len(starts)]:
    note = tr.note(turns[: starts[k - 1] + 1])
    print(f"--- before agent turn {k}: chapters {tr.kept}\n{note}\n")
print("usage", getattr(tr.model, "usage", {}))
