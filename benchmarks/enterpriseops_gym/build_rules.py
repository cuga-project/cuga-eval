#!/usr/bin/env python3
"""Offline intake: build the rule set for each ITSM policy version used by the chosen tasks.

Input is only the policy text (task system_prompt) and the server's tool schemas (tasks/itsm_tools.json);
task prompts and verifiers are never read.

Default (pipeline): ``cuga.policy_layer.builder.build_policy_set`` → benchmarks/policy_eval/builds_v5/<policy_hash>.json
(``rules`` as RuleSetHooks reads them, ``procedures``, and the full ``build``). The pipeline runs the repairs of
``rule_repair`` itself (tools for verify rules, typed rules for verify rules, role grants as ``remind``, ``when`` values
as lists); ``--no-repair`` leaves them out. The builds that runs measured (``builds``, ``builds_v2``, ``builds_v4``) are
never written by this script. ``--legacy``: the older single-document builder → rules/<policy_hash>.json (the pilot's
files; kept unchanged otherwise). Model answers are cached on disk, in ``<out>/cache``.

After each version the build is checked as a new package (``validate_package(legacy=False)``) and the findings are
counted by code. The cost of each version goes to the ledger when it is built; a version over ``--max-version-cost`` or
a total over ``--max-total-cost`` stops the script.

  ~/dev/cuga-agent-gate/.venv/bin/python benchmarks/enterpriseops_gym/build_rules.py --versions h1,h2 [--no-model]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL_ROOT = HERE.parents[1]
MEASURED = ("builds", "builds_v2", "builds_v3", "builds_v4")  # what earlier runs read: never overwritten here


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--versions", help="comma-separated policy hashes")
    ap.add_argument("--model", default=os.environ.get("POLICY_MODEL_NAME", "aws/gpt-oss-120b"))
    ap.add_argument("--max-tokens", type=int, default=16000, help="answer limit of the model (reasoning included)")
    ap.add_argument("--no-model", action="store_true", help="code rules only")
    ap.add_argument("--legacy", action="store_true", help="older single-document builder, writes rules/")
    ap.add_argument("--out", help="build directory (default policy_eval/builds_v5)")
    ap.add_argument("--no-repair", action="store_true", help="skip the repair step of the pipeline")
    ap.add_argument("--variant", default="", help="file name <hash>.<variant>.json, for a build kept beside the main one")
    ap.add_argument("--max-version-cost", type=float, default=0.30, help="stop after a version that costs more ($)")
    ap.add_argument("--max-total-cost", type=float, default=1.00, help="stop when this script has spent this much ($)")
    args = ap.parse_args()

    from dotenv import dotenv_values

    for k, v in dotenv_values(EVAL_ROOT / ".env").items():
        if k in ("OPENAI_API_KEY", "OPENAI_BASE_URL") and v and k not in os.environ:
            os.environ[k] = v
    from cuga.policy_layer.builder import build, build_policy_set, cached_model, openai_json_model
    from cuga.policy_layer.documents import load_document
    from cuga.policy_layer.model import PolicySet, to_json
    from cuga.policy_layer.package import from_build
    from cuga.policy_layer.validate import validate_package

    tasks = json.loads((HERE / "tasks/itsm_oracle.json").read_text())
    versions = set()
    if args.pilot:
        versions |= {
            p["policy_version"] for p in json.loads((HERE / "tasks/pilot.json").read_text())["tasks"]
        }
    if args.versions:
        versions |= set(args.versions.split(","))
    policy = {t["_policy_hash"]: t["system_prompt"] for t in tasks if t["_policy_hash"] in versions}
    specs = json.loads((HERE / "tasks/itsm_tools.json").read_text())
    model = None if args.no_model else openai_json_model(args.model, max_tokens=args.max_tokens)
    out = (
        HERE / "rules"
        if args.legacy
        else Path(args.out)
        if args.out
        else HERE.parent / "policy_eval" / "builds_v5"
    )
    if not args.legacy and out.name in MEASURED:
        sys.exit(f"{out}: a measured build directory is never overwritten; use another --out")
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(HERE.parent))
    import policy_pilot_costs as costs

    if costs.over_budget():
        sys.exit(f"budget reached: {costs.line()}")
    spent_here = 0.0
    for h, text in sorted(policy.items()):
        before = dict(model.usage) if model is not None else {}
        version_cost = 0.0
        try:
            if args.legacy:
                res = build(text, specs, model=model, cache_dir=out / "cache")
                (out / f"{h}.json").write_text(json.dumps(res.to_dict(), indent=1))
                print(h, json.dumps(res.stats), "coverage:", dict(Counter(c.get("class") for c in res.coverage)))
            else:
                # the call that learns the heading styles is cached like the others, so a rebuild is the same
                structure_model = cached_model(model, out / "cache")
                ps = PolicySet(documents=[load_document(text, meta={"id": f"itsm-{h}"}, model=structure_model)])
                b = build_policy_set(ps, specs, model, cache_dir=out / "cache", repair=not args.no_repair)
                doc = {
                    "policy_hash": h,
                    "rules": [r.rule for r in b.rules],
                    "procedures": to_json(b.procedures),
                    "build": to_json(b),
                    "policy_set": to_json(ps),
                }
                (out / (f"{h}.{args.variant}.json" if args.variant else f"{h}.json")).write_text(json.dumps(doc, indent=1))
                print(h, json.dumps({k: v for k, v in b.stats.items() if k != "usage"}))
                found = Counter(f.code for f in validate_package(from_build(doc), specs, legacy=False))
                print(h, "validate_package(legacy=False):", dict(found) or "no findings")
        finally:  # the calls of a version that failed are paid too
            used = {k: model.usage[k] - before.get(k, 0) for k in model.usage} if model is not None else {}
            if used.get("calls"):
                costs.record("build_rules", h, policy={**used, "model": model.model_name})
                version_cost = costs.usage_cost(model.model_name, used)
                spent_here += version_cost
                print(h, f"cost ${version_cost:.4f} ({used['calls']} calls), this run ${spent_here:.4f}")
        if model is not None and (version_cost > args.max_version_cost or spent_here > args.max_total_cost):
            sys.exit(f"stopped after {h}: over the cost limit")
    print(costs.line())


if __name__ == "__main__":
    main()
