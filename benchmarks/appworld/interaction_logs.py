"""Write CUGA ToolCallTracker records into AppWorld leaderboard log files.

CUGA lite calls AppWorld APIs through the registry (HTTP to port 9111), so
``world.execute`` never sees them and ``environment_io.md`` / ``api_calls.jsonl``
would only contain ``complete_task``. After invoke we already have the real
calls on ``invoke_result.tool_calls`` (ToolCallTracker). This module copies
those records into the AppWorld log files **without re-executing** the APIs.

The ``complete_task`` interaction that the harness already logged via
``world.execute`` is kept as the last interaction.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from loguru import logger

from benchmarks.appworld.leaderboard import APP_NAMES

HORIZONTAL = "----------------------------------------------------------------------------"
_APP_SET = frozenset(APP_NAMES)
_HEADER_RE = re.compile(r"^### Environment Interaction (\d+(?:\.\d+)?)", re.MULTILINE)
_BLOCK_RE = re.compile(r"```python\n(.*?)\n```\n\n```\n(.*?)\n```", re.DOTALL)
# Zero-width space so a tracker payload that contains fences cannot break
# AppWorld's non-greedy parse_environment_io_log.
_ZWSP = "\u200b"
_FENCE = "```"
_FENCE_SAFE = "``" + _ZWSP + "`"
# AppWorld's _parse_environment_io_log also ends a block on a bare horizontal rule
# (`line.strip() == SINGLE_HORIZONTAL_RULE`) and starts one on a
# `#+ (Execution|Environment Interaction) N` header matched at column 0. A string
# tool result or error containing either verbatim would make the packed bundle
# unparseable for the leaderboard maintainers, and mis-split our own re-merge.
# Prefixing such a line with a zero-width space breaks both matches and reads the
# same; ZWSP is not whitespace to str.strip(), so the rule comparison misses too.
_UNSAFE_LINE_RE = re.compile(
    rf"^(?=[ \t]*-{{{len(HORIZONTAL)}}}[ \t]*$|#+ (?:Execution|Environment Interaction) \d)",
    re.MULTILINE,
)


def _as_dict(tc: Any) -> dict[str, Any]:
    if isinstance(tc, Mapping):
        return dict(tc)
    if hasattr(tc, "model_dump"):
        return dict(tc.model_dump())
    return {
        "name": getattr(tc, "name", ""),
        "arguments": getattr(tc, "arguments", getattr(tc, "args", {})) or {},
        "result": getattr(tc, "result", None),
        "error": getattr(tc, "error", None),
        "app_name": getattr(tc, "app_name", None),
        "operation_id": getattr(tc, "operation_id", None),
    }


def _app_name(record: Mapping[str, Any]) -> str | None:
    app = record.get("app_name")
    if isinstance(app, str) and app in _APP_SET:
        return app
    name = str(record.get("name") or "")
    if "__" in name:
        prefix = name.split("__", 1)[0]
        if prefix in _APP_SET:
            return prefix
    return None


def _is_supervisor_complete_task(
    app: str | None,
    name: str,
    operation_id: str | None,
    resolved_api: str | None = None,
) -> bool:
    """True for supervisor.complete_task, including OpenAPI ids like complete_task_message_post."""
    if app != "supervisor":
        return False
    if resolved_api == "complete_task":
        return True
    for cand in (name, operation_id or ""):
        if cand in {"complete_task", "supervisor__complete_task"}:
            return True
        if cand.startswith("complete_task_") or cand.startswith("supervisor__complete_task"):
            return True
    return False


def is_appworld_api_call(record: Mapping[str, Any]) -> bool:
    """True for registry calls against an AppWorld app, not CUGA-internal tools."""
    app = _app_name(record)
    if app is None:
        return False
    # AppWorld's RequestTracker also drops admin.com — it is not user-facing.
    if app == "admin":
        return False
    name = str(record.get("name") or "")
    op = str(record.get("operation_id") or "")
    # supervisor.complete_task is already written by the harness via world.execute.
    if _is_supervisor_complete_task(app, name, op):
        return False
    return True


def resolve_api_name(
    app_name: str,
    tool_name: str,
    operation_id: str | None,
    *,
    docs: Sequence[Mapping[str, Any]],
) -> str | None:
    """Map a CUGA tool name / OpenAPI operationId onto AppWorld's ``api_name``."""
    by_name = {str(d["api_name"]): d for d in docs if "api_name" in d}
    for cand in (tool_name, operation_id or ""):
        if cand in by_name:
            return cand
    stripped = ""
    if tool_name.startswith(f"{app_name}__"):
        stripped = tool_name[len(app_name) + 2 :]
        if stripped in by_name or not docs:
            return stripped
    if docs:
        # The prefix-stripped name is tried here too: a record with no
        # operation_id (the sandbox `call_api` helper defaults it to None) whose
        # tool name is "<app>__<api>_<suffix>" otherwise resolved to nothing and
        # its API call vanished from the submission logs.
        for cand in (tool_name, stripped, operation_id):
            if not cand:
                continue
            matches = [
                d["api_name"] for d in docs if cand == d["api_name"] or cand.startswith(f"{d['api_name']}_")
            ]
            if matches:
                return max(matches, key=len)
    elif tool_name:
        return tool_name
    return None


def load_app_docs(app_name: str) -> list[dict[str, Any]]:
    from appworld.api_docs import prepare_api_docs

    # Requester uses include_private_apis=True; only admin has private APIs and
    # those are already filtered out by is_appworld_api_call.
    return list(prepare_api_docs(app_name, include_private_apis=True))


def format_python_call(app_name: str, api_name: str, arguments: Mapping[str, Any] | None) -> str:
    args = arguments or {}
    kwargs = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return f"print(apis.{app_name}.{api_name}({kwargs}))"


def _safe_fence_body(text: str) -> str:
    return _UNSAFE_LINE_RE.sub(_ZWSP, text.replace(_FENCE, _FENCE_SAFE))


def format_output(record: Mapping[str, Any]) -> str:
    if record.get("error"):
        raw = str(record["error"])
    else:
        result = record.get("result")
        if result is None:
            raw = ""
        elif isinstance(result, (dict, list)):
            raw = json.dumps(result, indent=2, default=str)
        else:
            raw = str(result)
    return _safe_fence_body(raw)


def request_from_doc(
    doc: Mapping[str, Any],
    arguments: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build one ``api_calls.jsonl`` record the way AppWorld's RequestTracker does."""
    data = dict(arguments or {})
    path = str(doc["path"])
    for field_name in list(data):
        token = "{" + field_name + "}"
        if token in path:
            path = path.replace(token, str(data.pop(field_name)))
    return {
        "method": str(doc["method"]).lower(),
        "url": path,
        "data": data,
    }


def environment_io_block(number: int, python: str, output: str) -> str:
    return (
        f"\n### Environment Interaction {number}\n{HORIZONTAL}\n"
        f"```python\n{_safe_fence_body(python)}\n```\n\n"
        f"```\n{_safe_fence_body(output)}\n```\n\n"
    )


def parse_existing_blocks(text: str) -> list[tuple[str, str]]:
    """Return (python, output) pairs from an existing environment_io.md."""
    if not text.strip():
        return []
    parts = _HEADER_RE.split(text)
    # split keeps the number groups; entries are [preamble, num, body, num, body, ...]
    blocks: list[tuple[str, str]] = []
    bodies = parts[2::2] if len(parts) > 2 else []
    for body in bodies:
        m = _BLOCK_RE.search(body)
        if m:
            blocks.append((m.group(1), m.group(2)))
    n_headers = len(_HEADER_RE.findall(text))
    if n_headers != len(blocks):
        # Rewriting would drop the unparseable blocks, silently deleting real
        # interactions from a submission. Refuse instead: the caller logs and
        # leaves the original file untouched, and `validate` still flags the task.
        raise ValueError(
            f"environment_io.md: parsed {len(blocks)} blocks from {n_headers} headers; "
            "refusing to rewrite because that would drop the unparseable ones"
        )
    return blocks


def records_to_interactions(
    tool_calls: Sequence[Any],
    *,
    docs_for_app: Callable[[str], Sequence[Mapping[str, Any]]] | None = None,
) -> tuple[list[tuple[str, str]], list[dict[str, Any]], list[str]]:
    """Turn tracker records into (python, output) pairs and api_calls.jsonl rows.

    The third item is labels for AppWorld calls that could not be mapped to an
    ``api_name`` (intentionally skipped ``complete_task`` is not listed).
    """
    raw_get_docs = docs_for_app or load_app_docs
    docs_cache: dict[str, list[Mapping[str, Any]]] = {}

    def get_docs(app: str) -> list[Mapping[str, Any]]:
        if app not in docs_cache:
            docs_cache[app] = list(raw_get_docs(app))
        return docs_cache[app]

    interactions: list[tuple[str, str]] = []
    api_calls: list[dict[str, Any]] = []
    skipped: list[str] = []
    for raw in tool_calls:
        rec = _as_dict(raw)
        if not is_appworld_api_call(rec):
            continue
        app = _app_name(rec)
        if app is None:
            continue
        name = str(rec.get("name") or "")
        op = rec.get("operation_id")
        docs = get_docs(app)
        api = resolve_api_name(app, name, op, docs=docs)
        if _is_supervisor_complete_task(app, name, op, resolved_api=api):
            continue
        if not api:
            skipped.append(f"{app}.{name or op or '?'}")
            continue
        arguments = rec.get("arguments") or rec.get("args") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        if not isinstance(arguments, Mapping):
            arguments = {}
        interactions.append((format_python_call(app, api, arguments), format_output(rec)))
        by_name = {str(d["api_name"]): d for d in docs}
        doc = by_name.get(api)
        if doc is not None and "path" in doc and "method" in doc:
            api_calls.append(request_from_doc(doc, arguments))
    return interactions, api_calls, skipped


def merge_tracker_into_appworld_logs(
    logs_dir: str | Path,
    tool_calls: Sequence[Any],
    *,
    docs_for_app: Callable[[str], Sequence[Mapping[str, Any]]] | None = None,
) -> int:
    """Rewrite ``environment_io.md`` and ``api_calls.jsonl`` with tracker calls first.

    Returns the number of AppWorld API interactions written from the tracker.
    Existing ``complete_task`` (and any other) blocks are kept at the end.
    """
    logs = Path(logs_dir)
    logs.mkdir(parents=True, exist_ok=True)
    env_path = logs / "environment_io.md"
    api_path = logs / "api_calls.jsonl"

    new_io, new_api, skipped = records_to_interactions(tool_calls, docs_for_app=docs_for_app)
    if skipped:
        logger.warning(
            f"could not map AppWorld tool names to api_name ({len(skipped)}): {', '.join(skipped)}"
        )
    if not new_io:
        return 0

    existing_io = parse_existing_blocks(env_path.read_text() if env_path.is_file() else "")
    existing_api: list[dict[str, Any]] = []
    if api_path.is_file():
        for line in api_path.read_text().splitlines():
            line = line.strip()
            if line:
                existing_api.append(json.loads(line))

    all_io = new_io + existing_io
    body = "".join(
        environment_io_block(i, python, output) for i, (python, output) in enumerate(all_io, start=1)
    )
    env_path.write_text(body)
    rows = new_api + existing_api
    api_path.write_text("".join(json.dumps(row, default=str) + "\n" for row in rows))
    return len(new_io)
