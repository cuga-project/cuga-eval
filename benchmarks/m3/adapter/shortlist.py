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
        retrievers = [t.name for t in request.tools if is_retriever(t.name)]
        pinned = [
            ShortlistCandidate(name=n, score=scores.get(n, 1.0), reasoning="pinned retriever")
            for n in retrievers
        ]
        rest = [c for c in ranked if c.name not in set(retrievers)]
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
    if not cfg.shortlist_top_k:
        return None
    # Lazy: cuga optional at import time. `Shortlister` is re-exported at the
    # package top level; cuga.sdk only names it under TYPE_CHECKING.
    from cuga.backend.cuga_graph.nodes.cuga_lite.shortlister import Shortlister  # noqa: PLC0415

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
        strategy = PINNED_STRATEGY_PATH if cfg.shortlist_pin_retrievers else "embedding"
    return Shortlister(
        strategy=strategy,
        embedding_model=cfg.shortlist_model,
        embedding_provider=EMBEDDING_PROVIDER,
        top_k=cfg.shortlist_top_k,
        threshold=cfg.shortlist_top_k,
        min_score=0.0,
        query_weight=1.0,
    )
