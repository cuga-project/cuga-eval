#!/usr/bin/env python3
"""Offline intake on unseen long SOPs (HANDBOOK.md public sample): time, statements, types, links, procedures.

No tool list exists for these tasks outside their environment, so rules that need tool arguments are not compiled;
the run measures what intake extracts from a document it has never seen (generalization and speed).

  ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/intake_handbook.py <sop.html> [...]
"""

from __future__ import annotations

import collections
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "builds_handbook"


def main() -> None:
    sys.path.insert(0, str(HERE.parent))
    import policy_pilot_costs as costs
    from cuga.policy_layer.builder import build_policy_set
    from cuga.policy_layer.documents import load_policy_set
    from cuga.policy_layer.llm import openai_json_model
    from cuga.policy_layer.model import to_json

    OUT.mkdir(exist_ok=True)
    for src in sys.argv[1:]:
        path = Path(src)
        model = openai_json_model("aws/gpt-oss-120b")
        t0 = time.monotonic()
        ps = load_policy_set([str(path)], meta={}, model=model)
        t_load = time.monotonic() - t0
        build = build_policy_set(ps, [], model=model, cache_dir=OUT / "cache")
        t_all = time.monotonic() - t0
        doc = ps.documents[0]
        sts = [s for sec in doc.sections for s in sec.statements]
        types = collections.Counter(
            t.value if hasattr(t, "value") else str(t) for s in sts for t in (s.types or [])[:1]
        )
        links = collections.Counter(
            str(getattr(l, "kind", getattr(l, "type", "?"))) for l in getattr(build, "links", []) or []
        )
        procs = getattr(build, "procedures", []) or []
        stats = {
            "document": path.name,
            "chars": len(path.read_text(errors="replace")),
            "sections": len(doc.sections),
            "statements": len(sts),
            "types": dict(types.most_common()),
            "links": dict(links),
            "procedures": len(procs),
            "procedure_steps": sum(len(getattr(p, "steps", []) or []) for p in procs),
            "rules": len(getattr(build, "rules", []) or []),
            "load_s": round(t_load, 1),
            "total_s": round(t_all, 1),
            "usage": dict(getattr(model, "usage", {}) or {}),
        }
        (OUT / f"{path.stem}.json").write_text(
            json.dumps({"stats": stats, "build": to_json(build)}, indent=1, default=str)
        )
        costs.record("handbook_intake", path.name, policy={**stats["usage"], "model": "aws/gpt-oss-120b"})
        print(json.dumps(stats))
    print(costs.line())


if __name__ == "__main__":
    main()
