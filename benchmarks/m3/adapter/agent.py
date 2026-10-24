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

import asyncio
import inspect
from typing import Any, Callable, List, Optional

from langchain_core.messages import HumanMessage
from loguru import logger

from benchmarks.m3.adapter.config import (
    BIND_CAP_ENV,
    BIND_CAP_SETTING,
    CAMPAIGN_BIND_CAP,
    AdapterConfig,
    TaskContext,
    cuga_setting_pins,
    execution_mode_configurable,
    runtime_configurable,
)
from benchmarks.m3.adapter.demos import (
    DemoIndex,
    ParamValueIndex,
    bound_tool_namer,
    build_demo_index,
    build_param_value_index,
    select_prose_pairs,
)
from benchmarks.m3.adapter.final_answer import make_final_answer_fn, normalize_answer, strip_channel_tokens
from benchmarks.m3.adapter.guards import run_answer_pipeline
from benchmarks.m3.adapter.instructions import VERBATIM_RULE, compose_instruction_block
from benchmarks.m3.adapter.recording import RecordingScopedToolProvider
from benchmarks.m3.adapter.scope import resolve_scope
from benchmarks.m3.adapter.shortlist import (
    CosinePickStrategy,
    build_shortlister,
    campaign_rank,
    conversation_history,
    encode_texts,
    pick_turn_tools,
    prepick_tool,
)

#: Instruction line for ``tool_pick_hint``: the pre-selected API, named.
TOOL_PICK_HINT = (
    "TOOL HINT: a pre-selection over this domain's APIs found `{tool}` the most likely to answer this "
    "question on its own. Call it first unless its description clearly does not fit the question."
)


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


#: Exception class names (anywhere in the cause chain) that mean the LLM transport failed —
#: the turn itself may be fine on a retry. Our own agent_timeout TimeoutError is not one of them.
TRANSIENT_ERRORS = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "ServiceUnavailableError",
        "RateLimitError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "ReadError",
        "RemoteProtocolError",
    }
)


def is_transient_error(exc: BaseException) -> bool:
    seen = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if type(cur).__name__ in TRANSIENT_ERRORS or "connection error" in str(cur).lower():
            return True
        cur = cur.__cause__ or cur.__context__
    return False


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
        value_index: Optional[ParamValueIndex] = None,
    ):
        self._inner = inner
        self._cfg = cfg
        self._provider = provider
        self._demo_index = demo_index
        self._value_index = value_index
        self._final_answer_installed = final_answer_installed
        self._ctx = TaskContext()
        self._draft: Optional[tuple] = None  # (result, tool calls) of the last completed round
        self._llm_model = None
        self._namer: Optional[Callable[[str], str]] = None
        self._namer_source: Any = None  # the base provider the namer was built from

    def __getattr__(self, name: str) -> Any:  # .policies, .tool_provider, .initialize, ...
        return getattr(self._inner, name)

    def _value_examples_for(self, query: str) -> Optional[Callable[[List[str]], dict]]:
        """Per-task lookup for the empty-result hint: never the asked question's own values."""
        k = self._cfg.param_value_examples
        index = self._value_index
        if not (k and index is not None and self._cfg.empty_result_hint):
            return None
        return lambda params: index.examples(params, exclude_query=query, k=k)

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

    async def _turn_tools(self, query: str, message: Any) -> Optional[set]:
        """The tool names the agent may see this turn (None = all).

        ``prefilter_top_k``: the campaign's per-utterance top-k (only for a catalog of more than
        ``prefilter_min_tools`` tools). ``tool_pick`` outside native function
        calling: the conversation-aware pick (FC picks at bind time, through the shortlister instead).
        """
        cfg = self._cfg
        codeact_pick = cfg.tool_pick and cfg.execution_mode != "function_calling"
        base = self._provider.base_provider
        if not (cfg.prefilter_top_k or codeact_pick) or base is None or not query.strip():
            return None
        try:
            tools = list(await base.get_all_tools())
            if not codeact_pick and len(tools) <= cfg.prefilter_min_tools:
                return None  # the whole catalog fits the model: every tool (the cap4 A/B winner)
            if codeact_pick:
                history = conversation_history(message)
                names = await pick_turn_tools(
                    query, history, self._ctx.additional_instructions, tools, cfg, self._llm_ainvoke
                )
            else:
                ranked = await asyncio.to_thread(
                    campaign_rank,
                    query,
                    tools,
                    cfg.prefilter_top_k,
                    lambda texts: encode_texts(cfg.shortlist_model, texts),
                )
                names = [t.name for t, _, _ in ranked]
                logger.info("[m3-adapter prefilter] {} of {} tools exposed this turn", len(names), len(tools))
            return set(names)
        except Exception as exc:  # noqa: BLE001  (fall back to the full catalog, never fail the turn)
            logger.warning("[m3-adapter prefilter] failed ({}); exposing every tool this turn", exc)
            return None

    async def _tool_pick_hint(self, query: str) -> str:
        """Pick before the call and name the pick (``tool_pick_hint``); empty when the pick failed."""
        try:
            tools = list(await self._provider.get_all_tools())
            pick = await prepick_tool(query, tools, self._cfg, self._llm_ainvoke) if tools else None
        except Exception as exc:  # noqa: BLE001  (the hint is optional)
            logger.warning("[m3-adapter tool-pick] pre-pick failed ({}); no hint", exc)
            return ""
        return TOOL_PICK_HINT.format(tool=pick) if pick else ""

    async def _llm_ainvoke(self, prompt: str) -> str:
        """One-off LLM call for scope classification / self-verify (lazy model)."""
        if self._llm_model is None:
            from cuga.backend.llm.models import LLMManager  # noqa: PLC0415
            from cuga.config import settings  # noqa: PLC0415

            self._llm_model = LLMManager().get_model(settings.agent.code.model)
        response = await self._llm_model.ainvoke([HumanMessage(content=prompt)])
        return _text_of(getattr(response, "content", response))

    async def _demo_namer(self) -> Optional[Callable[[str], str]]:
        """Corpus tool name -> bound name, rebuilt when the base provider changes (cap1 re-list)."""
        base = self._provider.base_provider
        if self._namer is None or self._namer_source is not base:
            try:
                tools = await base.get_all_tools()  # names only: no recording wrappers needed
            except Exception as exc:  # noqa: BLE001  (demos are best-effort; keep the raw names)
                logger.warning("[m3-adapter demos] could not list tools for demo names ({})", exc)
                return None
            self._namer = bound_tool_namer(t.name for t in tools)
            self._namer_source = base
        return self._namer

    async def invoke(
        self, message: Any = None, thread_id: Optional[str] = None, config: Optional[dict] = None, **kwargs
    ) -> Any:
        """One task turn; ``agent_timeout`` caps its wall clock like the campaign's runner did.

        A timed-out turn raises ``TimeoutError``: the eval records the task as failed with an
        empty response — what the campaign's benchmark_runner wrote for a timed-out item.
        With ``infra_retries``, a turn that dies on the LLM transport (connection drop, 5xx,
        request timeout) is re-run from scratch on a fresh thread; the agent timeout is not
        retried.
        """
        attempts = 1 + max(0, self._cfg.infra_retries)
        for attempt in range(attempts):
            tid, conf = thread_id, config
            if attempt and thread_id:
                tid = f"{thread_id}-retry{attempt}"
                if config and "thread_id" in (config.get("configurable") or {}):
                    conf = {**config, "configurable": {**config["configurable"], "thread_id": tid}}
            try:
                return await self._timed_invoke(message, tid, conf, **kwargs)
            except Exception as exc:
                if attempt + 1 >= attempts or not is_transient_error(exc):
                    raise
                logger.warning(
                    "[m3-adapter] transient failure ({}); re-running the task on a fresh thread ({}/{})",
                    type(exc).__name__,
                    attempt + 1,
                    attempts - 1,
                )
        raise AssertionError("unreachable")  # pragma: no cover

    async def _timed_invoke(
        self, message: Any = None, thread_id: Optional[str] = None, config: Optional[dict] = None, **kwargs
    ) -> Any:
        timeout = self._cfg.agent_timeout
        if not timeout:
            return await self._invoke(message, thread_id, config, **kwargs)
        self._draft = None
        try:
            return await asyncio.wait_for(self._invoke(message, thread_id, config, **kwargs), timeout=timeout)
        except asyncio.TimeoutError as exc:
            logger.warning("[m3-adapter] task exceeded agent_timeout={}s; cancelled", timeout)
            kept = self._draft_result() if self._cfg.keep_draft_on_timeout else None
            if kept is not None:
                logger.warning("[m3-adapter] timeout during a re-ask: answering with the earlier draft")
                return kept
            raise TimeoutError(f"agent_timeout {timeout}s exceeded") from exc

    def _draft_result(self) -> Any:
        """The last completed round's result, with every tool call so far; None without an answer."""
        if self._draft is None:
            return None
        result, calls = self._draft
        answer = strip_channel_tokens(str(getattr(result, "answer", "") or ""))
        if not answer.strip():
            return None
        if self._cfg.normalize:
            answer = normalize_answer(answer)
        try:
            return result.model_copy(update={"answer": answer, "tool_calls": list(calls)})
        except AttributeError:  # non-pydantic result object
            result.answer, result.tool_calls = answer, list(calls)
            return result

    async def _invoke(
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
        self._provider.value_examples = self._value_examples_for(query)
        self._provider.allowed = await self._turn_tools(query, message)
        widen = cfg.tool_pick and cfg.tool_pick_widen and cfg.execution_mode == "function_calling"
        if widen:
            CosinePickStrategy.reset(query)
        self._provider.on_failure = (lambda: CosinePickStrategy.mark_failure(query)) if widen else None
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
        if cfg.tool_pick and cfg.tool_pick_hint and cfg.execution_mode == "function_calling":
            hint = await self._tool_pick_hint(query)
            if hint:
                conf["special_instructions"] = _join(conf.get("special_instructions", ""), hint)

        if cfg.demos and self._demo_index is not None:
            # bare tool names already match the corpus names; the namer maps them to registry names
            namer = await self._demo_namer() if cfg.demo_bound_names and not cfg.bare_tool_names else None
            pairs = select_prose_pairs(self._demo_index, query, cfg.demos_k, namer)
            if pairs:
                conf["mcp_few_shot_examples"] = pairs
                conf.setdefault("cuga_lite_enable_few_shots", True)

        # Execution mode (VAKRA_CUGA_FC): native function calling binds the
        # scoped / shortlisted toolset as tools instead of CodeAct code blocks.
        conf.update(execution_mode_configurable(cfg))
        # Campaign runtime: FC prompt knobs, no find_tools wall, step budget.
        conf.update(runtime_configurable(cfg))

        run_config["configurable"] = conf

        result = await self._inner.invoke(message, thread_id=thread_id, config=run_config, **kwargs)
        all_tool_calls = list(getattr(result, "tool_calls", None) or [])
        effective_thread = getattr(result, "thread_id", None) or thread_id
        self._draft = (result, all_tool_calls)  # what a timeout during the re-asks falls back to

        async def invoke_round(correction: str):
            if widen:  # the answer checks re-ask: something went wrong, show the wider tool set
                CosinePickStrategy.mark_failure(query)
            follow_up = await self._inner.invoke(
                [HumanMessage(content=correction)],
                thread_id=effective_thread,
                config=run_config,
                **kwargs,
            )
            all_tool_calls.extend(getattr(follow_up, "tool_calls", None) or [])
            if not getattr(follow_up, "error", None):
                self._draft = (follow_up, all_tool_calls)
            return follow_up

        answer = await run_answer_pipeline(
            invoke_round,
            result,
            cfg,
            ctx,
            self._provider.recorded_calls,
            self._llm_ainvoke,
            final_answer_installed=self._final_answer_installed,
            question=query,
        )
        try:
            return result.model_copy(update={"answer": answer, "tool_calls": all_tool_calls})
        except AttributeError:  # non-pydantic result object: mutate in place
            result.answer = answer
            result.tool_calls = all_tool_calls
            return result


def recording_provider(base_provider: Any, cfg: AdapterConfig) -> RecordingScopedToolProvider:
    """The recording wrapper with the config's cap, naming and empty-result hint."""
    provider = RecordingScopedToolProvider(
        base_provider,
        tool_cap=cfg.tool_cap,
        bare_names=cfg.bare_tool_names,
        empty_result_hint=cfg.empty_result_hint,
        hint_non_string_results=cfg.execution_mode == "function_calling",
    )
    provider.lowercase_retry = cfg.lowercase_retry
    provider.force_distinct_false = cfg.force_distinct_false
    provider.keep_full_results = cfg.composer_result_chars if cfg.answer_composer else 0
    return provider


def _warn_if_bind_cap_unsafe(cfg: AdapterConfig) -> None:
    """FC binds the scoped toolset natively. The validated runs never bound more than
    ``CAMPAIGN_BIND_CAP`` tools (their MiniLM shortlister kept the top 128 per utterance),
    and cuga's settings cap at its default reproduces that: above it the bind-time
    shortlister — the adapter's MiniLM config — reduces the domain to the top 128. A
    disabled (0) or raised cap binds whole domains (M3 has up to ~280 tools): never
    validated, and OpenAI-class providers reject more than 128 tools per request."""
    if cfg.execution_mode != "function_calling":
        return
    try:
        from cuga.config import settings  # noqa: PLC0415

        cap = int(getattr(settings.advanced_features, BIND_CAP_SETTING, CAMPAIGN_BIND_CAP))
    except Exception:  # noqa: BLE001  (settings unavailable: nothing to check)
        return
    if cap <= 0 or cap > CAMPAIGN_BIND_CAP:
        logger.warning(
            "[m3-adapter] execution_mode=function_calling with {}={} (settings): large domains get bound whole "
            "— the validated runs bound at most {} MiniLM-ranked tools, and OpenAI-class providers reject more "
            "than 128. Unset {} to restore the default.",
            BIND_CAP_SETTING,
            cap,
            CAMPAIGN_BIND_CAP,
            BIND_CAP_ENV,
        )


def apply_cuga_settings(cfg: AdapterConfig) -> None:
    """Pin the config's CUGA settings in-process (``cuga_settings`` + ``llm_http_timeout``).

    Process-wide by design: one eval process runs one adapter config. Must run before
    the agent builds its model (the LLM timeout is read when the client is created).
    """
    pins = cuga_setting_pins(cfg)
    if not pins:
        return
    from cuga.config import settings  # noqa: PLC0415

    setter, getter = getattr(settings, "set", None), getattr(settings, "get", None)
    if not callable(setter):
        logger.warning("[m3-adapter] cuga settings cannot be pinned here; not applied: {}", pins)
        return
    for key, value in pins:
        parent = key.rsplit(".", 1)[0]
        if key.startswith("agent.") and callable(getter) and getter(parent) is None:
            continue  # a model block this CUGA does not define: nothing to sample with
        before = getter(key) if callable(getter) else None
        setter(key, value)
        logger.info("[m3-adapter] pinned cuga setting {}={!r} (was {!r})", key, value, before)


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

    _warn_if_bind_cap_unsafe(config)
    apply_cuga_settings(config)
    provider = recording_provider(tool_provider, config)
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
    value_index = (
        build_param_value_index(demo_corpus) if (config.param_value_examples and demo_corpus) else None
    )
    if config.demos and demo_index is None:
        logger.info("[m3-adapter] demos enabled but no usable corpus — running without demos")
    logger.info("[m3-adapter] preset '{}' active (capability {})", config.preset, config.capability)
    return VakraAdapterAgent(
        inner,
        config,
        provider,
        demo_index,
        final_answer_installed=final_answer_installed,
        value_index=value_index,
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
    _warn_if_bind_cap_unsafe(config)
    apply_cuga_settings(config)  # prompt-time settings still apply; an already-built model keeps its timeout
    outer = getattr(agent, "tool_provider", None)
    toolguard_cls = _toolguard_provider_class()
    if outer is None:
        logger.warning(
            "[m3-adapter] wrapped agent exposes no tool_provider; evidence-based guards "
            "will see zero recorded calls"
        )
        provider = recording_provider(None, config)
    elif toolguard_cls is not None and isinstance(outer, toolguard_cls):
        provider = recording_provider(outer.base_provider, config)
        outer.base_provider = provider
        invalidate = getattr(outer, "invalidate_toolguard_runtime", None)
        if callable(invalidate):
            invalidate()  # guarded-tool cache is keyed by raw tool id; the raw tools just changed
    else:
        provider = recording_provider(outer, config)
        agent.tool_provider = provider
    demo_index = build_demo_index(demo_corpus) if (config.demos and demo_corpus) else None
    value_index = (
        build_param_value_index(demo_corpus) if (config.param_value_examples and demo_corpus) else None
    )
    logger.info(
        "[m3-adapter] preset '{}' wrapped existing agent (capability {})", config.preset, config.capability
    )
    return VakraAdapterAgent(
        agent, config, provider, demo_index, final_answer_installed=False, value_index=value_index
    )
