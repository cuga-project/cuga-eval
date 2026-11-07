"""MuSiQue and 2WikiMultihopQA as knowledge retrieval suites, ported from ProactiveInquirer.

Ports ``pi_eval/build/musique_build.py`` and ``wiki2_build.py`` (ProactiveInquirer, Apache-2.0):
same sources and SHA-256 pins, the same gold need graphs and the same depth semantics, without
the on-disk corpus and gold files, which only serve the paper's leakage controls.

Each task is a question with its own paragraph pool (MuSiQue: 20 paragraphs, 2Wiki: 10). The
retrieval side sees only the question and the paragraphs. The gold side records which
paragraphs a correct answer needs and at what hop depth:

- MuSiQue: one node per step of the human-written ``question_decomposition``; a step that says
  "#2" needs step 2 first. Gold evidence is the step's ``paragraph_support_idx``.
- 2Wiki: one node per evidence triple, chained object -> subject for compositional, inference
  and bridge-comparison questions; comparison questions are flat. Gold evidence is the
  paragraph titled with the triple's subject; triples that match no paragraph are dropped,
  as PI marks them untestable.

Depth is the longest prerequisite path from the question (PI's ``semantics="all"``). When two
nodes rest on the same paragraph, the paragraph keeps the shallower depth.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from collections.abc import Iterable
from pathlib import Path

from benchmarks.knowledge.synth import Doc, Task

CACHE = Path(os.environ.get("CUGA_EVAL_CACHE", "~/.cache/cuga-eval/knowledge")).expanduser()

MUSIQUE_URL = "https://huggingface.co/datasets/dgslibisey/MuSiQue/resolve/main/musique_ans_v1.0_dev.jsonl"
MUSIQUE_SHA256 = (
    "15fa63794d18a94ce12411aca6e2327e65b6e83b0b1490efab3f1962e48abf3b"  # pragma: allowlist secret
)
WIKI2_URL = "https://huggingface.co/datasets/xanhho/2WikiMultihopQA/resolve/main/dev.parquet"
WIKI2_SHA256 = "c0d8b60b9026b728fb07ad74c5252a0f188f6942e8ba5c02df4dfa369502ea8d"  # pragma: allowlist secret

_REF = re.compile(r"#(\d+)")
_PARENS = re.compile(r"\s*\([^)]*\)")
_NONWORD = re.compile(r"[^a-z0-9]+")
_CHAIN_TYPES = frozenset({"compositional", "inference", "bridge_comparison"})


def fetch(url: str, sha256: str, cache: Path = CACHE) -> Path:
    """Download ``url`` once into ``cache`` and refuse it unless its SHA-256 matches."""
    path = cache / url.rsplit("/", 1)[-1]
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(path.suffix + ".part")
        urllib.request.urlretrieve(url, part)  # noqa: S310 - fixed https URL, verified below
        part.rename(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != sha256:
        raise ValueError(f"{path} has sha256 {digest}, expected {sha256}; delete it to re-download")
    return path


def longest_path_depths(n: int, parents: dict[int, set[int]]) -> dict[int, int]:
    """Depth of each node 0..n-1: 0 without prerequisites, else 1 + the deepest prerequisite."""
    depth: dict[int, int] = {}

    def visit(i: int, stack: frozenset[int]) -> int:
        if i not in depth:
            ps = [p for p in parents.get(i, ()) if p not in stack]
            depth[i] = 1 + max(visit(p, stack | {i}) for p in ps) if ps else 0
        return depth[i]

    for i in range(n):
        visit(i, frozenset())
    return depth


def _gold(nodes: Iterable[tuple[str, int]]) -> dict[str, int]:
    gold: dict[str, int] = {}
    for doc_id, d in nodes:
        gold[doc_id] = min(d, gold.get(doc_id, d))
    return gold


def _stratified(tasks: list[Task], strata: list[str], limit: int | None) -> list[Task]:
    """Round-robin across strata (hop class or question type), so any prefix stays balanced.

    MuSiQue's dev file is sorted by hop count, so a head-N sample would be all 2-hop.
    """
    if limit is None:
        return tasks
    pools: dict[str, list[Task]] = {}
    for task, stratum in zip(tasks, strata):
        pools.setdefault(stratum, []).append(task)
    queues = [pools[k] for k in sorted(pools)]
    out: list[Task] = []
    while len(out) < limit and any(queues):
        for q in queues:
            if q and len(out) < limit:
                out.append(q.pop(0))
    return out


def musique_task(rec: dict) -> Task:
    tid = rec["id"]
    paragraphs = sorted(rec["paragraphs"], key=lambda p: p["idx"])
    docs = tuple(Doc(f"{tid}:{p['idx']}", p["title"], p["paragraph_text"]) for p in paragraphs)
    steps = rec["question_decomposition"]
    parents = {
        i: {int(m) - 1 for m in _REF.findall(s["question"]) if 0 < int(m) <= len(steps) and int(m) != i + 1}
        for i, s in enumerate(steps)
    }
    depth = longest_path_depths(len(steps), parents)
    valid = {p["idx"] for p in paragraphs}
    nodes = [
        (f"{tid}:{s['paragraph_support_idx']}", depth[i])
        for i, s in enumerate(steps)
        if s.get("paragraph_support_idx") in valid
    ]
    return Task(tid, rec["question"], docs, _gold(nodes), rec.get("answer", ""))


def musique(limit: int | None = None, path: Path | None = None) -> list[Task]:
    path = path or fetch(MUSIQUE_URL, MUSIQUE_SHA256)
    recs = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    recs = [r for r in recs if r.get("answerable", True)]
    return _stratified([musique_task(r) for r in recs], [r["id"].split("__")[0] for r in recs], limit)


def _key(title: str) -> str:
    """'Charles Saunders (director)' and 'Charles Saunders' are one entity in 2Wiki."""
    return _NONWORD.sub(" ", _PARENS.sub("", title).lower()).strip()


def _rows(value) -> list[list]:
    """2Wiki ships lists of lists; some exports ship them column-wise as a dict."""
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, dict):
        return [list(t) for t in zip(*value.values())]
    return [list(v) for v in value]


def _locate(entity: str, titles: list[str], preferred: set[str]) -> int | None:
    """The paragraph describing ``entity``: exact title first, then containment;
    paragraphs named in ``supporting_facts`` win ties."""
    ek = _key(entity)
    order = sorted(range(len(titles)), key=lambda i: (titles[i] not in preferred, i))
    for exact in (True, False):
        for i in order:
            tk = _key(titles[i])
            if (tk == ek) if exact else (ek and (ek in tk or tk in ek)):
                return i
    return None


def wiki2_task(rec: dict) -> Task:
    tid = rec.get("_id") or rec["id"]
    context = _rows(rec["context"])
    titles = [title for title, _ in context]
    docs = tuple(
        Doc(f"{tid}:{i}", title, " ".join(s.strip() for s in sents))
        for i, (title, sents) in enumerate(context)
    )
    triples = [t for t in _rows(rec.get("evidences", [])) if len(t) >= 3]
    preferred = {row[0] for row in _rows(rec.get("supporting_facts", []))}
    subjects = [_key(t[0]) for t in triples]
    objects = [_key(t[2]) for t in triples]
    parents: dict[int, set[int]] = {}
    if str(rec.get("type", "")).replace("-", "_").lower() in _CHAIN_TYPES:
        for i in range(len(triples)):
            for j in range(i + 1, len(triples)):
                if objects[i] and objects[i] == subjects[j]:
                    parents.setdefault(j, set()).add(i)
    depth = longest_path_depths(len(triples), parents)
    nodes = []
    for i, t in enumerate(triples):
        idx = _locate(t[0], titles, preferred)
        if idx is not None:
            nodes.append((f"{tid}:{idx}", depth[i]))
    return Task(tid, rec["question"], docs, _gold(nodes), rec.get("answer", ""))


def wiki2(limit: int | None = None, path: Path | None = None) -> list[Task]:
    import pyarrow.parquet as pq

    path = path or fetch(WIKI2_URL, WIKI2_SHA256)
    recs = pq.read_table(path).to_pylist()
    tasks = [wiki2_task(r) for r in recs]
    keep = [i for i, t in enumerate(tasks) if t.gold_depth]  # every triple unlocatable: nothing to score
    return _stratified([tasks[i] for i in keep], [str(recs[i].get("type", "")) for i in keep], limit)
