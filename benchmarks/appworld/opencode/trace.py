"""Shape the bridge's recorded tool calls for the OpenCode Langfuse trace output.

The MCP bridge records each call as ``{"name", "args", "output"}`` where ``args`` holds the
generated code (``{"code": ...}`` in repl mode) or the API call (``{"app", "api", "arguments"}``
in apis mode). The Langfuse trace must surface that code — not just the tool name — so the run is
inspectable in Langfuse. This is a pure transform (no I/O) so it is trivially testable.
"""

from __future__ import annotations

from typing import Any, Optional

_DEFAULT_OUTPUT_LIMIT = 2000


def summarize_tool_calls_for_trace(
    tool_calls: list[dict[str, Any]], output_limit: int = _DEFAULT_OUTPUT_LIMIT
) -> list[dict[str, Any]]:
    """Return one entry per call carrying the tool name, the generated code, full args, and a
    truncated output preview — the shape rendered in the Langfuse trace output.

    ``code`` is the repl-mode convenience field (``args["code"]``); it is ``None`` in apis mode,
    where the full ``args`` (app/api/arguments) carries the equivalent information.
    """
    summarized: list[dict[str, Any]] = []
    for call in tool_calls:
        args = call.get("args") or {}
        code: Optional[str] = args.get("code") if isinstance(args, dict) else None
        output = call.get("output") or ""
        summarized.append(
            {
                "name": call.get("name"),
                "code": code,
                "args": args,
                "output": output[:output_limit],
            }
        )
    return summarized
