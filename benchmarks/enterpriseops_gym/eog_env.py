"""EnterpriseOps-Gym task environment for CUGA: seed the task database, expose the task's MCP tools as
LangChain tools, and grade with the benchmark's own VerifierEngine.

The gym's MCP client, database helpers and verifier are imported from the vendored repo
(vendor/EnterpriseOps-Gym), so the protocol and grading are the benchmark's code, not ours.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

HERE = Path(__file__).resolve().parent
VENDOR = HERE / "vendor" / "EnterpriseOps-Gym"
sys.path.insert(0, str(VENDOR))

from benchmark.mcp_client import MCPClient, create_database_from_file, delete_database  # noqa: E402
from benchmark.models import VerifierConfig  # noqa: E402
from benchmark.verifier import VerifierEngine  # noqa: E402

TASKS = HERE / "tasks" / "itsm_oracle.json"
JSON_TYPES = {"string": str, "integer": int, "number": float, "boolean": bool, "array": list, "object": dict}


def _j(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def load_task(task_id: str) -> dict:
    """The task from any domain file (tasks/<domain>_oracle.json); IT service first, as before."""
    files = [TASKS] + sorted(p for p in (HERE / "tasks").glob("*_oracle.json") if p != TASKS)
    for task in (t for f in files for t in json.loads(f.read_text())):
        if task["task_id"] == task_id:
            for key in ("gym_servers_config", "verifiers"):
                task[key] = _j(task[key])
            return task
    raise KeyError(task_id)


def _content(result: Dict[str, Any]) -> Any:
    """MCP tools/call result → the value the model sees (JSON when the text is JSON)."""
    if not result.get("success"):
        return {"error": result.get("error")}
    if result.get("error"):
        return {"error": result["error"]}
    body = result.get("result") or {}
    texts = [
        c.get("text", "") for c in body.get("content", []) if isinstance(c, dict) and c.get("type") == "text"
    ]
    out: Any = "\n".join(texts) if texts else body
    if isinstance(out, str):
        try:
            out = json.loads(out)
        except ValueError:
            pass
    if body.get("isError"):
        return {"error": out}
    return out


class EOGTask:
    """One task run: its own database copy on the gym server, an MCP session, and the verifiers."""

    def __init__(self, task: dict, sink: Optional[Callable[[dict], None]] = None):
        self.task = task
        cfg = task["gym_servers_config"][0]
        self.gym_name = cfg["mcp_server_name"]
        self.url = os.environ.get(f"EOG_{(task.get('domain') or 'itsm').upper()}_URL", cfg["mcp_server_url"]).rstrip("/")
        self.seed_file = VENDOR / cfg["seed_database_file"]
        self.context = cfg.get("context") or {}
        self.user_info = cfg.get("user_info") or {}
        self.sink = sink
        self.database_id: Optional[str] = None
        self.client: Optional[MCPClient] = None
        self.specs: List[dict] = []

    async def start(self) -> None:
        self.database_id = create_database_from_file(self.url, str(self.seed_file))
        self.client = MCPClient(
            self.url,
            mcp_endpoint=self.task.get("mcp_endpoint") or "/mcp",
            database_id=self.database_id,
            context=self.context,
        )
        if not await self.client.connect():
            raise RuntimeError(f"MCP connect failed: {self.url}")
        tools = await self.client.list_tools()
        wanted = set(self.task.get("selected_tools") or [t["name"] for t in tools])
        blocked = set(self.task.get("restricted_tools") or [])
        self.specs = [t for t in tools if t["name"] in wanted and t["name"] not in blocked]
        missing = wanted - {t["name"] for t in self.specs} - blocked
        if missing:
            raise RuntimeError(f"tools missing on server: {sorted(missing)}")

    async def call(self, name: str, args: Dict[str, Any]) -> Any:
        started = time.time()
        clean = {k: v for k, v in args.items() if v is not None}
        result = _content(
            await self.client.call_tool(name, clean, database_id=self.database_id, context=self.context)
        )
        if self.sink:
            self.sink(
                {
                    "tool": name,
                    "args": clean,
                    "result": result,
                    "error": isinstance(result, dict) and "error" in result,
                    "ms": int((time.time() - started) * 1000),
                }
            )
        return result

    def _caller(self, name: str, order: List[str]):
        """CUGA calls ``tool.func`` (= the coroutine) directly, so positional arguments arrive here unvalidated.
        Map them to the schema fields in the order the prompt's signature shows; the tool name stays in the closure
        (it was a default argument, and a positional value replaced it: 7 calls went to tools named 'USER_003' etc.)."""

        async def _call(*args, **kwargs):
            if len(args) > len(order):
                return {
                    "error": f"{name}() takes at most {len(order)} positional arguments ({len(args)} given)"
                }
            return await self.call(name, {**dict(zip(order, args)), **kwargs})

        return _call

    def app_name(self) -> str:
        """The app name shown to the agent: the MCP server name without the gym-/-mcp affixes (gym-itsm-mcp -> itsm)."""
        name = self.gym_name
        for affix in ("gym-", "-mcp"):
            name = name.replace(affix, "")
        return name or self.gym_name

    def langchain_tools(self) -> list:
        from langchain_core.tools import StructuredTool
        from pydantic import Field, create_model

        tools = []
        for spec in self.specs:
            schema = spec.get("inputSchema") or {}
            required = set(schema.get("required") or [])
            fields = {}
            for pname, prop in (schema.get("properties") or {}).items():
                kind = prop.get("type")
                if isinstance(kind, list):  # e.g. ["string", "null"]
                    kind = next((k for k in kind if k != "null"), None)
                if kind is None and prop.get("anyOf"):
                    kind = next(
                        (a.get("type") for a in prop["anyOf"] if a.get("type") not in (None, "null")), None
                    )
                py = JSON_TYPES.get(kind, Any)
                desc = prop.get("description", "")
                if prop.get("enum"):
                    desc = f"{desc} Allowed values: {', '.join(map(str, prop['enum']))}.".strip()
                if pname in required:
                    fields[pname] = (py, Field(..., description=desc))
                else:
                    fields[pname] = (Optional[py], Field(None, description=desc))
            model = create_model(f"{spec['name']}_args", **fields)

            tools.append(
                StructuredTool.from_function(
                    coroutine=self._caller(spec["name"], list(fields)),
                    name=spec["name"],
                    description=spec.get("description") or spec["name"],
                    args_schema=model,
                )
            )
        return tools

    async def grade(self) -> Dict[str, Any]:
        engine = VerifierEngine({self.gym_name: self.client}, llm_client=None)
        rows = []
        for v in self.task["verifiers"]:
            res = await engine.execute_verifier(
                VerifierConfig(**v), {}, self.database_id, self.context, v.get("gym_name") or self.gym_name
            )
            rows.append(
                {
                    "name": v.get("name"),
                    "passed": bool(res.get("passed")),
                    "expected": res.get("expected"),
                    "actual": res.get("actual"),
                    "error": res.get("error"),
                }
            )
        return {
            "passed": all(r["passed"] for r in rows),
            "verifiers_passed": sum(r["passed"] for r in rows),
            "verifiers_total": len(rows),
            "verifiers": rows,
        }

    def close(self) -> None:
        if self.database_id:
            delete_database(self.url, self.database_id)
