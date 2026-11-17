import hashlib
import json
import math

import pytest

from benchmarks.knowledge.metrics import coverage_by_depth, evidence_coverage
from benchmarks.knowledge.synth import build

pytestmark = pytest.mark.sanity

# sha256 of the default suite, verified equal to ProactiveInquirer's
# data/corpora/synth/61fd50eebdb994c7/tasks.jsonl (all 24 tasks, docs in order).
UPSTREAM_DIGEST = (
    "4ef5da03be01f1b410c74d422757bd7b01b9780a13509a982c94987de80db0f2"  # pragma: allowlist secret
)


def _digest(tasks) -> str:
    payload = json.dumps(
        [[t.task_id, t.question, [[d.doc_id, d.title, d.text] for d in t.docs]] for t in tasks],
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def test_default_suite_matches_upstream():
    assert _digest(build()) == UPSTREAM_DIGEST


def test_task_shape_and_chain():
    task = build(n_tasks=1)[0]
    assert (
        task.question
        == "Starting from records KE8CA2BD5, K1DEC49FC, K1341FE73, report the final value of every facet."
    )
    assert len(task.gold_depth) == 3 * 6
    assert sum(":dist:" in d.doc_id for d in task.docs) == 6
    by_id = {d.doc_id: d for d in task.docs}
    # Each non-final record names the token of the next record in its facet.
    for f in range(3):
        for depth in range(5):
            next_token = by_id[f"0:{f}:{depth + 1}"].title.removeprefix("Record ")
            assert f"consult record {next_token}." in by_id[f"0:{f}:{depth}"].text
    assert task.answer == "V005 V015 V025"


def test_coverage_metrics():
    gold = {"a": 0, "b": 1, "c": 1}
    assert evidence_coverage({"a", "x"}, set(gold)) == pytest.approx(1 / 3)
    assert coverage_by_depth({"a", "b"}, gold) == {0: 1.0, 1: 0.5}
    assert math.isnan(evidence_coverage({"a"}, set()))
