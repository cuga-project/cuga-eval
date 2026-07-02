#!/usr/bin/env python3
"""Regenerate appworld_gpt52_comparison_report.html from final_report JSONs."""

from __future__ import annotations

import json
import sys
from collections import Counter
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cost_sample_data import (
    COST_AGENTS,
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

REPORTS = {
    "deepagents": "appworld_deepagents_20260629_155137_final_report.json",
    "openclaw": "appworld_openclaw_20260629_171301_final_report.json",
    "hermes": "appworld_hermes_20260629_190749_final_report.json",
}
AGENT_LABELS = {
    "deepagents": "Deep Agents",
    "openclaw": "OpenClaw",
    "hermes": "Hermes",
    "cuga": "Cuga SDK",
}
AGENT_COLORS = {
    "deepagents": "#8b5cf6",
    "openclaw": "#06b6d4",
    "hermes": "#f59e0b",
    "cuga": "#34d399",
}
OUT = Path(__file__).parent / "appworld_gpt52_comparison_report.html"
DIR = Path(__file__).parent / "outputs"
FULL_SUITE_TASKS = FULL_SUITE_TASKS

# Azure GPT-5.2 list pricing (USD per 1M tokens); cache is a subset of input, not additive.
PRICE_INPUT_PER_M = PRICING["gpt52"]["input"]
PRICE_OUTPUT_PER_M = PRICING["gpt52"]["output"]
PRICE_CACHE_INPUT_PER_M = PRICING["gpt52"]["cache"]

SAMPLE_TASK_ORDER = SAMPLE_TASK_ORDER
TOOL_CATALOG_TOKENS = 34_004


def classify(r: dict) -> str:
    if r.get("success"):
        return "passed"
    err = r.get("error")
    if err:
        e = str(err)
        if "Max steps" in e:
            return "max_steps"
        if "400" in e or "litellm" in e.lower() or "BadRequest" in e:
            return "llm_api"
        if "Connection error" in e:
            return "connection"
        return "other_error"
    mr = r.get("match_rate", 0) or 0
    if mr >= 0.5:
        return "partial_match"
    if mr > 0:
        return "low_match"
    return "zero_match"


CLASS_LABELS = {
    "passed": "Passed",
    "partial_match": "Wrong answer (≈50% match)",
    "low_match": "Wrong answer (<50% match)",
    "zero_match": "Wrong answer (0% match)",
    "max_steps": "Max steps (12) exhausted",
    "llm_api": "LLM API / content filter",
    "connection": "Connection error",
    "other_error": "Other runtime error",
}


def theme_for_intent(intent: str) -> str:
    i = intent.lower()
    if "gmail" in i or "email" in i:
        return "Gmail"
    if "amazon" in i or "cart" in i or "wishlist" in i or "prime" in i:
        return "Amazon"
    if "spotify" in i:
        return "Spotify"
    if "phone" in i or "text" in i or "contact" in i:
        return "Phone / contacts"
    if "file" in i or "folder" in i:
        return "File system"
    if "note" in i or "simple note" in i:
        return "Simple Note"
    if "venmo" in i or "splitwise" in i:
        return "Payments"
    return "Other"


SETUP_SECTION = """
  <section>
    <h2>Experiment details &amp; setup</h2>
    <div class="setup-grid">
      <div class="panel setup-panel">
        <h3 class="setup-h3">Benchmark</h3>
        <ul>
          <li><strong>Suite:</strong> <code>test_easy</code> — 43 level-1 AppWorld tasks (24 challenge-easy + 19 normal-easy)</li>
          <li><strong>Runs:</strong> 3 agents × 43 tasks = 129 evaluations, 29 Jun 2026</li>
          <li><strong>Scoring:</strong> AppWorld harness — pass = 100% answer match vs ground truth</li>
          <li><strong>Pre-auth:</strong> All task apps authenticated before each run via registry</li>
        </ul>
        <h3 class="setup-h3">Model &amp; gateway</h3>
        <ul>
          <li><strong>Profile:</strong> <code>gpt5.2</code> → <code>Azure/gpt-5.2-chat-2025-12-11</code></li>
          <li><strong>Routing:</strong> IBM LiteLLM gateway (<code>settings.openai.toml</code>)</li>
          <li><strong>Same model</strong> for all three agents — no per-agent model tuning</li>
        </ul>
        <h3 class="setup-h3">Agents under test</h3>
        <ul>
          <li><strong>Deep Agents</strong> — native tool binding when ≤128 tools; auto-fallback to ReAct when catalog exceeds cap (~473 tools on most tasks)</li>
          <li><strong>OpenClaw</strong> — always ReAct (<code>prefer_eval_llm=True</code>)</li>
          <li><strong>Hermes</strong> — always ReAct (<code>prefer_eval_llm=True</code>)</li>
        </ul>
      </div>

      <div class="diagram-card react-card">
        <h3>ReAct tool loop (shared by all externals)</h3>
        <svg viewBox="0 0 520 300" class="diagram-svg" aria-label="ReAct loop diagram">
          <defs>
            <marker id="reactArrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="#64748b"/>
            </marker>
          </defs>
          <g font-family="Instrument Sans, system-ui, sans-serif" font-size="11">
            <rect x="160" y="10" width="200" height="36" rx="8" fill="#1e293b" stroke="#5b9cf5"/>
            <text x="260" y="33" text-anchor="middle" fill="#93c5fd">Task intent + user context</text>

            <line x1="260" y1="46" x2="260" y2="62" stroke="#64748b" marker-end="url(#reactArrow)"/>

            <rect x="140" y="64" width="240" height="36" rx="8" fill="#1e293b" stroke="#8b5cf6"/>
            <text x="260" y="80" text-anchor="middle" fill="#c4b5fd">System: APPWORLD_AGENT_PROMPT</text>
            <text x="260" y="94" text-anchor="middle" fill="#64748b" font-size="9">pagination · filters · no guessing</text>

            <line x1="260" y1="100" x2="260" y2="116" stroke="#64748b" marker-end="url(#reactArrow)"/>

            <rect x="100" y="118" width="320" height="44" rx="8" fill="#2e1065" stroke="#8b5cf6" stroke-width="1.5"/>
            <text x="260" y="138" text-anchor="middle" fill="#ddd6fe">User turn: full tool catalog (~473 tools · ~34k tok)</text>
            <text x="260" y="154" text-anchor="middle" fill="#64748b" font-size="9">resent every LLM call · mostly cached after turn 1</text>

            <line x1="260" y1="162" x2="260" y2="178" stroke="#64748b" marker-end="url(#reactArrow)"/>

            <rect x="130" y="180" width="260" height="36" rx="8" fill="#1e293b" stroke="#f59e0b"/>
            <text x="260" y="203" text-anchor="middle" fill="#fde68a">LLM → JSON tool block or Final Answer</text>

            <line x1="200" y1="216" x2="120" y2="248" stroke="#64748b" marker-end="url(#reactArrow)"/>
            <line x1="320" y1="216" x2="400" y2="248" stroke="#64748b" marker-end="url(#reactArrow)"/>

            <rect x="20" y="250" width="200" height="44" rx="8" fill="#052e16" stroke="#34d399"/>
            <text x="120" y="270" text-anchor="middle" fill="#6ee7b7">Execute tool via AppWorld SDK</text>
            <text x="120" y="286" text-anchor="middle" fill="#64748b" font-size="9">observation → next turn</text>

            <rect x="300" y="250" width="200" height="44" rx="8" fill="#052e16" stroke="#34d399"/>
            <text x="400" y="270" text-anchor="middle" fill="#6ee7b7">Final Answer: &lt;answer&gt;</text>
            <text x="400" y="286" text-anchor="middle" fill="#64748b" font-size="9">harness scores vs ground truth</text>

            <path d="M 120 250 L 80 210 L 80 198 L 100 198" fill="none" stroke="#64748b" stroke-dasharray="4 3" marker-end="url(#reactArrow)"/>
            <text x="55" y="225" fill="#64748b" font-size="9" transform="rotate(-70 55 225)">repeat ≤12 steps</text>
          </g>
        </svg>
        <div class="react-specs">
          <div class="react-spec"><span class="spec-k">Max steps</span><span class="spec-v">12</span></div>
          <div class="react-spec"><span class="spec-k">Tool format</span><span class="spec-v mono">&#123;"action":"tool",…&#125;</span></div>
          <div class="react-spec"><span class="spec-k">Native bind cap</span><span class="spec-v">128 tools</span></div>
          <div class="react-spec"><span class="spec-k">Catalog size</span><span class="spec-v">~34k tok / call</span></div>
        </div>
      </div>
    </div>

    <div class="panel" style="margin-top:1rem">
      <p style="margin-bottom:.5rem"><strong>Fairness controls</strong> — identical across Deep Agents, OpenClaw, and Hermes:</p>
      <ul>
        <li>Same <code>APPWORLD_AGENT_PROMPT</code>, harness, pre-auth, and final-answer formatter</li>
        <li>Same 12-step ReAct cap and JSON tool-call protocol (<code>tool_loop.py</code>)</li>
        <li>Full tool catalog in prompt (128-cap bypass) — deliberately <em>without</em> CUGA Shortlister for apples-to-apples external comparison</li>
      </ul>
      <div class="cmd">./benchmarks/appworld/compare.sh \\
  --agents deepagents,openclaw,hermes \\
  --eval-key test_easy \\
  --models gpt5.2 \\
  --runs 1 \\
  --no-bundle</div>
    </div>
  </section>"""


def load() -> dict:
    return {k: json.loads((DIR / v).read_text()) for k, v in REPORTS.items()}


def _task_tokens(result: dict) -> int:
    return int(result.get("total_tokens") or 0)


def _task_llm_calls(result: dict) -> int:
    return int(result.get("total_llm_calls") or 0)


def token_stats_for_results(results: list[dict]) -> dict:
    total_tokens = sum(_task_tokens(r) for r in results)
    total_llm_calls = sum(_task_llm_calls(r) for r in results)
    n = len(results) or 1
    passed = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]
    passed_tokens = sum(_task_tokens(r) for r in passed)
    failed_tokens = sum(_task_tokens(r) for r in failed)
    return {
        "total_tokens": total_tokens,
        "avg_tokens_per_task": total_tokens / n,
        "total_llm_calls": total_llm_calls,
        "avg_llm_calls_per_task": total_llm_calls / n,
        "avg_tokens_passed": passed_tokens / len(passed) if passed else None,
        "avg_tokens_failed": failed_tokens / len(failed) if failed else None,
        "has_token_data": any(_task_tokens(r) for r in results),
    }


def _group_token_stats(results: list[dict], key_fn) -> list[tuple[str, dict]]:
    groups: dict[str, list[dict]] = {}
    for result in results:
        key = key_fn(result)
        groups.setdefault(key, []).append(result)
    return sorted((key, token_stats_for_results(items)) for key, items in groups.items())


def _fmt_out_per_call(output_tokens: int | float, llm_calls: int | float) -> str:
    if not llm_calls:
        return "—"
    return f"{output_tokens / llm_calls:.0f}"


def _fmt_out_in_ratio(output_tokens: int | float, input_tokens: int | float) -> str:
    if not input_tokens:
        return "—"
    return f"{100 * output_tokens / input_tokens:.2f}%"


def _fmt_tokens(value: float | int | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.0f}"
    return f"{value:,}"


def _fmt_cost(value: float | None, *, decimals: int = 4) -> str:
    if value is None:
        return "—"
    return f"${value:.{decimals}f}"


def render_value_quadrant(full_suite_acc: dict[str, dict], cost_stats: dict[str, dict]) -> str:
    """SVG scatter: Pass@1 (Y) vs estimated full-suite LLM cost (X)."""
    agent_order = ["cuga", "openclaw", "hermes", "deepagents"]
    points: list[dict] = []
    for key in agent_order:
        acc = full_suite_acc.get(key, {})
        cs = cost_stats.get(key, {})
        cost = cs.get("est_suite_cost")
        pass_rate = acc.get("pass_rate")
        if cost is None or pass_rate is None:
            continue
        passed = int(acc.get("passed") or 0)
        cost_per_pass = cost / passed if passed else None
        points.append(
            {
                "key": key,
                "label": AGENT_LABELS[key],
                "color": AGENT_COLORS[key],
                "cost": float(cost),
                "pass_pct": float(pass_rate) * 100,
                "cost_per_pass": cost_per_pass,
            }
        )

    if not points:
        return ""

    width, height = 680, 400
    pad_l, pad_r, pad_t, pad_b = 78, 28, 42, 62
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    x_max = 6.5
    y_max = 85.0

    def sx(cost: float) -> float:
        return pad_l + min(cost / x_max, 1.0) * plot_w

    def sy(pct: float) -> float:
        return pad_t + plot_h - min(pct / y_max, 1.0) * plot_h

    x_ticks = [0, 2, 4, 6]
    y_ticks = [0, 20, 40, 60, 80]

    grid_lines = []
    for tick in x_ticks:
        x = sx(tick)
        grid_lines.append(
            f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" y2="{pad_t + plot_h}" '
            f'stroke="rgba(255,255,255,.06)" stroke-width="1"/>'
        )
        grid_lines.append(
            f'<text x="{x:.1f}" y="{height - 28}" text-anchor="middle" fill="#64748b" '
            f'font-size="11" font-family="JetBrains Mono, monospace">${tick}</text>'
        )
    for tick in y_ticks:
        y = sy(tick)
        grid_lines.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l + plot_w}" y2="{y:.1f}" '
            f'stroke="rgba(255,255,255,.06)" stroke-width="1"/>'
        )
        grid_lines.append(
            f'<text x="{pad_l - 10}" y="{y + 4:.1f}" text-anchor="end" fill="#64748b" '
            f'font-size="11" font-family="Instrument Sans, system-ui, sans-serif">{tick}%</text>'
        )

    good_x = sx(3.0)
    good_y = sy(45)
    cuga = next((p for p in points if p["key"] == "cuga"), None)
    cuga_cpp = _fmt_cost(cuga["cost_per_pass"]) if cuga and cuga.get("cost_per_pass") else "—"
    best_ext = max(
        (p for p in points if p["key"] != "cuga"),
        key=lambda p: p["pass_pct"],
        default=None,
    )
    ext_cpp = _fmt_cost(best_ext["cost_per_pass"]) if best_ext and best_ext.get("cost_per_pass") else "—"

    label_offsets = {
        "cuga": (-8, -16, "end"),
        "openclaw": (12, 4, "start"),
        "hermes": (-12, 10, "end"),
        "deepagents": (12, -10, "start"),
    }

    dots = []
    for p in points:
        cx, cy = sx(p["cost"]), sy(p["pass_pct"])
        r = 11 if p["key"] == "cuga" else 9
        glow = (
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r + 7}" fill="{p["color"]}" opacity=".16"/>'
            if p["key"] == "cuga"
            else ""
        )
        dots.append(glow)
        dots.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{p["color"]}" '
            f'stroke="#07080c" stroke-width="2"/>'
        )
        ox, oy, anchor = label_offsets.get(p["key"], (10, -8, "start"))
        dots.append(
            f'<text x="{cx + ox:.1f}" y="{cy + oy:.1f}" text-anchor="{anchor}" '
            f'fill="{p["color"]}" font-size="12" font-weight="600" '
            f'font-family="Instrument Sans, system-ui, sans-serif">{escape(p["label"])}</text>'
        )
        dots.append(
            f'<text x="{cx + ox:.1f}" y="{cy + oy + 14:.1f}" text-anchor="{anchor}" '
            f'fill="#94a3b8" font-size="10" font-family="JetBrains Mono, monospace">'
            f'{p["pass_pct"]:.1f}% · {_fmt_cost(p["cost"], decimals=2)}</text>'
        )

    return f"""
    <div class="hero-chart">
      <p class="chart-kicker">Value at a glance</p>
      <p class="chart-title">Pass@1 vs estimated LLM cost</p>
      <p class="chart-sub">Up and left is better — accuracy on test_easy (43 tasks) vs projected suite spend</p>
      <svg viewBox="0 0 {width} {height}" class="quadrant-svg" role="img"
           aria-label="Quadrant chart of Pass at 1 accuracy versus estimated LLM cost for four agents">
        <defs>
          <linearGradient id="goodZone" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#34d399" stop-opacity=".16"/>
            <stop offset="100%" stop-color="#34d399" stop-opacity=".02"/>
          </linearGradient>
        </defs>
        <rect x="{pad_l}" y="{pad_t}" width="{good_x - pad_l:.1f}" height="{good_y - pad_t:.1f}"
              fill="url(#goodZone)" rx="8"/>
        <text x="{pad_l + 8}" y="{pad_t + 18}" fill="#6ee7b7" font-size="10" font-weight="600"
              font-family="Instrument Sans, system-ui, sans-serif">Better value zone</text>
        <line x1="{good_x:.1f}" y1="{pad_t}" x2="{good_x:.1f}" y2="{pad_t + plot_h}"
              stroke="rgba(52,211,153,.22)" stroke-width="1" stroke-dasharray="4 4"/>
        <line x1="{pad_l}" y1="{good_y:.1f}" x2="{pad_l + plot_w}" y2="{good_y:.1f}"
              stroke="rgba(52,211,153,.22)" stroke-width="1" stroke-dasharray="4 4"/>
        {"".join(grid_lines)}
        <line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" y2="{pad_t + plot_h}"
              stroke="rgba(255,255,255,.18)" stroke-width="1.5"/>
        <line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h}"
              stroke="rgba(255,255,255,.18)" stroke-width="1.5"/>
        <text x="{pad_l + plot_w / 2:.1f}" y="{height - 8}" text-anchor="middle"
              fill="#cbd5e1" font-size="11" font-family="Instrument Sans, system-ui, sans-serif">
              Est. LLM cost · 43 tasks
        </text>
        <text x="16" y="{pad_t + plot_h / 2:.1f}" text-anchor="middle"
              fill="#cbd5e1" font-size="11" font-family="Instrument Sans, system-ui, sans-serif"
              transform="rotate(-90 16 {pad_t + plot_h / 2:.1f})">Pass@1</text>
        {"".join(dots)}
      </svg>
      <p class="chart-foot">
        Cuga: <strong>{cuga_cpp}/successful task</strong>
        · best external: <strong>{ext_cpp}/pass</strong>
        · cost projected from 8-task sample averages
      </p>
    </div>"""


def compute_task_cost(input_tokens: int, output_tokens: int, cache_input_tokens: int = 0) -> float:
    cache = min(max(cache_input_tokens, 0), max(input_tokens, 0))
    uncached = max(input_tokens - cache, 0)
    return (
        uncached * PRICE_INPUT_PER_M / 1_000_000
        + cache * PRICE_CACHE_INPUT_PER_M / 1_000_000
        + output_tokens * PRICE_OUTPUT_PER_M / 1_000_000
    )


def _token_fields(result: dict) -> dict:
    inp = int(result.get("input_tokens") or 0)
    out = int(result.get("output_tokens") or 0)
    cache = int(result.get("total_cache_input_tokens") or 0)
    total = int(result.get("total_tokens") or (inp + out))
    calls = int(result.get("total_llm_calls") or 0)
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_input_tokens": cache,
        "total_tokens": total,
        "llm_calls": calls,
        "cost_usd": compute_task_cost(inp, out, cache) if inp or out else 0.0,
    }


def load_sample_token_runs() -> dict[str, dict[str, dict]]:
    """Load per-task token/cost rows from sample reports (+ Cuga trajectory fallback)."""
    samples = complete_cuga_sample_estimates(
        filter_sample_tasks(load_sample_runs(DIR, TRAJECTORY_DIR))
    )
    return {k: v for k, v in samples.items() if k in REPORTS or k == "cuga"}


EFFORT_SECTION = """
  <section>
    <h2>How we built this (~1 dev day + Cursor)</h2>
    <p style="color:var(--muted);font-size:.9rem;margin-bottom:1.25rem;max-width:52rem">
      One developer, roughly eight focused hours on 29 Jun 2026 — wiring external agents into the existing AppWorld harness,
      standing up fair comparison runs, and shipping this report. Cursor handled boilerplate, adapter scaffolding, and iteration speed.
    </p>

    <div class="effort-grid">
      <div class="diagram-card">
        <h3>Day timeline</h3>
        <svg viewBox="0 0 720 140" class="diagram-svg" aria-label="Development day timeline">
          <defs>
            <linearGradient id="tlGrad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stop-color="#5b9cf5"/>
              <stop offset="50%" stop-color="#8b5cf6"/>
              <stop offset="100%" stop-color="#06b6d4"/>
            </linearGradient>
          </defs>
          <line x1="40" y1="70" x2="680" y2="70" stroke="url(#tlGrad)" stroke-width="4" stroke-linecap="round"/>
          <g font-family="Instrument Sans, system-ui, sans-serif" font-size="11" fill="#94a3b8">
            <circle cx="80" cy="70" r="10" fill="#5b9cf5"/>
            <text x="80" y="38" text-anchor="middle" fill="#eef2ff" font-weight="600">AM</text>
            <text x="80" y="52" text-anchor="middle" fill="#cbd5e1" font-size="10">Harness</text>
            <text x="80" y="100" text-anchor="middle">~3h</text>
            <text x="80" y="115" text-anchor="middle" font-size="9">base + factory</text>

            <circle cx="240" cy="70" r="10" fill="#8b5cf6"/>
            <text x="240" y="38" text-anchor="middle" fill="#eef2ff" font-weight="600">Midday</text>
            <text x="240" y="52" text-anchor="middle" fill="#cbd5e1" font-size="10">3 agents</text>
            <text x="240" y="100" text-anchor="middle">~2.5h</text>
            <text x="240" y="115" text-anchor="middle" font-size="9">ReAct loop</text>

            <circle cx="400" cy="70" r="10" fill="#a78bfa"/>
            <text x="400" y="38" text-anchor="middle" fill="#eef2ff" font-weight="600">PM</text>
            <text x="400" y="52" text-anchor="middle" fill="#cbd5e1" font-size="10">Eval runs</text>
            <text x="400" y="100" text-anchor="middle">~1.5h</text>
            <text x="400" y="115" text-anchor="middle" font-size="9">gpt5.2 profile</text>

            <circle cx="560" cy="70" r="10" fill="#06b6d4"/>
            <text x="560" y="38" text-anchor="middle" fill="#eef2ff" font-weight="600">Evening</text>
            <text x="560" y="52" text-anchor="middle" fill="#cbd5e1" font-size="10">Report</text>
            <text x="560" y="100" text-anchor="middle">~1h</text>
            <text x="560" y="115" text-anchor="middle" font-size="9">dashboard + HTML</text>

            <circle cx="660" cy="70" r="14" fill="none" stroke="#34d399" stroke-width="2"/>
            <text x="660" y="74" text-anchor="middle" fill="#34d399" font-size="14">✓</text>
            <text x="660" y="100" text-anchor="middle" fill="#34d399">129 tasks</text>
            <text x="660" y="115" text-anchor="middle" font-size="9">3×43 evals</text>
          </g>
        </svg>
      </div>

      <div class="diagram-card">
        <h3>Effort breakdown</h3>
        <svg viewBox="0 0 720 160" class="diagram-svg" aria-label="Effort breakdown by area">
          <g font-family="Instrument Sans, system-ui, sans-serif">
            <rect x="40" y="30" width="252" height="28" rx="6" fill="#8b5cf6"/>
            <text x="52" y="49" fill="#fff" font-size="12" font-weight="500">Agent adapters (Deep / OpenClaw / Hermes)</text>
            <text x="680" y="49" fill="#8b5cf6" font-size="12" text-anchor="end" font-weight="600">35%</text>

            <rect x="40" y="66" width="180" height="28" rx="6" fill="#5b9cf5"/>
            <text x="52" y="85" fill="#fff" font-size="12" font-weight="500">Harness + eval pipeline</text>
            <text x="680" y="85" fill="#5b9cf5" font-size="12" text-anchor="end" font-weight="600">25%</text>

            <rect x="40" y="102" width="144" height="28" rx="6" fill="#f59e0b"/>
            <text x="52" y="121" fill="#fff" font-size="12" font-weight="500">Run + debug evals</text>
            <text x="680" y="121" fill="#f59e0b" font-size="12" text-anchor="end" font-weight="600">20%</text>

            <rect x="40" y="138" width="144" height="28" rx="6" fill="#06b6d4"/>
            <text x="52" y="157" fill="#fff" font-size="12" font-weight="500">Dashboard + this report</text>
            <text x="680" y="157" fill="#06b6d4" font-size="12" text-anchor="end" font-weight="600">20%</text>
          </g>
        </svg>
      </div>
    </div>

    <div class="diagram-card arch-card">
      <h3>What got wired together</h3>
      <svg viewBox="0 0 900 220" class="diagram-svg arch-svg" aria-label="System architecture diagram">
        <defs>
          <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill="#64748b"/>
          </marker>
        </defs>
        <g font-family="JetBrains Mono, monospace" font-size="11">
          <rect x="20" y="85" width="130" height="44" rx="8" fill="#1e293b" stroke="#5b9cf5" stroke-width="1.5"/>
          <text x="85" y="105" text-anchor="middle" fill="#93c5fd">compare.sh</text>
          <text x="85" y="120" text-anchor="middle" fill="#64748b" font-size="9">--agents ×3</text>

          <line x1="150" y1="107" x2="175" y2="107" stroke="#64748b" marker-end="url(#arrow)"/>

          <rect x="180" y="85" width="130" height="44" rx="8" fill="#1e293b" stroke="#5b9cf5" stroke-width="1.5"/>
          <text x="245" y="105" text-anchor="middle" fill="#93c5fd">eval.sh</text>
          <text x="245" y="120" text-anchor="middle" fill="#64748b" font-size="9">gpt5.2 profile</text>

          <line x1="310" y1="107" x2="335" y2="107" stroke="#64748b" marker-end="url(#arrow)"/>

          <rect x="340" y="72" width="160" height="70" rx="8" fill="#1e293b" stroke="#8b5cf6" stroke-width="1.5"/>
          <text x="420" y="95" text-anchor="middle" fill="#c4b5fd">appworld_eval</text>
          <text x="420" y="110" text-anchor="middle" fill="#c4b5fd">_external.py</text>
          <text x="420" y="128" text-anchor="middle" fill="#64748b" font-size="9">43 tasks · scoring</text>

          <line x1="500" y1="107" x2="525" y2="107" stroke="#64748b" marker-end="url(#arrow)"/>

          <rect x="530" y="85" width="120" height="44" rx="8" fill="#1e293b" stroke="#8b5cf6" stroke-width="1.5"/>
          <text x="590" y="112" text-anchor="middle" fill="#c4b5fd">factory.py</text>

          <line x1="590" y1="129" x2="590" y2="155" stroke="#64748b" marker-end="url(#arrow)"/>

          <rect x="470" y="160" width="90" height="36" rx="6" fill="#2e1065" stroke="#8b5cf6"/>
          <text x="515" y="182" text-anchor="middle" fill="#ddd6fe" font-size="10">Deep Agents</text>

          <rect x="570" y="160" width="90" height="36" rx="6" fill="#083344" stroke="#06b6d4"/>
          <text x="615" y="182" text-anchor="middle" fill="#a5f3fc" font-size="10">OpenClaw</text>

          <rect x="670" y="160" width="70" height="36" rx="6" fill="#451a03" stroke="#f59e0b"/>
          <text x="705" y="182" text-anchor="middle" fill="#fde68a" font-size="10">Hermes</text>

          <line x1="515" y1="160" x2="515" y2="145" stroke="#64748b"/>
          <line x1="615" y1="160" x2="615" y2="145" stroke="#64748b"/>
          <line x1="705" y1="160" x2="705" y2="145" stroke="#64748b"/>
          <line x1="515" y1="145" x2="705" y2="145" stroke="#64748b"/>

          <line x1="650" y1="107" x2="675" y2="107" stroke="#64748b" marker-end="url(#arrow)"/>

          <rect x="680" y="72" width="120" height="70" rx="8" fill="#1e293b" stroke="#f59e0b" stroke-width="1.5"/>
          <text x="740" y="95" text-anchor="middle" fill="#fde68a">tool_loop</text>
          <text x="740" y="110" text-anchor="middle" fill="#fde68a">(ReAct)</text>
          <text x="740" y="128" text-anchor="middle" fill="#64748b" font-size="9">473 tools in prompt</text>

          <line x1="740" y1="142" x2="740" y2="168" stroke="#64748b" marker-end="url(#arrow)"/>

          <rect x="680" y="170" width="120" height="36" rx="6" fill="#052e16" stroke="#34d399"/>
          <text x="740" y="192" text-anchor="middle" fill="#6ee7b7" font-size="10">AppWorld SDK</text>

          <rect x="780" y="85" width="100" height="44" rx="8" fill="#1e293b" stroke="#34d399" stroke-width="1.5" stroke-dasharray="4 2"/>
          <text x="830" y="105" text-anchor="middle" fill="#6ee7b7" font-size="10">final_report</text>
          <text x="830" y="120" text-anchor="middle" fill="#64748b" font-size="9">.json → HTML</text>
          <line x1="800" y1="107" x2="780" y2="107" stroke="#64748b" marker-end="url(#arrow)"/>
        </g>
      </svg>
    </div>

    <div class="effort-stats">
      <div class="stat-card">
        <span class="stat-num">~8h</span>
        <span class="stat-label">Developer time</span>
      </div>
      <div class="stat-card accent">
        <span class="stat-num">1</span>
        <span class="stat-label">Calendar day</span>
      </div>
      <div class="stat-card">
        <span class="stat-num">12</span>
        <span class="stat-label">New Python modules</span>
      </div>
      <div class="stat-card">
        <span class="stat-num">129</span>
        <span class="stat-label">Tasks evaluated</span>
      </div>
      <div class="stat-card cursor">
        <span class="stat-num">Cursor</span>
        <span class="stat-label">Adapter scaffolding, tests, report HTML — ~3× faster iteration</span>
      </div>
    </div>
  </section>"""


def main() -> None:
    agents = load()
    sample_runs = load_sample_token_runs()
    cost_stats = cost_stats_for_samples(sample_runs)
    full_suite_acc = load_full_suite_accuracy(DIR)
    task_order = [r["task_name"] for r in agents["deepagents"]["results"]]
    by_task = {
        tid: {n: next(r for r in agents[n]["results"] if r["task_name"] == tid) for n in REPORTS}
        for tid in task_order
    }

    # Metrics
    metrics = {n: agents[n]["metrics"] for n in REPORTS}
    breakdown = {n: Counter(classify(r) for r in agents[n]["results"]) for n in REPORTS}
    token_stats = {n: token_stats_for_results(agents[n]["results"]) for n in REPORTS}
    token_by_difficulty = {
        n: _group_token_stats(agents[n]["results"], lambda r: str(r.get("difficulty") or "?"))
        for n in REPORTS
    }
    token_by_theme = {
        n: _group_token_stats(
            agents[n]["results"],
            lambda r: theme_for_intent(str(r.get("intent") or "")),
        )
        for n in REPORTS
    }

    all_three_pass = sorted(
        tid
        for tid in task_order
        if all(by_task[tid][n].get("success") for n in REPORTS)
    )
    any_pass = {n: [r["task_name"] for r in agents[n]["results"] if r.get("success")] for n in REPORTS}

    # Failure themes (failed tasks only, openclaw as reference)
    fail_themes = Counter(
        theme_for_intent(by_task[tid]["openclaw"].get("intent", ""))
        for tid in task_order
        if not by_task[tid]["openclaw"].get("success")
    )

    # Build table rows
    rows = []
    for tid in task_order:
        cells = f"<td class='task-id'>{escape(tid)}</td>"
        for n in REPORTS:
            r = by_task[tid][n]
            c = classify(r)
            ok = r.get("success")
            mr = int(round((r.get("match_rate") or 0) * 100))
            cls = "pass" if ok else "fail"
            badge = "✓" if ok else "✗"
            tip = escape(str(r.get("error") or r.get("response", ""))[:120])
            tok = _task_tokens(r)
            tok_label = f"{tok:,}" if tok else "—"
            cells += (
                f"<td class='{cls}' title='{tip}'><span class='badge'>{badge}</span> {mr}%"
                f"<br><span class='tok'>{tok_label} tok</span></td>"
            )
        rows.append(f"<tr>{cells}</tr>")

    # Agent summary cards HTML
    cards = []
    for n in REPORTS:
        m = metrics[n]
        bd = breakdown[n]
        color = AGENT_COLORS[n]
        bar_parts = []
        total = 43
        for key in ["passed", "partial_match", "low_match", "zero_match", "max_steps", "llm_api", "connection", "other_error"]:
            cnt = bd.get(key, 0)
            if cnt:
                pct = cnt / total * 100
                bar_parts.append(
                    f"<div class='bar-seg' style='width:{pct}%;background:{color}' "
                    f"title='{CLASS_LABELS.get(key,key)}: {cnt}'></div>"
                )
        bar = "".join(bar_parts)
        ts = token_stats[n]
        cs = cost_stats[n]
        token_line = (
            f"<li>{_fmt_tokens(ts['total_tokens'])} total tokens "
            f"({_fmt_tokens(ts['avg_tokens_per_task'])}/task)</li>"
            if ts["has_token_data"]
            else "<li>Token data not in full-suite JSON</li>"
        )
        cost_line = ""
        if cs.get("avg_cost"):
            cost_line = (
                f"<li>Est. <strong>{_fmt_cost(cs['est_suite_cost'], decimals=2)}</strong> for "
                f"{FULL_SUITE_TASKS} tasks "
                f"(sample avg {_fmt_cost(cs['avg_cost'])}/task)</li>"
            )
        cards.append(f"""
        <article class="agent-card" style="--accent:{color}">
          <header><h3>{AGENT_LABELS[n]}</h3><span class="rate">{m['pass_rate']*100:.1f}%</span></header>
          <div class="big-stats">
            <div><strong>{m['passed']}</strong><span>passed</span></div>
            <div><strong>{m['failed']}</strong><span>failed</span></div>
          </div>
          <div class="stack-bar">{bar}</div>
          <ul class="mini-legend">
            {token_line}
            {cost_line}
            <li>{bd.get('partial_match',0)} partial-match wrong answers</li>
            <li>{bd.get('max_steps',0)} max-step timeouts</li>
            <li>{bd.get('llm_api',0)+bd.get('connection',0)+bd.get('other_error',0)} infra/API errors</li>
          </ul>
          <p class="file mono">{escape(REPORTS[n])}</p>
        </article>""")

    token_summary_rows = []
    for n in REPORTS:
        ts = token_stats[n]
        color = AGENT_COLORS[n]
        token_summary_rows.append(
            f"<tr>"
            f"<td style='text-align:left;color:{color};font-weight:600'>{AGENT_LABELS[n]}</td>"
            f"<td>{_fmt_tokens(ts['total_tokens'])}</td>"
            f"<td>{_fmt_tokens(ts['avg_tokens_per_task'])}</td>"
            f"<td>{_fmt_tokens(ts['avg_tokens_passed'])}</td>"
            f"<td>{_fmt_tokens(ts['avg_tokens_failed'])}</td>"
            f"<td>{_fmt_tokens(ts['total_llm_calls'])}</td>"
            f"<td>{_fmt_tokens(ts['avg_llm_calls_per_task'])}</td>"
            f"</tr>"
        )

    difficulty_rows = []
    for n in REPORTS:
        for diff, stats in token_by_difficulty[n]:
            if not stats["has_token_data"]:
                continue
            difficulty_rows.append(
                f"<tr>"
                f"<td style='text-align:left'>{AGENT_LABELS[n]}</td>"
                f"<td>{escape(diff)}</td>"
                f"<td>{_fmt_tokens(stats['avg_tokens_per_task'])}</td>"
                f"<td>{_fmt_tokens(stats['total_tokens'])}</td>"
                f"</tr>"
            )

    theme_rows = []
    for n in REPORTS:
        for theme, stats in token_by_theme[n]:
            if not stats["has_token_data"]:
                continue
            theme_rows.append(
                f"<tr>"
                f"<td style='text-align:left'>{AGENT_LABELS[n]}</td>"
                f"<td>{escape(theme)}</td>"
                f"<td>{_fmt_tokens(stats['avg_tokens_per_task'])}</td>"
                f"<td>{_fmt_tokens(stats['total_tokens'])}</td>"
                f"</tr>"
            )

    has_any_tokens = any(token_stats[n]["has_token_data"] for n in REPORTS)
    has_sample_cost = any(
        cost_stats.get(n, {}).get("est_suite_cost") for n in (*REPORTS.keys(), "cuga")
    )

    acc_rows = []
    for agent_key in (*REPORTS.keys(), "cuga"):
        acc = full_suite_acc[agent_key]
        acc_rows.append(
            f"<tr>"
            f"<td style='text-align:left;font-weight:600;color:{AGENT_COLORS[agent_key]}'>"
            f"{AGENT_LABELS[agent_key]}</td>"
            f"<td style='text-align:left'>{escape(acc['model'])}</td>"
            f"<td><strong>{acc['pass_rate']*100:.1f}%</strong></td>"
            f"<td>{acc['passed']}/{acc['total_tasks']}</td>"
            f"</tr>"
        )
    accuracy_section = f"""
  <section>
    <h2>Pass@1 — full suite (test_easy, 43 tasks)</h2>
    <div class="table-wrap" style="max-height:none;margin-bottom:1rem">
      <table>
        <thead>
          <tr>
            <th style="text-align:left">Agent</th>
            <th style="text-align:left">Model</th>
            <th>Pass@1</th>
            <th>Passed</th>
          </tr>
        </thead>
        <tbody>{"".join(acc_rows)}</tbody>
      </table>
    </div>
    <p style="color:var(--muted);font-size:.85rem;margin:0">
      External agents: Azure <strong>GPT-5.2</strong> via LiteLLM (29 Jun full runs).
      Cuga SDK: <strong>Groq gpt-oss-120b</strong> (full test_easy run).
    </p>
  </section>"""

    cuga_card = ""
    cs = cost_stats.get("cuga", {})
    if cs.get("est_suite_cost"):
        est_n = cs.get("estimated_tasks", 0)
        est_note = (
            f"<li>{est_n} sample tasks estimated at sample avg "
            f"{_fmt_cost(cs['avg_cost'])}/task</li>"
            if est_n
            else ""
        )
        cuga_card = f"""
        <article class="agent-card" style="--accent:{AGENT_COLORS['cuga']}">
          <header><h3>{AGENT_LABELS['cuga']}</h3><span class="rate">{full_suite_acc['cuga']['pass_rate']*100:.1f}%</span></header>
          <div class="big-stats">
            <div><strong>{full_suite_acc['cuga']['passed']}</strong><span>passed</span></div>
            <div><strong>{full_suite_acc['cuga']['total_tasks'] - full_suite_acc['cuga']['passed']}</strong><span>failed</span></div>
          </div>
          <ul class="mini-legend">
            <li>{COST_AGENTS['cuga']['model']}</li>
            <li>Est. <strong>{_fmt_cost(cs['est_suite_cost'], decimals=2)}</strong> for {FULL_SUITE_TASKS} tasks</li>
            <li>Sample avg {_fmt_cost(cs['avg_cost'])}/task · {_fmt_tokens(cs['avg_tokens'])} tok</li>
            {est_note}
          </ul>
        </article>"""

    cost_section = ""
    if has_sample_cost:
        sample_rows = []
        matrix_rows = []
        for agent in (*REPORTS.keys(), "cuga"):
            color = AGENT_COLORS[agent]
            tasks = sample_runs.get(agent, {})
            for task_id in SAMPLE_TASK_ORDER:
                row = tasks.get(task_id)
                if not row:
                    continue
                cost_cell = _fmt_cost(row["cost_usd"])
                if row.get("estimated"):
                    cost_cell = f"~{cost_cell}"
                sample_rows.append(
                    f"<tr>"
                    f"<td style='text-align:left;color:{color};font-weight:600'>{AGENT_LABELS[agent]}</td>"
                    f"<td class='task-id'>{escape(task_id)}</td>"
                    f"<td>{row['input_tokens']:,}</td>"
                    f"<td>{row['output_tokens']:,}</td>"
                    f"<td>{_fmt_out_per_call(row['output_tokens'], row['llm_calls'])}</td>"
                    f"<td>{_fmt_out_in_ratio(row['output_tokens'], row['input_tokens'])}</td>"
                    f"<td>{row['cache_input_tokens']:,}</td>"
                    f"<td>{row['total_tokens']:,}</td>"
                    f"<td class='cost-cell'>{cost_cell}</td>"
                    f"<td>{row['llm_calls']:.0f}</td>"
                    f"</tr>"
                )

        for task_id in SAMPLE_TASK_ORDER:
            cells = [f"<td class='task-id'>{escape(task_id)}</td>"]
            for agent in (*REPORTS.keys(), "cuga"):
                row = sample_runs.get(agent, {}).get(task_id)
                if not row:
                    cells.append("<td>—</td>")
                else:
                    c = _fmt_cost(row["cost_usd"])
                    if row.get("estimated"):
                        c = f"~{c}"
                    cells.append(f"<td class='cost-cell'>{c}</td>")
            matrix_rows.append(f"<tr>{''.join(cells)}</tr>")

        est_cards = []
        for agent in (*REPORTS.keys(), "cuga"):
            cs = cost_stats[agent]
            if not cs.get("est_suite_cost"):
                continue
            color = AGENT_COLORS[agent]
            model = COST_AGENTS[agent]["model"]
            est_note = ""
            if cs.get("estimated_tasks"):
                est_note = (
                    f"<li>{cs['estimated_tasks']} sample tasks estimated at sample avg</li>"
                )
            est_cards.append(f"""
            <div class="cost-est-card" style="--accent:{color}">
              <h4>{AGENT_LABELS[agent]}</h4>
              <p class="cost-sub">{model}</p>
              <p class="cost-big">{_fmt_cost(cs['est_suite_cost'], decimals=2)}</p>
              <p class="cost-sub">est. {FULL_SUITE_TASKS} tasks</p>
              <ul>
                <li>Sample avg {_fmt_cost(cs['avg_cost'])}/task · {_fmt_tokens(cs['avg_tokens'])} tok</li>
                <li>{cs['avg_out_per_call']:.0f} out/call · {100 * cs['avg_out_in_ratio']:.2f}% out/input</li>
                <li>{cs['avg_calls']:.1f} LLM calls / sample task</li>
                {est_note}
              </ul>
            </div>""")

        combined = cost_stats["_combined"]
        groq = PRICING["groq"]
        token_profile_rows = []
        for agent in (*REPORTS.keys(), "cuga"):
            cs = cost_stats.get(agent, {})
            if not cs.get("avg_output"):
                continue
            color = AGENT_COLORS[agent]
            token_profile_rows.append(
                f"<tr>"
                f"<td style='text-align:left;color:{color};font-weight:600'>{AGENT_LABELS[agent]}</td>"
                f"<td>{cs['avg_output']:,.0f}</td>"
                f"<td>{cs['avg_input']:,.0f}</td>"
                f"<td>{cs['avg_out_per_call']:.0f}</td>"
                f"<td>{100 * cs['avg_out_in_ratio']:.2f}%</td>"
                f"<td>{cs['avg_calls']:.1f}</td>"
                f"</tr>"
            )
        ext_out = [
            cost_stats[a]["avg_out_per_call"]
            for a in REPORTS
            if cost_stats.get(a, {}).get("avg_out_per_call")
        ]
        ext_ratio = [
            cost_stats[a]["avg_out_in_ratio"]
            for a in REPORTS
            if cost_stats.get(a, {}).get("avg_out_in_ratio")
        ]
        cuga_out = cost_stats.get("cuga", {}).get("avg_out_per_call")
        cuga_ratio = cost_stats.get("cuga", {}).get("avg_out_in_ratio")
        ext_out_avg = sum(ext_out) / len(ext_out) if ext_out else 0
        ext_ratio_avg = sum(ext_ratio) / len(ext_ratio) if ext_ratio else 0
        cost_section = f"""
  <section>
    <h2>Cost &amp; token usage</h2>
    <div class="panel" style="margin-bottom:1rem">
      <p style="margin-bottom:.75rem"><strong>Pricing</strong> (list rates, cache-aware):</p>
      <div class="price-formula mono" style="margin-bottom:.75rem">
        External agents (Azure GPT-5.2): (input − cache) × ${PRICE_INPUT_PER_M}/M + cache × ${PRICE_CACHE_INPUT_PER_M}/M + output × ${PRICE_OUTPUT_PER_M}/M
      </div>
      <div class="price-formula mono">
        Cuga SDK (Groq gpt-oss-120b): (input − cache) × ${groq['input']}/M + cache × ${groq['cache']}/M + output × ${groq['output']}/M
      </div>
      <ul style="margin-top:.75rem">
        <li>Sample cost extrapolation uses <strong>8 representative test_easy tasks</strong> (same set for all agents)</li>
        <li>Cuga rows marked <strong>~</strong> are estimated from measured sample average where direct token logs are pending</li>
        <li>External ReAct agents emit tiny JSON tool blocks (~{ext_out_avg:.0f} output tok / LLM call); tool results re-enter as <strong>input</strong> on the next turn — see Out/call and Out/input columns below</li>
        <li>Cuga graph nodes generate longer text (~{cuga_out:.0f} output tok / call, {100 * cuga_ratio:.2f}% out/input) vs ReAct externals (~{100 * ext_ratio_avg:.2f}% out/input)</li>
      </ul>
    </div>

    <p style="margin-top:1.25rem;margin-bottom:.5rem;font-size:.9rem;color:var(--muted)">Sample token profile (8-task average)</p>
    <div class="table-wrap" style="max-height:none;margin-bottom:1rem">
      <table>
        <thead>
          <tr>
            <th style="text-align:left">Agent</th>
            <th>Avg output</th>
            <th>Avg input</th>
            <th>Out / call</th>
            <th>Out / input</th>
            <th>Calls</th>
          </tr>
        </thead>
        <tbody>{"".join(token_profile_rows)}</tbody>
      </table>
    </div>

    <div class="cost-est-grid">{"".join(est_cards)}</div>

    <div class="panel" style="margin-top:1rem">
      <p><strong>Combined estimate</strong> — sample avg × {FULL_SUITE_TASKS} tasks × 4 agents:</p>
      <p class="cost-combined">
        <span>{_fmt_cost(combined['est_full_matrix'], decimals=2)}</span> projected full suite LLM cost
      </p>
    </div>

    <p style="margin-top:1.25rem;margin-bottom:.5rem;font-size:.9rem;color:var(--muted)">Per-task cost (8 sample tasks)</p>
    <div class="table-wrap" style="max-height:none;margin-bottom:1rem">
      <table>
        <thead>
          <tr>
            <th style="text-align:left">Task</th>
            <th style="color:{AGENT_COLORS['deepagents']}">Deep Agents</th>
            <th style="color:{AGENT_COLORS['openclaw']}">OpenClaw</th>
            <th style="color:{AGENT_COLORS['hermes']}">Hermes</th>
            <th style="color:{AGENT_COLORS['cuga']}">Cuga SDK</th>
          </tr>
        </thead>
        <tbody>{"".join(matrix_rows)}</tbody>
      </table>
    </div>

    <div class="table-wrap" style="max-height:none;margin-top:1rem">
      <table>
        <thead>
          <tr>
            <th style="text-align:left">Agent</th>
            <th style="text-align:left">Task</th>
            <th>Input</th>
            <th>Output</th>
            <th>Out/call</th>
            <th>Out/input</th>
            <th>Cache</th>
            <th>Total</th>
            <th>Cost</th>
            <th>Calls</th>
          </tr>
        </thead>
        <tbody>{"".join(sample_rows)}</tbody>
      </table>
    </div>

    <div class="insight-grid" style="margin-top:1rem">
      <div class="insight good">
        <h4>Why external output looks low</h4>
        <p>ReAct externals average <strong>{ext_out_avg:.0f} output tokens per LLM call</strong> and <strong>{100 * ext_ratio_avg:.2f}%</strong> of input — each step returns a short JSON tool block or <code>Final Answer: …</code>. Large API/tool payloads are counted on the <strong>input</strong> side when the conversation is re-sent. This is expected, not a tracking bug.</p>
      </div>
      <div class="insight good">
        <h4>Cuga cost advantage</h4>
        <p>Sample avg <strong>{_fmt_cost(cost_stats['cuga']['avg_cost'])}/task</strong> on Groq vs <strong>{_fmt_cost(cost_stats['openclaw']['avg_cost'])}/task</strong>–<strong>{_fmt_cost(cost_stats['deepagents']['avg_cost'])}/task</strong> on GPT-5.2 ReAct — roughly <strong>5–6× cheaper</strong> per task in this sample, with <strong>{full_suite_acc['cuga']['pass_rate']*100:.1f}% Pass@1</strong> vs 18–30% for externals.</p>
      </div>
      <div class="insight warn">
        <h4>Why external cost varies</h4>
        <p>Identical token counts when agents share the ReAct path (Deep Agents ≈ OpenClaw on most tasks). Hermes can differ on cache hit rate — e.g. <code>7847649_1</code> costs <strong>$0.026</strong> vs <strong>$0.080</strong> with 3× more cache tokens.</p>
      </div>
      <div class="insight bad">
        <h4>Tool catalog dominates external spend</h4>
        <p>~{TOOL_CATALOG_TOKENS:,} tokens × LLM calls ≈ most input on ReAct agents. Max-step tasks hit <strong>$0.21/task</strong>; easy 3-call tasks ~<strong>$0.08</strong>.</p>
      </div>
    </div>
  </section>"""

    token_section = ""
    if has_any_tokens:
        token_section = f"""
  <section>
    <h2>Token usage</h2>
    <div class="table-wrap" style="max-height:none;margin-bottom:1rem">
      <table>
        <thead>
          <tr>
            <th style="text-align:left">Agent</th>
            <th>Total tokens</th>
            <th>Avg / task</th>
            <th>Avg / pass</th>
            <th>Avg / fail</th>
            <th>LLM calls</th>
            <th>Avg calls / task</th>
          </tr>
        </thead>
        <tbody>{"".join(token_summary_rows)}</tbody>
      </table>
    </div>
    <div class="insight-grid">
      <div class="panel">
        <p><strong>By difficulty</strong> (avg tokens / task)</p>
        <div class="table-wrap" style="max-height:40vh;margin-top:.75rem">
          <table>
            <thead><tr><th style="text-align:left">Agent</th><th>Diff</th><th>Avg tok</th><th>Total</th></tr></thead>
            <tbody>{"".join(difficulty_rows) or "<tr><td colspan='4'>—</td></tr>"}</tbody>
          </table>
        </div>
      </div>
      <div class="panel">
        <p><strong>By theme</strong> (avg tokens / task)</p>
        <div class="table-wrap" style="max-height:40vh;margin-top:.75rem">
          <table>
            <thead><tr><th style="text-align:left">Agent</th><th>Theme</th><th>Avg tok</th><th>Total</th></tr></thead>
            <tbody>{"".join(theme_rows) or "<tr><td colspan='4'>—</td></tr>"}</tbody>
          </table>
        </div>
      </div>
    </div>
  </section>"""
    elif not has_sample_cost:
        token_section = """
  <section>
    <h2>Token usage</h2>
    <div class="panel">
      <p style="color:var(--muted);font-size:.9rem;margin:0">
        No <code>total_tokens</code> fields in the loaded report JSONs. Re-run evals with the token callback harness
        or use <code>backfill_tokens.py</code> on reports that have Langfuse trace IDs.
      </p>
    </div>
  </section>"""

    est_pill = ""
    value_quadrant = render_value_quadrant(full_suite_acc, cost_stats)
    if has_sample_cost:
        total_est = cost_stats["_combined"]["est_full_matrix"]
        est_pill = f'<span class="pill">~{_fmt_cost(total_est, decimals=2)} est. LLM cost / suite</span>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AppWorld Agent Comparison — GPT-5.2 vs Cuga</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #07080c; --bg2: #0e1118; --card: #12161f; --border: rgba(255,255,255,.08);
      --text: #eef2ff; --muted: #94a3b8; --pass: #34d399; --fail: #fb7185;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Instrument Sans', system-ui, sans-serif;
      background: var(--bg); color: var(--text); line-height: 1.55;
      background-image: radial-gradient(ellipse 80% 50% at 50% -20%, rgba(91,156,245,.18), transparent),
                        radial-gradient(ellipse 60% 40% at 100% 0%, rgba(139,92,246,.12), transparent);
    }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 2.5rem 1.5rem 4rem; }}
    .hero {{ padding: 2rem 0 2.5rem; border-bottom: 1px solid var(--border); margin-bottom: 2rem; }}
    .hero-grid {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(300px, 420px); gap: 2rem; align-items: center; margin-top: 1.5rem; }}
    .hero-chart {{
      background: linear-gradient(145deg, var(--card), var(--bg2));
      border: 1px solid var(--border); border-radius: 18px; padding: 1rem 1rem .85rem;
    }}
    .chart-kicker {{ font-size: .68rem; text-transform: uppercase; letter-spacing: .12em; color: var(--muted); font-weight: 600; margin-bottom: .35rem; }}
    .chart-title {{ font-size: 1rem; font-weight: 600; color: var(--text); margin-bottom: .25rem; }}
    .chart-sub {{ font-size: .78rem; color: var(--muted); margin-bottom: .75rem; line-height: 1.4; }}
    .chart-foot {{ font-size: .72rem; color: var(--muted); margin-top: .55rem; line-height: 1.45; }}
    .chart-foot strong {{ color: #fde68a; font-family: 'JetBrains Mono', monospace; font-weight: 600; }}
    .quadrant-svg {{ width: 100%; height: auto; display: block; }}
    .eyebrow {{ text-transform: uppercase; letter-spacing: .14em; font-size: .72rem; color: var(--muted); font-weight: 600; }}
    h1 {{ font-size: clamp(1.8rem, 4vw, 2.6rem); font-weight: 700; letter-spacing: -.03em; margin: .5rem 0; }}
    .lead {{ color: var(--muted); max-width: 52rem; font-size: 1.05rem; }}
    .pill-row {{ display: flex; flex-wrap: wrap; gap: .5rem; margin-top: 1.25rem; }}
    .pill {{ background: rgba(255,255,255,.06); border: 1px solid var(--border); border-radius: 999px; padding: .35rem .85rem; font-size: .8rem; color: #cbd5e1; }}
    section {{ margin-bottom: 2.5rem; }}
    h2 {{ font-size: 1.25rem; font-weight: 600; margin-bottom: 1rem; display: flex; align-items: center; gap: .5rem; }}
    h2::before {{ content: ''; width: 4px; height: 1.1em; background: linear-gradient(180deg,#5b9cf5,#8b5cf6); border-radius: 2px; }}
    .grid3 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }}
    .agent-card {{
      background: linear-gradient(145deg, var(--card), var(--bg2));
      border: 1px solid var(--border); border-radius: 16px; padding: 1.25rem;
      border-top: 3px solid var(--accent);
    }}
    .agent-card header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 1rem; }}
    .agent-card h3 {{ font-size: 1rem; }}
    .rate {{ font-size: 1.5rem; font-weight: 700; color: var(--accent); }}
    .big-stats {{ display: grid; grid-template-columns: repeat(2,1fr); gap: .5rem; text-align: center; margin-bottom: 1rem; }}
    .big-stats strong {{ display: block; font-size: 1.4rem; }}
    .big-stats span {{ font-size: .68rem; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }}
    .stack-bar {{ display: flex; height: 8px; border-radius: 999px; overflow: hidden; background: rgba(255,255,255,.06); margin-bottom: .75rem; }}
    .mini-legend {{ list-style: none; font-size: .78rem; color: var(--muted); }}
    .mini-legend li {{ margin: .2rem 0; }}
    .file {{ font-size: .7rem; margin-top: .75rem; word-break: break-all; opacity: .7; }}
    .mono {{ font-family: 'JetBrains Mono', monospace; }}
    .panel {{ background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 1.5rem; }}
    .panel p, .panel li {{ color: #b8c5d6; font-size: .92rem; }}
    .panel ul {{ margin: .5rem 0 0 1.1rem; }}
    .panel li {{ margin: .4rem 0; }}
    .insight-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1rem; }}
    .insight {{
      background: rgba(255,255,255,.03); border: 1px solid var(--border); border-radius: 12px;
      padding: 1rem 1.1rem; border-left: 3px solid #5b9cf5;
    }}
    .insight.warn {{ border-left-color: #fbbf24; }}
    .insight.bad {{ border-left-color: #fb7185; }}
    .insight.good {{ border-left-color: #34d399; }}
    .insight h4 {{ font-size: .85rem; margin-bottom: .4rem; color: var(--text); }}
    .insight p {{ font-size: .82rem; color: var(--muted); margin: 0; }}
    .cmd {{ background: #0a0d14; border: 1px solid var(--border); border-radius: 10px; padding: 1rem; font-family: 'JetBrains Mono', monospace; font-size: .78rem; color: #93c5fd; overflow-x: auto; margin-top: 1rem; white-space: pre; }}
    .theme-bar {{ display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .75rem; }}
    .theme-tag {{ background: rgba(251,113,133,.12); border: 1px solid rgba(251,113,133,.25); color: #fecdd3; padding: .3rem .65rem; border-radius: 8px; font-size: .78rem; }}
    .table-wrap {{ overflow: auto; max-height: 65vh; border: 1px solid var(--border); border-radius: 12px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: .78rem; }}
    th, td {{ padding: .5rem .6rem; border-bottom: 1px solid var(--border); text-align: center; }}
    th {{ position: sticky; top: 0; background: #151922; color: var(--muted); font-weight: 500; text-transform: uppercase; font-size: .68rem; letter-spacing: .05em; z-index: 1; }}
    td.task-id {{ text-align: left; font-family: 'JetBrains Mono', monospace; position: sticky; left: 0; background: #12161f; z-index: 1; }}
    td.pass {{ color: var(--pass); }}
    td.fail {{ color: var(--fail); }}
    .badge {{ opacity: .85; }}
    .tok {{ display: block; font-size: .62rem; color: var(--muted); margin-top: .15rem; font-family: 'JetBrains Mono', monospace; }}
    .cost-cell {{ color: #fde68a; font-family: 'JetBrains Mono', monospace; font-weight: 500; }}
    .price-formula {{ background: #0a0d14; border: 1px solid var(--border); border-radius: 8px; padding: .75rem 1rem; font-size: .78rem; color: #fde68a; }}
    .cost-est-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; margin-bottom: .5rem; }}
    .cost-est-card {{
      background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 1.1rem 1.25rem;
      border-top: 3px solid var(--accent);
    }}
    .cost-est-card h4 {{ font-size: .9rem; margin-bottom: .35rem; color: var(--accent); }}
    .cost-big {{ font-size: 1.75rem; font-weight: 700; color: #fde68a; font-family: 'JetBrains Mono', monospace; line-height: 1.1; }}
    .cost-sub {{ font-size: .75rem; color: var(--muted); margin-bottom: .65rem; }}
    .cost-est-card ul {{ list-style: none; font-size: .78rem; color: var(--muted); }}
    .cost-est-card li {{ margin: .25rem 0; }}
    .cost-combined {{ font-size: 1rem; color: #cbd5e1; margin: .5rem 0 0; }}
    .cost-combined span {{ color: #fde68a; font-family: 'JetBrains Mono', monospace; font-weight: 600; }}
    footer {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--border); color: var(--muted); font-size: .78rem; }}
    .effort-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 1rem; margin-bottom: 1rem; }}
    .diagram-card {{
      background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 1.25rem 1.5rem;
    }}
    .diagram-card h3 {{ font-size: .85rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; margin-bottom: 1rem; }}
    .diagram-card h3::before {{ display: none; }}
    .diagram-svg {{ width: 100%; height: auto; display: block; }}
    .arch-card {{ margin-bottom: 1rem; }}
    .arch-svg {{ max-height: 240px; }}
    .effort-stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: .75rem; }}
    .stat-card {{
      background: rgba(255,255,255,.03); border: 1px solid var(--border); border-radius: 12px;
      padding: 1rem; text-align: center;
    }}
    .stat-card.accent {{ border-color: rgba(139,92,246,.4); background: rgba(139,92,246,.08); }}
    .stat-card.cursor {{ grid-column: span 2; text-align: left; border-color: rgba(52,211,153,.35); background: rgba(52,211,153,.06); }}
    .stat-num {{ display: block; font-size: 1.5rem; font-weight: 700; color: var(--text); line-height: 1.2; }}
    .stat-card.cursor .stat-num {{ font-size: 1.1rem; color: #6ee7b7; }}
    .stat-label {{ display: block; font-size: .72rem; color: var(--muted); margin-top: .25rem; text-transform: uppercase; letter-spacing: .05em; }}
    .stat-card.cursor .stat-label {{ text-transform: none; letter-spacing: 0; font-size: .82rem; }}
    .setup-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; align-items: start; }}
    .setup-panel ul {{ margin-bottom: 1rem; }}
    .setup-h3 {{ font-size: .78rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; margin: 0 0 .5rem; }}
    .react-card {{ margin: 0; }}
    .react-specs {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: .5rem; margin-top: 1rem; }}
    .react-spec {{ background: rgba(255,255,255,.03); border: 1px solid var(--border); border-radius: 8px; padding: .5rem .65rem; }}
    .spec-k {{ display: block; font-size: .65rem; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }}
    .spec-v {{ display: block; font-size: .85rem; color: var(--text); margin-top: .15rem; }}
    @media (max-width: 900px) {{ .setup-grid {{ grid-template-columns: 1fr; }} .hero-grid {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 640px) {{ .big-stats {{ grid-template-columns: 1fr; }} .stat-card.cursor {{ grid-column: span 1; }} .react-specs {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <div class="hero-grid">
      <div class="hero-copy">
        <p class="eyebrow">AppWorld · test_easy · 43 tasks · Jun 2026</p>
        <h1>Agent Benchmark Report</h1>
        <p class="lead">External ReAct agents on Azure GPT-5.2 vs Cuga SDK on Groq gpt-oss-120b — same AppWorld harness, cost and Pass@1 on test_easy.</p>
        <div class="pill-row">
          <span class="pill">43 tasks · test_easy</span>
          <span class="pill">GPT-5.2 · 3 ReAct agents</span>
          <span class="pill">Groq gpt-oss-120b · Cuga SDK</span>
          {est_pill}
        </div>
      </div>
      {value_quadrant}
    </div>
  </header>

{SETUP_SECTION}

{accuracy_section}

  <section>
    <h2>External agents — results at a glance</h2>
    <div class="grid3">{"".join(cards)}</div>
    <p style="margin-top:1rem;color:var(--muted);font-size:.85rem">All three external agents passed the same 5 tasks: {escape(", ".join(all_three_pass))}.</p>
  </section>

  <section>
    <h2>Cuga SDK</h2>
    <div class="grid3">{cuga_card}</div>
  </section>

{cost_section}
{token_section if has_any_tokens and not has_sample_cost else ""}

  <section>
    <h2>Why tasks failed</h2>
    <div class="insight-grid">
      <div class="insight bad">
        <h4>1 · Pagination &amp; filtering (~40% of failures)</h4>
        <p>Many “count/list” tasks failed with <strong>50% match</strong> — close but wrong. Example: <code>e775c78_1</code> used correct Gmail filters (<code>label=priority-1, read=false</code>) but counted only page 0 (answered <strong>5</strong>, truth <strong>15</strong>). The shared prompt mentions pagination; 12 steps often isn’t enough to paginate + compute.</p>
      </div>
      <div class="insight warn">
        <h4>2 · Max-step exhaustion (11 tasks total)</h4>
        <p>Multi-step workflows (Amazon cart moves, Spotify playlist renames, wishlist orders) hit the <strong>12-step ReAct cap</strong> before emitting <code>Final Answer:</code>. Deep Agents 5 · OpenClaw 4 · Hermes 4. Several had partial tool progress (7–9 calls) but no final submission.</p>
      </div>
      <div class="insight warn">
        <h4>3 · Entity resolution (contacts, relationships)</h4>
        <p>Tasks like <code>dbc0276_1</code> (“text my husband”) failed across agents: models couldn’t map “husband” → a contact record and gave up or answered N/A. Requires supervisor/phone contact graph traversal the loop rarely completes in time.</p>
      </div>
      <div class="insight bad">
        <h4>4 · Full-catalog prompt overload</h4>
        <p>~300–470 tools inlined in every turn (no Shortlister). Models pick plausible-but-wrong APIs, skip filter params, or burn steps on exploration. Fair across externals, but harder than CUGA’s ranked tool subset.</p>
      </div>
      <div class="insight warn">
        <h4>5 · Infra / API errors (4 tasks)</h4>
        <p>Deep Agents: 2× Azure content-filter 400 on <code>ba46d91_1</code>, <code>afc4005_1</code> (0 steps). Hermes: 2× connection errors on <code>afc4005_1</code>, <code>425a494_1</code>. OpenClaw had zero LLM transport failures.</p>
      </div>
      <div class="insight good">
        <h4>What worked</h4>
        <p>Simpler single-app lookups with one clear API path (e.g. <code>81be677_1</code>, <code>3650990_1</code>, <code>7847649_1</code>) passed for all three. OpenClaw led on pass rate (13/43) with fewer infra errors; Hermes 10/43; Deep Agents 8/43.</p>
      </div>
    </div>
    <div class="panel" style="margin-top:1rem">
      <p><strong>Failure themes</strong> (OpenClaw failed tasks by domain):</p>
      <div class="theme-bar">
        {"".join(f'<span class="theme-tag">{escape(k)} · {v}</span>' for k,v in fail_themes.most_common())}
      </div>
    </div>
  </section>

{EFFORT_SECTION}

  <section>
    <h2>Per-task matrix</h2>
    <p style="color:var(--muted);font-size:.85rem;margin-bottom:.75rem">Hover cells for error/response snippet. ✓ = harness pass (100% match).</p>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Task</th>
            <th style="color:{AGENT_COLORS['deepagents']}">Deep Agents</th>
            <th style="color:{AGENT_COLORS['openclaw']}">OpenClaw</th>
            <th style="color:{AGENT_COLORS['hermes']}">Hermes</th>
          </tr>
        </thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>
  </section>

  <footer>
    Generated from <code>benchmarks/appworld/experiments/outputs/</code> ·
    Reports: deepagents <code>155137</code>, openclaw <code>171301</code>, hermes <code>190749</code>
  </footer>
</div>
</body>
</html>"""

    OUT.write_text(html)
    print(f"Wrote {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
