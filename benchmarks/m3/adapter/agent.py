"""The configured-CUGA wrapper and its factories.

``build_m3_agent`` is the single construction seam: with the ``off`` preset it
returns a plain ``CugaAgent`` built exactly as the eval builds it today; with a
preset enabled it layers the validated VAKRA behaviors on an UNMODIFIED agent
through public SDK surfaces only (tool provider, ``special_instructions``
configurable, ``final_answer``, ``shortlister``, ``mcp_few_shot_examples``).

``VakraAdapterAgent`` exposes the same ``invoke()`` surface the eval helpers
already call and delegates everything else (``.policies``, ...) to the inner
agent, so no helper code changes.
"""

from __future__ import annotations

import inspect
from typing import Any, List, Optional

from langchain_core.messages import HumanMessage
from loguru import logger

from benchmarks.m3.adapter.config import AdapterConfig, TaskContext
from benchmarks.m3.adapter.demos import DemoIndex, build_demo_index, select_prose_pairs
from benchmarks.m3.adapter.final_answer import make_final_answer_fn
from benchmarks.m3.adapter.guards import run_answer_pipeline
from benchmarks.m3.adapter.instructions import VERBATIM_RULE, compose_instruction_block
from benchmarks.m3.adapter.recording import RecordingScopedToolProvider
from benchmarks.m3.adapter.scope import resolve_scope
from benchmarks.m3.adapter.shortlist import build_shortlister


def _text_of(content: Any) -> str:
    """LLM content may be a string or a structured block list."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return str(content or "")


def _last_user_text(message: Any) -> str:
    """The text to scope/shortlist/demo-match on: the latest user turn."""
    if message is None:
        return ""
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        for m in reversed(message):
            if getattr(m, "type", "") == "human" or m.__class__.__name__ == "HumanMessage":
                return _text_of(getattr(m, "content", ""))
        return _text_of(getattr(message[-1], "content", "")) if message else ""
    return _text_of(getattr(message, "content", message))


def _join(a: str, b: str) -> str:
    return "\n\n".join(p for p in (a, b) if p)


class VakraAdapterAgent:
    """Configured CUGA: same ``invoke()`` surface, adapter behaviors around it."""

    def __init__(
        self,
        inner: Any,
        cfg: AdapterConfig,
        provider: RecordingScopedToolProvider,
        demo_index: Optional[DemoIndex] = None,
        *,
        final_answer_installed: bool = True,
    ):
        self._inner = inner
        self._cfg = cfg
        self._provider = provider
        self._demo_index = demo_index
        self._final_answer_installed = final_answer_installed
        self._ctx = TaskContext()
        self._llm_model = None

    def __getattr__(self, name: str) -> Any:  # .policies, .tool_provider, .initialize, ...
        return getattr(self._inner, name)

    # ------------------------------------------------------------------
    # Runner-facing hooks
    # ------------------------------------------------------------------

    def set_task_context(
        self,
        *,
        additional_instructions: str = "",
        initial_data_handle: Optional[str] = None,
        initial_data_peek: Optional[dict] = None,
        domain: str = "",
    ) -> None:
        """Called by the eval before each task/sample (tasks run sequentially)."""
        self._ctx = TaskContext(
            additional_instructions=additional_instructions or "",
            initial_data_handle=initial_data_handle,
            initial_data_peek=initial_data_peek,
            domain=domain,
        )

    def refresh_tools(self, tools: List[Any]) -> None:
        """cap1 re-list: rebind the toolset after the environment switches the
        per-item tool universe. CUGA re-fetches tools from the provider at every
        invoke, so swapping the base provider is sufficient — no agent rebuild."""
        from cuga.backend.cuga_graph.nodes.cuga_lite.providers.langchain import (  # noqa: PLC0415
            DirectLangChainToolsProvider,
        )

        self._provider.base_provider = DirectLangChainToolsProvider(tools)
        logger.info("[m3-adapter] refreshed toolset ({} tools)", len(tools))

    # ------------------------------------------------------------------

    async def _llm_ainvoke(self, prompt: str) -> str:
        """One-off LLM call for scope classification / self-verify (lazy model)."""
        if self._llm_model is None:
            from cuga.backend.llm.models import LLMManager  # noqa: PLC0415
            from cuga.config import settings  # noqa: PLC0415

            self._llm_model = LLMManager().get_model(settings.agent.code.model)
        response = await self._llm_model.ainvoke([HumanMessage(content=prompt)])
        return _text_of(getattr(response, "content", response))

    async def invoke(
        self, message: Any = None, thread_id: Optional[str] = None, config: Optional[dict] = None, **kwargs
    ) -> Any:
        cfg = self._cfg
        ctx = self._ctx
        self._provider.recorded_calls.clear()  # per user turn, like the validated adapter
        run_config = dict(config or {})
        conf = dict(run_config.get("configurable") or {})
        query = _last_user_text(message)

        # cap4 deterministic policy scoping (one cheap LLM call for conditional rules).
        ctx.last_scope = "all"
        self._provider.scope = "all"
        if cfg.scope and ctx.additional_instructions:
            scope = await resolve_scope(ctx.additional_instructions, query, self._llm_ainvoke)
            ctx.last_scope = scope
            self._provider.scope = scope
            if scope != "all":
                # The scoped subset is already the selection — lift the find_tools wall.
                conf["shortlisting_tool_threshold"] = 10**6
                logger.info("[m3-adapter scope] {} tool scope applied", scope)

        block = compose_instruction_block(cfg, ctx)
        if ctx.last_scope == "retriever_only" and cfg.verbatim_on_retriever_scope:
            block = _join(block, VERBATIM_RULE)
        if block:
            conf["special_instructions"] = _join(conf.get("special_instructions", ""), block)

        if cfg.demos and self._demo_index is not None:
            pairs = select_prose_pairs(self._demo_index, query, cfg.demos_k)
            if pairs:
                conf["mcp_few_shot_examples"] = pairs
                conf.setdefault("cuga_lite_enable_few_shots", True)

        run_config["configurable"] = conf

        result = await self._inner.invoke(message, thread_id=thread_id, config=run_config, **kwargs)
        all_tool_calls = list(getattr(result, "tool_calls", None) or [])
        effective_thread = getattr(result, "thread_id", None) or thread_id

        async def invoke_round(correction: str):
            follow_up = await self._inner.invoke(
                [HumanMessage(content=correction)],
                thread_id=effective_thread,
                config=run_config,
                **kwargs,
            )
            all_tool_calls.extend(getattr(follow_up, "tool_calls", None) or [])
            return follow_up

        answer = await run_answer_pipeline(
            invoke_round,
            result,
            cfg,
            ctx,
            self._provider.recorded_calls,
            self._llm_ainvoke,
            final_answer_installed=self._final_answer_installed,
        )
        try:
            return result.model_copy(update={"answer": answer, "tool_calls": all_tool_calls})
        except AttributeError:  # non-pydantic result object: mutate in place
            result.answer = answer
            result.tool_calls = all_tool_calls
            return result


def build_m3_agent(
    *,
    tool_provider: Any,
    special_instructions: Optional[str] = None,
    config: AdapterConfig,
    demo_corpus: Optional[List[dict]] = None,
    callbacks: Optional[List[Any]] = None,
    **cuga_kwargs: Any,
):
    """Single construction seam for the m3 eval.

    ``config.enabled`` False (the ``off`` preset) returns a plain ``CugaAgent``
    with exactly the caller's kwargs — current behavior, unchanged. Enabled
    presets wrap the provider for recording/scoping and configure the agent
    through SDK kwargs only.
    """
    from cuga.sdk import CugaAgent  # noqa: PLC0415  (lazy: keeps module importable without cuga)

    base_kwargs = dict(cuga_kwargs)
    if callbacks is not None:
        base_kwargs["callbacks"] = callbacks
    if not config.enabled:
        return CugaAgent(
            tool_provider=tool_provider, special_instructions=special_instructions, **base_kwargs
        )

    provider = RecordingScopedToolProvider(tool_provider, tool_cap=config.tool_cap)
    shortlister = build_shortlister(config)
    if shortlister is not None:
        base_kwargs["shortlister"] = shortlister

    # final_answer merged to cuga main in #621; feature-detect so a stale
    # sibling checkout degrades to the equivalent post-invoke fallback.
    final_answer_installed = False
    if "final_answer" in inspect.signature(CugaAgent.__init__).parameters:
        base_kwargs["final_answer"] = make_final_answer_fn(config)
        final_answer_installed = True
    else:
        logger.warning(
            "[m3-adapter] cuga.sdk.CugaAgent has no final_answer kwarg (pre-#621 checkout); "
            "applying the answer function post-invoke instead"
        )

    inner = CugaAgent(tool_provider=provider, special_instructions=special_instructions, **base_kwargs)
    demo_index = build_demo_index(demo_corpus) if (config.demos and demo_corpus) else None
    if config.demos and demo_index is None:
        logger.info("[m3-adapter] demos enabled but no usable corpus — running without demos")
    logger.info("[m3-adapter] preset '{}' active (capability {})", config.preset, config.capability)
    return VakraAdapterAgent(
        inner, config, provider, demo_index, final_answer_installed=final_answer_installed
    )


def _toolguard_provider_class():
    """cuga's ToolGuard provider-decorator class, or None when it cannot be imported."""
    try:
        from cuga.backend.cuga_graph.nodes.cuga_lite.providers.toolguard import (  # noqa: PLC0415
            ToolGuardingToolProvider,
        )
    except Exception:  # noqa: BLE001  (fake/partial cuga in tests, older checkouts)
        return None
    return ToolGuardingToolProvider


def wrap_existing_agent(agent: Any, config: AdapterConfig, demo_corpus: Optional[List[dict]] = None):
    """Wrap an already-constructed CugaAgent (e.g. from ``setup_agent_with_tools``).

    Must run BEFORE the agent's first invoke, while the provider reference can
    still flow into the graph build. The in-graph final_answer function cannot
    be injected post-construction, so the equivalent post-invoke fallback runs
    instead. No-op passthrough when the preset is off.

    ``CugaAgent.__init__`` installs a ToolGuard decorator around the caller's
    provider; the recording wrapper goes *inside* it so ToolGuard stays
    outermost — it is what normalizes positional tool args and what the SDK
    hands policy storage to (``configure_toolguard_provider`` is a no-op on any
    other outer object). ``build_m3_agent`` ends up in the same order because
    the constructor wraps whatever it is given.
    """
    if not config.enabled:
        return agent
    outer = getattr(agent, "tool_provider", None)
    toolguard_cls = _toolguard_provider_class()
    if outer is None:
        logger.warning(
            "[m3-adapter] wrapped agent exposes no tool_provider; evidence-based guards "
            "will see zero recorded calls"
        )
        provider = RecordingScopedToolProvider(None, tool_cap=config.tool_cap)
    elif toolguard_cls is not None and isinstance(outer, toolguard_cls):
        provider = RecordingScopedToolProvider(outer.base_provider, tool_cap=config.tool_cap)
        outer.base_provider = provider
        invalidate = getattr(outer, "invalidate_toolguard_runtime", None)
        if callable(invalidate):
            invalidate()  # guarded-tool cache is keyed by raw tool id; the raw tools just changed
    else:
        provider = RecordingScopedToolProvider(outer, tool_cap=config.tool_cap)
        agent.tool_provider = provider
    demo_index = build_demo_index(demo_corpus) if (config.demos and demo_corpus) else None
    logger.info(
        "[m3-adapter] preset '{}' wrapped existing agent (capability {})", config.preset, config.capability
    )
    return VakraAdapterAgent(agent, config, provider, demo_index, final_answer_installed=False)
