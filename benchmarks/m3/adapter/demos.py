"""Prose few-shot demos from solved train samples (ported from ``_DemoRetriever``).

The validated caps 1-3 runs injected k=2 similar solved examples per query as
chat pairs through CUGA's documented ``configurable["mcp_few_shot_examples"]``
channel (``VAKRA_CUGA_DEMOS=1, DEMOS_MODE=prose``): a user turn with the solved
query, an assistant turn with the tool chain used and the final answer.

The corpus comes from the merged m3-data samples the eval already loads (no new
data files): ``dialogue.turns[i].query`` + ``expected_output.gold_sequence[i]``
+ ``expected_output.answer_per_turn[i]``. Similarity uses the same MiniLM model
as the original (``sentence-transformers`` is already a repo dependency); with
no usable corpus the feature degrades to a no-op.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

from loguru import logger


def _iter_calls(gold_turn: Any):
    """Yield ``{name, arguments}`` dicts from a per-turn gold_sequence entry.

    Tolerant to shape: the entry may be a dict with ``tool_call`` holding
    per-call groups (dicts or lists of dicts), or already a list of calls.
    """
    if isinstance(gold_turn, dict):
        gold_turn = gold_turn.get("tool_call", [])
    if not isinstance(gold_turn, list):
        return
    for entry in gold_turn:
        if isinstance(entry, dict) and entry.get("name"):
            yield entry
        elif isinstance(entry, list):
            for sub in entry:
                if isinstance(sub, dict) and sub.get("name"):
                    yield sub


def _format_call(call: dict) -> str:
    args = dict(call.get("arguments") or {})
    args.pop("database_path", None)  # authoring-machine path, irrelevant noise
    compact = {k: (str(v)[:60] + "…" if len(str(v)) > 60 else v) for k, v in args.items()}
    return f"{call.get('name')}({json.dumps(compact, ensure_ascii=False, default=str)})"


class DemoIndex:
    """Embedded (query, calls, answer) entries for one demo corpus."""

    def __init__(self, entries: List[dict]):
        self.entries = entries
        self._embeddings = None
        self._model = None

    def _embedder(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415  (lazy, heavy)

            self._model = SentenceTransformer("all-MiniLM-L6-v2")
        return self._model

    def _ensure_embeddings(self):
        if self._embeddings is None and self.entries:
            self._embeddings = self._embedder().encode(
                [e["query"] for e in self.entries], convert_to_numpy=True
            )
        return self._embeddings


def build_demo_index(samples: Optional[List[dict]]) -> Optional[DemoIndex]:
    """Extract solved (query, calls, answer) turns from merged m3-data samples."""
    if not samples:
        return None
    entries: List[dict] = []
    for sample in samples:
        turns = (sample.get("dialogue") or {}).get("turns") or []
        expected = sample.get("expected_output") or {}
        gold = expected.get("gold_sequence") or []
        answers = expected.get("answer_per_turn") or []
        for i, turn in enumerate(turns):
            query = (turn or {}).get("query")
            if not query:
                continue
            calls = list(_iter_calls(gold[i] if i < len(gold) else None))
            if not calls:
                continue
            answer = answers[i] if i < len(answers) else None
            entries.append({"query": query, "calls": calls, "answer": answer})
    if not entries:
        return None
    return DemoIndex(entries)


def select_prose_pairs(index: Optional[DemoIndex], query: str, k: int) -> List[dict]:
    """Top-k similar solved examples as ``mcp_few_shot_examples`` chat pairs."""
    if index is None or k <= 0 or not index.entries:
        return []
    try:
        embeddings = index._ensure_embeddings()
        if embeddings is None:
            return []
        import numpy as np  # noqa: PLC0415  (transitively available via sentence-transformers)

        q = index._embedder().encode([query], convert_to_numpy=True)
        sims = (embeddings / np.maximum(np.linalg.norm(embeddings, axis=1, keepdims=True), 1e-9)) @ (
            q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-9)
        ).T
        order = np.argsort(sims.squeeze(axis=1))[::-1]
    except Exception as exc:  # noqa: BLE001  (demos are best-effort; never fail the run)
        logger.warning("[m3-adapter demos] embedding failed ({}); skipping demos", exc)
        return []
    pairs: List[dict] = []
    picked = 0
    for i in order:
        e = index.entries[int(i)]
        if e["query"].strip() == query.strip():
            continue  # self-leak guard: never use a task as its own demo
        chain = " -> ".join(_format_call(c) for c in e["calls"][:6])
        pairs.append({"role": "user", "content": e["query"]})
        pairs.append(
            {
                "role": "assistant",
                "content": (
                    f"Chain used: {chain}\nFinal answer: {json.dumps(e['answer'], default=str)[:120]}"
                ),
            }
        )
        picked += 1
        if picked >= k:
            break
    return pairs
