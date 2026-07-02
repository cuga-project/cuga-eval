#!/usr/bin/env python3
"""Print token/cost summary from AppWorld sample-task eval reports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cost_sample_data import (
    COST_AGENTS,
    DIR,
    FULL_SUITE_TASKS,
    PRICING,
    SAMPLE_TASK_ORDER,
    TRAJECTORY_DIR,
    complete_cuga_sample_estimates,
    cost_stats_for_samples,
    filter_sample_tasks,
    load_full_suite_accuracy,
    load_sample_runs,
)


def fmt_cost(value: float | None, *, decimals: int = 4) -> str:
    if value is None:
        return "—"
    return f"${value:.{decimals}f}"


def fmt_num(value: float | int | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.0f}"
    return f"{value:,}"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def print_summary(
    samples: dict[str, dict[str, dict]],
    full_suite: dict[str, dict],
) -> None:
    stats = cost_stats_for_samples(samples)

    print("AppWorld cost + accuracy summary")
    print(f"Sample tasks ({len(SAMPLE_TASK_ORDER)}): {', '.join(SAMPLE_TASK_ORDER)}")
    print(f"Full suite: {FULL_SUITE_TASKS} tasks (test_easy)")
    print()

    print("Full-suite Pass@1 (43 tasks)")
    acc_header = f"{'Agent':<14} {'Model':<20} {'Pass@1':>8} {'Passed':>10}"
    print(acc_header)
    print("-" * len(acc_header))
    for agent_key in COST_AGENTS:
        meta = COST_AGENTS[agent_key]
        acc = full_suite[agent_key]
        passed_str = f"{acc['passed']}/{acc['total_tasks']}"
        print(
            f"{meta['label']:<14} {acc['model']:<20} {fmt_pct(acc['pass_rate']):>8} "
            f"{passed_str:>10}"
        )
    print()

    header = (
        f"{'Agent':<14} {'Model':<20} "
        f"{'Avg$/task':>10} {'Avg tok':>10} {'Calls':>6} {'Est 43$':>10}"
    )
    print("Sample-task cost (extrapolated to 43 tasks)")
    print(header)
    print("-" * len(header))

    external_est = 0.0
    for agent_key in COST_AGENTS:
        meta = COST_AGENTS[agent_key]
        s = stats[agent_key]
        if not s.get("avg_cost"):
            continue
        print(
            f"{meta['label']:<14} {meta['model']:<20} "
            f"{fmt_cost(s['avg_cost']):>10} {fmt_num(s['avg_tokens']):>10} "
            f"{s['avg_calls'] or 0:>6.1f} "
            f"{fmt_cost(s['est_suite_cost'], decimals=2):>10}"
        )
        external_est += s["est_suite_cost"] or 0

    cuga_est = stats["cuga"].get("estimated_tasks", 0)
    if cuga_est:
        print()
        print(
            f"Cuga: {cuga_est} sample tasks use estimated cost "
            f"(sample avg {fmt_cost(stats['cuga']['avg_cost'])}/task)"
        )

    print()
    print(f"Projected full matrix (43 tasks × 4 agents): {fmt_cost(external_est, decimals=2)}")
    print()

    print("Per-task cost (sample order)")
    task_header = f"{'Task':<14}" + "".join(f"{COST_AGENTS[a]['label'][:10]:>12}" for a in COST_AGENTS)
    print(task_header)
    print("-" * len(task_header))
    for task_id in SAMPLE_TASK_ORDER:
        cells = []
        for agent_key in COST_AGENTS:
            row = samples[agent_key].get(task_id)
            if not row:
                cells.append("—")
            elif row.get("estimated"):
                cells.append(f"~{fmt_cost(row['cost_usd'])[1:]}")
            else:
                cells.append(fmt_cost(row["cost_usd"]))
        print(f"{task_id:<14}" + "".join(f"{c:>12}" for c in cells))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs-dir", type=Path, default=DIR)
    parser.add_argument("--trajectory-dir", type=Path, default=TRAJECTORY_DIR)
    args = parser.parse_args()
    samples = complete_cuga_sample_estimates(
        filter_sample_tasks(load_sample_runs(args.outputs_dir, args.trajectory_dir))
    )
    print_summary(samples, load_full_suite_accuracy(args.outputs_dir))


if __name__ == "__main__":
    main()
