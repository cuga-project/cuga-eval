#!/usr/bin/env python3
"""Offline intake of a τ² domain policy (the text τ² gives the agent) with the domain's tool catalog (agent tools,
plus user-device tools prefixed `user__`): sections, statements, links, procedures, rules. Same builder as HANDBOOK.
Inputs: policy_eval/tau2/<domain>_policy.md and <domain>_tools.json. Output: policy_eval/tau2/builds/<domain>.json.

  ~/dev/cuga-agent-gate/.venv/bin/python benchmarks/policy_eval/tau2/intake_tau2.py telecom [--model aws/gpt-oss-120b]
"""

import argparse
import collections
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "builds"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("domain")
    ap.add_argument("--model", default="aws/gpt-oss-120b")
    a = ap.parse_args()
    from dotenv import dotenv_values

    for k, v in dotenv_values(HERE.parents[2] / ".env").items():
        if k in ("OPENAI_API_KEY", "OPENAI_BASE_URL") and v and k not in os.environ:
            os.environ[k] = v
    sys.path.insert(0, str(HERE.parents[1]))
    import policy_pilot_costs as costs
    from cuga.policy_layer.builder import build_policy_set, cached_model
    from cuga.policy_layer.documents import load_policy_set
    from cuga.policy_layer.llm import openai_json_model
    from cuga.policy_layer.model import to_json

    pol = HERE / f"{a.domain}_policy.md"
    specs = json.loads((HERE / f"{a.domain}_tools.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / os.environ.get("INTAKE_CACHE", f"cache_{a.domain}")
    model = openai_json_model(a.model, timeout=300, max_tokens=16000)
    t0 = time.monotonic()
    ps = load_policy_set([str(pol)], meta={}, model=cached_model(model, cache))
    build = build_policy_set(ps, specs, model=model, cache_dir=cache)
    j = to_json(build)
    procs = j.get("procedures") or []
    stats = {
        "sections": len(ps.documents[0].sections),
        "procedures": len(procs),
        "steps": sum(len(p.get("steps") or []) for p in procs),
        "steps_with_tool": sum(1 for p in procs for s in p.get("steps") or [] if s.get("action")),
        "preconditions": sum(len(p.get("preconditions") or []) for p in procs),
        "exceptions": sum(len(p.get("exceptions") or []) for p in procs),
        "escalations": sum(len(p.get("escalations") or []) for p in procs),
        "rules": dict(collections.Counter(r.get("type") for r in j.get("rules") or []).most_common()),
        "seconds": round(time.monotonic() - t0),
        "usage": dict(getattr(model, "usage", {}) or {}),
    }
    (OUT / f"{a.domain}.json").write_text(
        json.dumps({"stats": stats, "build": j, "policy_set": to_json(ps)}, indent=1, default=str)
    )
    costs.record("tau2_intake", a.domain, policy={**stats["usage"], "model": a.model})
    print(json.dumps(stats, indent=1))
    for p in procs:
        print(
            f'- {p.get("name")}: {len(p.get("steps") or [])} steps, pre {len(p.get("preconditions") or [])}, '
            f'exc {len(p.get("exceptions") or [])}, esc {len(p.get("escalations") or [])}'
        )


if __name__ == "__main__":
    main()
