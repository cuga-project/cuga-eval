#!/usr/bin/env python3
"""Offline intake of one HANDBOOK SOP with the task's tool catalog: sections, statements, graph links, procedures, rules.

The SOP is downloaded content: it is only read as data. Output: policy_eval/builds_handbook/v3/<task>.json + stats.

  ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/handbook/intake_one.py <task> [--model aws/gpt-oss-120b]
"""

import argparse
import collections
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = Path.home() / "dev/untrusted/handbook-sample/tasks"
OUT = HERE.parent / "policy_eval/builds_handbook" / os.environ.get("HB_BUILDS", "v3")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("--model", default="aws/gpt-oss-120b")
    a = ap.parse_args()
    from dotenv import dotenv_values

    for k, v in dotenv_values(HERE.parents[1] / ".env").items():
        if k in ("OPENAI_API_KEY", "OPENAI_BASE_URL") and v and k not in os.environ:
            os.environ[k] = v
    sys.path.insert(0, str(HERE.parent))
    import policy_pilot_costs as costs
    from cuga.policy_layer.builder import build_policy_set, cached_model
    from cuga.policy_layer.documents import load_policy_set
    from cuga.policy_layer.llm import openai_json_model
    from cuga.policy_layer.model import to_json

    sop = next(iter(sorted((TASKS / a.task / "environment/initial_workspace").glob("*SOP*"))))
    specs = json.loads((HERE / "tools" / f"{a.task}.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    model = openai_json_model(a.model, timeout=300, max_tokens=16000)
    t0 = time.monotonic()
    ps = load_policy_set(
        [str(sop)], meta={}, model=cached_model(model, OUT / os.environ.get("INTAKE_CACHE", "cache"))
    )  # structure learning cached too
    build = build_policy_set(ps, specs, model=model, cache_dir=OUT / os.environ.get("INTAKE_CACHE", "cache"))
    secs = time.monotonic() - t0
    doc = ps.documents[0]
    sts = [s for sec in doc.sections for s in sec.statements]
    j = to_json(build)
    rules = j.get("rules") or []
    stats = {
        "sop": sop.name,
        "sections": len(doc.sections),
        "statements": len(sts),
        "statement_types": dict(
            collections.Counter(
                str(getattr(t, "value", t)) for s in sts for t in (s.types or [])[:1]
            ).most_common()
        ),
        "links": dict(
            collections.Counter(
                str(l.get("kind") or l.get("type")) for l in j.get("links") or []
            ).most_common()
        ),
        "procedures": len(j.get("procedures") or []),
        "procedure_steps": sum(len(p.get("steps") or []) for p in j.get("procedures") or []),
        "steps_with_tool": sum(
            1 for p in j.get("procedures") or [] for s in p.get("steps") or [] if s.get("action")
        ),
        "rules": dict(collections.Counter(r.get("type") for r in rules).most_common()),
        "coverage": dict(collections.Counter(c.get("kind") for c in j.get("coverage") or []).most_common()),
        "seconds": round(secs),
        "usage": dict(getattr(model, "usage", {}) or {}),
    }
    (OUT / f"{a.task}.json").write_text(
        json.dumps({"stats": stats, "build": j, "policy_set": to_json(ps)}, indent=1, default=str)
    )
    costs.record("handbook_intake_v3", a.task, policy={**stats["usage"], "model": a.model})
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
