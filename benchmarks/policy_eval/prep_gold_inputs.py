#!/usr/bin/env python3
"""Inputs for the gold rule sets of the tuning policies (Task 12). Reads only policy text, task data and tool schemas.

ITSM: the policy text of each version used by a tuning task -> gold/inputs/itsm-<hash>.md, tools -> itsm_tools.json.
AutomationBench: for each tuning task, its request, initial state and tool schemas -> gold/inputs/ab/<task>.json
(the initial state holds the policy records; the gold build decides which records are policies).
Rubrics and verifiers are never written.

  benchmarks/automationbench/.venv/bin/python -I benchmarks/policy_eval/prep_gold_inputs.py
"""

from __future__ import annotations

import inspect
import json
import typing
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
OUT = HERE / "gold" / "inputs"


def main() -> None:
    sel = json.loads((HERE / "policy_eval_tasks.json").read_text())
    tasks = {
        t["task_id"]: t for t in json.loads((BENCH / "enterpriseops_gym/tasks/itsm_oracle.json").read_text())
    }
    for h in sorted({tasks[i]["_policy_hash"] for i in sel["itsm"]["tune"]}):
        text = next(t["system_prompt"] for t in tasks.values() if t["_policy_hash"] == h)
        (OUT / f"itsm-{h}.md").write_text(text)
    (OUT / "itsm_tools.json").write_text((BENCH / "enterpriseops_gym/tasks/itsm_tools.json").read_text())

    from automationbench.domains import PUBLIC_DOMAINS, get_domain_dataset
    from automationbench.tools import ALL_TOOLS
    from langchain_core.tools import StructuredTool

    wanted = set(sel["automationbench"]["tune"])
    by_name = {f.__name__: f for f in ALL_TOOLS}
    for dom in PUBLIC_DOMAINS:
        for row in get_domain_dataset(dom):
            info = row["info"] if isinstance(row["info"], dict) else json.loads(row["info"])
            name = info.get("task_name")
            if name not in wanted:
                continue
            specs = []
            for tname in info.get("zapier_tools", []):
                fn = by_name.get(tname)
                if fn is None:
                    continue
                sig = inspect.signature(fn)
                params = [p for n, p in sig.parameters.items() if n != "world"]

                def stub(**kw):  # schema only
                    return None

                stub.__signature__ = sig.replace(parameters=params, return_annotation=inspect.Signature.empty)
                stub.__name__, stub.__doc__ = fn.__name__, fn.__doc__
                hints = typing.get_type_hints(fn)
                stub.__annotations__ = {k: v for k, v in hints.items() if k not in ("world", "return")}
                try:
                    tool = StructuredTool.from_function(
                        func=stub, name=fn.__name__, parse_docstring=True, error_on_invalid_docstring=False
                    )
                except ValueError:  # a docstring that names an argument the signature does not have
                    tool = StructuredTool.from_function(
                        func=stub, name=fn.__name__, description=fn.__doc__ or fn.__name__
                    )
                specs.append(
                    {
                        "name": tool.name,
                        "description": (tool.description or "")[:300],
                        "inputSchema": tool.args_schema.model_json_schema(),
                    }
                )
            user = "\n\n".join(m["content"] for m in row["prompt"] if m["role"] == "user")
            (OUT / "ab" / f"{name}.json").write_text(
                json.dumps(
                    {
                        "task": name,
                        "domain": dom,
                        "request": user,
                        "initial_state": info.get("initial_state"),
                        "tools": specs,
                    },
                    indent=1,
                    default=str,
                )
            )
    print(sorted(p.name for p in OUT.iterdir()), len(list((OUT / "ab").iterdir())), "AutomationBench tasks")


if __name__ == "__main__":
    main()
