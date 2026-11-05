"""Synthetic multi-hop retrieval suite, ported from ProactiveInquirer.

Port of ``pi_eval/build/synth_build.py::build`` (ProactiveInquirer, Apache-2.0, commit a7358f9).
Same tokens, texts, seed and shuffle order, so task ``s{t}`` is the upstream task. The defaults
reproduce the upstream corpus ``data/corpora/synth/61fd50eebdb994c7`` (6-hop chains; the
upstream builder's own default is 3). Dropped:
canaries, the gold-graph firewall and on-disk output, which only serve the paper's leakage
controls.

Each task chains records: a record is found by its own token and names the next record's token.
The question names only the depth-0 tokens, so depth d is reachable only after reading depth d-1.
Distractor notes share the format but belong to no chain.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Doc:
    doc_id: str
    title: str
    text: str


@dataclass(frozen=True)
class Task:
    task_id: str
    question: str
    docs: tuple[Doc, ...]
    gold_depth: dict[str, int]  # required doc_id -> hop depth (0 = token stated in the question)
    answer: str


def _token(task: int, facet: int, depth: int) -> str:
    return "K" + hashlib.sha256(f"{task}:{facet}:{depth}".encode()).hexdigest()[:8].upper()


def build(
    n_tasks: int = 24, n_facets: int = 3, depth: int = 6, n_distractors: int = 6, seed: int = 7
) -> list[Task]:
    rng = random.Random(seed)  # noqa: S311 — seeded on purpose: reproduces the upstream suite, not crypto
    tasks: list[Task] = []
    for t in range(n_tasks):
        docs: list[dict[str, str]] = []
        gold: dict[str, int] = {}
        answers: list[str] = []
        for f in range(n_facets):
            for d in range(depth):
                tok = _token(t, f, d)
                nxt = _token(t, f, d + 1) if d + 1 < depth else ""
                body = f"Record {tok}. The value for facet {f} step {d} is V{t}{f}{d}." + (
                    f" To continue, consult record {nxt}." if nxt else " This is the final step."
                )
                docs.append({"doc_id": f"{t}:{f}:{d}", "title": f"Record {tok}", "text": body})
                gold[f"{t}:{f}:{d}"] = d
            answers.append(f"V{t}{f}{depth - 1}")
        for j in range(n_distractors):
            tok = "D" + hashlib.sha256(f"{t}:dist:{j}".encode()).hexdigest()[:8].upper()
            text = f"Unrelated note {tok} about topic {rng.randint(100, 999)}."
            docs.append({"doc_id": f"{t}:dist:{j}", "title": f"Note {tok}", "text": text})
        rng.shuffle(docs)
        opening = ", ".join(_token(t, f, 0) for f in range(n_facets))
        tasks.append(
            Task(
                task_id=f"s{t}",
                question=f"Starting from records {opening}, report the final value of every facet.",
                docs=tuple(Doc(**d) for d in docs),
                gold_depth=gold,
                answer=" ".join(answers),
            )
        )
    return tasks
