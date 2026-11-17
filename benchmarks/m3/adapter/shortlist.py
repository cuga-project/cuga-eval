"""Shortlisting config for the adapter — the exact VAKRA setup via the SDK.

The validated runs shortlisted with MiniLM (``all-MiniLM-L6-v2``) cosine
similarity, top-k bounded (128 for capabilities 1-3, 40 for capability 4),
no score floor, pure-query embedding — with ``query_*`` document retrievers
always pinned into the list. CUGA main's pluggable shortlister expresses all
of that as configuration:

* plain runs use ``Shortlister(strategy="embedding", embedding_model=MiniLM,
  top_k=K, threshold=K, min_score=0.0, query_weight=1.0)``;
* the retriever-pinning variant is this module's ``MiniLMPinnedStrategy``,
  selected by dotted class path (an SDK-documented mechanism) — it delegates
  ranking to the SDK's embedding strategy and pins retrievers into the top-k.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from loguru import logger

from benchmarks.m3.adapter.config import MINILM_MODEL, AdapterConfig
from benchmarks.m3.adapter.scope import is_retriever

#: Dotted path handed to ``Shortlister(strategy=...)`` for the pinned variant.
PINNED_STRATEGY_PATH = "benchmarks.m3.adapter.shortlist.MiniLMPinnedStrategy"


class MiniLMPinnedStrategy:
    """SDK shortlist strategy: embedding ranking with ``query_*`` tools pinned.

    Instantiated by CUGA's shortlister factory (which passes ``plan=`` when the
    constructor accepts it). Ranking is delegated to the SDK's own
    ``EmbeddingShortlister`` built from the same plan, so model/provider/knobs
    stay configuration-driven; the only added behavior is the pin.
    """

    name = "m3_minilm_pinned"
    #: Set by ``build_shortlister`` from the preset (the SDK instantiates the class with ``plan=`` only).
    pin_retrievers: bool = True
    pin_pattern: str = ""

    def __init__(self, plan: Any = None):
        self._plan = plan
        self._inner = None

    def _ensure_inner(self):
        if self._inner is None:
            from cuga.backend.cuga_graph.nodes.cuga_lite.shortlister.embedding import (
                EmbeddingShortlister,
            )

            plan = self._plan
            self._inner = EmbeddingShortlister(
                model_name=getattr(plan, "embedding_model", None),
                provider=getattr(plan, "embedding_provider", None),
                query_weight=getattr(plan, "query_weight", None),
                min_score=getattr(plan, "min_score", None),
            )
        return self._inner

    async def shortlist(self, request):
        from cuga.backend.cuga_graph.nodes.cuga_lite.shortlister.base import (
            ShortlistCandidate,
            ShortlistResult,
        )

        result = await self._ensure_inner().shortlist(request)
        ranked = list(result.candidates)
        scores = {c.name: c.score for c in ranked}
        rx = re.compile(self.pin_pattern) if self.pin_pattern else None
        retrievers = [t.name for t in request.tools if self.pin_retrievers and is_retriever(t.name)]
        tools = [t.name for t in request.tools if rx and rx.fullmatch(t.name) and t.name not in retrievers]
        pinned = [
            ShortlistCandidate(name=n, score=scores.get(n, 1.0), reasoning="pinned retriever")
            for n in retrievers
        ] + [ShortlistCandidate(name=n, score=scores.get(n, 1.0), reasoning="pinned tool") for n in tools]
        pinned_names = set(retrievers) | set(tools)
        rest = [c for c in ranked if c.name not in pinned_names]
        merged = pinned + rest
        if request.top_k:
            merged = merged[: request.top_k]
        return ShortlistResult(candidates=merged, notes=result.notes)


#: Dotted path for the campaign's own shortlister (see ``CampaignMiniLMStrategy``).
CAMPAIGN_STRATEGY_PATH = "benchmarks.m3.adapter.shortlist.CampaignMiniLMStrategy"

_ST_MODELS: dict = {}  # model name -> SentenceTransformer
_ST_VECTORS: dict = {}  # (model name, text) -> embedding


def _sentence_model(model_name: str):
    model = _ST_MODELS.get(model_name)
    if model is None:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415  (heavy; loaded on first use)

        model = _ST_MODELS[model_name] = SentenceTransformer(model_name)
    return model


def _encode(model_name: str, texts: list):
    """Plain ``SentenceTransformer.encode`` (no query prefix), memoized per text."""
    import numpy as np  # noqa: PLC0415

    missing = [t for t in dict.fromkeys(texts) if (model_name, t) not in _ST_VECTORS]
    if missing:
        for text, vector in zip(missing, _sentence_model(model_name).encode(missing, convert_to_numpy=True)):
            _ST_VECTORS[(model_name, text)] = vector
    return np.array([_ST_VECTORS[(model_name, t)] for t in texts])


def encode_texts(model_name: str, texts: list):
    """Memoized MiniLM embeddings (the campaign's shortlister encoder)."""
    return _encode(model_name, texts)


def campaign_rank(query: str, tools: list, top_k: int, encode) -> list:
    """vakra-main ``ToolShortlister.shortlist`` (agents/components/tool_shortlister.py), as written.

    Returns ``(tool, score, reason)`` triples: the catalog untouched when it fits in ``top_k``;
    otherwise every ``query_*`` retriever, then the most cosine-similar of the rest between the
    query and ``"<name>: <description>"``. ``encode(texts) -> ndarray`` is the embedder.
    """
    import numpy as np  # noqa: PLC0415

    from benchmarks.m3.adapter.recording import bare_tool_name  # noqa: PLC0415

    if len(tools) <= top_k:
        return [(t, 1.0, "catalog within top_k") for t in tools]
    pinned = [t for t in tools if bare_tool_name(t).startswith("query_")]
    candidates = [t for t in tools if not bare_tool_name(t).startswith("query_")]
    keep = [(t, 1.0, "pinned retriever") for t in pinned]
    remaining = top_k - len(pinned)
    if remaining <= 0 or not candidates:
        return keep
    if remaining >= len(candidates):
        return keep + [(t, 1.0, "within remaining slots") for t in candidates]
    tool_embs = encode([f"{t.name}: {t.description}" for t in candidates])
    query_emb = encode([query])
    tool_norms = np.linalg.norm(tool_embs, axis=1, keepdims=True)
    query_norm = np.linalg.norm(query_emb, axis=1, keepdims=True)
    tool_embs = tool_embs / np.where(tool_norms == 0, 1, tool_norms)
    query_emb = query_emb / np.where(query_norm == 0, 1, query_norm)
    similarities = (tool_embs @ query_emb.T).squeeze(axis=1)
    top = np.argsort(similarities)[::-1][:remaining]
    return keep + [(candidates[i], float(similarities[i]), f"cosine {similarities[i]:.3f}") for i in top]


class CampaignMiniLMStrategy:
    """The campaign's shortlister as an SDK strategy (``Shortlister(strategy=<dotted path>)``).

    Unlike the SDK embedding strategy — which embeds app, split name, description,
    parameters and return fields and applies a score floor — this ranks exactly as
    the campaign did (see :func:`campaign_rank`), on the latest user query.
    """

    name = "m3_campaign_minilm"

    def __init__(self, plan: Any = None):
        self._model = getattr(plan, "embedding_model", None) or MINILM_MODEL

    async def shortlist(self, request):
        import asyncio  # noqa: PLC0415

        from cuga.backend.cuga_graph.nodes.cuga_lite.shortlister.base import (  # noqa: PLC0415
            ShortlistCandidate,
            ShortlistResult,
        )

        tools = list(request.tools or [])
        top_k = request.top_k or len(tools)
        query = (request.query or getattr(request, "task_context", "") or "").strip()
        ranked = await asyncio.to_thread(
            campaign_rank, query, tools, top_k, lambda texts: _encode(self._model, texts)
        )
        if len(tools) > top_k:
            logger.info(
                "[m3-adapter shortlist] campaign ranking kept {}/{} tools ({} pinned retrievers)",
                len(ranked),
                len(tools),
                sum(1 for _, _, r in ranked if r == "pinned retriever"),
            )
        return ShortlistResult(
            candidates=[ShortlistCandidate(name=t.name, score=s, reasoning=r) for t, s, r in ranked]
        )


#: Dotted path for the two-stage tool pick (see ``CosinePickStrategy``).
PICK_STRATEGY_PATH = "benchmarks.m3.adapter.shortlist.CosinePickStrategy"

TOOL_PICK_PROMPT = """You choose the ONE API call that answers a user's question.

The APIs below were each generated from one specific database query, so a single API usually answers
the whole question at once: its name and description encode the question's filters, aggregation and
ordering. Prefer the one API whose description matches the WHOLE question over combining generic APIs.
Read parameter descriptions carefully and fill the arguments exactly as the API expects them.

Question: {query}

Candidate APIs:
{candidates}

Reply with JSON only: {{"tool": "<api name>", "arguments": {{...}}, "runner_up": "<api name>"}}"""


TOOL_RANK_PROMPT = """You rank the API calls that could answer a user's question.

The APIs below were each generated from one specific database query, so a single API usually answers the
whole question at once: its name and description encode the question's filters, aggregation and ordering.
Rank the candidates by how likely each one ALONE answers the WHOLE question, most likely first.

Question: {query}

Candidate APIs:
{candidates}

Reply with JSON only: {{"ranked": ["<api name>", ...]}} — the {n} most likely APIs, best first."""


def parse_tool_ranking(text: str, names: list) -> list:
    """The ``ranked`` list of the reply, candidates only, in order, without repeats."""
    import json  # noqa: PLC0415
    import re  # noqa: PLC0415

    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        data = json.loads(match.group(0)) if match else {}
    except ValueError:
        data = {}
    known = set(names)
    return list(dict.fromkeys(n for n in (data.get("ranked") or []) if isinstance(n, str) and n in known))


def render_tool_for_pick(tool: Any) -> str:
    """``- name: description`` plus every parameter's type and description."""
    props: dict = {}
    schema = getattr(tool, "args_schema", None)
    try:
        if schema is not None and hasattr(schema, "model_json_schema"):
            props = schema.model_json_schema().get("properties") or {}
        elif isinstance(schema, dict):
            props = schema.get("properties") or {}
    except Exception:  # noqa: BLE001  (render without parameters rather than fail the pick)
        props = {}
    params = "; ".join(f"{p} ({s.get('type', 'any')}): {s.get('description', '')}" for p, s in props.items())
    return (
        f"- {tool.name}: {(getattr(tool, 'description', '') or '').strip()}\n  parameters: {params or 'none'}"
    )


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, list):  # content blocks
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content or "")


def parse_tool_pick(text: str, names: list) -> tuple:
    """``(pick, runner_up)`` from the picker's JSON reply; names not among the candidates -> None.

    A bare name (no ``<domain>_`` prefix) matches the one candidate it suffixes.
    """
    import json  # noqa: PLC0415
    import re  # noqa: PLC0415

    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        data = json.loads(match.group(0)) if match else {}
    except ValueError:
        data = {}

    def resolve(value: Any) -> Optional[str]:
        if not isinstance(value, str) or not value.strip():
            return None
        value = value.strip()
        if value in names:
            return value
        suffixed = [n for n in names if n.endswith("_" + value)]
        return suffixed[0] if len(suffixed) == 1 else None

    pick = resolve(data.get("tool"))
    runner_up = resolve(data.get("runner_up"))
    return pick, (runner_up if runner_up != pick else None)


class CosinePickStrategy:
    """Two-stage tool narrowing as an SDK strategy (``Shortlister(strategy=<dotted path>)``).

    Stage 1 ranks the catalog by cosine similarity with the SDK's own embedding strategy (the
    configured model and text) and keeps the top ``pool``. Stage 2 asks the run's model, in one
    call, for the single API that answers the whole question, plus a runner-up. Returns
    ``[pick, runner_up, remaining cosine order]``; the bind cap keeps the first few. One pick per
    (query, catalog) per process: the bind cap re-shortlists on every model call of a task.
    A failed or unparsable pick falls back to the cosine order.
    """

    name = "m3_cosine_pick"
    # Process-wide settings (build_shortlister copies them from the AdapterConfig).
    pool = 32  # cosine width
    bind = 0  # tools returned per model call (0 = as many as CUGA asks for)
    widen = 0  # tools returned once the task has failed (0 = never widen)
    fill = "cosine"  # what follows [pick, runner-up]: "cosine" order or an LLM ranking ("llm")
    _picks: dict = {}  # (query, catalog names) -> ranked names
    _widened: set = set()  # questions whose task has failed: later model calls bind `widen` tools

    @classmethod
    def mark_failure(cls, query: str) -> None:
        """A call returned nothing / failed, or the answer checks re-ask: bind the wider set from now on."""
        if cls.widen and query.strip() and query.strip() not in cls._widened:
            cls._widened.add(query.strip())
            logger.info(
                "[m3-adapter tool-pick] failure in this task: later model calls bind {} tools", cls.widen
            )

    @classmethod
    def reset(cls, query: str) -> None:
        cls._widened.discard(query.strip())

    def __init__(self, plan: Any = None):
        self._plan = plan
        self._inner = None

    def _embedding(self):
        if self._inner is None:
            from cuga.backend.cuga_graph.nodes.cuga_lite.shortlister.embedding import (  # noqa: PLC0415
                EmbeddingShortlister,
            )

            plan = self._plan
            self._inner = EmbeddingShortlister(
                model_name=getattr(plan, "embedding_model", None),
                provider=getattr(plan, "embedding_provider", None),
                query_weight=getattr(plan, "query_weight", None),
                min_score=getattr(plan, "min_score", None),
            )
        return self._inner

    async def _cosine_order(self, request) -> list:
        import dataclasses  # noqa: PLC0415

        width = min(self.pool, len(request.tools))
        result = await self._embedding().shortlist(
            dataclasses.replace(request, top_k=width, max_results=None)
        )
        return [c.name for c in result.candidates][:width]

    async def _pick(self, query: str, candidates: list, llm: Any) -> tuple:
        if llm is None:
            return None, None
        prompt = TOOL_PICK_PROMPT.format(
            query=query, candidates="\n".join(render_tool_for_pick(t) for t in candidates)
        )
        reply = await llm.ainvoke(prompt)
        return parse_tool_pick(_message_text(reply), [t.name for t in candidates])

    async def _llm_rank(self, query: str, candidates: list, llm: Any, n: int) -> list:
        """A second LLM call: the candidates ranked by how likely each alone answers the question."""
        if llm is None or n <= 0:
            return []
        prompt = TOOL_RANK_PROMPT.format(
            query=query, n=n, candidates="\n".join(render_tool_for_pick(t) for t in candidates)
        )
        return parse_tool_ranking(_message_text(await llm.ainvoke(prompt)), [t.name for t in candidates])

    async def shortlist(self, request):
        from cuga.backend.cuga_graph.nodes.cuga_lite.shortlister.base import (  # noqa: PLC0415
            ShortlistCandidate,
            ShortlistResult,
        )

        tools = list(request.tools or [])
        query = (request.query or "").strip()
        key = (query, tuple(sorted(t.name for t in tools)))
        ranked = self._picks.get(key)
        if ranked is None:
            cosine = await self._cosine_order(request)
            by_name = {t.name: t for t in tools}
            pool = [by_name[n] for n in cosine if n in by_name]
            try:
                pick, runner_up = await self._pick(query, pool, request.llm)
            except Exception as exc:  # noqa: BLE001  (never fail the model call over the pick)
                logger.warning("[m3-adapter tool-pick] pick call failed ({}); keeping the cosine order", exc)
                pick, runner_up = None, None
            head = [n for n in (pick, runner_up) if n]
            middle: list = []
            if self.fill == "llm":
                try:
                    middle = await self._llm_rank(query, pool, request.llm, max(self.bind, self.widen))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[m3-adapter tool-pick] ranking call failed ({}); filling by cosine", exc)
            middle = [n for n in middle if n not in head]
            ranked = list(dict.fromkeys(head + middle + [n for n in cosine if n not in head]))
            self._picks[key] = ranked
            logger.info(
                "[m3-adapter tool-pick] {} tools -> cosine top {} -> pick {} (runner-up {}){}",
                len(tools),
                len(pool),
                pick,
                runner_up,
                "" if pick else " — no valid pick, cosine order kept",
            )
        top_k = request.top_k or len(ranked)
        count = self.widen if (self.widen and query in self._widened) else self.bind
        if count:
            top_k = min(top_k, count)
        return ShortlistResult(
            candidates=[
                ShortlistCandidate(name=n, score=float(len(ranked) - i), reasoning="tool pick")
                for i, n in enumerate(ranked[:top_k])
            ]
        )


class PromptLLM:
    """``ainvoke(prompt)`` over a prompt -> text coroutine (the adapter's own LLM helper)."""

    def __init__(self, fn):
        self._fn = fn

    async def ainvoke(self, prompt: Any) -> str:
        return await self._fn(prompt)


async def prepick_tool(query: str, tools: list, cfg: AdapterConfig, llm_ainvoke) -> Optional[str]:
    """Run the FC pick before the agent does (for ``tool_pick_hint``); CUGA's bind-time call reuses it.

    The cache key is (question, catalog names): the same tools CUGA's bind cap will rank.
    """
    from types import SimpleNamespace  # noqa: PLC0415

    from cuga.backend.cuga_graph.nodes.cuga_lite.shortlister.base import ShortlistRequest  # noqa: PLC0415

    plan = SimpleNamespace(
        embedding_model=cfg.shortlist_model,
        embedding_provider=EMBEDDING_PROVIDER,
        query_weight=1.0,
        min_score=0.0,
    )
    result = await CosinePickStrategy(plan=plan).shortlist(
        ShortlistRequest(query=query, tools=list(tools), apps=[], top_k=None, llm=PromptLLM(llm_ainvoke))
    )
    return result.candidates[0].name if result.candidates else None


TOOL_PICK_CONVERSATION_PROMPT = """You choose the ONE API call that answers the user's latest question in a conversation.

The APIs below were each generated from one specific database query (or search a document collection), so a
single API usually answers the whole question: its name and description encode the question's filters,
aggregation and ordering. The latest question may refer to earlier turns; resolve those references first.
Respect the policy, if any.

Policy: {policy}

Conversation so far:
{history}

Latest question: {query}

Candidate APIs:
{candidates}

Reply with JSON only: {{"tool": "<api name>", "runner_up": "<api name>"}}"""


def conversation_history(message: Any, max_answer_chars: int = 300) -> str:
    """The turns before the latest user turn, as ``User:`` / ``Assistant:`` lines."""
    if not isinstance(message, list):
        return "(none)"
    turns = list(message)
    for i in range(len(turns) - 1, -1, -1):  # drop the latest user turn: it is the question
        if getattr(turns[i], "type", "") == "human":
            turns = turns[:i]
            break
    lines = []
    for m in turns:
        role = "User" if getattr(m, "type", "") == "human" else "Assistant"
        text = _message_text(m)
        lines.append(f"{role}: {text if role == 'User' else text[:max_answer_chars]}")
    return "\n".join(lines) or "(none)"


async def pick_turn_tools(
    query: str, history: str, policy: str, tools: list, cfg: AdapterConfig, llm_ainvoke
) -> list:
    """Tool names to expose this turn: [pick, runner-up, cosine fill] up to ``tool_pick_bind``, plus retrievers.

    The candidates are the campaign's ranking (``campaign_rank``: retrievers pinned, then cosine) cut to
    ``tool_pick_pool``; one LLM call picks with the conversation and the policy. Retrievers stay exposed
    (the campaign always pinned them; the policy scope may still remove them). An invalid pick keeps
    the cosine order.
    """
    import asyncio  # noqa: PLC0415

    from benchmarks.m3.adapter.recording import bare_tool_name  # noqa: PLC0415

    ranked = await asyncio.to_thread(
        campaign_rank, query, tools, cfg.tool_pick_pool, lambda texts: _encode(cfg.shortlist_model, texts)
    )
    candidates = [t for t, _, _ in ranked]
    names = [t.name for t in candidates]
    prompt = TOOL_PICK_CONVERSATION_PROMPT.format(
        policy=(policy or "none").strip()[:1500],
        history=history,
        query=query,
        candidates="\n".join(render_tool_for_pick(t) for t in candidates),
    )
    try:
        pick, runner_up = parse_tool_pick(await llm_ainvoke(prompt), names)
    except Exception as exc:  # noqa: BLE001  (never fail the turn over the pick)
        logger.warning("[m3-adapter tool-pick] pick call failed ({}); keeping the cosine order", exc)
        pick, runner_up = None, None
    retrievers = [t.name for t in tools if bare_tool_name(t).startswith("query_")]
    head = [n for n in (pick, runner_up) if n]
    rest = [n for n in names if n not in head and n not in retrievers]
    exposed = (head + rest)[: cfg.tool_pick_bind]
    logger.info(
        "[m3-adapter tool-pick] {} tools -> pool {} -> pick {} (runner-up {}); exposing {} + {} retrievers",
        len(tools),
        len(candidates),
        pick,
        runner_up,
        exposed,
        len(retrievers),
    )
    return exposed + [r for r in retrievers if r not in exposed]


EMBEDDING_PROVIDER = "local"  # sentence-transformers in-process, like the validated runs


def prewarm_embedding_backend(cfg: AdapterConfig) -> Optional[bool]:
    """Load the MiniLM backend now, so the very first shortlist call already ranks with it.

    The SDK loads embedding backends lazily in the background and serves a call
    that arrives before the load finished with its ``llm`` fallback. In the M3
    eval every domain is a fresh process, so without this the first task of every
    domain would be shortlisted by an LLM instead of the validated cosine ranking.
    Returns True/False for loaded/failed, None when the SDK exposes no prewarm.
    """
    try:
        from cuga.backend.cuga_graph.nodes.cuga_lite.shortlister.embedding import prewarm  # noqa: PLC0415
    except Exception:  # noqa: BLE001  (fake/partial cuga in tests, older checkouts)
        return None
    try:
        loaded = bool(prewarm(EMBEDDING_PROVIDER, cfg.shortlist_model))
    except Exception as exc:  # noqa: BLE001  (never fail agent construction over a warm-up)
        logger.warning(
            "[m3-adapter shortlist] embedding prewarm raised ({}); first call may use the LLM fallback", exc
        )
        return False
    if not loaded:
        logger.warning(
            "[m3-adapter shortlist] embedding backend {}:{} did not load; the SDK will shortlist with its LLM "
            "fallback — not the validated MiniLM ranking",
            EMBEDDING_PROVIDER,
            cfg.shortlist_model,
        )
    return loaded


def build_shortlister(cfg: AdapterConfig) -> Optional[Any]:
    """Build the SDK ``Shortlister`` for a preset (None when no top-k is set).

    ``threshold=top_k`` engages the cosine stage only above top_k candidates —
    at or below it the catalog passes through untouched, which is exactly the
    validated runs' "top-k 128 => effectively no trimming" semantics. The
    embedding backend is pre-warmed here (see ``prewarm_embedding_backend``).
    """
    fc_pick = cfg.tool_pick and cfg.execution_mode == "function_calling"  # CodeAct picks per turn (agent.py)
    if not cfg.shortlist_top_k and not fc_pick:
        return None
    # Lazy: cuga optional at import time. `Shortlister` is re-exported at the
    # package top level; cuga.sdk only names it under TYPE_CHECKING.
    from cuga.backend.cuga_graph.nodes.cuga_lite.shortlister import Shortlister  # noqa: PLC0415

    if fc_pick:
        # top_k/threshold = the bind count, so the strategy runs for every catalog above it; the
        # bind cap (pinned to the same number, config.cuga_setting_pins) makes CUGA ask for it.
        prewarm_embedding_backend(cfg)
        cap = max(
            cfg.tool_pick_bind, cfg.tool_pick_widen
        )  # the strategy returns `bind`, or `widen` after a failure
        CosinePickStrategy.pool = cfg.tool_pick_pool
        CosinePickStrategy.bind = cfg.tool_pick_bind
        CosinePickStrategy.widen = cfg.tool_pick_widen
        CosinePickStrategy.fill = cfg.tool_pick_fill
        return Shortlister(
            strategy=PICK_STRATEGY_PATH,
            embedding_model=cfg.shortlist_model,
            embedding_provider=EMBEDDING_PROVIDER,
            top_k=cap,
            threshold=cap,
            min_score=0.0,
            query_weight=1.0,
        )
    if cfg.shortlist_strategy == "campaign":
        try:
            _sentence_model(cfg.shortlist_model)  # load now: the first task must rank like the rest
        except Exception as exc:  # noqa: BLE001  (surface loudly; the SDK would fall back to its LLM ranker)
            logger.error(
                "[m3-adapter shortlist] campaign strategy could not load {}: {}", cfg.shortlist_model, exc
            )
        strategy = CAMPAIGN_STRATEGY_PATH
    else:
        prewarm_embedding_backend(cfg)
        MiniLMPinnedStrategy.pin_retrievers = cfg.shortlist_pin_retrievers
        MiniLMPinnedStrategy.pin_pattern = cfg.shortlist_pin_pattern
        pinned = cfg.shortlist_pin_retrievers or bool(cfg.shortlist_pin_pattern)
        strategy = PINNED_STRATEGY_PATH if pinned else "embedding"
    return Shortlister(
        strategy=strategy,
        embedding_model=cfg.shortlist_model,
        embedding_provider=EMBEDDING_PROVIDER,
        top_k=cfg.shortlist_top_k,
        threshold=cfg.shortlist_top_k,
        min_score=0.0,
        query_weight=1.0,
    )
