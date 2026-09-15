"""Prose few-shot demos from solved train samples (ported from ``_DemoRetriever``).

The validated caps 1-3 runs injected k=2 similar solved examples per query as
chat pairs through CUGA's documented ``configurable["mcp_few_shot_examples"]``
channel (``VAKRA_CUGA_DEMOS=1, DEMOS_MODE=prose``): a user turn with the solved
query, an assistant turn with the tool chain used and the final answer.

The corpus is read from an explicit demo source — ``--demo-data`` /
``M3_ADAPTER_DEMO_DATA``, default the bundled train split — never from the
samples under evaluation (see ``load_demo_corpus``). Entries are
``dialogue.turns[i].query`` + ``expected_output.gold_sequence[i]`` +
``expected_output.answer_per_turn[i]`` (no new data files). Similarity uses the
same MiniLM model as the original (``sentence-transformers`` is already a repo
dependency); with no usable corpus the feature degrades to a no-op.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, List, Optional, Union

from loguru import logger

from benchmarks.m3.adapter.config import AdapterConfig

#: Default demo corpus: the bundled VAKRA train split (CC BY-NC-SA; see data/NOTICE).
DEFAULT_DEMO_DATA = Path(__file__).resolve().parents[1] / "data" / "small_train.zip"


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


# ---------------------------------------------------------------------------
# Corpus source
# ---------------------------------------------------------------------------


def resolve_demo_source(demo_data: Optional[str]) -> Path:
    """Path of the demo corpus: the configured one, else the bundled train split."""
    return Path(demo_data).expanduser() if demo_data else DEFAULT_DEMO_DATA


def _same_path(a: Union[str, Path], b: Union[str, Path]) -> bool:
    try:
        return Path(a).expanduser().resolve() == Path(b).expanduser().resolve()
    except OSError:
        return str(a) == str(b)


def _default_loader(source: Path):
    from benchmarks.m3.m3_data_loader import M3DataLoader  # noqa: PLC0415  (cuga-eval module, lazy)

    return M3DataLoader(source)


def load_demo_corpus(
    cfg: AdapterConfig,
    *,
    task_id: int,
    domain: str,
    eval_source: Optional[Union[str, Path]] = None,
    loader_factory: Optional[Callable[[Path], Any]] = None,
) -> Optional[List[dict]]:
    """Solved samples to build demos from, or None (demos off / nothing usable).

    The corpus always comes from an explicit demo source (``cfg.demo_data``, i.e.
    ``--demo-data`` / ``M3_ADAPTER_DEMO_DATA``, default the bundled train split),
    loaded for the run's own task/domain — never implicitly from the samples
    being evaluated: those carry gold tool chains and answers, and injecting them
    as few-shots for sibling items of a test split is label leakage. When the
    demo source *is* the evaluated data the run is warned; that is acceptable
    only for train-split smoke runs. Every failure degrades to "no demos".
    """
    if not cfg.demos:
        return None
    source = resolve_demo_source(cfg.demo_data)
    if eval_source is not None and _same_path(source, eval_source):
        logger.warning(
            "[m3-adapter demos] demo source is the evaluated data ({}): sibling items' gold chains "
            "and answers become few-shots. Fine for train-split runs; never report test scores from it.",
            source,
        )
    if not source.exists():
        logger.warning("[m3-adapter demos] demo source {} not found; running without demos", source)
        return None
    try:
        samples = (loader_factory or _default_loader)(source).load_domain(task_id, domain)
    except Exception as exc:  # noqa: BLE001  (demos are best-effort; never fail the run)
        logger.warning(
            "[m3-adapter demos] no demos for task_{}/{} from {} ({}); running without demos",
            task_id,
            domain,
            source,
            exc,
        )
        return None
    if not samples:
        logger.info("[m3-adapter demos] demo source {} has no task_{}/{} samples", source, task_id, domain)
        return None
    logger.info(
        "[m3-adapter demos] {} demo samples for task_{}/{} from {}", len(samples), task_id, domain, source
    )
    return samples
