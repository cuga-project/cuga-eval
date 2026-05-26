"""
Compare evaluation results across multiple models and configurations.

Reads result file paths grouped by config from stdin (JSON format),
computes aggregate metrics, and outputs plain text + LaTeX tables.

Input format (via stdin):
    {"model:config": ["file1.json", "file2.json"], ...}

Usage:
    echo '{"gpt-oss:policies": ["r1.json", "r2.json"]}' | python -m bpo_benchmark.scripts.compare_results
    echo '...' | python -m bpo_benchmark.scripts.compare_results --output report.md
"""

import argparse
import json
import sys
from pathlib import Path

# Display names for model profiles
MODEL_DISPLAY_NAMES = {
    "gpt-oss": "GPT-OSS-120B",
    "gpt4o": "GPT-4o",
    "gpt4.1": "GPT-4.1",
    "opus4.5": "Claude Opus 4.5",
}


def normalize_result(data: dict) -> dict:
    """Normalize result format to BPO-benchmark schema.

    Handles the internal eval format (metrics.passed, results[].success)
    by converting to BPO format (final_score_passes, detailed_results[].task_final_score).
    BPO-format results pass through unchanged.
    """
    # Already in BPO format
    if "detailed_results" in data or "final_score_passes" in data:
        return data

    # Internal eval format: {metrics: {total_tasks, passed}, results: [{success, ...}]}
    metrics = data.get("metrics", {})
    results_list = data.get("results", [])

    total_tasks = metrics.get("total_tasks", len(results_list))
    passed = metrics.get("passed", sum(1 for r in results_list if r.get("success")))

    detailed = []
    cum_tokens = 0
    cum_cache = 0
    cum_llm = 0
    for r in results_list:
        cum_tokens += r.get("total_tokens", 0) or 0
        cum_cache += r.get("total_cache_input_tokens", 0) or 0
        cum_llm += r.get("total_llm_calls", 0) or 0
        detailed.append(
            {
                "task_id": r.get("task_name", ""),
                "task_final_score": 1 if r.get("success") else 0,
                "metadata": {
                    "total_tokens": cum_tokens,
                    "total_cache_input_tokens": cum_cache,
                    "total_llm_calls": cum_llm,
                    "duration": r.get("full_execution_time"),
                },
            }
        )

    return {
        "total_tasks": total_tasks,
        "final_score_passes": passed,
        "final_score_accuracy": passed / total_tasks if total_tasks > 0 else 0,
        "detailed_results": detailed,
        "total_tokens": sum(r.get("total_tokens", 0) for r in results_list),
        "total_cache_input_tokens": sum(r.get("total_cache_input_tokens", 0) or 0 for r in results_list),
        "total_llm_calls": sum(r.get("total_llm_calls", 0) or 0 for r in results_list),
        "total_duration": sum(r.get("full_execution_time", 0) or 0 for r in results_list),
    }


def load_results(file_paths: list[str]) -> list[dict]:
    """Load result JSON files, returning list of parsed results."""
    results = []
    for path in file_paths:
        p = Path(path)
        if not p.exists():
            print(f"Warning: result file not found: {path}", file=sys.stderr)
            continue
        with open(p) as f:
            results.append(normalize_result(json.load(f)))
    return results


def compute_metrics(results: list[dict]) -> dict:
    """Compute aggregate metrics from multiple run results.

    Returns dict with: mean_accuracy, std_accuracy, pass_at_n, pass_pow_n,
    mean_tokens, per_run_passes, num_runs, total_tasks.
    """
    if not results:
        return {
            "mean_accuracy": 0,
            "std_accuracy": 0,
            "pass_at_n": 0,
            "pass_pow_n": 0,
            "mean_tokens": 0,
            "per_run_passes": [],
            "num_runs": 0,
            "total_tasks": 0,
            "per_task_details": [],
        }

    num_runs = len(results)
    total_tasks = results[0].get("total_tasks", 0)

    # Per-run pass counts and accuracy
    per_run_passes = []
    per_run_accuracy = []
    for r in results:
        passes = r.get("final_score_passes", 0)
        per_run_passes.append(passes)
        per_run_accuracy.append(r.get("final_score_accuracy", 0))

    mean_accuracy = sum(per_run_accuracy) / num_runs
    variance = sum((a - mean_accuracy) ** 2 for a in per_run_accuracy) / num_runs
    std_accuracy = variance**0.5

    # Per-task pass/fail across runs for pass@N and pass^N
    # pass@N: fraction of tasks where at least one run passed
    # pass^N: fraction of tasks where all runs passed
    per_task_details = []
    if total_tasks > 0:
        any_pass_count = 0
        all_pass_count = 0

        # Pre-compute per-task deltas for cumulative metadata fields.
        # Metadata like total_tokens/total_llm_calls are session-cumulative,
        # so per-task value = current - previous. Duration is already per-task.
        CUMULATIVE_FIELDS = ["total_tokens", "total_cache_input_tokens", "total_llm_calls"]

        def _get_per_task_deltas(run_result: dict) -> list[dict]:
            """Convert cumulative metadata to per-task values for one run."""
            detailed = run_result.get("detailed_results", [])
            deltas = []
            prev = {f: 0 for f in CUMULATIVE_FIELDS}
            for task_result in detailed:
                meta = task_result.get("metadata", {}) or {}
                delta = {}
                for field in CUMULATIVE_FIELDS:
                    v = meta.get(field)
                    if v is not None:
                        delta[field] = v - prev[field]
                        prev[field] = v
                    else:
                        delta[field] = None
                # Duration is already per-task (not cumulative)
                delta["duration"] = meta.get("duration")
                deltas.append(delta)
            return deltas

        run_deltas = [_get_per_task_deltas(r) for r in results]

        for task_idx in range(total_tasks):
            task_passes = []
            for r in results:
                detailed = r.get("detailed_results", [])
                if task_idx < len(detailed):
                    task_passes.append(detailed[task_idx].get("task_final_score", 0))
                else:
                    task_passes.append(0)

            success_count = sum(1 for p in task_passes if p == 1)
            success_rate = success_count / num_runs if num_runs > 0 else 0

            # Extract task_id from first result's detailed_results
            task_id = f"task_{task_idx + 1}"
            if results[0].get("detailed_results", []):
                detailed_0 = results[0]["detailed_results"]
                if task_idx < len(detailed_0):
                    task_id = detailed_0[task_idx].get("task_id", task_id)

            # Extract per-task metadata means across runs (using deltas)
            meta_tokens = []
            meta_cached = []
            meta_llm = []
            meta_duration = []
            for run_idx in range(num_runs):
                if task_idx < len(run_deltas[run_idx]):
                    d = run_deltas[run_idx][task_idx]
                    if d["total_tokens"] is not None:
                        meta_tokens.append(d["total_tokens"])
                    if d["total_cache_input_tokens"] is not None:
                        meta_cached.append(d["total_cache_input_tokens"])
                    if d["total_llm_calls"] is not None:
                        meta_llm.append(d["total_llm_calls"])
                    if d["duration"] is not None:
                        meta_duration.append(d["duration"])

            per_task_details.append(
                {
                    "task_id": task_id,
                    "runs": [int(p) for p in task_passes],
                    "success_count": success_count,
                    "success_rate": success_rate,
                    "mean_tokens": sum(meta_tokens) / len(meta_tokens) if meta_tokens else None,
                    "mean_cached": sum(meta_cached) / len(meta_cached) if meta_cached else None,
                    "mean_llm_calls": sum(meta_llm) / len(meta_llm) if meta_llm else None,
                    "mean_duration": sum(meta_duration) / len(meta_duration) if meta_duration else None,
                }
            )

            if any(p == 1 for p in task_passes):
                any_pass_count += 1
            if all(p == 1 for p in task_passes):
                all_pass_count += 1

        pass_at_n = any_pass_count / total_tasks
        pass_pow_n = all_pass_count / total_tasks
    else:
        pass_at_n = 0
        pass_pow_n = 0

    # Token usage (total across all tasks, averaged across runs)
    # Metadata total_tokens is cumulative, so the last task's value is the run total
    token_totals = []
    cache_totals = []
    llm_totals = []
    duration_totals = []
    for r in results:
        total = r.get("total_tokens", 0)
        if total == 0:
            detailed = r.get("detailed_results", [])
            if detailed:
                last_meta = detailed[-1].get("metadata", {}) or {}
                total = last_meta.get("total_tokens", 0)
        token_totals.append(total)

        cache = r.get("total_cache_input_tokens", 0) or 0
        if cache == 0:
            detailed = r.get("detailed_results", [])
            if detailed:
                last_meta = detailed[-1].get("metadata", {}) or {}
                cache = last_meta.get("total_cache_input_tokens", 0) or 0
        cache_totals.append(cache)

        llm = r.get("total_llm_calls", 0) or 0
        if llm == 0:
            detailed = r.get("detailed_results", [])
            if detailed:
                last_meta = detailed[-1].get("metadata", {}) or {}
                llm = last_meta.get("total_llm_calls", 0) or 0
        llm_totals.append(llm)

        dur = r.get("total_duration", 0) or 0
        if dur == 0:
            # Sum per-task durations from detailed_results
            detailed = r.get("detailed_results", [])
            for d in detailed:
                meta = d.get("metadata", {}) or {}
                task_dur = meta.get("duration")
                if task_dur is not None:
                    dur += task_dur
        if dur > 0:
            duration_totals.append(dur)

    mean_tokens = sum(token_totals) / num_runs if num_runs > 0 else 0
    mean_cached = sum(cache_totals) / num_runs if num_runs > 0 else 0
    mean_llm_calls = sum(llm_totals) / num_runs if num_runs > 0 else 0
    mean_duration = sum(duration_totals) / len(duration_totals) if duration_totals else None

    return {
        "mean_accuracy": mean_accuracy,
        "std_accuracy": std_accuracy,
        "pass_at_n": pass_at_n,
        "pass_pow_n": pass_pow_n,
        "mean_tokens": mean_tokens,
        "mean_cached": mean_cached,
        "mean_llm_calls": mean_llm_calls,
        "mean_duration": mean_duration,
        "per_run_passes": per_run_passes,
        "num_runs": num_runs,
        "total_tasks": total_tasks,
        "per_task_details": per_task_details,
    }


def format_pct(value: float) -> str:
    """Format a fraction as a percentage string like '82.3%'."""
    return f"{value * 100:.1f}%"


def format_tokens(tokens: float) -> str:
    """Format token count in millions like '6.6M'."""
    return f"{tokens / 1_000_000:.1f}M"


def format_tokens_k(tokens) -> str:
    """Format token count in thousands like '31K' for per-task display.

    Returns '--' when value is None.
    """
    if tokens is None:
        return "--"
    k = tokens / 1000
    if k < 100:
        return f"{k:.1f}K"
    return f"{int(k)}K"


def format_duration(seconds) -> str:
    """Format duration in seconds like '3.6s'. Returns '--' when None."""
    if seconds is None:
        return "--"
    return f"{seconds:.1f}s"


def format_llm_calls(calls) -> str:
    """Format LLM call count as integer. Returns '--' when None."""
    if calls is None:
        return "--"
    return str(int(calls))


def _split_config_key(config_key: str) -> tuple[str, str, str]:
    """Split a "model[:agent[:policy]]" key into (model, agent, policy).

    Defaults: agent="cuga", policy="policies". Tolerates legacy 2-tuple
    "model:policy" inputs by treating any second segment ending in "policies"
    as a policy_config rather than an agent.
    """
    parts = config_key.split(":")
    model = parts[0]
    agent = "cuga"
    policy = "policies"
    if len(parts) == 1:
        return model, agent, policy
    if len(parts) == 2:
        # Legacy 2-tuple: if the second part is "policies"/"no-policies", it's a
        # policy mode; otherwise treat it as an agent name.
        if parts[1] in ("policies", "no-policies"):
            policy = parts[1]
        else:
            agent = parts[1]
        return model, agent, policy
    # 3-tuple (or longer; ignore extras): model:agent:policy
    agent = parts[1] or "cuga"
    policy = parts[2] or "policies"
    return model, agent, policy


def build_model_data(config_results: dict[str, list[str]]) -> dict:
    """Group configs by (model, agent) and compute metrics.

    Returns: {(model, agent): {"policies": metrics_dict, "no-policies": metrics_dict}}
    """
    model_data: dict[tuple[str, str], dict[str, dict]] = {}
    for config_key, file_paths in config_results.items():
        model, agent, policy_config = _split_config_key(config_key)

        results = load_results(file_paths)
        metrics = compute_metrics(results)

        bucket = model_data.setdefault((model, agent), {})
        bucket[policy_config] = metrics

    return model_data


def _label(group_key: tuple[str, str], compare_agents: bool) -> str:
    """Render a (model, agent) tuple for display. Suffix with agent when comparing."""
    model, agent = group_key
    name = MODEL_DISPLAY_NAMES.get(model, model)
    if compare_agents:
        return f"{name} ({agent})"
    return name


def generate_plain_text(model_data: dict, compare_policies: bool, compare_agents: bool = False) -> str:
    """Generate plain text comparison table."""
    lines = []
    num_runs = 0

    # Determine N from first available metrics
    for model_metrics in model_data.values():
        for m in model_metrics.values():
            if m["num_runs"] > 0:
                num_runs = m["num_runs"]
                break
        if num_runs > 0:
            break

    if compare_policies:
        lines.append("## Summary Table\n")
        lines.append("```text")

        header = (
            f"{'Model':<20} {'Accuracy (W/O -> W)':>22}  {'Std Dev':>10}  "
            f"{'Gain':>9}  {'pass@' + str(num_runs) + ' (W/O -> W)':>22}  "
            f"{'pass^' + str(num_runs) + ' (W/O -> W)':>22}  {'Tokens (W/O -> W)':>22}"
            f"  {'Cached':>10}  {'LLM':>6}  {'Time':>8}"
        )
        lines.append(header)
        lines.append("─" * len(header))

        for group_key, configs in model_data.items():
            display_name = _label(group_key, compare_agents)
            wo = configs.get("no-policies", {})
            w = configs.get("policies", {})

            if wo and w:
                acc_str = (
                    f"{format_pct(wo.get('mean_accuracy', 0))} -> {format_pct(w.get('mean_accuracy', 0))}"
                )
                std_str = f"{wo.get('std_accuracy', 0) * 100:.1f}/{w.get('std_accuracy', 0) * 100:.1f}"
                gain = (w.get("mean_accuracy", 0) - wo.get("mean_accuracy", 0)) * 100
                gain_str = f"+{gain:.1f} pp" if gain >= 0 else f"{gain:.1f} pp"
                pass_n_str = f"{format_pct(wo.get('pass_at_n', 0))} -> {format_pct(w.get('pass_at_n', 0))}"
                pass_pow_str = (
                    f"{format_pct(wo.get('pass_pow_n', 0))} -> {format_pct(w.get('pass_pow_n', 0))}"
                )
                tok_str = (
                    f"{format_tokens(wo.get('mean_tokens', 0))} -> {format_tokens(w.get('mean_tokens', 0))}"
                )
                cached_str = format_tokens(w.get("mean_cached", 0))
                llm_str = format_llm_calls(w.get("mean_llm_calls"))
                dur_str = format_duration(w.get("mean_duration"))
            elif w:
                acc_str = format_pct(w.get("mean_accuracy", 0))
                std_str = f"{w.get('std_accuracy', 0) * 100:.1f}"
                gain_str = "N/A"
                pass_n_str = format_pct(w.get("pass_at_n", 0))
                pass_pow_str = format_pct(w.get("pass_pow_n", 0))
                tok_str = format_tokens(w.get("mean_tokens", 0))
                cached_str = format_tokens(w.get("mean_cached", 0))
                llm_str = format_llm_calls(w.get("mean_llm_calls"))
                dur_str = format_duration(w.get("mean_duration"))
            else:
                continue

            lines.append(
                f"{display_name:<20} {acc_str:>22}  {std_str:>10}  "
                f"{gain_str:>9}  {pass_n_str:>22}  {pass_pow_str:>22}  {tok_str:>22}"
                f"  {cached_str:>10}  {llm_str:>6}  {dur_str:>8}"
            )

        lines.append("```\n")
    else:
        # Single config (policies only)
        lines.append("## Summary Table\n")
        lines.append("```text")

        header = (
            f"{'Model':<20} {'Accuracy':>10}  {'Std Dev':>10}  "
            f"{'pass@' + str(num_runs):>10}  {'pass^' + str(num_runs):>10}  "
            f"{'Tokens':>10}  {'Cached':>10}  {'LLM':>6}  {'Time':>8}"
        )
        lines.append(header)
        lines.append("─" * len(header))

        for group_key, configs in model_data.items():
            display_name = _label(group_key, compare_agents)
            m = configs.get("policies", configs.get("no-policies", {}))
            if not m:
                continue
            std_str = f"{m.get('std_accuracy', 0) * 100:.1f}"
            lines.append(
                f"{display_name:<20} {format_pct(m.get('mean_accuracy', 0)):>10}  "
                f"{std_str:>10}  "
                f"{format_pct(m.get('pass_at_n', 0)):>10}  "
                f"{format_pct(m.get('pass_pow_n', 0)):>10}  "
                f"{format_tokens(m.get('mean_tokens', 0)):>10}  "
                f"{format_tokens(m.get('mean_cached', 0)):>10}  "
                f"{format_llm_calls(m.get('mean_llm_calls')):>6}  "
                f"{format_duration(m.get('mean_duration')):>8}"
            )

        lines.append("```\n")

    # Per-run scores table
    # Find max runs across all configs for column alignment
    max_runs = 0
    for model_metrics in model_data.values():
        for m in model_metrics.values():
            max_runs = max(max_runs, m.get("num_runs", 0))

    lines.append("## Per-Run Scores\n")
    lines.append("```text")

    run_headers = " ".join(f"Run{i + 1:>1}" for i in range(max_runs))
    per_run_header = f"{'Model':<20} {'Config':<12} {run_headers}  {'Mean':>6}"
    lines.append(per_run_header)
    lines.append("─" * len(per_run_header))

    for group_key, configs in model_data.items():
        display_name = _label(group_key, compare_agents)
        for config_name in ["no-policies", "policies"]:
            m = configs.get(config_name)
            if not m:
                continue
            config_label = (
                "no pol"
                if config_name == "no-policies"
                else f"{max_runs} pol"
                if compare_policies
                else "policies"
            )
            passes = m.get("per_run_passes", [])
            # Pad to max_runs columns for alignment
            padded = passes + [""] * (max_runs - len(passes))
            run_scores = " ".join(f"{p:>4}" if isinstance(p, int) else f"{'—':>4}" for p in padded)
            mean_passes = sum(passes) / len(passes) if passes else 0
            lines.append(f"{display_name:<20} {config_label:<12} {run_scores}  {mean_passes:>5.1f}")
        # Blank line between groups
        if compare_policies:
            lines.append("")

    lines.append("```\n")

    return "\n".join(lines)


def generate_per_task_details(model_data: dict, compare_policies: bool, compare_agents: bool = False) -> str:
    """Generate per-task detail tables showing pass/fail per run."""
    lines = []
    lines.append("## Per-Task Details\n")

    for group_key, configs in model_data.items():
        display_name = _label(group_key, compare_agents)
        for config_name in ["no-policies", "policies"]:
            m = configs.get(config_name)
            if not m or not m.get("per_task_details"):
                continue

            num_runs = m["num_runs"]
            total_tasks = m["total_tasks"]
            details = m["per_task_details"]

            if compare_policies:
                label = f"{display_name} ({config_name})"
            else:
                label = display_name

            lines.append(f"### {label}\n")
            lines.append("```text")

            # Header
            run_cols = "  ".join(f"R{i + 1}" for i in range(num_runs))
            header = (
                f"{'Task ID':<12} {run_cols}   {'Successes':>10}   {'Rate':>6}"
                f"   {'Tokens':>8} {'Cached':>8} {'LLM':>4} {'Time':>6}"
            )
            lines.append(header)
            lines.append("─" * len(header))

            # Per-task rows
            total_successes = 0
            sum_tokens = 0.0
            sum_cached = 0.0
            sum_llm = 0.0
            sum_duration = 0.0
            count_tokens = 0
            count_cached = 0
            count_llm = 0
            count_duration = 0
            for d in details:
                symbols = "  ".join("✓ " if r == 1 else "✗ " for r in d["runs"])
                task_id = d["task_id"]
                sc = d["success_count"]
                total_successes += sc
                rate = d["success_rate"] * 100

                mt = d.get("mean_tokens")
                mc = d.get("mean_cached")
                ml = d.get("mean_llm_calls")
                md = d.get("mean_duration")

                if mt is not None:
                    sum_tokens += mt
                    count_tokens += 1
                if mc is not None:
                    sum_cached += mc
                    count_cached += 1
                if ml is not None:
                    sum_llm += ml
                    count_llm += 1
                if md is not None:
                    sum_duration += md
                    count_duration += 1

                lines.append(
                    f"{task_id:<12} {symbols}   {sc:>3}/{num_runs:<3}       {rate:>5.1f}%"
                    f"   {format_tokens_k(mt):>8} {format_tokens_k(mc):>8} {format_llm_calls(ml):>4} {format_duration(md):>6}"
                )

            # Average row
            lines.append("─" * len(header))
            avg_successes = total_successes / total_tasks if total_tasks > 0 else 0
            avg_rate = avg_successes / num_runs * 100 if num_runs > 0 else 0
            avg_label = "AVERAGE"
            spacer = "  ".join("──" for _ in range(num_runs))

            avg_tok = format_tokens_k(sum_tokens / count_tokens) if count_tokens > 0 else "--"
            avg_cac = format_tokens_k(sum_cached / count_cached) if count_cached > 0 else "--"
            avg_llm = format_llm_calls(sum_llm / count_llm) if count_llm > 0 else "--"
            avg_dur = format_duration(sum_duration / count_duration) if count_duration > 0 else "--"

            lines.append(
                f"{avg_label:<12} {spacer}   {avg_successes:>3.1f}/{num_runs:<3}       {avg_rate:>5.1f}%"
                f"   {avg_tok:>8} {avg_cac:>8} {avg_llm:>4} {avg_dur:>6}"
            )

            # Summary footer
            any_pass = sum(1 for d in details if d["success_count"] > 0)
            all_pass = sum(1 for d in details if d["success_count"] == num_runs)

            lines.append("")
            lines.append(f"{'k':<4} {'Tasks':>5}  {'pass@k':>8}  {'pass^k':>8}  {'Average':>10}")
            lines.append(
                f"{num_runs:<4} {total_tasks:>5}  "
                f"{any_pass:>3}/{total_tasks:<3}   "
                f"{all_pass:>3}/{total_tasks:<3}   "
                f"{avg_rate:>9.1f}%"
            )
            lines.append("```\n")

    return "\n".join(lines)


def generate_latex(model_data: dict, compare_policies: bool, compare_agents: bool = False) -> str:
    """Generate LaTeX table."""
    lines = []
    num_runs = 0
    for model_metrics in model_data.values():
        for m in model_metrics.values():
            num_runs = max(num_runs, m.get("num_runs", 0))

    lines.append("## LaTeX Table\n")
    lines.append("```latex")
    lines.append(r"\begin{table}[h]")
    lines.append(r"\centering")
    lines.append(
        r"\caption{BPO Benchmark: Success Rate, Token Usage, and Policy Gain ("
        + str(num_runs)
        + r" runs each).}"
    )
    lines.append(r"\label{tab:bpo-results}")

    if compare_policies:
        lines.append(r"\begin{tabular}{lccccc}")
        lines.append(r"\toprule")
        lines.append(
            r"\textbf{Model} & \textbf{Accuracy (W/O $\to$ W)} & \textbf{Gain} & "
            r"\textbf{pass@" + str(num_runs) + r" (W/O $\to$ W)} & "
            r"\textbf{pass\textsuperscript{" + str(num_runs) + r"} (W/O $\to$ W)} & "
            r"\textbf{Tokens (W/O $\to$ W)} \\"
        )
        lines.append(r"\midrule")

        for group_key, configs in model_data.items():
            display_name = _label(group_key, compare_agents)
            wo = configs.get("no-policies", {})
            w = configs.get("policies", {})

            if wo and w:
                acc = (
                    f"{format_pct(wo.get('mean_accuracy', 0))} $\\to$ {format_pct(w.get('mean_accuracy', 0))}"
                )
                gain = (w.get("mean_accuracy", 0) - wo.get("mean_accuracy", 0)) * 100
                gain_str = f"+{gain:.1f} pp" if gain >= 0 else f"{gain:.1f} pp"
                pass_n = f"{format_pct(wo.get('pass_at_n', 0))} $\\to$ {format_pct(w.get('pass_at_n', 0))}"
                pass_pow = (
                    f"{format_pct(wo.get('pass_pow_n', 0))} $\\to$ {format_pct(w.get('pass_pow_n', 0))}"
                )
                tok = f"{format_tokens(wo.get('mean_tokens', 0))} $\\to$ {format_tokens(w.get('mean_tokens', 0))}"
            elif w:
                acc = format_pct(w.get("mean_accuracy", 0))
                gain_str = "N/A"
                pass_n = format_pct(w.get("pass_at_n", 0))
                pass_pow = format_pct(w.get("pass_pow_n", 0))
                tok = format_tokens(w.get("mean_tokens", 0))
            else:
                continue

            # Escape % for LaTeX
            acc = acc.replace("%", r"\%")
            pass_n = pass_n.replace("%", r"\%")
            pass_pow = pass_pow.replace("%", r"\%")

            lines.append(f"{display_name} & {acc} & {gain_str} & {pass_n} & {pass_pow} & {tok} \\\\")
    else:
        lines.append(r"\begin{tabular}{lcccc}")
        lines.append(r"\toprule")
        lines.append(
            r"\textbf{Model} & \textbf{Accuracy} & "
            r"\textbf{pass@" + str(num_runs) + r"} & "
            r"\textbf{pass\textsuperscript{" + str(num_runs) + r"}} & "
            r"\textbf{Tokens} \\"
        )
        lines.append(r"\midrule")

        for group_key, configs in model_data.items():
            display_name = _label(group_key, compare_agents)
            m = configs.get("policies", configs.get("no-policies", {}))
            if not m:
                continue
            acc = format_pct(m.get("mean_accuracy", 0)).replace("%", r"\%")
            pn = format_pct(m.get("pass_at_n", 0)).replace("%", r"\%")
            pp = format_pct(m.get("pass_pow_n", 0)).replace("%", r"\%")
            tok = format_tokens(m.get("mean_tokens", 0))
            lines.append(f"{display_name} & {acc} & {pn} & {pp} & {tok} \\\\")

    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    lines.append(r"\end{table}")
    lines.append("```\n")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Compare BPO Benchmark evaluation results")
    parser.add_argument("--output", "-o", help="Save report to markdown file")
    args = parser.parse_args()

    # Read config->files mapping from stdin
    stdin_data = sys.stdin.read().strip()
    if not stdin_data:
        print("Error: no input provided on stdin", file=sys.stderr)
        print("Expected JSON: {\"model:config\": [\"file1.json\", ...], ...}", file=sys.stderr)
        sys.exit(1)

    config_results = json.loads(stdin_data)

    # Determine which dimensions vary across configs
    seen_agents: set[str] = set()
    seen_policies: set[str] = set()
    for key in config_results:
        _, agent, policy = _split_config_key(key)
        seen_agents.add(agent)
        seen_policies.add(policy)
    compare_policies = "no-policies" in seen_policies and "policies" in seen_policies
    compare_agents = len(seen_agents) > 1

    # Compute metrics for all configs
    model_data = build_model_data(config_results)

    if not model_data:
        print("Error: no valid results found", file=sys.stderr)
        sys.exit(1)

    # Determine run count for header
    num_runs = 0
    for model_metrics in model_data.values():
        for m in model_metrics.values():
            num_runs = max(num_runs, m["num_runs"])

    # Generate report
    report_parts = []
    report_parts.append("# BPO Benchmark: Multi-Model Evaluation Results\n")
    report_parts.append(f"{num_runs} runs per configuration.")
    if compare_policies:
        report_parts.append("Policies = CUGA playbook/tool-guide policies.\n")
    else:
        report_parts.append("\n")

    report_parts.append(generate_plain_text(model_data, compare_policies, compare_agents))
    report_parts.append(generate_per_task_details(model_data, compare_policies, compare_agents))
    report_parts.append(generate_latex(model_data, compare_policies, compare_agents))

    report = "\n".join(report_parts)

    # Output
    print(report)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            f.write(report)
        print(f"\nReport saved to: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
