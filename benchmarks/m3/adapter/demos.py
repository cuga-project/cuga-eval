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
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Union

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


def bound_tool_namer(tool_names: Iterable[str]) -> Callable[[str], str]:
    """Map a corpus tool name to the name the agent is bound with.

    Demo chains carry the environment's raw tool names; a registry-backed provider
    exposes the same tools as ``<domain>_<tool>``. A raw name maps to the bound name
    equal to it or ending in ``_<raw>`` (the shortest such name — the plain domain
    prefix — when several match); a name with no match is left as is.
    """
    names = sorted(set(tool_names), key=len)

    def namer(raw: str) -> str:
        for name in names:
            if name == raw or name.endswith("_" + raw):
                return name
        return raw

    return namer


def _format_call(call: dict, namer: Optional[Callable[[str], str]] = None) -> str:
    raw = call.get("arguments") or {}
    if isinstance(raw, str):  # some corpora serialize the arguments as a JSON string
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {"_raw": raw}
    args = dict(raw) if isinstance(raw, dict) else {"_raw": raw}  # odd shapes stay visible, never raise
    args.pop("database_path", None)  # authoring-machine path, irrelevant noise
    compact = {k: (str(v)[:60] + "…" if len(str(v)) > 60 else v) for k, v in args.items()}
    name = call.get("name")
    if namer is not None and isinstance(name, str):
        name = namer(name)
    return f"{name}({json.dumps(compact, ensure_ascii=False, default=str)})"


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
            if not isinstance(query, str) or not query.strip():
                continue  # select_prose_pairs / the embedder need real text
            calls = list(_iter_calls(gold[i] if i < len(gold) else None))
            if not calls:
                continue
            answer = answers[i] if i < len(answers) else None
            entries.append({"query": query, "calls": calls, "answer": answer})
    if not entries:
        return None
    return DemoIndex(entries)


class ParamValueIndex:
    """The argument values the domain's solved examples passed, per parameter name.

    The data's value conventions (codes like ``'F'``/``'W'``, ``'2y all'``, LIKE patterns,
    fractions) are invisible in the tool schemas; other questions' gold calls show them.
    """

    MAX_VALUE_CHARS = 60

    def __init__(self, entries: List[dict]):
        self._rows: List[tuple] = []  # (question, parameter, value)
        for entry in entries:
            question = str(entry.get("query") or "").strip()
            for call in entry.get("calls") or []:
                args = call.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        continue
                if not isinstance(args, dict):
                    continue
                for param, value in args.items():
                    if param == "database_path" or value is None or isinstance(value, (dict, list)):
                        continue
                    text = str(value).strip()
                    if text and len(text) <= self.MAX_VALUE_CHARS:
                        self._rows.append((question, param, text))

    def examples(self, params: Iterable[str], exclude_query: str = "", k: int = 6) -> Dict[str, List[str]]:
        """``{param: up to k values, most used first}``, never from the question being asked."""
        asked = (exclude_query or "").strip()
        out: Dict[str, List[str]] = {}
        for param in params:
            counts = Counter(v for q, p, v in self._rows if p == param and q != asked)
            if counts:
                out[param] = [v for v, _ in counts.most_common(k)]
        return out


def build_param_value_index(samples: Optional[List[dict]]) -> Optional[ParamValueIndex]:
    index = build_demo_index(samples)
    return ParamValueIndex(index.entries) if index is not None else None


class ToolUsageIndex:
    """The solved questions each tool's gold calls answered, per raw tool name (lowercased)."""

    MAX_QUESTION_CHARS = 200

    def __init__(self, entries: List[dict]):
        self._by_tool: Dict[str, List[str]] = {}
        for entry in entries:
            question = str(entry.get("query") or "").strip()
            for call in entry.get("calls") or []:
                name = str(call.get("name") or "").lower()
                if name and question:
                    questions = self._by_tool.setdefault(name, [])
                    if question not in questions:
                        questions.append(question)

    def questions(self, tool_name: str, exclude_query: str = "", k: int = 2) -> List[str]:
        """Up to k questions for a bound tool (``<domain>_<raw>`` or raw), never the question being asked."""
        name = tool_name.lower()
        found = self._by_tool.get(name)
        while found is None and "_" in name:  # bound names carry a registry prefix
            name = name.split("_", 1)[1]
            found = self._by_tool.get(name)
        asked = (exclude_query or "").strip()
        return [q[: self.MAX_QUESTION_CHARS] for q in (found or []) if q != asked][:k]


def build_tool_usage_index(samples: Optional[List[dict]]) -> Optional[ToolUsageIndex]:
    index = build_demo_index(samples)
    return ToolUsageIndex(index.entries) if index is not None else None


def load_tool_usage_corpus(
    cfg: AdapterConfig, *, domain: str, eval_source: Optional[Union[str, Path]] = None, **kwargs: Any
) -> Optional[List[dict]]:
    """The demo source's caps 2-4 samples of ``domain`` (one API catalogue), or None (off / none)."""
    if not cfg.tool_usage_examples:
        return None
    samples: List[dict] = []
    for task_id in (2, 3, 4):
        samples += (
            load_demo_corpus(cfg, task_id=task_id, domain=domain, eval_source=eval_source, **kwargs) or []
        )
    return samples or None


def select_prose_pairs(
    index: Optional[DemoIndex], query: str, k: int, namer: Optional[Callable[[str], str]] = None
) -> List[dict]:
    """Top-k similar solved examples as ``mcp_few_shot_examples`` chat pairs.

    ``namer`` (see :func:`bound_tool_namer`) renames chain tools to the bound names.
    """
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
        chain = " -> ".join(_format_call(c, namer) for c in e["calls"][:6])
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
    if not (cfg.demos or cfg.param_value_examples or cfg.tool_usage_examples):
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
