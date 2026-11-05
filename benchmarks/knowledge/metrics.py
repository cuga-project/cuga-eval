"""Evidence-coverage metrics, ported from ProactiveInquirer ``pi_eval/metrics/discovery.py`` (Apache-2.0)."""

from __future__ import annotations

import math


def evidence_coverage(retrieved: set[str], gold: set[str]) -> float:
    """|gold retrieved| / |gold|; NaN when there is no gold, so it never counts as a pass."""
    if not gold:
        return math.nan
    return len(retrieved & gold) / len(gold)


def coverage_by_depth(retrieved: set[str], gold_depth: dict[str, int]) -> dict[int, float]:
    """Coverage of the gold units at each hop depth."""
    by_depth: dict[int, set[str]] = {}
    for doc_id, depth in gold_depth.items():
        by_depth.setdefault(depth, set()).add(doc_id)
    return {d: evidence_coverage(retrieved, ids) for d, ids in sorted(by_depth.items())}
