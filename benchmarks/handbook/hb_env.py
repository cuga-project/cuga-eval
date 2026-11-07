#!/usr/bin/env python3
"""HANDBOOK.md as the harness uses it: the task container, its MCP tools and each task's own rubric verifier.

HANDBOOK.md ships a Harbor + OpenHands harness that runs the agent inside the task container. CUGA runs on the host instead:
  1. ``start_container`` starts the task container (image ``handbook_task:<task>``, built from the task's environment/Dockerfile
     on ``handbook_base`` = Dockerfile.base here) with the task.toml environment variables, the task's MCP proxy in it
     (``/app/scripts/start.sh --method http --port 8000``, as the harness does) and a TCP forwarder (the proxy binds 127.0.0.1
     only) on a published port;
  2. ``logged_tools`` wraps the MCP tools for the agent and logs every call; ``specs_of`` gives their schemas;
  3. ``grade`` copies the task's tests/ into the container, runs tests/test.sh (the task's sop_verifier.py) and reads
     /tests/results.json: one pass/fail per rubric item.

The sample is downloaded content: files are only read here; the agent's code tools (executeBash, executePython) run inside the
container. Moved unchanged from the old runner (``policy_eval/launchers/archive/run_cuga_handbook.py``).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
SAMPLE = Path(os.environ.get("HANDBOOK_SAMPLE", str(Path.home() / "dev/untrusted/handbook-sample")))
TASKS = SAMPLE / "tasks"
TOOL_LOG_LIMIT = 4000


def image(task: str) -> str:
    return f"handbook_task:{task.lower()[:60]}"


def sh(cmd: List[str], timeout: float = 120, check: bool = True) -> subprocess.CompletedProcess:
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and out.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:4])} failed ({out.returncode}): {out.stderr[-500:]}")
    return out


# ── container ────────────────────────────────────────────────────────────────


def start_container(task: str, name: str) -> int:
    cfg = tomllib.loads((TASKS / task / "task.toml").read_text())
    env = (cfg.get("environment") or {}).get("env") or {}
    sh(["docker", "rm", "-f", name], check=False)
    cmd = ["docker", "run", "-d", "--name", name, "-p", "127.0.0.1::8001"]
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    sh(cmd + [image(task), "sleep", "infinity"])
    sh(["docker", "cp", str(HERE / "tcp_forward.py"), f"{name}:/tmp/tcp_forward.py"])
    sh(
        [
            "docker",
            "exec",
            "-d",
            name,
            "bash",
            "-c",
            "mkdir -p /logs/agent && nohup /app/scripts/start.sh --method http --port 8000 </dev/null >>/logs/agent/mcp-proxy.log 2>&1 &",
        ]
    )
    sh(["docker", "exec", "-d", name, "python3", "/tmp/tcp_forward.py", "8001", "8000"])
    port = int(sh(["docker", "port", name, "8001/tcp"]).stdout.strip().rsplit(":", 1)[1])
    import urllib.request

    for _ in range(90):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    return port
        except Exception:  # noqa: BLE001 - not up yet
            pass
        time.sleep(2)
    raise RuntimeError("MCP proxy did not become healthy in 180 s")


def grade(task: str, name: str) -> Dict[str, Any]:
    sh(["docker", "exec", name, "rm", "-rf", "/tests"], check=False)
    sh(["docker", "cp", str(TASKS / task / "tests"), f"{name}:/tests"])
    run = sh(["docker", "exec", name, "bash", "/tests/test.sh"], timeout=900, check=False)
    got = sh(["docker", "exec", name, "cat", "/tests/results.json"], check=False)
    try:
        res = json.loads(got.stdout)
    except ValueError:
        return {"grader_error": (run.stdout + run.stderr)[-2000:]}
    rubrics = {r["id"]: r for r in json.loads((TASKS / task / "tests/rubrics.json").read_text())}
    items = [
        {
            "id": r["id"],
            "pass": r.get("pass"),
            "text": (rubrics.get(r["id"]) or {}).get("rubric_text", "")[:300],
            "feedback": str(r.get("feedback", ""))[:300],
        }
        for r in res.get("rubric_results") or []
    ]
    return {
        "passed": res.get("passed"),
        "rubrics_passed": res.get("rubrics_passed"),
        "rubrics_total": res.get("rubrics_total"),
        "score": res.get("score"),
        "rubrics": items,
    }


# ── tools ────────────────────────────────────────────────────────────────────


def _trunc(value: Any) -> Any:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= TOOL_LOG_LIMIT else text[:TOOL_LOG_LIMIT] + f"... [{len(text)} chars]"


def input_model(name: str, schema: Any) -> Any:
    """A pydantic input model from an MCP tool's JSON schema (CUGA reads ``args_schema.model_fields``), with the same
    type mapping CUGA's registry provider uses."""
    from typing import Optional

    from pydantic import BaseModel, Field, create_model

    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema
    from cuga.backend.tools_env.registry.utils.schema_utils import python_type_for_schema

    props = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or [])
    fields: Dict[str, Any] = {}
    for pname, ps in props.items():
        typ = python_type_for_schema(ps)
        desc = ps.get("description", "")
        if pname in required:
            fields[pname] = (typ, Field(..., description=desc))
        else:
            default = ps.get("default")
            fields[pname] = (
                Optional[typ],
                Field(default=None if isinstance(default, (list, dict)) else default, description=desc),
            )
    return create_model(f"{name}Input", **fields)


def unwrap(out: Any) -> Any:
    """MCP results come as content blocks; text blocks are joined into the plain text the server sent."""
    if isinstance(out, list) and out and all(isinstance(b, dict) and b.get("type") == "text" for b in out):
        return "\n".join(str(b.get("text", "")) for b in out)
    return out


def logged_tools(tools: List[Any], log: List[Dict[str, Any]]) -> List[Any]:
    from langchain_core.tools import StructuredTool

    def wrap(t: Any) -> Any:
        async def _call(**kwargs: Any) -> Any:
            started = time.monotonic()
            try:
                out = unwrap(await t.ainvoke(kwargs))
            except Exception as exc:  # noqa: BLE001 - a tool error is returned to the agent, as in the other runners
                out = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
            log.append(
                {
                    "tool": t.name,
                    "args": kwargs,
                    "result": _trunc(out),
                    "s": round(time.monotonic() - started, 2),
                }
            )
            return out

        model = input_model(t.name, t.args_schema)

        async def _call_set(
            **kwargs: Any,
        ) -> Any:  # schema defaults are not part of the call (as the hooks wrapper)
            return await _call(**{k: v for k, v in kwargs.items() if v is not None})

        return StructuredTool.from_function(
            coroutine=_call_set, name=t.name, description=t.description or "", args_schema=model
        )

    return [wrap(t) for t in tools]


def specs_of(tools: List[Any]) -> List[Dict[str, Any]]:
    out = []
    for t in tools:
        schema = (
            t.args_schema
            if isinstance(t.args_schema, dict)
            else (t.args_schema.model_json_schema() if t.args_schema else {})
        )
        out.append({"name": t.name, "description": t.description or "", "inputSchema": schema})
    return out
