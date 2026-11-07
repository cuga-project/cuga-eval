"""Cost ledger and budget stop for the policy-layer pilot (EnterpriseOps-Gym + AutomationBench).

Cost = input tokens x $0.75 + output tokens x $3.75 per 1M (Gemini 3.8 Flash intro price, valid through
2026-12-31; cache reads charged at the full input rate, so this is an upper bound). Tokens come from CUGA's run
receipt (agent) plus the policy layer's own model calls. The gateway's spend API is not available to our key.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict

LEDGER = Path(__file__).resolve().parent / "policy_pilot_ledger.jsonl"
PRICE_IN, PRICE_OUT = 0.75, 3.75  # $ per 1M tokens
BUDGET = float(os.environ.get("POLICY_PILOT_BUDGET", "2000"))  # raised from 1000 (2026-11-03), 1200, 1500, 1700 and 2000 (2026-11-04) by the user


def cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * PRICE_IN + output_tokens * PRICE_OUT) / 1e6


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    return sum(json.loads(line)["cost_usd"] for line in LEDGER.read_text().splitlines() if line.strip())


PRICES = {
    "gcp/gemini-3.8-flash": (0.75, 3.75),
    "aws/gpt-oss-120b": (0.15, 0.60),
    "aws/claude-haiku-5-5": (0.076, 0.38),  # the gateway price (model/info, 2026-11-05)
    "Azure/gpt-5-mini-2025-08-07": (0.25, 2.00),
    "azure/DeepSeek-V4-Pro": (1.74, 3.48),
    "gcp/gemini-3.5-flash-lite": (0.30, 2.50),
    "aws/nemotron-super-3-120b": (0.15, 0.65),
    "openai/Azure/gpt-4.1": (2.00, 8.00),  # the τ² user simulator
}  # $ per 1M in/out (list)


def _price(model: str | None) -> tuple:
    """Known list price, else the Gemini price (an upper bound for the models used here)."""
    return PRICES.get(model or "", (PRICE_IN, PRICE_OUT))


def usage_cost(model: str | None, usage: Dict[str, Any]) -> float:
    """Tokens at the model's price, plus a cost the provider reported (Kev-4B reports dollars and no tokens)."""
    price_in, price_out = _price(model)
    tokens = usage.get("input_tokens", 0) * price_in + usage.get("output_tokens", 0) * price_out
    return tokens / 1e6 + float(usage.get("cost") or 0.0)


def _refuse_no_model(side: str, kind: str, name: str, usage: Dict[str, Any], model: str | None) -> None:
    if not model and (usage.get("input_tokens") or usage.get("output_tokens") or usage.get("cost")):
        raise ValueError(
            f"ledger: {kind} {name}: {side} usage names no model, so it has no price; nothing was recorded"
        )


def record(
    kind: str,
    name: str,
    agent: Dict[str, Any] | None = None,
    policy: Dict[str, Any] | None = None,
    component: str | None = None,
) -> float:
    """Add one line to the ledger and return its cost. Usage with no model name raises, and writes nothing: a missing name
    used to price the tokens as Gemini. ``component``: which part of a run this line is (agent, gate, tracker, ...)."""
    agent, policy = agent or {}, policy or {}
    a_in, a_out = agent.get("input_tokens", 0), agent.get("output_tokens", 0)
    p_in, p_out = policy.get("input_tokens", 0), policy.get("output_tokens", 0)
    a_model = (agent.get("models") or [None])[0]
    p_model = policy.get("model") or os.environ.get("POLICY_MODEL_NAME")
    _refuse_no_model("agent", kind, name, agent, a_model)
    _refuse_no_model("policy", kind, name, policy, p_model)
    c = usage_cost(a_model, agent) + usage_cost(p_model, policy)
    entry = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "kind": kind,
        "name": name,
        "agent_in": a_in,
        "agent_out": a_out,
        "policy_in": p_in,
        "policy_out": p_out,
        "policy_calls": policy.get("calls", 0),
        "cost_usd": round(c, 4),
    }
    if component:
        entry["component"] = component
        entry["model"] = a_model or p_model
    with LEDGER.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return c


def over_budget() -> bool:
    return spent() >= BUDGET


def line() -> str:
    return f"spent ${spent():.2f} of ${BUDGET:.0f} budget"
