#!/usr/bin/env python3
"""Save the exact CugaLite system prompt and tool list for one benchmark task, without any LLM call.

Builds the agent the way the runner does, captures the prompt when prepare_node renders it, then stops the run.
Use it to check what the agent sees: app names, tool names, signatures, docs, the task's system text.

  CUGA_ENV_FILE=cuga.gptoss.env ~/dev/cuga-agent-gate/.venv/bin/python benchmarks/policy_eval/dump_agent_prompt.py \
      ab sales.zoom_calendar_conflict
  CUGA_ENV_FILE=cuga.gptoss.env ... dump_agent_prompt.py eog task_20251218_093719_611_764e5ead_5817d09a
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "prompts"


class _Captured(Exception):
    pass


def _env(bench_dir: Path, child_env) -> None:
    os.environ.update(child_env())
    env_file = Path(os.environ["ENV_FILE"])
    for line in env_file.read_text().splitlines():  # as the EOG runner does: cuga reads some at import
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _patch(path: Path) -> None:
    from cuga.backend.cuga_graph.nodes.cuga_lite.adapter import prepare_node

    real = prepare_node.create_mcp_prompt

    def capture(tools, *args, **kwargs):
        prompt = real(tools, *args, **kwargs)
        path.write_text(prompt)
        meta = {
            "tools": [getattr(t, "name", str(t)) for t in tools or []],
            "apps": [getattr(a, "name", str(a)) for a in (kwargs.get("apps") or [])],
            "enable_find_tools": kwargs.get("enable_find_tools"),
            "prompt_chars": len(prompt),
        }
        path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1))
        raise _Captured(str(path))

    prepare_node.create_mcp_prompt = capture


def main() -> None:
    bench, task = sys.argv[1], sys.argv[2]
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{bench}_{task}.prompt.txt"
    tmp = Path(tempfile.mkdtemp(prefix="dump_prompt_"))
    if bench == "ab":
        sys.path.insert(0, str(HERE.parent / "automationbench"))
        import run_cuga as runner

        _env(HERE.parent / "automationbench", lambda: runner.child_env(None))
        _patch(path)
        rec = asyncio.run(
            runner.run_one(task, os.environ.get("AB_TOOLSET", "limited_zapier"), tmp, 120, arm="A")
        )
    else:
        sys.path.insert(0, str(HERE.parent / "enterpriseops_gym"))
        import run_cuga_eog as runner

        _env(HERE.parent / "enterpriseops_gym", runner.child_env)
        _patch(path)
        rec = asyncio.run(runner.run_one(task, "A", tmp, 120))
    print("error:", str(rec.get("error"))[:200])
    print("saved:", path if path.exists() else "NOT CAPTURED")


if __name__ == "__main__":
    main()
