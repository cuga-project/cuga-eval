"""Shared sample-task cost/accuracy data for AppWorld comparison reports."""

from __future__ import annotations

import json
from pathlib import Path

DIR = Path(__file__).parent / "outputs"
TRAJECTORY_DIR = Path(__file__).parent.parent / "logging" / "trajectory_data"
FULL_SUITE_TASKS = 43
TRAJECTORY_OUTPUT_RATIO = 0.04

FULL_SUITE_REPORTS = {
    "deepagents": "appworld_deepagents_20260629_155137_final_report.json",
    "openclaw": "appworld_openclaw_20260629_171301_final_report.json",
    "hermes": "appworld_hermes_20260629_190749_final_report.json",
}

CUGA_FULL_SUITE = {
    "total_tasks": FULL_SUITE_TASKS,
    "pass_rate": 0.791,
}

SAMPLE_TASK_ORDER = [
    "81be677_1",
    "7847649_1",
    "e775c78_1",
    "9aae7da_1",
    "07bb666_1",
    "f3f60f0_1",
    "dbc0276_1",
    "552869a_1",
]

COST_AGENTS = {
    "deepagents": {
        "label": "Deep Agents",
        "glob": "appworld_deepagents_*_final_report.json",
        "pricing": "gpt52",
        "model": "Azure GPT-5.2",
    },
    "openclaw": {
        "label": "OpenClaw",
        "glob": "appworld_openclaw_*_final_report.json",
        "pricing": "gpt52",
        "model": "Azure GPT-5.2",
    },
    "hermes": {
        "label": "Hermes",
        "glob": "appworld_hermes_*_final_report.json",
        "pricing": "gpt52",
        "model": "Azure GPT-5.2",
    },
    "cuga": {
        "label": "Cuga SDK",
        "glob": "appworld_sdk_*_final_report.json",
        "pricing": "groq",
        "model": "Groq gpt-oss-120b",
    },
}

PRICING = {
    "gpt52": {"label": "Azure GPT-5.2", "input": 1.75, "cache": 0.175, "output": 14.0},
    "groq": {"label": "Groq gpt-oss-120b", "input": 0.15, "cache": 0.075, "output": 0.60},
}


def compute_task_cost(
    input_tokens: int,
    output_tokens: int,
    cache_input_tokens: int,
    *,
    pricing_key: str,
) -> float:
    price = PRICING[pricing_key]
    cache = min(max(cache_input_tokens, 0), max(input_tokens, 0))
    uncached = max(input_tokens - cache, 0)
    return (
        uncached * price["input"] / 1_000_000
        + cache * price["cache"] / 1_000_000
        + output_tokens * price["output"] / 1_000_000
    )


def token_fields(result: dict, pricing_key: str) -> dict:
    inp = int(result.get("input_tokens") or 0)
    out = int(result.get("output_tokens") or 0)
    cache = int(result.get("total_cache_input_tokens") or 0)
    total = int(result.get("total_tokens") or (inp + out))
    calls = int(result.get("total_llm_calls") or 0)
    cost = compute_task_cost(inp, out, cache, pricing_key=pricing_key) if inp or out else 0.0
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_input_tokens": cache,
        "total_tokens": total,
        "llm_calls": calls,
        "cost_usd": cost,
    }


def _is_sdk_trajectory_dir(path: Path) -> bool:
    if path.name.startswith("appworld_sdk_"):
        return True
    meta_path = path / "metadata.json"
    if not meta_path.exists():
        return False
    meta = json.loads(meta_path.read_text())
    return "AppWorld SDK" in (meta.get("description") or "")


def token_fields_from_trajectory(row: dict, pricing_key: str) -> dict | None:
    total = int(row.get("total_tokens") or 0)
    if not total:
        return None
    cache = int(row.get("total_cache_input_tokens") or 0)
    calls = int(row.get("total_llm_calls") or 0)
    output = max(int(total * TRAJECTORY_OUTPUT_RATIO), 1)
    return token_fields(
        {
            "input_tokens": total - output,
            "output_tokens": output,
            "total_cache_input_tokens": cache,
            "total_tokens": total,
            "total_llm_calls": calls,
        },
        pricing_key,
    )


def load_cuga_from_trajectories(trajectory_dir: Path) -> dict[str, dict]:
    by_task: dict[str, dict] = {}
    if not trajectory_dir.is_dir():
        return by_task
    for run_dir in sorted(trajectory_dir.iterdir()):
        if not run_dir.is_dir() or not _is_sdk_trajectory_dir(run_dir):
            continue
        results_path = run_dir / "results.json"
        if not results_path.exists():
            continue
        data = json.loads(results_path.read_text())
        if not isinstance(data, dict):
            continue
        for task_id, row in data.items():
            if not isinstance(row, dict):
                continue
            fields = token_fields_from_trajectory(row, COST_AGENTS["cuga"]["pricing"])
            if not fields:
                continue
            by_task[task_id] = {"task_name": task_id, "agent": "cuga", **fields}
    return by_task


def load_sample_runs(outputs_dir: Path, trajectory_dir: Path) -> dict[str, dict[str, dict]]:
    by_agent_task: dict[str, dict[str, dict]] = {key: {} for key in COST_AGENTS}
    for task, row in load_cuga_from_trajectories(trajectory_dir).items():
        by_agent_task["cuga"][task] = row
    for agent_key, meta in COST_AGENTS.items():
        for path in sorted(outputs_dir.glob(meta["glob"])):
            data = json.loads(path.read_text())
            for result in data.get("results") or []:
                fields = token_fields(result, meta["pricing"])
                if not fields["input_tokens"]:
                    continue
                task = str(result.get("task_name") or "")
                if not task:
                    continue
                by_agent_task[agent_key][task] = {
                    "task_name": task,
                    "agent": agent_key,
                    **fields,
                }
    return by_agent_task


def filter_sample_tasks(by_agent_task: dict[str, dict[str, dict]]) -> dict[str, dict[str, dict]]:
    sample_set = set(SAMPLE_TASK_ORDER)
    return {
        agent: {task: row for task, row in rows.items() if task in sample_set}
        for agent, rows in by_agent_task.items()
    }


def complete_cuga_sample_estimates(samples: dict[str, dict[str, dict]]) -> dict[str, dict[str, dict]]:
    """Fill missing Cuga sample tasks using average of measured sample rows."""
    cuga = dict(samples.get("cuga", {}))
    measured = [row for tid, row in cuga.items() if tid in SAMPLE_TASK_ORDER]
    if not measured:
        samples["cuga"] = cuga
        return samples
    avg_cost = sum(r["cost_usd"] for r in measured) / len(measured)
    avg_tokens = sum(r["total_tokens"] for r in measured) / len(measured)
    avg_calls = sum(r["llm_calls"] for r in measured) / len(measured)
    avg_cache = sum(r["cache_input_tokens"] for r in measured) / len(measured)
    output = max(int(avg_tokens * TRAJECTORY_OUTPUT_RATIO), 1)
    inp = int(avg_tokens) - output
    for task in SAMPLE_TASK_ORDER:
        if task in cuga:
            continue
        cuga[task] = {
            "task_name": task,
            "agent": "cuga",
            "input_tokens": inp,
            "output_tokens": output,
            "cache_input_tokens": int(avg_cache),
            "total_tokens": int(avg_tokens),
            "llm_calls": avg_calls,
            "cost_usd": avg_cost,
            "estimated": True,
        }
    samples["cuga"] = cuga
    return samples


def cost_stats_for_samples(samples: dict[str, dict[str, dict]]) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    for agent in COST_AGENTS:
        rows = [samples[agent][t] for t in SAMPLE_TASK_ORDER if t in samples.get(agent, {})]
        n = len(rows) or 1
        total_cost = sum(r["cost_usd"] for r in rows)
        total_tokens = sum(r["total_tokens"] for r in rows)
        avg_input = sum(r["input_tokens"] for r in rows) / n if rows else None
        avg_output = sum(r["output_tokens"] for r in rows) / n if rows else None
        out_per_call_rows = [
            r["output_tokens"] / r["llm_calls"]
            for r in rows
            if r.get("llm_calls")
        ]
        stats[agent] = {
            "avg_cost": total_cost / n if rows else None,
            "total_cost": total_cost,
            "avg_tokens": total_tokens / n if rows else None,
            "avg_input": avg_input,
            "avg_output": avg_output,
            "avg_out_per_call": (
                sum(out_per_call_rows) / len(out_per_call_rows) if out_per_call_rows else None
            ),
            "avg_out_in_ratio": (
                avg_output / avg_input if avg_input and avg_output is not None else None
            ),
            "avg_calls": sum(r["llm_calls"] for r in rows) / n if rows else None,
            "est_suite_cost": (total_cost / n) * FULL_SUITE_TASKS if rows else None,
            "est_suite_tokens": int((total_tokens / n) * FULL_SUITE_TASKS) if rows else None,
            "estimated_tasks": sum(1 for r in rows if r.get("estimated")),
        }
    stats["_combined"] = {
        "est_full_matrix": sum(s["est_suite_cost"] or 0 for s in stats.values() if s.get("est_suite_cost")),
    }
    return stats


def load_full_suite_accuracy(outputs_dir: Path) -> dict[str, dict]:
    accuracy: dict[str, dict] = {}
    for agent_key, filename in FULL_SUITE_REPORTS.items():
        path = outputs_dir / filename
        metrics = json.loads(path.read_text()).get("metrics") or {}
        accuracy[agent_key] = {
            "total_tasks": int(metrics.get("total_tasks") or FULL_SUITE_TASKS),
            "passed": int(metrics.get("passed") or 0),
            "pass_rate": metrics.get("pass_rate"),
            "model": COST_AGENTS[agent_key]["model"],
            "source": path.name,
        }
    cuga_passed = round(CUGA_FULL_SUITE["pass_rate"] * CUGA_FULL_SUITE["total_tasks"])
    accuracy["cuga"] = {
        "total_tasks": CUGA_FULL_SUITE["total_tasks"],
        "passed": cuga_passed,
        "pass_rate": CUGA_FULL_SUITE["pass_rate"],
        "model": COST_AGENTS["cuga"]["model"],
        "source": "full test_easy run (Groq)",
    }
    return accuracy
