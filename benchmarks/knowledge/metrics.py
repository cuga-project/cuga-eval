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


# ProactiveInquirer's preregistered depth weights (pi_eval/score.py DWR_WEIGHTS): a deeper
# hop is worth more, because reaching it means every hop before it was found too.
DWR_WEIGHTS: dict[int, float] = {0: 0.5, 1: 1.0, 2: 1.5, 3: 2.0, 4: 2.0, 5: 2.0}


def depth_weighted_recall(cad: dict[int, float], weights: dict[int, float] = DWR_WEIGHTS) -> float:
    """DWR = sum_d w_d C@d / sum_d w_d over the depths the task has (pi_eval/metrics/structure.py)."""
    num = sum(weights.get(d, 0.0) * c for d, c in cad.items() if not math.isnan(c))
    den = sum(weights.get(d, 0.0) for d, c in cad.items() if not math.isnan(c))
    return num / den if den else math.nan
