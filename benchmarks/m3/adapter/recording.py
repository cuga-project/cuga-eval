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
"""

from __future__ import annotations

from typing import Any, List, Optional

from langchain_core.tools import StructuredTool

from benchmarks.m3.adapter.scope import is_retriever


class RecordingScopedToolProvider:
    """ToolProviderInterface wrapper: record calls, cap runaways, apply scope."""

    def __init__(self, base_provider: Any, tool_cap: Optional[int] = None):
        self.base_provider = base_provider
        self.tool_cap = tool_cap
        self.recorded_calls: List[dict] = []  # cleared by the agent wrapper per task
        self.scope: str = "all"  # set by the agent wrapper per invoke

    async def initialize(self) -> None:
        if hasattr(self.base_provider, "initialized") and not self.base_provider.initialized:
            await self.base_provider.initialize()
        elif not hasattr(self.base_provider, "initialized"):
            init = getattr(self.base_provider, "initialize", None)
            if init is not None:
                await init()

    async def get_apps(self):
        return await self.base_provider.get_apps()

    async def get_tools(self, app_name: str):
        return self._apply(await self.base_provider.get_tools(app_name))

    async def get_all_tools(self):
        return self._apply(await self.base_provider.get_all_tools())

    # ------------------------------------------------------------------

    def _apply(self, tools: List[StructuredTool]) -> List[StructuredTool]:
        if self.scope == "retriever_only":
            tools = [t for t in tools if is_retriever(t.name)]
        elif self.scope == "no_retriever":
            tools = [t for t in tools if not is_retriever(t.name)]
        return [self._record(t) for t in tools]

    def _record(self, tool: StructuredTool) -> StructuredTool:
        """Wrap a tool so each call is appended to ``recorded_calls``."""
        inner_coro = tool.coroutine
        inner_func = tool.func
        sink = self.recorded_calls
        cap = self.tool_cap
        name = tool.name

        async def recording_coro(**kwargs):
            if cap is not None and len(sink) >= cap:
                raise RuntimeError(
                    f"Tool-call cap reached ({cap}); stop looping and answer from data already retrieved."
                )
            record = {"tool_name": name, "arguments": dict(kwargs), "result": ""}
            sink.append(record)
            try:
                result = await inner_coro(**kwargs) if inner_coro is not None else inner_func(**kwargs)
                record["result"] = str(result)[:4000]
                return result
            except Exception as exc:
                record["result"] = f"Error: {exc}"
                raise

        # model_copy keeps metadata/response_format/return_direct intact;
        # func=None ensures the async wrapper is the single execution path.
        return tool.model_copy(update={"coroutine": recording_coro, "func": None})
