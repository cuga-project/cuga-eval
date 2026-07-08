"""Generate evaluation reports from result files.

Works with both SDK-style results (BPO, M3, Oak) and appworld-style results.

Modes:
    # Compare report (from stdin JSON)
    echo '{"gpt-oss": ["r1.json"], "gpt4o": ["r2.json"]}' | \
        python -m benchmarks.helpers.compare_report --output report.md

    # Single-eval report
    python -m benchmarks.helpers.compare_report eval \
        --result-file results.json --output report.md
"""

import argparse
import json
import sys
import tomllib
from pathlib import Path

from benchmarks.helpers.content_filter import FAILURE_REASON_CONTENT_FILTER

MODEL_DISPLAY_NAMES = {
    "gpt-oss": "GPT-OSS-120B",
    "gpt4o": "GPT-4o",
    "gpt4.1": "GPT-4.1",
    "opus4.5": "Claude Opus 4.5",
}


def _task_result_mark(task: dict, *, markdown: bool = True) -> str:
    """Render pass/fail mark, annotating known non-agent failure reasons.

    Markdown tables don't need fixed-width cells, so the content-filter
    annotation spells out "content_filter" there. Plain-text tables use
    fixed-width columns (see the ``mark:<2`` cells below), so every
    non-markdown return value here is exactly 2 characters wide — "✗c" for a
    content-filter failure, "✓ "/"✗ " otherwise — the full word would blow
    out row alignment for every column after it, and a narrower ``✓``/``✗``
    without the padding space would misalign against the 2-char "✗c" rows.
    """
    if task.get("success"):
        return "✓" if markdown else "✓ "
    if task.get("failure_reason") == FAILURE_REASON_CONTENT_FILTER:
        return "✗ content_filter" if markdown else "✗c"
    return "✗" if markdown else "✗ "


def _content_filter_failure_count(tasks: dict) -> int:
    return sum(
        1
        for t in tasks.values()
        if not t.get("success") and t.get("failure_reason") == FAILURE_REASON_CONTENT_FILTER
    )


def _append_content_filter_summary(lines: list[str], tasks: dict, *, markdown: bool) -> None:
    count = _content_filter_failure_count(tasks)
    if count <= 0:
        return
    note = (
        f"{count} task(s) failed because Azure's content filter rejected the request "
        "(scored 0.0; prompt vs. completion not distinguishable from the captured error text)"
    )
    if markdown:
        lines.append(f"- **Content filter failures**: {note}")
    else:
        lines.append(f"  Content filter    {note}")


def _format_config_label(config_key: str) -> str:
    """Render a "model[:agent[:policy]]" key for the per-task subheading.

    Format: "<agent>[ — <policy>] (<MODEL_DISPLAY>)" — the agent comes first
    because the typical comparison fans out across agents within one model,
    and seeing "cuga"/"react" up front is more useful than the model name. If
    the key is just "model" with no agent, render as the model display name.
    Unknown models pass through verbatim.
    """
    parts = config_key.split(":")
    model_name = parts[0]
    agent = parts[1] if len(parts) > 1 and parts[1] else None
    policy = parts[2] if len(parts) > 2 and parts[2] else None
    display_model = MODEL_DISPLAY_NAMES.get(model_name, model_name)
    if agent is None:
        return display_model
    label = agent
    if policy is not None:
        label += f" — {policy}"
    return f"{label} ({display_model})"


def _fmt(val, fmt=","):
    """Format a numeric value, returning '--' if None (zero is shown as 0)."""
    if val is None:
        return "--"
    if fmt == ",":
        # Use 1-decimal precision for floats so we don't surface float-repr
        # noise like '252385.22000000003' in summary rows.
        if isinstance(val, float):
            return f"{val:,.1f}"
        return f"{val:,}"
    if fmt == "$":
        return f"${val:.4f}"
    if fmt == "s":
        return f"{val:.1f}s"
    return str(val)


def _fmt_score(val) -> str:
    """Format a 0.0-1.0 Vakra dialogue/judge score to 2dp, or '--' if absent."""
    return f"{val:.2f}" if val is not None else "--"


# Vakra LLM-judge dimensions, in display order. Mirrors
# ``m3_vakra_score._JUDGE_KEYS`` / ``_last_turn_judge_scores``; re-implemented
# here (rather than imported) so this module stays benchmark-agnostic.
_JUDGE_KEYS = ("exactmatch", "answer", "groundedness")


def _last_turn_judge_scores(vakra: dict) -> dict:
    """Extract per-judge scores from the last scored turn of a Vakra dialogue.

    ``vakra`` is the ``r["vakra"]`` dict M3 attaches to scored results
    (``{"score": ..., "details": {"per_turn": [{"metadata": {...}}, ...]}}``).
    Returns {} if ``vakra`` has no per-turn data, or a subset of
    ``_JUDGE_KEYS`` for judges that ran on the last turn (a judge may be
    skipped, e.g. the answer judge when exactmatch already scored 1.0).
    """
    per_turn = (vakra.get("details") or {}).get("per_turn") or []
    if not per_turn:
        return {}
    meta = per_turn[-1].get("metadata") or {}
    scores = {}
    for key in _JUDGE_KEYS:
        val = meta.get(f"{key}_score")
        if val is not None:
            scores[key] = float(val)
    return scores


def _parse_sdk_results(data: dict) -> dict:
    """Parse SDK-style results (BPO, M3, Oak)."""
    metrics = data.get("metrics", {})
    results = data.get("results", [])
    total = metrics.get("total_tasks", len(results))
    passed = metrics.get("passed", sum(1 for r in results if r.get("success")))
    total_tokens = sum(r.get("total_tokens", 0) or 0 for r in results)
    total_cost = sum(r.get("total_cost", 0) or 0 for r in results)
    total_llm_calls = sum(r.get("total_llm_calls", 0) or 0 for r in results)
    total_cache_tokens = sum(r.get("total_cache_input_tokens", 0) or 0 for r in results)

    tasks = {}
    total_duration = 0.0
    has_duration = False
    for r in results:
        name = r.get("task_name", r.get("name", "unknown"))
        dur = r.get("full_execution_time") or r.get("duration")
        if dur is not None:
            total_duration += dur
            has_duration = True
        tasks[name] = {
            "success": r.get("success", False),
            "tokens": r.get("total_tokens", 0) or 0,
            "cost": r.get("total_cost", 0) or 0,
            "llm_calls": r.get("total_llm_calls", 0) or 0,
            "cache_tokens": r.get("total_cache_input_tokens", 0) or 0,
            "duration": dur,
            "steps": r.get("steps"),
            # AppWorld results carry a per-task difficulty band; preserved for
            # the per-difficulty breakdown in the multi-run summary. Other
            # benchmarks won't emit it and the breakdown will collapse to None.
            "difficulty": r.get("difficulty"),
            # M3-specific tags so the eval report can group by (task, domain).
            "m3_task_id": r.get("m3_task_id"),
            "domain": r.get("domain"),
            # 1-based position of this sample within its (capability, domain)
            # input file. Lets reports show the source "task number".
            "task_number": r.get("task_number"),
            "uuid": r.get("uuid") or r.get("task_name") or r.get("name"),
            # Vakra LLM-judge scores (M3 only). `match_rate` is the aggregated
            # dialogue score (>= 1.0 = pass); `judge_scores` is a subset of
            # _JUDGE_KEYS from the last scored turn. Both are absent (None /
            # {}) for non-Vakra-scored results.
            "match_rate": r.get("match_rate"),
            "judge_scores": _last_turn_judge_scores(r.get("vakra") or {}),
            "failure_reason": r.get("failure_reason"),
        }

    return {
        "total": total,
        "passed": passed,
        "rate": passed / total if total else 0,
        "tokens": total_tokens,
        "cost": total_cost,
        "llm_calls": total_llm_calls,
        "cache_tokens": total_cache_tokens,
        "duration": total_duration if has_duration else None,
        "tasks": tasks,
    }


def _parse_appworld_results(data: dict) -> dict:
    """Parse appworld-style results."""
    task_results = data.get("task_results", {})
    total = data.get("tasks_total", len(task_results))
    passed = data.get("tasks_completed", sum(1 for t in task_results.values() if t.get("success")))
    total_tokens = sum(t.get("total_tokens", 0) or 0 for t in task_results.values())
    total_cost = sum(t.get("total_cost", 0) or 0 for t in task_results.values())
    total_llm_calls = sum(t.get("total_llm_calls", 0) or 0 for t in task_results.values())
    total_cache_tokens = sum(t.get("cache_input_tokens", 0) or 0 for t in task_results.values())
    total_duration = data.get("duration") or sum(
        t.get("full_execution_time", 0) or 0 for t in task_results.values()
    )

    tasks = {}
    for tid, t in task_results.items():
        tasks[tid] = {
            "success": t.get("success", False),
            "tokens": t.get("total_tokens", 0) or 0,
            "cost": t.get("total_cost", 0) or 0,
            "llm_calls": t.get("total_llm_calls", 0) or 0,
            "cache_tokens": t.get("cache_input_tokens", 0) or 0,
            "duration": t.get("full_execution_time") or t.get("duration"),
            "steps": t.get("steps"),
            "difficulty": t.get("difficulty"),
            "uuid": tid,
            "failure_reason": t.get("failure_reason"),
        }

    return {
        "total": total,
        "passed": passed,
        "rate": passed / total if total else 0,
        "tokens": total_tokens,
        "cost": total_cost,
        "llm_calls": total_llm_calls,
        "cache_tokens": total_cache_tokens,
        "duration": total_duration,
        "tasks": tasks,
    }


def parse_result_file(path: str) -> dict:
    data = json.loads(Path(path).read_text())
    if "task_results" in data:
        return _parse_appworld_results(data)
    return _parse_sdk_results(data)


def _avg(xs):
    """Average of a list, ignoring None entries. Returns None if all None/empty."""
    vals = [x for x in xs if x is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _pass_stats_for_tasks(runs, task_filter=None):
    """Compute per-task pass tallies across runs, returning (n_tasks, any_pass,
    all_pass, maj_pass). ``task_filter`` is an optional callable accepting a
    task dict from any run and returning True to include the task."""
    all_tasks: set = set()
    for r in runs:
        if task_filter is None:
            all_tasks.update(r["tasks"].keys())
        else:
            all_tasks.update(tid for tid, t in r["tasks"].items() if task_filter(t))
    k = len(runs)
    any_pass = 0
    all_pass = 0
    maj_pass = 0
    for task in all_tasks:
        statuses = [r["tasks"].get(task, {}).get("success", False) for r in runs]
        n_ok = sum(1 for s in statuses if s)
        if n_ok >= 1:
            any_pass += 1
        if n_ok == k:
            all_pass += 1
        if n_ok > k / 2:
            maj_pass += 1
    return len(all_tasks), any_pass, all_pass, maj_pass


def _per_config_pass_stats(runs, task_filter=None) -> dict:
    """Bundle the per-config aggregate metrics shown in the Summary row."""
    n_tasks, any_pass, all_pass, maj_pass = _pass_stats_for_tasks(runs, task_filter)
    k = len(runs)
    # avg_rate across runs limited to the filtered task subset.
    if task_filter is not None and n_tasks > 0:
        per_run_rates = []
        for r in runs:
            filt = {tid: t for tid, t in r["tasks"].items() if task_filter(t)}
            n = len(filt)
            if n == 0:
                per_run_rates.append(0.0)
            else:
                per_run_rates.append(sum(1 for t in filt.values() if t.get("success")) / n)
        avg_rate = sum(per_run_rates) / k if k else 0.0
    else:
        avg_rate = sum(r["rate"] for r in runs) / k if k else 0.0
    return {
        "n_tasks": n_tasks,
        "any_pass": any_pass,
        "all_pass": all_pass,
        "maj_pass": maj_pass,
        "pass_at_n": (any_pass / n_tasks) if n_tasks else 0.0,
        "pass_pow_n": (all_pass / n_tasks) if n_tasks else 0.0,
        "maj_at_n": (maj_pass / n_tasks) if n_tasks else 0.0,
        # Normalized consistency: of the tasks the agent solves "most of the
        # time", what fraction does it solve *every* time? 1.0 = perfectly
        # reliable on its winnable tasks; <1.0 = flaky. Undefined when no task
        # passes a majority.
        "consistency": (all_pass / maj_pass) if maj_pass else None,
        "avg_rate": avg_rate,
    }


def _difficulty_group(t: dict) -> str | None:
    """Group key: AppWorld difficulty band, or None for non-AppWorld tasks."""
    d = t.get("difficulty")
    if d in (None, "", "unknown"):
        return None
    return str(d)


def _difficulty_sort_key(d: str):
    try:
        return (0, int(d))
    except (ValueError, TypeError):
        return (1, d)


def _m3_capability_domain_group(t: dict) -> str | None:
    """Group key: M3 "m3_task_<id>/<domain>", or None when absent."""
    tid = t.get("m3_task_id")
    dom = t.get("domain")
    if tid is None or not dom:
        return None
    return f"m3_task_{tid}/{dom}"


def _m3_capability_group(t: dict) -> str | None:
    """Group key: M3 capability only, "m3_task_<id>", or None when absent.

    A coarser rollup than `_m3_capability_domain_group` — one row per
    capability instead of per (capability, domain).
    """
    tid = t.get("m3_task_id")
    if tid is None:
        return None
    return f"m3_task_{tid}"


def _m3_capability_sort_key(g: str):
    """Sort m3_task_<id> capability labels by numeric id (m3_task_2 < m3_task_10)."""
    try:
        return (0, int(g.rsplit("_", 1)[-1]))
    except (ValueError, TypeError):
        return (1, g)


def _load_appworld_categories(config_path: Path | None = None) -> dict[str, str]:
    """Map AppWorld task ids to "normal"/"challenge" via the
    ``test_challenge_*`` / ``test_normal_all_*`` lists in
    ``benchmarks/appworld/eval_config.toml``.

    Returns {} if that file doesn't exist (keeps non-AppWorld reports
    unaffected), warning on stderr since the file is a committed repo asset.
    ``config_path`` is overridable for tests.
    """
    if config_path is None:
        config_path = Path(__file__).resolve().parents[1] / "appworld" / "eval_config.toml"
    if not config_path.exists():
        # This is a committed repo asset, so its absence almost always means it
        # was moved/renamed in a refactor — which would silently drop the
        # AppWorld test-set breakdown from every report. Surface it on stderr
        # (not the report stdout) instead of failing silently (issue #51 review).
        print(
            f"WARNING: AppWorld category config not found at {config_path}; "
            "AppWorld test-set breakdown will be omitted.",
            file=sys.stderr,
        )
        return {}
    with config_path.open("rb") as f:
        config = tomllib.load(f).get("eval_config", {})
    categories: dict[str, str] = {}
    for key, ids in config.items():
        if not isinstance(ids, list):
            continue
        if key.startswith("test_challenge_"):
            label = "challenge"
        elif key.startswith("test_normal_all_"):
            label = "normal"
        else:
            continue
        for tid in ids:
            categories[str(tid)] = label
    return categories


def _appworld_test_set_group(categories: dict[str, str]):
    """Return a group_fn mapping a task's ``uuid`` to "normal"/"challenge"
    via ``categories`` (from ``_load_appworld_categories``). Tasks whose
    ``uuid`` isn't in ``categories`` (non-AppWorld, or outside the
    categorized full test set) are excluded."""

    def _group(t: dict) -> str | None:
        return categories.get(t.get("uuid"))

    return _group


def _aggregate_costs(tasks: dict) -> dict:
    """Sum and average tokens / LLM calls / duration across a dict of task
    dicts (as produced by ``_parse_sdk_results`` / ``_parse_appworld_results``).

    ``total_duration`` / ``avg_duration`` are None when no task carries a
    duration.
    """
    n = len(tasks)
    total_tokens = sum(t.get("tokens", 0) or 0 for t in tasks.values())
    total_llm_calls = sum(t.get("llm_calls", 0) or 0 for t in tasks.values())
    durations = [t.get("duration") for t in tasks.values() if t.get("duration") is not None]
    total_duration = sum(durations) if durations else None
    return {
        "n_tasks": n,
        "total_tokens": total_tokens,
        "total_llm_calls": total_llm_calls,
        "total_duration": total_duration,
        "avg_tokens": (total_tokens / n) if n else None,
        "avg_llm_calls": (total_llm_calls / n) if n else None,
        "avg_duration": (total_duration / n) if (n and total_duration is not None) else None,
    }


def _per_config_cost_stats(runs, task_filter=None) -> dict:
    """Mean tokens / LLM calls / duration *per task* across runs for the
    filtered task subset. Companion to ``_per_config_pass_stats`` so the
    per-group compare sections can answer "did this group cost more?" and not
    just "did it pass more?" (issue #51 review). Per-task means (not totals)
    keep groups of different sizes comparable.
    """
    tokens, llm, durs = [], [], []
    for r in runs:
        for t in r["tasks"].values():
            if task_filter is not None and not task_filter(t):
                continue
            tokens.append(t.get("tokens"))
            llm.append(t.get("llm_calls"))
            durs.append(t.get("duration"))
    return {
        "avg_tokens": _avg(tokens),
        "avg_llm_calls": _avg(llm),
        "avg_duration": _avg(durs),
    }


def _per_group_section(
    model_data, fence_open, fence_close, h2, *, title, col_label, group_fn, sort_key=None
) -> list[str]:
    """Build a per-group breakdown section (difficulty / test-set /
    capability+domain / ...).

    ``group_fn(task_dict) -> str | None`` assigns each task to a group label;
    tasks for which it returns a falsy value are excluded from every group.
    Returns [] when no task is assigned to a group, so reports that don't
    carry the relevant metadata stay unchanged.
    """
    groups: set = set()
    for runs in model_data.values():
        for r in runs:
            for t in r["tasks"].values():
                g = group_fn(t)
                if g:
                    groups.add(g)
    if not groups:
        return []

    sorted_groups = sorted(groups, key=sort_key) if sort_key else sorted(groups)
    grp_w = max(len(col_label), max(len(g) for g in sorted_groups))
    out: list[str] = [h2(title), ""]
    if fence_open():
        out.append(fence_open())
    header = (
        f"{'Configuration':<28} {col_label:>{grp_w}}  {'Tasks':>5}  "
        f"{'Pass@1':>9}  {'pass@k':>8}  {'pass^k':>8}  "
        f"{'maj@k':>8}  {'Cons':>5}  "
        f"{'Tok/Task':>10}  {'LLM/Task':>9}  {'Dur/Task':>9}"
    )
    out.append(header)
    out.append("─" * len(header))
    for config_key, runs in model_data.items():
        display = _format_config_label(config_key)
        for grp in sorted_groups:
            grp_filter = lambda t, _g=grp: group_fn(t) == _g  # noqa: E731
            stats = _per_config_pass_stats(runs, task_filter=grp_filter)
            if stats["n_tasks"] == 0:
                continue
            cost = _per_config_cost_stats(runs, task_filter=grp_filter)
            cons_s = f"{stats['consistency']:.2f}" if stats["consistency"] is not None else "  --"
            out.append(
                f"{display:<28} {grp:>{grp_w}}  {stats['n_tasks']:>5}  "
                f"{stats['avg_rate'] * 100:>8.1f}%  "
                f"{stats['pass_at_n'] * 100:>7.1f}%  {stats['pass_pow_n'] * 100:>7.1f}%  "
                f"{stats['maj_at_n'] * 100:>7.1f}%  {cons_s:>5}  "
                f"{_fmt(cost['avg_tokens']):>10}  {_fmt(cost['avg_llm_calls']):>9}  "
                f"{_fmt(cost['avg_duration'], 's'):>9}"
            )
    if fence_close():
        out.append(fence_close())
    out.append("")
    return out


def _eval_group_breakdown(
    tasks: dict, fence_open, fence_close, h2, *, title, col_label, group_fn, sort_key=None, markdown=False
) -> list[str]:
    """Per-group cost/pass breakdown for a single eval report.

    No pass@k / pass^k / maj@k here — those are compare-only metrics (a
    single eval run has k=1). Returns [] when no task is assigned to a group.

    When ``markdown`` is set the section is rendered as a GitHub-flavored
    markdown table (matching the Per-Task Results table) instead of a
    fixed-width monospace block; otherwise the legacy fenced text table is used.
    """
    groups: dict[str, dict] = {}
    for name, t in tasks.items():
        g = group_fn(t)
        if not g:
            continue
        groups.setdefault(g, {})[name] = t
    if not groups:
        return []

    sorted_groups = sorted(groups, key=sort_key) if sort_key else sorted(groups)

    # Totals AND per-task averages: raw totals across groups of different sizes
    # aren't directly comparable, so the avg-per-task columns let you compare
    # cost across groups (issue #51 review).
    cols = (
        col_label,
        "Tasks",
        "Pass@1",
        "Tokens",
        "Tok/Task",
        "LLM Calls",
        "LLM/Task",
        "Duration",
        "Dur/Task",
    )

    def _row_cells(grp: str) -> tuple:
        grp_tasks = groups[grp]
        n = len(grp_tasks)
        passed = sum(1 for t in grp_tasks.values() if t.get("success"))
        rate = (passed / n * 100) if n else 0.0
        agg = _aggregate_costs(grp_tasks)
        return (
            grp,
            str(n),
            f"{rate:.1f}%",
            _fmt(agg["total_tokens"]),
            _fmt(agg["avg_tokens"]),
            _fmt(agg["total_llm_calls"]),
            _fmt(agg["avg_llm_calls"]),
            _fmt(agg["total_duration"], "s"),
            _fmt(agg["avg_duration"], "s"),
        )

    out: list[str] = [h2(title), ""]
    if markdown:
        out.append("| " + " | ".join(cols) + " |")
        out.append("|" + "|".join("---" for _ in cols) + "|")
        for grp in sorted_groups:
            out.append("| " + " | ".join(_row_cells(grp)) + " |")
        out.append("")
        return out

    grp_w = max(len(col_label), max(len(g) for g in sorted_groups))
    if fence_open():
        out.append(fence_open())
    header = (
        f"{col_label:<{grp_w}}  {'Tasks':>5}  {'Pass@1':>8}  "
        f"{'Tokens':>10}  {'Tok/Task':>10}  {'LLM Calls':>9}  {'LLM/Task':>9}  "
        f"{'Duration':>9}  {'Dur/Task':>9}"
    )
    out.append(header)
    out.append("─" * len(header))
    for grp in sorted_groups:
        cells = _row_cells(grp)
        out.append(
            f"{cells[0]:<{grp_w}}  {cells[1]:>5}  {cells[2]:>8}  "
            f"{cells[3]:>10}  {cells[4]:>10}  {cells[5]:>9}  {cells[6]:>9}  "
            f"{cells[7]:>9}  {cells[8]:>9}"
        )
    if fence_close():
        out.append(fence_close())
    out.append("")
    return out


def _task_run_symbol(success, failure_reason) -> str:
    """Render a single run's compact pass/fail cell for the Per-Task Details table."""
    if success is None:
        return "— "
    if success:
        return "✓ "
    if failure_reason == FAILURE_REASON_CONTENT_FILTER:
        return "✗c"
    return "✗ "


def _stats_for_task(task_runs):
    """Aggregate per-task across runs: ✓/✗ list, success counts, mean tokens/llm/time."""
    statuses = [r.get("success") for r in task_runs]
    failure_reasons = [r.get("failure_reason") for r in task_runs]
    successes = sum(1 for s in statuses if s)
    total = len(task_runs)
    rate = successes / total if total else 0.0
    return {
        "statuses": statuses,
        "failure_reasons": failure_reasons,
        "successes": successes,
        "total": total,
        "rate": rate,
        "mean_tokens": _avg([r.get("tokens") for r in task_runs]),
        "mean_llm": _avg([r.get("llm_calls") for r in task_runs]),
        "mean_dur": _avg([r.get("duration") for r in task_runs]),
        # Vakra scores (M3 only): mean dialogue score and mean per-judge
        # scores across runs, ignoring runs where a judge was skipped.
        "mean_match_rate": _avg([r.get("match_rate") for r in task_runs]),
        "mean_judge": {
            key: _avg([(r.get("judge_scores") or {}).get(key) for r in task_runs]) for key in _JUDGE_KEYS
        },
    }


def generate_report(config_results: dict[str, list[str]], markdown: bool = True) -> str:
    """Generate a multi-run comparison report with pass@k / pass^k, compact
    per-task ✓/✗ rows, and aggregated tokens/LLM/time per task.

    When ``markdown=True`` (default), section titles use markdown headers and
    tabular sections are wrapped in fenced code blocks — that's what gets saved
    to report.md. When ``markdown=False``, the same content is emitted as plain
    text (no ``##`` / no ```` ``` ``` ````) so it's readable on a terminal in a
    monospace font without rendering.
    """
    h1 = (lambda s: f"# {s}") if markdown else (lambda s: f"\n{s}\n{'=' * len(s)}")
    h2 = (lambda s: f"## {s}") if markdown else (lambda s: f"\n{s}\n{'-' * len(s)}")
    h3 = (lambda s: f"### {s}") if markdown else (lambda s: f"\n{s}")
    fence_open = (lambda: "```text") if markdown else (lambda: "")
    fence_close = (lambda: "```") if markdown else (lambda: "")
    # ---- 1. Parse all result files into model_data {config_key: [run_dict, ...]}
    model_data = {}
    max_runs = 0
    for config_key, file_paths in sorted(config_results.items()):
        runs = []
        for fp in file_paths:
            try:
                runs.append(parse_result_file(fp))
            except Exception as e:
                print(f"Warning: Failed to parse {fp}: {e}", file=sys.stderr)
        if not runs:
            continue
        model_data[config_key] = runs
        max_runs = max(max_runs, len(runs))

    if not model_data:
        return f"{h1('Evaluation Comparison Report')}\n\nNo valid result files found.\n"

    lines = [h1("Evaluation Comparison Report"), ""]
    lines.append(f"{max_runs} run(s) per configuration.")
    lines.append("")

    # ---- 2. Summary Table (with pass@k, pass^k, maj@k, consistency)
    lines.append(h2("Summary"))
    lines.append("")
    if fence_open():
        lines.append(fence_open())
    header = (
        f"{'Configuration':<28} {'Runs':>4}  {'Pass@1':>9}  "
        f"{'pass@' + str(max_runs):>9}  {'pass^' + str(max_runs):>9}  "
        f"{'maj@' + str(max_runs):>9}  {'Cons':>5}  "
        f"{'Tokens':>10}  {'LLM':>5}  {'Time':>7}"
    )
    lines.append(header)
    lines.append("─" * len(header))
    for config_key, runs in model_data.items():
        display = _format_config_label(config_key)
        stats = _per_config_pass_stats(runs)
        n = len(runs)
        avg_tokens = sum(r["tokens"] for r in runs) / n
        avg_llm = sum(r["llm_calls"] for r in runs) / n
        avg_dur = _avg([r["duration"] for r in runs])

        cons_s = f"{stats['consistency']:.2f}" if stats["consistency"] is not None else "  --"
        lines.append(
            f"{display:<28} {n:>4}  {stats['avg_rate'] * 100:>8.1f}%  "
            f"{stats['pass_at_n'] * 100:>8.1f}%  {stats['pass_pow_n'] * 100:>8.1f}%  "
            f"{stats['maj_at_n'] * 100:>8.1f}%  {cons_s:>5}  "
            f"{_fmt(avg_tokens):>10}  {_fmt(avg_llm):>5}  {_fmt(avg_dur, 's'):>7}"
        )
    if fence_close():
        lines.append(fence_close())
    lines.append("")

    total_content_filter = sum(
        _content_filter_failure_count(r["tasks"]) for runs in model_data.values() for r in runs
    )
    if total_content_filter > 0:
        note = (
            f"{total_content_filter} task run(s) failed because Azure's content filter rejected the "
            "request (scored 0.0; prompt vs. completion not distinguishable from the captured error "
            "text — marked ✗c in Per-Task Details)"
        )
        if markdown:
            lines.append(f"- **Content filter failures**: {note}")
        else:
            lines.append(f"  Content filter    {note}")
        lines.append("")

    # ---- 2a. Cost Summary: per-config totals and per-task averages for
    # tokens, LLM calls, and time. "Total" here is the per-run total averaged
    # across runs (same basis as the Tokens/LLM/Time columns above);
    # "Avg/Task" divides that by the average task count per run.
    lines.append(h2("Cost Summary"))
    lines.append("")
    if fence_open():
        lines.append(fence_open())
    cost_header = (
        f"{'Configuration':<28} {'Tokens':>10}  {'Avg/Task':>10}  "
        f"{'LLM':>6}  {'Avg/Task':>9}  {'Time':>8}  {'Avg/Task':>9}"
    )
    lines.append(cost_header)
    lines.append("─" * len(cost_header))
    for config_key, runs in model_data.items():
        display = _format_config_label(config_key)
        n = len(runs)
        avg_tokens = sum(r["tokens"] for r in runs) / n
        avg_llm = sum(r["llm_calls"] for r in runs) / n
        avg_dur = _avg([r["duration"] for r in runs])
        avg_n_tasks = _avg([r["total"] for r in runs])
        per_task_tokens = (avg_tokens / avg_n_tasks) if avg_n_tasks else None
        per_task_llm = (avg_llm / avg_n_tasks) if avg_n_tasks else None
        per_task_dur = (avg_dur / avg_n_tasks) if (avg_dur is not None and avg_n_tasks) else None
        lines.append(
            f"{display:<28} {_fmt(avg_tokens):>10}  {_fmt(per_task_tokens):>10}  "
            f"{_fmt(avg_llm):>6}  {_fmt(per_task_llm):>9}  "
            f"{_fmt(avg_dur, 's'):>8}  {_fmt(per_task_dur, 's'):>9}"
        )
    if fence_close():
        lines.append(fence_close())
    lines.append("")

    # ---- 2b. Per-group breakdowns (only when result files carry the relevant
    # metadata, so unrelated reports stay unchanged):
    #   - difficulty (AppWorld)
    #   - normal/challenge test set (AppWorld, via eval_config.toml)
    #   - capability/domain (M3)
    diff_section = _per_group_section(
        model_data,
        fence_open,
        fence_close,
        h2,
        title="Per-Difficulty Breakdown",
        col_label="Diff",
        group_fn=_difficulty_group,
        sort_key=_difficulty_sort_key,
    )
    if diff_section:
        lines.extend(diff_section)

    testset_section = _per_group_section(
        model_data,
        fence_open,
        fence_close,
        h2,
        title="Per-Test-Set Breakdown (AppWorld)",
        col_label="Test Set",
        group_fn=_appworld_test_set_group(_load_appworld_categories()),
    )
    if testset_section:
        lines.extend(testset_section)

    capdom_section = _per_group_section(
        model_data,
        fence_open,
        fence_close,
        h2,
        title="Per-Capability/Domain Breakdown (M3)",
        col_label="Capability/Domain",
        group_fn=_m3_capability_domain_group,
    )
    if capdom_section:
        lines.extend(capdom_section)

    # ---- 3. Per-Run Scores
    lines.append(h2("Per-Run Scores"))
    lines.append("")
    if fence_open():
        lines.append(fence_open())
    run_cols = "  ".join(f"R{i + 1}" for i in range(max_runs))
    per_run_header = f"{'Configuration':<28} {run_cols}  {'Mean':>5}"
    lines.append(per_run_header)
    lines.append("─" * len(per_run_header))
    for config_key, runs in model_data.items():
        display = _format_config_label(config_key)
        passes = [r["passed"] for r in runs]
        padded = passes + [None] * (max_runs - len(passes))
        cells = "  ".join(f"{p:>2}" if isinstance(p, int) else f"{'—':>2}" for p in padded)
        mean_passes = sum(passes) / len(passes) if passes else 0.0
        lines.append(f"{display:<28} {cells}  {mean_passes:>5.1f}")
    if fence_close():
        lines.append(fence_close())
    lines.append("")

    # ---- 4. Per-Task Details (compact ✓/✗ row + aggregate columns + pass@k footer)
    lines.append(h2("Per-Task Details"))
    lines.append("")
    for config_key, runs in model_data.items():
        display = _format_config_label(config_key)
        lines.append(h3(display))
        lines.append("")
        if fence_open():
            lines.append(fence_open())

        # Collect all task IDs across runs
        all_tasks = list({t for r in runs for t in r["tasks"].keys()})

        # M3 result files tag each task with capability (m3_task_id), domain and
        # the 1-based task number from the input data. When present we surface
        # them as leading columns and order rows by (capability, domain, #) so a
        # UUID-only row becomes attributable. Non-M3 benchmarks (e.g. AppWorld)
        # don't set these → columns are suppressed and the legacy layout stands.
        task_meta = {}
        for r in runs:
            for tname, t in r["tasks"].items():
                task_meta.setdefault(tname, t)

        def _cap_label(t, _m=task_meta):
            tid = _m.get(t, {}).get("m3_task_id")
            return f"m3_task_{tid}" if tid is not None else ""

        def _dom_label(t, _m=task_meta):
            return _m.get(t, {}).get("domain") or ""

        def _num_label(t, _m=task_meta):
            n = _m.get(t, {}).get("task_number")
            return str(n) if n is not None else ""

        m3_mode = any(
            task_meta.get(t, {}).get("m3_task_id") is not None and task_meta.get(t, {}).get("domain")
            for t in all_tasks
        )
        # Vakra-scored M3 results carry `match_rate` on every task; when
        # present, the table gains Dialogue + per-judge mean-score columns.
        has_vakra = m3_mode and any(
            r["tasks"].get(t, {}).get("match_rate") is not None for r in runs for t in all_tasks
        )
        if m3_mode:
            all_tasks.sort(
                key=lambda t: (
                    task_meta.get(t, {}).get("m3_task_id") or 0,
                    _dom_label(t),
                    task_meta.get(t, {}).get("task_number") or 0,
                    t,
                )
            )
            cap_w = max(len("Capability"), max((len(_cap_label(t)) for t in all_tasks), default=0))
            dom_w = max(len("Domain"), max((len(_dom_label(t)) for t in all_tasks), default=0))
            num_w = max(len("#"), max((len(_num_label(t)) for t in all_tasks), default=0))
            prefix_hdr = f"{'Capability':<{cap_w}} {'Domain':<{dom_w}} {'#':>{num_w}}  "
        else:
            all_tasks.sort()
            cap_w = dom_w = num_w = 0
            prefix_hdr = ""

        n_runs = len(runs)
        run_cols = "  ".join(f"R{i + 1}" for i in range(n_runs))
        # Truncate task IDs to keep table readable but distinguishable
        col_task_w = min(28, max((len(t) for t in all_tasks), default=8))
        vakra_hdr = f"{'Dialog':>6} {'ExctM':>5} {'Answer':>6} {'Ground':>6}   " if has_vakra else ""
        task_header = (
            f"{prefix_hdr}{'Task':<{col_task_w}} {run_cols}   {'Successes':>10}   "
            f"{'Rate':>6}   {vakra_hdr}{'Tokens':>8} {'LLM':>5} {'Time':>6}"
        )
        lines.append(task_header)
        lines.append("─" * len(task_header))

        # Track aggregates across tasks for the AVERAGE row
        sum_tokens = 0.0
        n_tokens = 0
        sum_llm = 0.0
        n_llm = 0
        sum_dur = 0.0
        n_dur = 0
        sum_match_rate = 0.0
        n_match_rate = 0
        sum_judge = dict.fromkeys(_JUDGE_KEYS, 0.0)
        n_judge = dict.fromkeys(_JUDGE_KEYS, 0)
        total_successes = 0
        any_pass = 0
        all_pass = 0
        maj_pass = 0

        for task in all_tasks:
            task_runs = [r["tasks"].get(task, {}) for r in runs]
            stats = _stats_for_task(task_runs)
            symbols = "  ".join(
                _task_run_symbol(s, fr) for s, fr in zip(stats["statuses"], stats["failure_reasons"])
            )
            successes = stats["successes"]
            total = stats["total"]
            rate_pct = stats["rate"] * 100
            total_successes += successes
            if successes > 0:
                any_pass += 1
            if successes == total and total > 0:
                all_pass += 1
            if total > 0 and successes > total / 2:
                maj_pass += 1
            mt = stats["mean_tokens"]
            ml = stats["mean_llm"]
            md = stats["mean_dur"]
            if mt is not None:
                sum_tokens += mt
                n_tokens += 1
            if ml is not None:
                sum_llm += ml
                n_llm += 1
            if md is not None:
                sum_dur += md
                n_dur += 1
            mr = stats["mean_match_rate"]
            if mr is not None:
                sum_match_rate += mr
                n_match_rate += 1
            for key in _JUDGE_KEYS:
                jv = stats["mean_judge"].get(key)
                if jv is not None:
                    sum_judge[key] += jv
                    n_judge[key] += 1

            task_disp = task if len(task) <= col_task_w else task[: col_task_w - 1] + "…"
            row_prefix = (
                f"{_cap_label(task):<{cap_w}} {_dom_label(task):<{dom_w}} {_num_label(task):>{num_w}}  "
                if m3_mode
                else ""
            )
            vakra_cols = ""
            if has_vakra:
                mj = stats["mean_judge"]
                vakra_cols = (
                    f"{_fmt_score(mr):>6} "
                    f"{_fmt_score(mj.get('exactmatch')):>5} "
                    f"{_fmt_score(mj.get('answer')):>6} "
                    f"{_fmt_score(mj.get('groundedness')):>6}   "
                )
            lines.append(
                f"{row_prefix}{task_disp:<{col_task_w}} {symbols}   "
                f"{successes:>3}/{total:<3}   {rate_pct:>5.1f}%   {vakra_cols}"
                f"{_fmt(mt):>8} {_fmt(ml):>5} {_fmt(md, 's'):>6}"
            )

        # AVERAGE row
        n_tasks = len(all_tasks)
        if n_tasks:
            avg_successes = total_successes / n_tasks
            avg_rate = avg_successes / n_runs * 100 if n_runs else 0.0
            avg_tok = _fmt(sum_tokens / n_tokens) if n_tokens else "--"
            avg_llm = _fmt(sum_llm / n_llm) if n_llm else "--"
            avg_dur = _fmt(sum_dur / n_dur, "s") if n_dur else "--"
            lines.append("─" * len(task_header))
            spacer = "  ".join("──" for _ in range(n_runs))
            avg_prefix = f"{'':<{cap_w}} {'':<{dom_w}} {'':>{num_w}}  " if m3_mode else ""
            avg_vakra_cols = ""
            if has_vakra:
                avg_mr = _fmt_score(sum_match_rate / n_match_rate) if n_match_rate else "--"
                avg_judge = {
                    key: (_fmt_score(sum_judge[key] / n_judge[key]) if n_judge[key] else "--")
                    for key in _JUDGE_KEYS
                }
                avg_vakra_cols = (
                    f"{avg_mr:>6} {avg_judge['exactmatch']:>5} "
                    f"{avg_judge['answer']:>6} {avg_judge['groundedness']:>6}   "
                )
            lines.append(
                f"{avg_prefix}{'AVERAGE':<{col_task_w}} {spacer}   "
                f"{avg_successes:>3.1f}/{n_runs:<3}   {avg_rate:>5.1f}%   {avg_vakra_cols}"
                f"{avg_tok:>8} {avg_llm:>5} {avg_dur:>6}"
            )
            lines.append("")
            cons = (all_pass / maj_pass) if maj_pass else None
            cons_s = f"{cons:.2f}" if cons is not None else "  --"
            lines.append(
                f"{'k':<4} {'Tasks':>5}  {'pass@k':>9}  {'pass^k':>9}  "
                f"{'maj@k':>9}  {'Cons':>5}  {'Average':>10}"
            )
            lines.append(
                f"{n_runs:<4} {n_tasks:>5}  "
                f"{any_pass:>3}/{n_tasks:<3}   {all_pass:>3}/{n_tasks:<3}   "
                f"{maj_pass:>3}/{n_tasks:<3}   {cons_s:>5}  "
                f"{avg_rate:>9.1f}%"
            )

        if fence_close():
            lines.append(fence_close())
        lines.append("")

    # ---- 5. Metric glossary
    lines.append(h2("Metrics"))
    lines.append("")
    lines.append("- **pass@k**: at least 1 success across k runs (any-pass coverage).")
    lines.append("- **pass^k**: all k runs successful (perfect reliability).")
    lines.append("- **maj@k**: majority of runs passed (> k/2). Captures tasks solved more often than not.")
    lines.append(
        "- **Cons** (Consistency): pass^k / maj@k. Of the tasks the agent solves most of the time, "
        "what fraction does it solve every time? 1.0 = perfectly reliable on its winnable tasks; "
        "lower = higher variance. `--` when no task passes a majority."
    )
    lines.append(
        "- **✗c**: task run aborted by Azure's content filter (scored 0.0; prompt vs. completion not "
        "distinguishable from the captured error text — see Content filter failures note under Summary)."
    )
    lines.append("")

    return "\n".join(lines)


def _bucket_m3_tasks(tasks: dict) -> tuple:
    """Group M3 tasks by (m3_task_id, domain) and assign a 1-N ordinal within
    each bucket. Returns (rows, has_grouping) where rows is a list of dicts
    with the new column shape and has_grouping is False when no result has
    m3_task_id/domain set (non-m3 callers — fall back to legacy flat table).
    """
    has_grouping = any(t.get("m3_task_id") is not None and t.get("domain") for t in tasks.values())
    if not has_grouping:
        rows = []
        for name, t in tasks.items():
            rows.append(
                {
                    "label": name,
                    "m3_task_id": None,
                    "domain": None,
                    "ordinal": None,
                    "uuid": t.get("uuid") or name,
                    "data": t,
                }
            )
        return rows, False

    # Group by (task_id, domain), sort within each group by uuid for stability.
    from collections import defaultdict

    buckets: dict = defaultdict(list)
    ungrouped = []
    for name, t in tasks.items():
        tid = t.get("m3_task_id")
        dom = t.get("domain")
        if tid is None or not dom:
            ungrouped.append((name, t))
            continue
        buckets[(int(tid), str(dom))].append((name, t))

    rows = []
    for key in sorted(buckets.keys()):
        # Order within a (capability, domain) bucket by the input-data task
        # number when present (stable, matches the source file), else by uuid.
        members = sorted(
            buckets[key],
            key=lambda nt: (nt[1].get("task_number") or 0, nt[1].get("uuid") or nt[0]),
        )
        for i, (name, t) in enumerate(members, start=1):
            rows.append(
                {
                    "label": name,
                    "m3_task_id": key[0],
                    "domain": key[1],
                    # Prefer the source task number; fall back to positional.
                    "ordinal": t.get("task_number") if t.get("task_number") is not None else i,
                    "uuid": t.get("uuid") or name,
                    "data": t,
                }
            )
    for name, t in ungrouped:
        rows.append(
            {
                "label": name,
                "m3_task_id": None,
                "domain": None,
                "ordinal": None,
                "uuid": t.get("uuid") or name,
                "data": t,
            }
        )
    return rows, True


def generate_eval_report(result_file: str, markdown: bool = True) -> str:
    """Generate a single-evaluation-run report.

    When the result file is M3-shaped (each task has ``m3_task_id`` + ``domain``),
    tasks are grouped per (capability, domain) with a 1-N ordinal so the table
    rows are readable instead of an unattributed UUID. When ``markdown=False``,
    the same content is rendered as a plain-text monospace table for terminals
    (compare.sh's stdout path); ``markdown=True`` (default) is what gets saved
    into the bundle's report.md.
    """
    parsed = parse_result_file(result_file)
    rows, grouped = _bucket_m3_tasks(parsed["tasks"])
    cost = _aggregate_costs(parsed["tasks"])

    h1 = (lambda s: f"# {s}") if markdown else (lambda s: f"\n{s}\n{'=' * len(s)}")
    h2 = (lambda s: f"## {s}") if markdown else (lambda s: f"\n{s}\n{'-' * len(s)}")
    fence_open = (lambda: "```text") if markdown else (lambda: "")
    fence_close = (lambda: "```") if markdown else (lambda: "")

    lines = [h1("Evaluation Report"), ""]
    lines.append(h2("Summary"))
    lines.append("")
    if markdown:
        lines.append(f"- **Pass@1**: {parsed['passed']}/{parsed['total']} ({parsed['rate']:.1%})")
        lines.append(f"- **Total Tokens**: {_fmt(parsed['tokens'])}")
        lines.append(f"- **Avg Tokens / Task**: {_fmt(cost['avg_tokens'])}")
        lines.append(f"- **Total LLM Calls**: {_fmt(parsed['llm_calls'])}")
        lines.append(f"- **Avg LLM Calls / Task**: {_fmt(cost['avg_llm_calls'])}")
        lines.append(f"- **Total Duration**: {_fmt(parsed.get('duration'), 's')}")
        lines.append(f"- **Avg Duration / Task**: {_fmt(cost['avg_duration'], 's')}")
    else:
        lines.append(f"  Pass@1             {parsed['passed']}/{parsed['total']} ({parsed['rate']:.1%})")
        lines.append(f"  Total Tokens       {_fmt(parsed['tokens'])}")
        lines.append(f"  Avg Tokens/Task    {_fmt(cost['avg_tokens'])}")
        lines.append(f"  Total LLM Calls    {_fmt(parsed['llm_calls'])}")
        lines.append(f"  Avg LLM Calls/Task {_fmt(cost['avg_llm_calls'])}")
        lines.append(f"  Total Duration     {_fmt(parsed.get('duration'), 's')}")
        lines.append(f"  Avg Duration/Task  {_fmt(cost['avg_duration'], 's')}")
    _append_content_filter_summary(lines, parsed["tasks"], markdown=markdown)
    lines.append("")

    lines.append(h2("Per-Task Results"))
    lines.append("")

    # M3 Vakra-scored results carry `match_rate` (dialogue score) on every
    # task. When present, the table gains Dialogue + per-judge columns; absent
    # for non-Vakra-scored M3 runs (e.g. keyword-only scoring) so those reports
    # stay unchanged.
    has_vakra = grouped and any(row["data"].get("match_rate") is not None for row in rows)
    if has_vakra:
        lines.append(
            "Dialogue = Vakra aggregated dialogue score (>= 1.00 = pass). "
            "ExactMatch/Answer/Groundedness = last-turn judge scores (`--` = judge skipped)."
        )
        lines.append("")

    if grouped:
        if markdown:
            if has_vakra:
                lines.append(
                    "| Task | Domain | # | Result | Dialogue | ExactMatch | Answer | Groundedness "
                    "| Tokens | Cost | LLM Calls | Cache Tokens | Duration | Steps |"
                )
                lines.append(
                    "|------|--------|---|--------|----------|------------|--------|--------------"
                    "|--------|------|-----------|--------------|----------|-------|"
                )
            else:
                lines.append(
                    "| Task | Domain | # | Result | Tokens | Cost | LLM Calls | Cache Tokens | Duration | Steps |"
                )
                lines.append(
                    "|------|--------|---|--------|--------|------|-----------|--------------|----------|-------|"
                )
            current_key: tuple = (None, None)
            for row in rows:
                t = row["data"]
                tid = row["m3_task_id"]
                dom = row["domain"] or ""
                ordn = row["ordinal"]
                key = (tid, dom)
                # Blank task/domain cells on continuation rows for readability.
                if key == current_key:
                    tid_disp = ""
                    dom_disp = ""
                else:
                    tid_disp = str(tid) if tid is not None else "—"
                    dom_disp = dom
                    current_key = key
                ordn_disp = str(ordn) if ordn is not None else "—"
                status = _task_result_mark(t)
                vakra_cols = ""
                if has_vakra:
                    judge = t.get("judge_scores") or {}
                    vakra_cols = (
                        f"| {_fmt_score(t.get('match_rate'))} "
                        f"| {_fmt_score(judge.get('exactmatch'))} "
                        f"| {_fmt_score(judge.get('answer'))} "
                        f"| {_fmt_score(judge.get('groundedness'))} "
                    )
                lines.append(
                    f"| {tid_disp} | {dom_disp} | {ordn_disp} | {status} {vakra_cols}"
                    f"| {_fmt(t['tokens'])} | {_fmt(t.get('cost'), '$')} "
                    f"| {_fmt(t.get('llm_calls'))} | {_fmt(t.get('cache_tokens'))} "
                    f"| {_fmt(t.get('duration'), 's')} | {_fmt(t.get('steps'))} |"
                )
        else:
            # Plain-text table — fixed widths, separators between (task, domain) groups.
            col_task = "Task"
            col_dom_w = max(len("Domain"), max((len(r["domain"] or "") for r in rows), default=8))
            if has_vakra:
                header = (
                    f"  {col_task:<4}  {'Domain':<{col_dom_w}}  {'#':>2}  "
                    f"{'R':<2}  {'Dialog':>6}  {'ExctM':>5}  {'Answer':>6}  {'Ground':>6}  "
                    f"{'Tokens':>10}  {'Cost':>7}  {'LLM':>5}  "
                    f"{'Cache':>10}  {'Duration':>9}  {'Steps':>5}"
                )
            else:
                header = (
                    f"  {col_task:<4}  {'Domain':<{col_dom_w}}  {'#':>2}  "
                    f"{'R':<2}  {'Tokens':>10}  {'Cost':>7}  {'LLM':>5}  "
                    f"{'Cache':>10}  {'Duration':>9}  {'Steps':>5}"
                )
            lines.append(header)
            lines.append("  " + "─" * (len(header) - 2))
            current_key2: tuple = (None, None)
            for row in rows:
                t = row["data"]
                tid = row["m3_task_id"]
                dom = row["domain"] or ""
                ordn = row["ordinal"]
                key = (tid, dom)
                if key != current_key2 and current_key2 != (None, None):
                    lines.append("  " + "─" * (len(header) - 2))
                if key == current_key2:
                    tid_disp = ""
                    dom_disp = ""
                else:
                    tid_disp = str(tid) if tid is not None else "—"
                    dom_disp = dom
                    current_key2 = key
                ordn_disp = str(ordn) if ordn is not None else "—"
                mark = _task_result_mark(t, markdown=False)
                vakra_cols = ""
                if has_vakra:
                    judge = t.get("judge_scores") or {}
                    vakra_cols = (
                        f"{_fmt_score(t.get('match_rate')):>6}  "
                        f"{_fmt_score(judge.get('exactmatch')):>5}  "
                        f"{_fmt_score(judge.get('answer')):>6}  "
                        f"{_fmt_score(judge.get('groundedness')):>6}  "
                    )
                lines.append(
                    f"  {tid_disp:<4}  {dom_disp:<{col_dom_w}}  {ordn_disp:>2}  "
                    f"{mark:<2}  {vakra_cols}"
                    f"{_fmt(t['tokens']):>10}  "
                    f"{_fmt(t.get('cost'), '$'):>7}  "
                    f"{_fmt(t.get('llm_calls')):>5}  "
                    f"{_fmt(t.get('cache_tokens')):>10}  "
                    f"{_fmt(t.get('duration'), 's'):>9}  "
                    f"{_fmt(t.get('steps')):>5}"
                )
    else:
        # Legacy flat table (e.g. AppWorld where m3_task_id/domain aren't set).
        if markdown:
            lines.append("| Task | Result | Tokens | Cost | LLM Calls | Cache Tokens | Duration | Steps |")
            lines.append("|------|--------|--------|------|-----------|--------------|----------|-------|")
            for row in rows:
                t = row["data"]
                status = _task_result_mark(t)
                lines.append(
                    f"| {row['label']} | {status} | {_fmt(t['tokens'])} "
                    f"| {_fmt(t.get('cost'), '$')} | {_fmt(t.get('llm_calls'))} "
                    f"| {_fmt(t.get('cache_tokens'))} | {_fmt(t.get('duration'), 's')} "
                    f"| {_fmt(t.get('steps'))} |"
                )
        else:
            col_task_w = min(40, max(len("Task"), max((len(r["label"]) for r in rows), default=8)))
            header = (
                f"  {'Task':<{col_task_w}}  {'R':<2}  {'Tokens':>10}  "
                f"{'Cost':>7}  {'LLM':>5}  {'Cache':>10}  "
                f"{'Duration':>9}  {'Steps':>5}"
            )
            lines.append(header)
            lines.append("  " + "─" * (len(header) - 2))
            for row in rows:
                t = row["data"]
                lbl = row["label"]
                if len(lbl) > col_task_w:
                    lbl = lbl[: col_task_w - 1] + "…"
                mark = _task_result_mark(t, markdown=False)
                lines.append(
                    f"  {lbl:<{col_task_w}}  {mark:<2}  "
                    f"{_fmt(t['tokens']):>10}  "
                    f"{_fmt(t.get('cost'), '$'):>7}  "
                    f"{_fmt(t.get('llm_calls')):>5}  "
                    f"{_fmt(t.get('cache_tokens')):>10}  "
                    f"{_fmt(t.get('duration'), 's'):>9}  "
                    f"{_fmt(t.get('steps')):>5}"
                )

    lines.append("")

    # ---- Per-group breakdowns (only when this report's tasks carry the
    # relevant metadata, so unrelated reports stay unchanged):
    #   - capability rollup (M3)        — coarse, one row per capability
    #   - capability/domain (M3)        — fine, one row per (capability, domain)
    #   - difficulty (AppWorld)
    #   - normal/challenge test set (AppWorld, via eval_config.toml)
    lines.extend(
        _eval_group_breakdown(
            parsed["tasks"],
            fence_open,
            fence_close,
            h2,
            title="Capability Breakdown",
            col_label="Capability",
            group_fn=_m3_capability_group,
            sort_key=_m3_capability_sort_key,
            markdown=markdown,
        )
    )
    lines.extend(
        _eval_group_breakdown(
            parsed["tasks"],
            fence_open,
            fence_close,
            h2,
            title="Capability/Domain Breakdown",
            col_label="Capability/Domain",
            group_fn=_m3_capability_domain_group,
            markdown=markdown,
        )
    )
    lines.extend(
        _eval_group_breakdown(
            parsed["tasks"],
            fence_open,
            fence_close,
            h2,
            title="Difficulty Breakdown",
            col_label="Diff",
            group_fn=_difficulty_group,
            sort_key=_difficulty_sort_key,
            markdown=markdown,
        )
    )
    lines.extend(
        _eval_group_breakdown(
            parsed["tasks"],
            fence_open,
            fence_close,
            h2,
            title="Test-Set Breakdown (AppWorld)",
            col_label="Test Set",
            group_fn=_appworld_test_set_group(_load_appworld_categories()),
            markdown=markdown,
        )
    )

    return "\n".join(lines)


def main():
    # Detect subcommand mode: if first positional arg is "eval" or "compare", use subcommands.
    # Otherwise, fall back to legacy mode (compare from stdin with --output).
    if len(sys.argv) > 1 and sys.argv[1] in ("eval", "compare"):
        command = sys.argv[1]
        if command == "eval":
            parser = argparse.ArgumentParser(description="Generate single-eval report")
            parser.add_argument("command")  # consume "eval"
            parser.add_argument("--result-file", required=True)
            parser.add_argument("--output", "-o", default=None)
            args = parser.parse_args()
            report = generate_eval_report(args.result_file)
        else:
            parser = argparse.ArgumentParser(description="Generate comparison report")
            parser.add_argument("command")  # consume "compare"
            parser.add_argument("--output", "-o", default=None)
            args = parser.parse_args()
            config_results = json.loads(sys.stdin.read())
            report = generate_report(config_results)
    else:
        # Legacy mode: compare report from stdin (no subcommand)
        parser = argparse.ArgumentParser(description="Generate comparison report")
        parser.add_argument("--output", "-o", default=None)
        args = parser.parse_args()
        config_results = json.loads(sys.stdin.read())
        report = generate_report(config_results)

    # When --output is given (compare.sh's normal flow): write markdown to the
    # file, print the plain-text version to stdout. Without --output: just
    # print plain text. We don't echo the saved path here — compare.sh emits
    # the canonical bundle location at the end of the run, which is what the
    # user actually wants to navigate to.
    if args.output:
        # Compare-mode and eval-mode both produce markdown for the saved file
        # and re-render plain text for the terminal.
        if "command" in args and getattr(args, "command", None) == "eval":
            plain = generate_eval_report(args.result_file, markdown=False)
        else:
            plain = generate_report(config_results, markdown=False)
        Path(args.output).write_text(report)
        print(plain)
    else:
        # No file requested — just print whatever generate_* produced.
        print(report)


if __name__ == "__main__":
    main()
