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
   cap4 policy scoping;
4. a call the benchmark's tool server timed out on (its 30 s limit on a cold
   database) is retried before the agent sees the error.

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

import ast
import asyncio
import functools
import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from langchain_core.tools import StructuredTool
from loguru import logger

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


def bare_tool_name(tool: Any) -> str:
    """The tool's MCP name: the registry's ``<app>_<tool>`` minus the stamped ``_app_name`` prefix.

    The registry provider stamps ``_app_name`` on the tool or its entry points (in the m3
    eval the app is the domain). Tools without it — direct MCP tools, as cap1 binds them —
    already carry their bare name and are returned unchanged.
    """
    name = getattr(tool, "name", "") or ""
    for target in (tool, getattr(tool, "func", None), getattr(tool, "coroutine", None)):
        app = getattr(target, "_app_name", None) if target is not None else None
        if app:
            prefix = f"{app}_"
            return name[len(prefix) :] if name.startswith(prefix) and len(name) > len(prefix) else name
    return name


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


#: Appended to a call's result when it returned no rows (``AdapterConfig.empty_result_hint``).
EMPTY_RESULT_HINT = (
    "NOTE: this call returned no rows. If the question implies there should be results, the argument "
    "values probably do not match how the database stores them: a code or abbreviation instead of the "
    "full word (or the reverse), a fraction instead of a percentage, the exact stored spelling of a name, "
    "or an SQL LIKE pattern for partial matches. Call the tool again with the values in the stored format."
)


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_empty_value(v) for v in value)  # [] , [[]], [[None]]
    if isinstance(value, dict):
        return all(_is_empty_value(v) for v in value.values())
    return False


def is_empty_result(result: Any) -> bool:
    """No rows: None, an empty container, or containers of nothing (``[[]]``, ``[[null]]``). A 0 is a value."""
    if isinstance(result, str):
        text = result.strip()
        if text in ("", "None"):
            return True
        try:
            result = json.loads(text)
        except ValueError:
            return False
    return _is_empty_value(result)


def looks_like_error(result: Any) -> bool:
    """A tool that reports a failure in its result instead of raising: ``Error: ...`` / ``{"error": ...}``."""
    if isinstance(result, dict):
        return "error" in result and len(result) <= 2
    if isinstance(result, str):
        head = result.lstrip()[:40].lower()
        return head.startswith(("error", '{"error"', "{'error'"))
    return False


#: Retries for a call the tool server timed out on. The VAKRA servers give up on an API after 30 s
#: and answer ``Error calling API: `` (httpx's ReadTimeout has no message); the slow APIs are slow
#: only while their database is cold, and the server keeps the query running, so a repeat answers
#: (a movie_platform lookup: >30 s cold, then 19 s, then 1.3 s).
API_TIMEOUT_RETRIES = 2


def is_api_timeout(result: Any) -> bool:
    """The tool server's timeout reply: ``Error calling API:`` with no message, or one saying it timed out."""
    if not isinstance(result, str):
        return False
    head, sep, rest = result.strip().partition("Error calling API:")
    if head or not sep:
        return False
    rest = rest.strip().lower()
    return not rest or "timed out" in rest or "timeout" in rest


def _all_zero(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, (list, tuple)):
        return bool(value) and all(_all_zero(v) or v is None for v in value)
    if isinstance(value, dict):
        return bool(value) and all(_all_zero(v) or v is None for v in value.values())
    return False


def is_empty_or_zero(result: Any) -> bool:
    """No rows, or rows of nothing but zeros (``{"count": 0}``, ``[[0]]``): a filter that matched nothing."""
    if is_empty_result(result):
        return True
    if isinstance(result, str):
        try:
            result = json.loads(result.strip())
        except ValueError:
            try:
                result = ast.literal_eval(result.strip())
            except (ValueError, SyntaxError):
                return False
    return _all_zero(result)


#: cap1 data tools that take ``distinct``; the train ground truth keeps duplicates in ~94% of their calls.
_DISTINCT_TOOLS = re.compile(r"retrieve_data|aggregate_data|compute_data_\w+")


def without_distinct(name: str, call_kwargs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """``call_kwargs`` with ``distinct`` set to False for a cap1 data tool, or None when nothing changes."""
    if not _DISTINCT_TOOLS.fullmatch(name.rsplit("__", 1)[-1]) or "distinct" not in call_kwargs:
        return None
    if call_kwargs["distinct"] in (False, None) or str(call_kwargs["distinct"]).lower() == "false":
        return None
    return dict(call_kwargs, distinct=False)


def lowercased_args(call_kwargs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The arguments with every text value lowercased; None when nothing would change."""
    lowered = {k: v.lower() if isinstance(v, str) else v for k, v in call_kwargs.items()}
    return lowered if lowered != call_kwargs else None


def with_empty_result_hint(result: Any, examples: Optional[Dict[str, List[str]]] = None) -> str:
    """The raw result, the hint, and (when known) values other questions passed for these parameters."""
    text = result if isinstance(result, str) else json.dumps(result, default=str)
    hint = EMPTY_RESULT_HINT
    if examples:
        listed = "; ".join(
            f"{p}: " + ", ".join(repr(v) for v in vals) for p, vals in examples.items() if vals
        )
        if listed:
            hint += f" Values other questions on this database passed for these parameters: {listed}."
    return f"{text}\n\n{hint}"


class RecordingScopedToolProvider:
    """ToolProviderInterface wrapper: record calls, cap runaways, apply scope."""

    def __init__(
        self,
        base_provider: Any,
        tool_cap: Optional[int] = None,
        bare_names: bool = False,
        empty_result_hint: bool = False,
        hint_non_string_results: bool = False,
    ):
        # name -> (raw tool, exposed name, wrapper)
        self._wrapped: Dict[str, Tuple[Any, str, StructuredTool]] = {}
        self._base_provider = base_provider
        self.tool_cap = tool_cap
        self.bare_names = bare_names  # expose registry tools under their MCP names (the campaign's)
        # The agent sees EMPTY_RESULT_HINT after a no-rows result (the record keeps the raw result).
        # Non-string results are only rewritten as text when the caller says that is safe (native
        # function calling serializes every result to message text; CodeAct code may iterate it).
        self.empty_result_hint = empty_result_hint
        self.hint_non_string_results = hint_non_string_results
        # Per task (set by the agent wrapper): parameter names -> example values for the hint.
        self.value_examples: Optional[Callable[[List[str]], Dict[str, List[str]]]] = None
        # Per user turn (set by the agent wrapper): raw tool names the agent may see; None = all.
        self.allowed: Optional[set] = None
        # Per task (set by the agent wrapper): called when a call returns no rows or fails.
        self.on_failure: Optional[Callable[[], None]] = None
        self.api_timeout_retries = API_TIMEOUT_RETRIES
        self.lowercase_retry = False  # retry an empty/zero call once with lowercased text arguments
        self.force_distinct_false = (
            False  # cap1 data tools: keep duplicate rows (the ground truth's convention)
        )
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
        if self.allowed is not None:  # the per-turn prefilter, applied before the policy scope
            tools = [t for t in tools if t.name in self.allowed]
        if self.scope == "retriever_only":
            tools = [t for t in tools if is_retriever(t.name)]
        elif self.scope == "no_retriever":
            tools = [t for t in tools if not is_retriever(t.name)]
        exposed = [t.name for t in tools]
        if self.bare_names:
            bare = [bare_tool_name(t) for t in tools]
            # two registry tools that share a bare name keep their registry names
            exposed = [b if bare.count(b) == 1 else t.name for b, t in zip(bare, tools)]
        return [self._wrap_cached(t, name) for t, name in zip(tools, exposed)]

    def _wrap_cached(self, tool: StructuredTool, exposed: Optional[str] = None) -> StructuredTool:
        """Stable wrapper identity per raw tool object; re-wrap only when the provider hands out a new one."""
        exposed = exposed or tool.name
        entry = self._wrapped.get(tool.name)
        if entry is not None and entry[0] is tool and entry[1] == exposed:
            return entry[2]
        wrapped = self._record(tool, exposed)
        self._wrapped[tool.name] = (tool, exposed, wrapped)
        return wrapped

    def _record(self, tool: StructuredTool, exposed: Optional[str] = None) -> StructuredTool:
        """Wrap a tool so each call is appended to ``recorded_calls`` (bound as ``exposed``)."""
        inner_coro = getattr(tool, "coroutine", None)
        inner_func = getattr(tool, "func", None)
        if inner_coro is None and inner_func is None:  # BaseTool subclass exposing only _run/_arun

            async def inner_coro(**kwargs):
                return await tool.ainvoke(kwargs)

        param_names = param_names_of(tool)
        sink = self.recorded_calls
        cap = self.tool_cap
        name = exposed or tool.name
        hint_empty = self.empty_result_hint
        hint_any_type = self.hint_non_string_results
        provider = self

        async def call_inner(call_kwargs: Dict[str, Any]) -> Any:
            retries = provider.api_timeout_retries
            for attempt in range(retries + 1):
                try:
                    if inner_coro is not None:
                        result = await inner_coro(**call_kwargs)
                    else:  # sync-only tool: off the event loop, like CUGA's make_tool_awaitable
                        loop = asyncio.get_running_loop()
                        result = await loop.run_in_executor(
                            None, functools.partial(inner_func, **call_kwargs)
                        )
                except (TimeoutError, asyncio.TimeoutError):  # cuga's own tool-call timeout
                    if attempt == retries:
                        raise
                else:
                    if attempt == retries or not is_api_timeout(result):
                        return result
                logger.info("[m3-adapter] {} timed out; retrying ({}/{})", name, attempt + 1, retries)

        async def recording_coro(*args, **kwargs):
            if cap is not None and len(sink) >= cap:
                raise RuntimeError(
                    f"Tool-call cap reached ({cap}); stop looping and answer from data already retrieved."
                )
            call_kwargs = merge_call_args(args, kwargs, param_names)
            if provider.force_distinct_false:
                kept = without_distinct(name, call_kwargs)
                if kept is not None:
                    logger.info("[m3-adapter distinct] {}: distinct=True -> False", name)
                    call_kwargs = kept
            record = {"tool_name": name, "arguments": dict(call_kwargs), "result": ""}
            sink.append(record)
            try:
                result = await call_inner(call_kwargs)
                if provider.lowercase_retry and is_empty_or_zero(result):
                    lowered = lowercased_args(call_kwargs)
                    if lowered is not None:
                        retried = await call_inner(lowered)
                        if not is_empty_or_zero(retried) and not looks_like_error(retried):
                            logger.info(
                                "[m3-adapter lowercase-retry] {} matched with lowercased arguments", name
                            )
                            result = retried
                            record["arguments"] = dict(lowered)
                record["result"] = str(result)[:RESULT_MAX_CHARS]
                if provider.on_failure is not None and (is_empty_result(result) or looks_like_error(result)):
                    provider.on_failure()
                if hint_empty and (isinstance(result, str) or hint_any_type) and is_empty_result(result):
                    lookup = provider.value_examples  # read per call: it is set per task
                    examples = lookup(list(param_names or call_kwargs)) if lookup is not None else None
                    return with_empty_result_hint(result, examples)
                return result
            except Exception as exc:
                record["result"] = f"Error: {exc}"
                if provider.on_failure is not None:
                    provider.on_failure()
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
        # attributes set on the tool object itself) intact. The call itself goes
        # straight to the raw tool's entry point, so renaming never re-routes it.
        update: Dict[str, Any] = {"coroutine": recording_coro, "func": recording_func}
        if name != tool.name:
            update["name"] = name
        return tool.model_copy(update=update)
