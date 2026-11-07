#!/usr/bin/env python3
"""A third held-out set, drawn 2026-11-02 after unseen2 failures were inspected (unseen2 is no longer clean).

Same rules as select_tasks.py (written 2026-11-01), applied to what is left of the same pools:
- AutomationBench: policy tasks from the detector probe's test half with a must-not check, minus pilot,
  cross-reference, tuning, unseen and unseen2 tasks; at most 2 per domain; 10 tasks; seed 20261103.
- ITSM: the remaining tasks of the ITSM pool (status changes, change requests, SLA or approvals), minus tuning,
  unseen, unseen2 and cross-reference tasks; 10 tasks; seed 20261103.
Task contents are not read here; only names and the pool rules.

  automationbench/.venv/bin/python policy_eval/select_unseen3.py
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import select_tasks as st  # noqa: E402

SEED = 20261103
N = 10


def main() -> None:
    used = json.loads((HERE / "policy_eval_tasks.json").read_text())
    taken_ab = (
        set(used["automationbench"]["tune"])
        | set(used["automationbench"]["unseen"])
        | set(used["automationbench"]["xref"])
    )
    taken_itsm = set(used["itsm"]["tune"]) | set(used["itsm"]["unseen"]) | set(used["itsm"]["xref"])
    u2 = json.loads((HERE / "policy_eval_tasks_unseen2.json").read_text())
    taken_ab |= set(u2["automationbench"]["unseen2"])
    taken_itsm |= set(u2["itsm"]["unseen2"])

    # AutomationBench: rebuild the pool exactly as select_tasks.automationbench() does, then take the test half's rest
    from automationbench.domains import PUBLIC_DOMAINS, get_domain_dataset

    probe = st.BENCH / "automationbench/results/detector_probe"
    records = {
        json.loads(line)["id"]: json.loads(line)
        for line in (probe / "records.jsonl").read_text().splitlines()
        if line.strip()
    }
    labels = {
        json.loads(line)["id"]: json.loads(line)
        for line in (probe / "labels.jsonl").read_text().splitlines()
        if line.strip()
    }
    review = json.loads((probe / "review.json").read_text()) if (probe / "review.json").exists() else {}
    is_policy = {i: (review[i] if i in review else lab.get("is_policy")) for i, lab in labels.items()}
    policy_tasks = {
        records[i]["task"]: records[i]["split"] for i, v in is_policy.items() if v is True and i in records
    }
    pilot = {
        t["task"] for t in json.loads((st.BENCH / "automationbench/policy_pilot.json").read_text())["tasks"]
    }
    negative, domain = set(), {}
    for dom in PUBLIC_DOMAINS:
        for row in get_domain_dataset(dom):
            info = row["info"] if isinstance(row["info"], dict) else json.loads(row["info"])
            name = info.get("task_name")
            domain[name] = dom
            if any(st.NEGATIVE.search(str(a.get("type", ""))) for a in info.get("assertions") or []):
                negative.add(name)
    cands = sorted(
        t
        for t in policy_tasks
        if t in negative and t not in pilot and t not in taken_ab and policy_tasks[t] == "test"
    )
    rng = random.Random(SEED)
    rng.shuffle(cands)
    ab, per_dom = [], defaultdict(int)
    for t in cands:
        if per_dom[domain[t]] < 2:
            ab.append(t)
            per_dom[domain[t]] += 1
        if len(ab) == N:
            break

    tasks = json.loads((st.BENCH / "enterpriseops_gym/tasks/itsm_oracle.json").read_text())
    pilot_itsm = {
        t["task_id"]
        for t in json.loads((st.BENCH / "enterpriseops_gym/tasks/pilot.json").read_text())["tasks"]
    }
    rest = sorted(
        t["task_id"]
        for t in tasks
        if st.ITSM_RULE.search(t["user_prompt"])
        and t["task_id"] not in pilot_itsm | st.ITSM_BROKEN | taken_itsm
    )
    rng = random.Random(SEED)
    rng.shuffle(rest)
    out = {
        "seed": SEED,
        "written": "2026-11-02 (unseen3)",
        "rules": __doc__.strip().split("\n\n")[1],
        "automationbench": {"candidates": len(cands), "unseen3": ab},
        "itsm": {"candidates": len(rest), "unseen3": rest[:N]},
    }
    (HERE / "policy_eval_tasks_unseen3.json").write_text(json.dumps(out, indent=1))
    print(
        "automationbench",
        len(cands),
        "candidates ->",
        len(ab),
        "| itsm",
        len(rest),
        "candidates ->",
        len(rest[:N]),
    )


if __name__ == "__main__":
    main()
