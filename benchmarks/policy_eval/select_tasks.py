#!/usr/bin/env python3
"""Fixed task selection for the policy-intake evaluation (rules written 2026-11-01, before any run).

ITSM (EnterpriseOps-Gym oracle tasks):
  - the user prompt involves status changes, change requests, SLA or approvals (keyword rule below);
  - minus the 5 pilot tasks (tasks/pilot.json) and the 2 tasks with broken verifiers (upstream issues #21, #22);
  - cross-reference study: one task on policy version cb2d4ee021 and one on c47f8ceef3 (seeded pick), kept out of
    the tuning and unseen sets;
  - the rest: 10 tuning and 10 unseen tasks, seed 20261101.
AutomationBench (public tasks):
  - in the detector-probe pool with at least one record that Gemini labelled as a policy (hand review applied);
  - at least one must-not check in the rubric (an assertion type with "not"; only types are read, never values);
  - minus the 5 pilot tasks and the 5 cross-reference study tasks;
  - tuning tasks from the probe's tune half, unseen tasks from its test half (so the Kev threshold never saw them);
  - at most 2 per domain, 10 each, seed 20261101.

Run with the AutomationBench venv (the rubric types come from the benchmark package):
  benchmarks/automationbench/.venv/bin/python -I benchmarks/policy_eval/select_tasks.py
"""

from __future__ import annotations

import json
import random
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
SEED = 20261101
N = 10
ITSM_RULE = re.compile(
    r"\b(resolv\w*|clos\w*|on hold|transition\w*|change request\w*|sla\w*|approv\w*)\b", re.I
)
ITSM_BROKEN = {"task_20251212_172511_458_e6427839_47076c15", "task_20251210_205620_593_391f1eff_ad65c160"}
ITSM_XREF_VERSIONS = ("cb2d4ee021", "c47f8ceef3")
AB_XREF = [
    "operations.twilio_afterhours_incident",
    "operations.sheets_asana_approved_request",
    "marketing.customer_feedback_aggregation",
    "hr.benefits_enrollment_review",
    "marketing.hashtag_performance",
]
NEGATIVE = re.compile(r"(^|_)not(_|$)")


def itsm() -> dict:
    tasks = json.loads((BENCH / "enterpriseops_gym/tasks/itsm_oracle.json").read_text())
    pilot = {
        t["task_id"] for t in json.loads((BENCH / "enterpriseops_gym/tasks/pilot.json").read_text())["tasks"]
    }
    pool = [
        t for t in tasks if ITSM_RULE.search(t["user_prompt"]) and t["task_id"] not in pilot | ITSM_BROKEN
    ]
    rng = random.Random(SEED)
    xref = []
    for v in ITSM_XREF_VERSIONS:
        cands = sorted(
            t["task_id"] for t in tasks if t["_policy_hash"] == v and t["task_id"] not in pilot | ITSM_BROKEN
        )
        if cands:
            xref.append(rng.choice(cands))
    rest = sorted(t["task_id"] for t in pool if t["task_id"] not in xref)
    rng.shuffle(rest)
    return {"pool": len(pool), "tune": rest[:N], "unseen": rest[N : 2 * N], "xref": xref}


def automationbench() -> dict:
    from automationbench.domains import PUBLIC_DOMAINS, get_domain_dataset

    probe = BENCH / "automationbench/results/detector_probe"
    records = {
        json.loads(l)["id"]: json.loads(l)
        for l in (probe / "records.jsonl").read_text().splitlines()
        if l.strip()
    }
    labels = {
        json.loads(l)["id"]: json.loads(l)
        for l in (probe / "labels.jsonl").read_text().splitlines()
        if l.strip()
    }
    review = json.loads((probe / "review.json").read_text()) if (probe / "review.json").exists() else {}
    is_policy = {i: (review[i] if i in review else lab.get("is_policy")) for i, lab in labels.items()}
    policy_tasks = {
        records[i]["task"]: records[i]["split"] for i, v in is_policy.items() if v is True and i in records
    }
    pilot = {
        t["task"] for t in json.loads((BENCH / "automationbench/policy_pilot.json").read_text())["tasks"]
    }
    negative, domain = set(), {}
    for dom in PUBLIC_DOMAINS:
        for row in get_domain_dataset(dom):
            info = row["info"] if isinstance(row["info"], dict) else json.loads(row["info"])
            name = info.get("task_name")
            domain[name] = dom
            if any(NEGATIVE.search(str(a.get("type", ""))) for a in info.get("assertions") or []):
                negative.add(name)
    pool = sorted(t for t in policy_tasks if t in negative and t not in pilot and t not in AB_XREF)
    rng = random.Random(SEED)
    out = {"pool": len(pool), "xref": AB_XREF}
    for split, key in (("tune", "tune"), ("test", "unseen")):
        cands = [t for t in pool if policy_tasks[t] == split]
        rng.shuffle(cands)
        picked, per_dom = [], defaultdict(int)
        for t in cands:
            if per_dom[domain[t]] < 2:
                picked.append(t)
                per_dom[domain[t]] += 1
            if len(picked) == N:
                break
        out[key] = picked
    return out


def main() -> None:
    result = {
        "seed": SEED,
        "written": "2026-11-01",
        "rules": __doc__.split("Run with")[0].strip(),
        "itsm": itsm(),
        "automationbench": automationbench(),
    }
    (HERE / "policy_eval_tasks.json").write_text(json.dumps(result, indent=1))
    for bench in ("itsm", "automationbench"):
        r = result[bench]
        print(
            bench,
            "pool",
            r["pool"],
            "tune",
            len(r["tune"]),
            "unseen",
            len(r["unseen"]),
            "xref",
            len(r["xref"]),
        )


if __name__ == "__main__":
    main()
