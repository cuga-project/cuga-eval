"""Recording + scoping tool provider (ported from ``CugaCleanAgent._record_tool``).

Wraps any ToolProviderInterface-shaped provider (CombinedToolProvider,
FilteredToolProvider, DirectLangChainToolsProvider...) so that:

1. every tool call is recorded into a per-task sink in the VAKRA submission
   shape ``{tool_name, arguments, result[:4000]}`` — the evidence the answer
   guards (evidence-gate / support-check / bluff-map) key on;
2. a runaway CodeAct loop is stopped mid-run with an observable tool error at
   ``tool_cap`` calls (the model reads it and answers from data already
   retrieved — different, deliberately, from CUGA's terminal per-run cap);
3. a mutable ``scope`` predicate filters retriever/non-retriever tools for the
   cap4 policy scoping.

CUGA re-fetches tools from the provider at every invoke (prepare node), so
mutating ``scope`` or swapping ``base_provider`` takes effect on the next
invoke without rebuilding the agent.

The wrapper has to be invisible to CUGA apart from the recording, so three
fidelity rules are enforced here:

* The sandbox calls ``tool.coroutine`` with whatever the generated code wrote —
  positionally, as one dict, or as kwargs — and provider tools normalize that
  through ``resolve_tool_call_args`` (cuga ``tracking/arguments``).
  ``merge_call_args`` mirrors it, so a wrapped tool accepts exactly what the
  raw tool accepts.
* Prompt rendering reads ``_response_schemas`` / ``_param_constraints`` off
  ``tool.func`` and ToolGuard copies its metadata from there too, so the wrapper
  keeps a sync ``func`` shim and re-attaches those attributes to both entry
  points instead of nulling ``func``.
* Wrapped tools are memoized per raw tool object. ToolGuard caches its own
  wrappers by ``id(raw_tool)``; handing it a fresh object per fetch would defeat
  that cache and grow it on every invoke.
"""

from __future__ import annotations

import asyncio
import functools
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.tools import StructuredTool

from benchmarks.m3.adapter.scope import is_retriever

#: Function-level attributes CUGA hangs on ``tool.func`` / ``tool.coroutine`` and
#: reads back: prompt rendering (``_response_schemas``, ``_param_constraints``),
#: tracking (``_app_name``, ``_operation_id``) and record de-duplication
#: (``_cuga_tracked`` — set by ``@tracked_tool``; without it CUGA adds a second
#: recording layer around direct tools).
METADATA_ATTRS = ("_app_name", "_operation_id", "_param_constraints", "_response_schemas", "_cuga_tracked")

RESULT_MAX_CHARS = 4000


def param_names_of(tool: Any) -> List[str]:
    """Schema parameter names in declaration order (empty when the tool has no schema)."""
    schema = getattr(tool, "args_schema", None)
    if schema is None:
        return []
    model_fields = getattr(schema, "model_fields", None)
    if isinstance(model_fields, dict):
        return list(model_fields.keys())
    if isinstance(schema, dict):
        return list((schema.get("properties") or {}).keys())
    try:
        return list(tool.args.keys())
    except Exception:  # noqa: BLE001  (exotic schema objects: treat as schema-less)
        return []


def merge_call_args(args: tuple, kwargs: Dict[str, Any], param_names: List[str]) -> Dict[str, Any]:
    """Positional/keyword merge identical to cuga's ``merge_tool_call_args``.

    A single positional dict whose keys are all parameter names is a kwargs bag;
    one with no known key is a nested payload for the first parameter; extra
    positionals become ``arg<i>`` (which the raw tool then rejects exactly as it
    would have without the wrapper).
    """
    merged: Dict[str, Any] = {}
    if len(args) == 1 and isinstance(args[0], dict):
        payload: Dict[str, Any] = args[0]
        if not param_names:
            merged.update(payload)
        else:
            known = set(param_names)
            picked = {k: v for k, v in payload.items() if k in known}
            if picked:
                merged.update(picked)
            elif payload:
                merged[param_names[0]] = payload
    else:
        for i, value in enumerate(args):
            merged[param_names[i] if i < len(param_names) else f"arg{i}"] = value
    merged.update(kwargs)
    return merged


def _copy_metadata(tool: Any, *targets: Any) -> None:
    """Re-attach CUGA's function-level metadata (func first, then coroutine, then the tool)."""
    sources = [getattr(tool, "func", None), getattr(tool, "coroutine", None), tool]
    for attr in METADATA_ATTRS:
        for src in sources:
            if src is not None and hasattr(src, attr):
                value = getattr(src, attr)
                for target in targets:
                    setattr(target, attr, value)
                break


class RecordingScopedToolProvider:
    """ToolProviderInterface wrapper: record calls, cap runaways, apply scope."""

    def __init__(self, base_provider: Any, tool_cap: Optional[int] = None):
        self._wrapped: Dict[str, Tuple[Any, StructuredTool]] = {}  # name -> (raw tool, wrapper)
        self._base_provider = base_provider
        self.tool_cap = tool_cap
        self.recorded_calls: List[dict] = []  # cleared by the agent wrapper per task
        self.scope: str = "all"  # set by the agent wrapper per invoke

    @property
    def base_provider(self) -> Any:
        return self._base_provider

    @base_provider.setter
    def base_provider(self, provider: Any) -> None:
        # A new provider means new raw tools (cap1 re-list): drop the memo so no
        # wrapper keeps calling into the previous toolset.
        self._base_provider = provider
        self._wrapped.clear()

    async def initialize(self) -> None:
        base = self._base_provider
        if hasattr(base, "initialized") and not base.initialized:
            await base.initialize()
        elif not hasattr(base, "initialized"):
            init = getattr(base, "initialize", None)
            if init is not None:
                await init()

    async def get_apps(self):
        return await self._base_provider.get_apps()

    async def get_tools(self, app_name: str):
        return self._apply(await self._base_provider.get_tools(app_name))

    async def get_all_tools(self):
        return self._apply(await self._base_provider.get_all_tools())

    # ------------------------------------------------------------------

    def _apply(self, tools: List[StructuredTool]) -> List[StructuredTool]:
        if self.scope == "retriever_only":
            tools = [t for t in tools if is_retriever(t.name)]
        elif self.scope == "no_retriever":
            tools = [t for t in tools if not is_retriever(t.name)]
        return [self._wrap_cached(t) for t in tools]

    def _wrap_cached(self, tool: StructuredTool) -> StructuredTool:
        """Stable wrapper identity per raw tool object; re-wrap only when the provider hands out a new one."""
        entry = self._wrapped.get(tool.name)
        if entry is not None and entry[0] is tool:
            return entry[1]
        wrapped = self._record(tool)
        self._wrapped[tool.name] = (tool, wrapped)
        return wrapped

    def _record(self, tool: StructuredTool) -> StructuredTool:
        """Wrap a tool so each call is appended to ``recorded_calls``."""
        inner_coro = getattr(tool, "coroutine", None)
        inner_func = getattr(tool, "func", None)
        if inner_coro is None and inner_func is None:  # BaseTool subclass exposing only _run/_arun

            async def inner_coro(**kwargs):
                return await tool.ainvoke(kwargs)

        param_names = param_names_of(tool)
        sink = self.recorded_calls
        cap = self.tool_cap
        name = tool.name

        async def recording_coro(*args, **kwargs):
            if cap is not None and len(sink) >= cap:
                raise RuntimeError(
                    f"Tool-call cap reached ({cap}); stop looping and answer from data already retrieved."
                )
            call_kwargs = merge_call_args(args, kwargs, param_names)
            record = {"tool_name": name, "arguments": dict(call_kwargs), "result": ""}
            sink.append(record)
            try:
                if inner_coro is not None:
                    result = await inner_coro(**call_kwargs)
                else:  # sync-only tool: off the event loop, like CUGA's make_tool_awaitable
                    loop = asyncio.get_running_loop()
                    result = await loop.run_in_executor(None, functools.partial(inner_func, **call_kwargs))
                record["result"] = str(result)[:RESULT_MAX_CHARS]
                return result
            except Exception as exc:
                record["result"] = f"Error: {exc}"
                raise

        def recording_func(*args, **kwargs):
            # Sync entry point (same contract as cuga's provider tools): usable
            # outside an event loop, refuses to block a running one. CUGA's
            # sandbox never calls it — it prefers .coroutine — but prompt
            # rendering and ToolGuard read metadata off `tool.func`.
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(recording_coro(*args, **kwargs))
            raise RuntimeError(
                f"Tool '{name}' was invoked synchronously while an event loop is running; use ainvoke()."
            )

        for fn in (recording_coro, recording_func):
            fn.__name__ = name
            fn.__doc__ = tool.description
        _copy_metadata(tool, recording_coro, recording_func)

        # model_copy keeps metadata/response_format/return_direct (and any
        # attributes set on the tool object itself) intact.
        return tool.model_copy(update={"coroutine": recording_coro, "func": recording_func})
