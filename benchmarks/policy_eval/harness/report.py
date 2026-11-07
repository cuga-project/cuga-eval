#!/usr/bin/env python3
"""One report over old and new result files: the arms of an experiment, side by side, each task counted once.

  python3 benchmarks/policy_eval/harness/report.py --runs ph_AF ph_B4TF
  python3 benchmarks/policy_eval/harness/report.py --runs test1_A,test2_A test1_T,test2_T
  python3 benchmarks/policy_eval/harness/report.py --runs pt_AF pt_B4TF ph_AF ph_B4TF     # tuning next to held-out

Each value of ``--runs`` is one arm: run names joined by commas. A run name finds, in the result folders of all benchmarks:
``<name>``; ``<name>_t<n>`` (one folder per trial); ``<a>_<x>_<b>_t<n>`` for ``<a>_<b>`` (``hbq_A`` finds ``hbq_ci_A_t1``);
``logging_<name>_s<n>`` (τ² shards). A folder that holds two arms (old IT service runs) needs ``<name>:<arm>``.

Statistics (as ``automationbench/report_policy_types.py`` has done since change 93): per task the mean over the arm's
results, then a two-sided exact sign test on the tasks that are better or worse. Score, Pass and Guardrails are means over
an arm's own tasks; Diff and the test use the Pairs, the tasks both arms have, so the two can differ when a task drops. Items
pools results, with its total next to it. The first arm of a group is the base. A run
name's first word and the benchmark are the group: arms of one group run on the same tasks, and each group is reported with
the label of its task set from the registry (``build_registry.set_label``: tuning, seen, or held-out only when no model has
run it) and how many of its tasks the arms' agent models have run. A result with no score is listed and not counted: it is
not a 0. Below the table, the ``code_sha`` and ``profile_hash`` of each arm; an arm that has more than one says so, because
its results do not describe one system. An old file with no such field shows as not recorded.

Reads only. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HARNESS = Path(__file__).resolve().parent
POLICY_EVAL = HARNESS.parent
BENCHMARKS = POLICY_EVAL.parent
if str(BENCHMARKS) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS))
from policy_eval.harness.result import NotAResult, Result, all_from_legacy  # noqa: E402

RESULTS = HARNESS / "results"  # runs of the harness
TAU2_ROOT = Path.home() / "dev/cuga-eval-tau2/benchmarks/tau2"
ROOTS = [
    RESULTS,
    BENCHMARKS / "automationbench" / "results",
    BENCHMARKS / "enterpriseops_gym" / "results",
    BENCHMARKS / "handbook" / "results",
]
SAME = 1e-9


class ReportError(ValueError):
    """A run name finds nothing, finds folders in two places, or a folder holds two arms."""


def sign_p(k: int, n: int) -> float:
    """Two-sided exact sign test: ``k`` of ``n`` tasks that changed went one way."""
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2**n
    return min(1.0, 2 * tail)


# -- finding the runs ----------------------------------------------------------------------------------------------------


def _folders(name: str, roots: List[Path], tau2_root: Path) -> List[Path]:
    words = name.split("_")
    patterns = [re.escape(name), re.escape(name) + r"_t\d+"]
    if len(words) >= 2:
        patterns.append(re.escape(words[0]) + r"_[^_]+_" + re.escape("_".join(words[1:])) + r"_t\d+")
    found: Dict[Path, List[Path]] = {}
    for root in roots:
        if root.is_dir():
            for pattern in patterns:
                hits = sorted(p for p in root.iterdir() if p.is_dir() and re.fullmatch(pattern, p.name))
                if hits:
                    found[root] = hits
                    break
    if tau2_root.is_dir():
        hits = sorted(
            p
            for p in tau2_root.glob(f"logging_{name}*")
            if p.is_dir() and re.fullmatch(r"logging_" + re.escape(name) + r"(_s\d+)?", p.name)
        )
        if hits:
            found[tau2_root] = hits
    if not found:
        raise ReportError(f"no run matches {name}")
    if len(found) > 1:
        raise ReportError(f"{name} matches runs in {len(found)} places: {[str(r) for r in found]}")
    return next(iter(found.values()))


def _files(folder: Path, arm: Optional[str]) -> List[Path]:
    if (folder / "results").is_dir() and folder.name.startswith("logging_"):
        return sorted((folder / "results").glob("tau2_*.json"))
    files = sorted(folder.glob("*.json"))
    if arm:
        return [f for f in files if f.name.startswith(f"{arm}_")]
    arms = {f.name.split("_", 1)[0] for f in files if re.match(r"[A-Z][A-Za-z0-9]*_task_", f.name)}
    if len(arms) > 1:
        raise ReportError(f"{folder.name} holds the arms {sorted(arms)}: write {folder.name}:<arm>")
    return files


def load_arm(spec: str, roots: Optional[List[Path]] = None, tau2_root: Optional[Path] = None) -> List[Result]:
    """Every result of one arm. One result per run and task: a later file of a run replaces an earlier one."""
    by_key: Dict[Tuple[str, str], Result] = {}
    for part in spec.split(","):
        name, _, arm = part.strip().partition(":")
        for folder in _folders(name, roots if roots is not None else ROOTS, tau2_root or TAU2_ROOT):
            for path in _files(folder, arm or None):
                try:
                    results = all_from_legacy(path)
                except NotAResult:  # a run folder also holds other files (a review, a violations list)
                    continue
                for result in results:
                    by_key[(result.run, result.task)] = result
    if not by_key:
        raise ReportError(f"no result in {spec}")
    return list(by_key.values())


# -- statistics ----------------------------------------------------------------------------------------------------------


@dataclass
class ArmReport:
    arm: str
    results: int  # with a score
    tasks: int
    mean: Optional[float]  # of the per-task means; None: nothing was graded, which is not a 0
    per_task: Dict[str, float]
    pass_rate: Optional[float]  # per task, as guardrails_broken: arms with different trials stay comparable
    items_passed: Optional[int]
    items_total: Optional[int]
    guardrails_broken: Optional[float]  # per task: the mean over its results, then the mean over tasks
    not_graded: List[str] = field(default_factory=list)  # "task: error"
    ended_on_error: int = 0  # graded, and the agent stopped on an error
    code_shas: List[Optional[str]] = field(
        default_factory=list
    )  # of the results that count; None: not recorded
    profile_hashes: List[Optional[str]] = field(default_factory=list)
    # against the base of the group
    diff: Optional[float] = None
    better: Optional[int] = None
    worse: Optional[int] = None
    same: Optional[int] = None
    p: Optional[float] = None
    common: Optional[int] = None


def _per_task(pairs: List[Tuple[str, float]]) -> Dict[str, float]:
    by_task: Dict[str, List[float]] = defaultdict(list)
    for task, value in pairs:
        by_task[task].append(value)
    return {t: statistics.mean(v) for t, v in by_task.items()}


def _mean_over_tasks(pairs: List[Tuple[str, float]]) -> Optional[float]:
    return statistics.mean(_per_task(pairs).values()) if pairs else None


def summarize(arm: str, results: List[Result]) -> ArmReport:
    scored = [r for r in results if r.score is not None]
    per_task = _per_task([(r.task, r.score.primary) for r in scored])
    items = [r.score.detail for r in scored if "items_total" in r.score.detail]
    return ArmReport(
        arm=arm,
        results=len(scored),
        tasks=len(per_task),
        mean=statistics.mean(per_task.values()) if per_task else None,
        per_task=per_task,
        pass_rate=_mean_over_tasks(
            [(r.task, float(r.score.passed)) for r in scored if r.score.passed is not None]
        ),
        items_passed=sum(d["items_passed"] for d in items) if items else None,
        items_total=sum(d["items_total"] for d in items) if items else None,
        guardrails_broken=_mean_over_tasks(
            [
                (r.task, float(r.score.guardrails_broken))
                for r in scored
                if r.score.guardrails_broken is not None
            ]
        ),
        not_graded=[f"{r.task}: {r.error}" for r in results if r.score is None],
        ended_on_error=sum(bool(r.error) for r in scored),
        code_shas=_values(r.code_sha for r in scored),
        profile_hashes=_values(r.profile_hash for r in scored),
    )


def _values(values: Iterable[Optional[str]]) -> List[Optional[str]]:
    """The distinct values, ``None`` (not recorded) last."""
    found = set(values)
    return sorted(v for v in found if v is not None) + ([None] if None in found else [])


def paired(base: ArmReport, other: ArmReport) -> None:
    """Fill the comparison of ``other`` against ``base``: one count per task, over the tasks both arms have."""
    common = sorted(set(base.per_task) & set(other.per_task))
    diffs = [other.per_task[t] - base.per_task[t] for t in common]
    other.common = len(common)
    if not common:
        return
    other.better = sum(d > SAME for d in diffs)
    other.worse = sum(d < -SAME for d in diffs)
    other.same = len(diffs) - other.better - other.worse
    other.diff = statistics.mean(diffs)
    other.p = sign_p(other.better, other.better + other.worse)


# -- task sets ------------------------------------------------------------------------------------------------------------


def task_set_of(
    benchmark: str, tasks: set, registry_path: Optional[Path] = None, models: Iterable[str] = ()
) -> str:
    """The smallest registered set that holds all these tasks, with its label and how many of its tasks each of ``models``
    has run (``seen_n``)."""
    from policy_eval.sets.build_registry import REGISTRY, set_label, task_ids

    entries = json.loads((registry_path or REGISTRY).read_text())["sets"]
    best: Optional[Dict[str, Any]] = None
    for entry in entries:
        if entry["benchmark"] != benchmark or entry["n"] < len(tasks):
            continue
        if best is not None and best["n"] <= entry["n"]:
            continue
        try:
            if tasks <= set(task_ids(entry)):
                best = entry
        except OSError:  # the set file is on another worktree that is not here
            continue
    if best is None:
        return "no registered set holds these tasks"
    seen = [f"{m} ran {best.get('seen_n', {}).get(m, 0)} of {best['n']}" for m in sorted(models)]
    return f"{best['id']} ({'; '.join([set_label(best), *seen])})"


# -- report -------------------------------------------------------------------------------------------------------------


def _group_of(spec: str, results: List[Result]) -> str:
    return f"{spec.split(',')[0].split(':')[0].split('_')[0]}: {results[0].benchmark}"


def compare(loaded: Dict[str, List[Result]]) -> Dict[str, List[ArmReport]]:
    """Arm reports per group, in the order given; each group's first arm is its base."""
    groups: Dict[str, List[ArmReport]] = {}
    for spec, results in loaded.items():
        groups.setdefault(_group_of(spec, results), []).append(summarize(spec, results))
    for arms in groups.values():
        for other in arms[1:]:
            paired(arms[0], other)
    return groups


def _versions(arm: ArmReport) -> str:
    """The code and the profile an arm ran on. More than one of either means its results describe several systems."""

    def show(name: str, values: List[Optional[str]]) -> str:
        known = [v if v is not None else "not recorded" for v in values]
        return f"{name} {', '.join(known) or 'none'}"

    line = f"{arm.arm}: {show('code_sha', arm.code_shas)}; {show('profile_hash', arm.profile_hashes)}."
    mixed = [n for n, v in (("code_sha", arm.code_shas), ("profile_hash", arm.profile_hashes)) if len(v) > 1]
    return line + (f" **MIXED: more than one {' and '.join(mixed)} in this arm.**" if mixed else "")


def _percent(value: Optional[float]) -> str:
    """One decimal. ``100 * 0.6375`` is 63.74999... as a float, and 51 of 80 is 63.75: the noise goes before the rounding."""
    return "" if value is None else f"{round(100 * value, 9):.1f}%"


def render(specs: List[str], **where: Any) -> str:
    lines: List[str] = []
    loaded = {spec: load_arm(spec, **where) for spec in specs}
    for name, arms in compare(loaded).items():
        benchmark = loaded[arms[0].arm][0].benchmark
        tasks = {r.task for a in arms for r in loaded[a.arm]}
        models = {r.agent_model or "unknown" for a in arms for r in loaded[a.arm]}
        lines += [f"## {name}, set {task_set_of(benchmark, tasks, models=models)}", ""]
        lines += [
            f"| Arm | Results | Tasks | Score | Pass | Items | Guardrails broken per task | Pairs | Diff vs {arms[0].arm} "
            "(pts) | Better / worse / same | Sign test p |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for a in arms:
            items = f"{a.items_passed} of {a.items_total}" if a.items_total else ""
            broken = "" if a.guardrails_broken is None else f"{a.guardrails_broken:.2f}"
            pairs = "" if a.common is None else str(a.common)
            versus = (
                ["", "", ""]
                if a.diff is None
                else [f"{100 * a.diff:+.1f}", f"{a.better} / {a.worse} / {a.same}", f"{a.p:.3f}"]
            )
            lines.append(
                f"| {a.arm} | {a.results} | {a.tasks} | {_percent(a.mean)} | {_percent(a.pass_rate)} | {items} | "
                f"{broken} | {pairs} | " + " | ".join(versus) + " |"
            )
        lines.append("")
        lines += [_versions(a) for a in arms]
        for a in arms:
            if a.ended_on_error:
                lines.append(f"\n{a.arm}: {a.ended_on_error} graded results ended on an agent error.")
            if a.not_graded:
                lines.append(f"\n{a.arm}: {len(a.not_graded)} results not graded, not counted:")
                lines += [f"- {x[:200]}" for x in a.not_graded]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="+", required=True, help="one value per arm: run names joined by commas")
    args = ap.parse_args()
    try:
        print(render(args.runs))
    except ReportError as exc:
        print(f"report: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
