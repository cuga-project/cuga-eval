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
from pathlib import Path

MODEL_DISPLAY_NAMES = {
    "gpt-oss": "GPT-OSS-120B",
    "gpt4o": "GPT-4o",
    "gpt4.1": "GPT-4.1",
    "opus4.5": "Claude Opus 4.5",
}


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
    """Format a numeric value, returning '--' if zero/None."""
    if val is None or val == 0:
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
            "steps": None,
            # AppWorld results carry a per-task difficulty band; preserved for
            # the per-difficulty breakdown in the multi-run summary. Other
            # benchmarks won't emit it and the breakdown will collapse to None.
            "difficulty": r.get("difficulty"),
            # M3-specific tags so the eval report can group by (task, domain).
            "m3_task_id": r.get("m3_task_id"),
            "domain": r.get("domain"),
            "uuid": r.get("uuid") or r.get("task_name") or r.get("name"),
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


def _per_difficulty_section(model_data, fence_open, fence_close, h2) -> list[str]:
    """Build per-difficulty breakdown rows. Returns [] when no difficulty info
    is available (so non-AppWorld reports stay unchanged)."""
    # Collect all difficulty levels seen across configs/runs.
    levels: set = set()
    for runs in model_data.values():
        for r in runs:
            for t in r["tasks"].values():
                d = t.get("difficulty")
                if d not in (None, "", "unknown"):
                    levels.add(str(d))
    if not levels:
        return []

    def _sort_key(d: str):
        try:
            return (0, int(d))
        except (ValueError, TypeError):
            return (1, d)

    sorted_levels = sorted(levels, key=_sort_key)
    out: list[str] = [h2("Per-Difficulty Breakdown"), ""]
    if fence_open():
        out.append(fence_open())
    header = (
        f"{'Configuration':<28} {'Diff':>4}  {'Tasks':>5}  "
        f"{'Pass Rate':>9}  {'pass@k':>8}  {'pass^k':>8}  "
        f"{'maj@k':>8}  {'Cons':>5}"
    )
    out.append(header)
    out.append("─" * len(header))
    for config_key, runs in model_data.items():
        display = _format_config_label(config_key)
        for lvl in sorted_levels:
            stats = _per_config_pass_stats(
                runs, task_filter=lambda t, _lvl=lvl: str(t.get("difficulty")) == _lvl
            )
            if stats["n_tasks"] == 0:
                continue
            cons_s = f"{stats['consistency']:.2f}" if stats["consistency"] is not None else "  --"
            out.append(
                f"{display:<28} {lvl:>4}  {stats['n_tasks']:>5}  "
                f"{stats['avg_rate'] * 100:>8.1f}%  "
                f"{stats['pass_at_n'] * 100:>7.1f}%  {stats['pass_pow_n'] * 100:>7.1f}%  "
                f"{stats['maj_at_n'] * 100:>7.1f}%  {cons_s:>5}"
            )
    if fence_close():
        out.append(fence_close())
    out.append("")
    return out


def _stats_for_task(task_runs):
    """Aggregate per-task across runs: ✓/✗ list, success counts, mean tokens/llm/time."""
    statuses = [r.get("success") for r in task_runs]
    successes = sum(1 for s in statuses if s)
    total = len(task_runs)
    rate = successes / total if total else 0.0
    return {
        "statuses": statuses,
        "successes": successes,
        "total": total,
        "rate": rate,
        "mean_tokens": _avg([r.get("tokens") for r in task_runs]),
        "mean_llm": _avg([r.get("llm_calls") for r in task_runs]),
        "mean_dur": _avg([r.get("duration") for r in task_runs]),
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
        f"{'Configuration':<28} {'Runs':>4}  {'Pass Rate':>9}  "
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

    # ---- 2b. Per-difficulty breakdown (only when result files carry it).
    # Difficulty is opt-in: AppWorld emits a `difficulty` per task; other
    # benchmarks don't, in which case the entire section is suppressed so
    # SDK reports stay unchanged.
    diff_section = _per_difficulty_section(model_data, fence_open, fence_close, h2)
    if diff_section:
        lines.extend(diff_section)

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
        all_tasks = sorted({t for r in runs for t in r["tasks"].keys()})

        n_runs = len(runs)
        run_cols = "  ".join(f"R{i + 1}" for i in range(n_runs))
        # Truncate task IDs to keep table readable but distinguishable
        col_task_w = min(28, max((len(t) for t in all_tasks), default=8))
        task_header = (
            f"{'Task':<{col_task_w}} {run_cols}   {'Successes':>10}   "
            f"{'Rate':>6}   {'Tokens':>8} {'LLM':>5} {'Time':>6}"
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
        total_successes = 0
        any_pass = 0
        all_pass = 0
        maj_pass = 0

        for task in all_tasks:
            task_runs = [r["tasks"].get(task, {}) for r in runs]
            stats = _stats_for_task(task_runs)
            symbols = "  ".join(("✓ " if s else "✗ ") if s is not None else "— " for s in stats["statuses"])
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

            task_disp = task if len(task) <= col_task_w else task[: col_task_w - 1] + "…"
            lines.append(
                f"{task_disp:<{col_task_w}} {symbols}   "
                f"{successes:>3}/{total:<3}   {rate_pct:>5.1f}%   "
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
            lines.append(
                f"{'AVERAGE':<{col_task_w}} {spacer}   "
                f"{avg_successes:>3.1f}/{n_runs:<3}   {avg_rate:>5.1f}%   "
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
        members = sorted(buckets[key], key=lambda nt: nt[1].get("uuid") or nt[0])
        for i, (name, t) in enumerate(members, start=1):
            rows.append(
                {
                    "label": name,
                    "m3_task_id": key[0],
                    "domain": key[1],
                    "ordinal": i,
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

    h1 = (lambda s: f"# {s}") if markdown else (lambda s: f"\n{s}\n{'=' * len(s)}")
    h2 = (lambda s: f"## {s}") if markdown else (lambda s: f"\n{s}\n{'-' * len(s)}")

    lines = [h1("Evaluation Report"), ""]
    lines.append(h2("Summary"))
    lines.append("")
    if markdown:
        lines.append(f"- **Pass Rate**: {parsed['passed']}/{parsed['total']} ({parsed['rate']:.1%})")
        lines.append(f"- **Total Tokens**: {_fmt(parsed['tokens'])}")
        lines.append(f"- **Total LLM Calls**: {_fmt(parsed['llm_calls'])}")
        lines.append(f"- **Total Duration**: {_fmt(parsed.get('duration'), 's')}")
    else:
        lines.append(f"  Pass Rate         {parsed['passed']}/{parsed['total']} ({parsed['rate']:.1%})")
        lines.append(f"  Total Tokens      {_fmt(parsed['tokens'])}")
        lines.append(f"  Total LLM Calls   {_fmt(parsed['llm_calls'])}")
        lines.append(f"  Total Duration    {_fmt(parsed.get('duration'), 's')}")
    lines.append("")

    lines.append(h2("Per-Task Results"))
    lines.append("")

    if grouped:
        if markdown:
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
                status = "✓" if t["success"] else "✗"
                lines.append(
                    f"| {tid_disp} | {dom_disp} | {ordn_disp} | {status} "
                    f"| {_fmt(t['tokens'])} | {_fmt(t.get('cost'), '$')} "
                    f"| {_fmt(t.get('llm_calls'))} | {_fmt(t.get('cache_tokens'))} "
                    f"| {_fmt(t.get('duration'), 's')} | {_fmt(t.get('steps'))} |"
                )
        else:
            # Plain-text table — fixed widths, separators between (task, domain) groups.
            col_task = "Task"
            col_dom_w = max(len("Domain"), max((len(r["domain"] or "") for r in rows), default=8))
            header = (
                f"  {col_task:<4}  {'Domain':<{col_dom_w}}  {'#':>2}  "
                f"{'R':<1}  {'Tokens':>10}  {'Cost':>7}  {'LLM':>5}  "
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
                mark = "✓" if t["success"] else "✗"
                lines.append(
                    f"  {tid_disp:<4}  {dom_disp:<{col_dom_w}}  {ordn_disp:>2}  "
                    f"{mark:<1}  {_fmt(t['tokens']):>10}  "
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
                status = "✓" if t["success"] else "✗"
                lines.append(
                    f"| {row['label']} | {status} | {_fmt(t['tokens'])} "
                    f"| {_fmt(t.get('cost'), '$')} | {_fmt(t.get('llm_calls'))} "
                    f"| {_fmt(t.get('cache_tokens'))} | {_fmt(t.get('duration'), 's')} "
                    f"| {_fmt(t.get('steps'))} |"
                )
        else:
            col_task_w = min(40, max(len("Task"), max((len(r["label"]) for r in rows), default=8)))
            header = (
                f"  {'Task':<{col_task_w}}  {'R':<1}  {'Tokens':>10}  "
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
                mark = "✓" if t["success"] else "✗"
                lines.append(
                    f"  {lbl:<{col_task_w}}  {mark:<1}  "
                    f"{_fmt(t['tokens']):>10}  "
                    f"{_fmt(t.get('cost'), '$'):>7}  "
                    f"{_fmt(t.get('llm_calls')):>5}  "
                    f"{_fmt(t.get('cache_tokens')):>10}  "
                    f"{_fmt(t.get('duration'), 's'):>9}  "
                    f"{_fmt(t.get('steps')):>5}"
                )

    lines.append("")
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
