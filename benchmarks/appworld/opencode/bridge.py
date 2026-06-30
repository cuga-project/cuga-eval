"""In-process MCP bridge that exposes a live AppWorld ``world`` to an external
agent (OpenCode) over streamable HTTP.

Two tool surfaces are supported (selected via ``mode``):

- ``"repl"`` — a single ``execute_python(code)`` tool that routes to
  ``world.execute(code)``. This mirrors the codeact harness: a stateful Python
  REPL where ``apis.<app>.<method>(...)`` are available and variables persist
  across calls.
- ``"apis"`` — one tool per AppWorld API, named ``{app}__{api}``, each routing
  to ``world.execute("apis.{app}.{api}(**arguments)")``. This mirrors the cuga
  agent's discrete API-call surface. Real per-API descriptions/schemas come from
  AppWorld's ``ApiDocCollection`` (the same source AppWorld's own MCP server uses).

Crucially, **every** tool call flows through the SAME ``world`` object the harness
owns, so ``world.evaluate()`` sees the effects regardless of which surface is used.

The MCP server runs on a background daemon thread (uvicorn) so it can serve OpenCode's
tool calls while the harness ``await``s the ``opencode`` subprocess. Only one task runs
at a time, so there is no cross-task concurrency.
"""

from __future__ import annotations

import socket
import threading
import time
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any, Optional

import uvicorn
from loguru import logger

from utils.appworld_utils import completion_called, extract_completion_answer


def _free_port(host: str = "127.0.0.1") -> int:
    """Return an available TCP port on ``host``."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


@dataclass
class BridgeState:
    """Thread-shared record of what the agent did through the bridge.

    Populated from the MCP server thread (under ``_lock``) and read by the harness
    on the main thread after the ``opencode`` subprocess exits.
    """

    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str = ""
    completed: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, name: str, args: dict[str, Any], output: str) -> None:
        with self._lock:
            self.tool_calls.append({"name": name, "args": args, "output": output})

    def mark_complete(self, answer: str = "") -> None:
        with self._lock:
            self.completed = True
            if answer:
                self.final_answer = answer


class AppWorldMcpBridge:
    """Serve a live AppWorld ``world`` to OpenCode as MCP tools.

    Usage::

        bridge = AppWorldMcpBridge(world, mode="repl")
        url = bridge.start()           # http://127.0.0.1:<port>/mcp/
        ...                            # run opencode pointed at `url`
        bridge.stop()
        state = bridge.state           # tool_calls / final_answer / completed
    """

    def __init__(
        self,
        world: Any,
        mode: str = "repl",
        host: str = "127.0.0.1",
        port: Optional[int] = None,
    ) -> None:
        if mode not in ("repl", "apis"):
            raise ValueError(f"Unknown opencode tools mode: {mode!r} (expected 'repl' or 'apis')")
        self.world = world
        self.mode = mode
        self.host = host
        self.port = port or _free_port(host)
        self.state = BridgeState()
        self._exec_lock = threading.Lock()
        self._server: Optional[uvicorn.Server] = None
        self._thread: Optional[threading.Thread] = None
        self._mcp = self._build_server()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/mcp/"

    # ------------------------------------------------------------------ execution
    def _world_execute(self, code: str) -> str:
        """Run ``code`` in the AppWorld REPL. Serialized; errors surface as text."""
        with self._exec_lock:
            try:
                output = self.world.execute("\n" + code + "\n")
            except Exception as exc:  # surface to the agent, don't crash the tool
                logger.warning(f"[OPENCODE-BRIDGE] world.execute error: {exc}")
                return f"Error executing code:\n{exc}"
        return str(output)

    def _execute_python_tool(self, code: str) -> str:
        output = self._world_execute(code)
        self.state.record("execute_python", {"code": code}, output)
        if completion_called(code):
            self.state.mark_complete(extract_completion_answer(code))
        return output

    def _api_tool(self, app: str, api: str, arguments: Optional[dict[str, Any]]) -> str:
        arguments = arguments or {}
        output = self._world_execute(f"apis.{app}.{api}(**{arguments!r})")
        self.state.record(f"{app}__{api}", arguments, output)
        if app == "supervisor" and api == "complete_task":
            answer = arguments.get("answer")
            self.state.mark_complete("" if answer is None else str(answer))
        return output

    # --------------------------------------------------------------------- server
    def _build_server(self) -> Any:
        from fastmcp import FastMCP
        from fastmcp.tools import Tool

        mcp = FastMCP(name="appworld-bridge")

        if self.mode == "repl":

            def execute_python(code: str) -> str:
                """Execute Python in the AppWorld REPL.

                ``apis.<app>.<method>(...)`` are available and variables persist across
                calls. Returns the printed/echoed output. Finish the task by calling
                ``apis.supervisor.complete_task(answer=...)`` (omit ``answer`` if none).
                """
                return self._execute_python_tool(code)

            mcp.add_tool(Tool.from_function(execute_python, name="execute_python", run_in_thread=True))
        else:
            self._register_api_tools(mcp, Tool)

        return mcp

    def _register_api_tools(self, mcp: Any, tool_cls: Any) -> None:
        docs = self._build_api_docs()
        count = 0
        for doc in docs:
            name = doc.get("name", "")
            if "__" not in name:
                continue
            app, api = name.split("__", 1)
            description = self._render_api_description(doc)

            def _make(_app: str, _api: str):
                def _fn(arguments: Optional[dict] = None) -> str:
                    return self._api_tool(_app, _api, arguments)

                return _fn

            mcp.add_tool(
                tool_cls.from_function(
                    _make(app, api), name=name, description=description, run_in_thread=True
                )
            )
            count += 1

        if count == 0:
            logger.warning(
                "[OPENCODE-BRIDGE] No per-API tools could be built; falling back to generic call_api()"
            )

            def call_api(app_name: str, api_name: str, arguments: Optional[dict] = None) -> str:
                """Call an AppWorld API: ``apis.<app_name>.<api_name>(**arguments)``.

                Discover apps/apis and finish with
                ``apis.supervisor.complete_task(answer=...)``.
                """
                return self._api_tool(app_name, api_name, arguments)

            mcp.add_tool(tool_cls.from_function(call_api, name="call_api", run_in_thread=True))
        else:
            logger.info(f"[OPENCODE-BRIDGE] Registered {count} per-API tools (apis mode)")

    def _build_api_docs(self) -> list[dict[str, Any]]:
        app_names = sorted(self.world.task.app_descriptions.keys())
        try:
            from appworld.collections.api_docs import ApiDocCollection  # type: ignore

            return list(ApiDocCollection.build(load_apps=app_names).mcp())
        except Exception as exc:
            logger.warning(
                f"[OPENCODE-BRIDGE] Could not build AppWorld api docs ({exc}); "
                "apis mode will expose a generic call_api() tool instead"
            )
            return []

    @staticmethod
    def _render_api_description(doc: dict[str, Any]) -> str:
        desc = (doc.get("description") or "").strip()
        schema = doc.get("input_schema") or {}
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        if props:
            lines = []
            for pname, pinfo in props.items():
                ptype = pinfo.get("type", "any")
                req = " (required)" if pname in required else ""
                pdesc = (pinfo.get("description") or "").strip()
                lines.append(f"  - {pname}: {ptype}{req} {pdesc}".rstrip())
            desc += "\nParameters (pass as the `arguments` object):\n" + "\n".join(lines)
        desc += "\nCall this tool with `arguments` as a JSON object of the parameters above."
        return desc[:4000]

    # ---------------------------------------------------------------- lifecycle
    def start(self, timeout: float = 20.0) -> str:
        """Start the MCP server on a daemon thread; return the bridge URL."""
        app = self._mcp.http_app(path="/mcp", transport="http")
        config = uvicorn.Config(
            app, host=self.host, port=self.port, log_level="warning", lifespan="on"
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, name="opencode-mcp-bridge", daemon=True
        )
        self._thread.start()

        deadline = time.time() + timeout
        while time.time() < deadline:
            if getattr(self._server, "started", False):
                logger.info(
                    f"[OPENCODE-BRIDGE] MCP bridge ({self.mode}) listening at {self.url}"
                )
                return self.url
            time.sleep(0.05)
        self.stop()
        raise RuntimeError(f"AppWorld MCP bridge failed to start within {timeout}s")

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
        logger.info("[OPENCODE-BRIDGE] MCP bridge stopped")

    def __enter__(self) -> "AppWorldMcpBridge":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()


# Made with Bob
