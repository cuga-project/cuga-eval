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

from benchmarks.m3.adapter.config import AdapterConfig
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

    prewarm_embedding_backend(cfg)
    return Shortlister(
        strategy=PINNED_STRATEGY_PATH if cfg.shortlist_pin_retrievers else "embedding",
        embedding_model=cfg.shortlist_model,
        embedding_provider=EMBEDDING_PROVIDER,
        top_k=cfg.shortlist_top_k,
        threshold=cfg.shortlist_top_k,
        min_score=0.0,
        query_weight=1.0,
    )
