#!/usr/bin/env python3
"""AutomationBench as the harness uses it: tasks, the world of a task, its tools and the rubric. No CUGA import.

The benchmark's own runner (verifiers) drives a model loop, so CUGA cannot be plugged in as a model. Instead:
  1. ``build_world`` builds the task's WorldState exactly like AutomationBenchEnv.setup_state,
  2. ``make_tool`` exposes the toolset as LangChain tools with ``world`` bound,
  3. the harness (``policy_eval/harness/adapters/automationbench.py``) runs the agent,
  4. ``score`` scores the final world with automationbench.rubric.partial_credit.

Moved unchanged from the old runner (``policy_eval/launchers/archive/run_cuga.py``). Offline tools import this module too.
"""

from __future__ import annotations

import copy
import inspect
import json
import time
import typing
from typing import Any, Callable

TOOL_LOG_LIMIT = 4000


def load_task(name: str) -> dict:
    from automationbench.domains import PUBLIC_DOMAINS, get_domain_dataset

    domain = name.split(".", 1)[0]
    for dom in [domain] if domain in PUBLIC_DOMAINS else PUBLIC_DOMAINS:
        for row in get_domain_dataset(dom):
            info = row["info"] if isinstance(row["info"], dict) else json.loads(row["info"])
            if info.get("task_name") == name:
                return {"domain": dom, "prompt": row["prompt"], "info": info}
    raise KeyError(f"task not found: {name}")


def build_world(info: dict):
    from automationbench.runner import compute_allowed_services, strip_none_values
    from automationbench.schema.world import WorldState

    info = copy.deepcopy(info)
    initial = strip_none_values(info.get("initial_state", {}))
    info["assertions"] = [strip_none_values(a) for a in info.get("assertions", [])]
    world = WorldState(**initial)
    world.meta.allowed_services = compute_allowed_services(
        initial, info["assertions"], info.get("zapier_tools", [])
    )
    return world, info, copy.deepcopy(initial)


def score(world, info: dict, initial: dict) -> dict:
    from automationbench.rubric import partial_credit
    from automationbench.rubric.registry import AssertionRegistry
    from automationbench.schema.world import WorldState

    state = {"world": world, "info": info, "initial_state": initial}
    pc = partial_credit(state)
    results = state.get("_assertion_results", [])
    w0 = WorldState(**copy.deepcopy(initial))
    for r, a in zip(results, info["assertions"]):
        r["negative"] = AssertionRegistry.is_negative(a["type"])
        # Guardrail as partial_credit defines it: a scored check that already passes in the initial state
        authored_out = a.get("scored") is False or a.get("excluded") is True
        r["guard"] = (
            not authored_out and a.get("excluded") is not False and bool(AssertionRegistry.check(w0, a))
        )
    scored = [r for r in results if not r["excluded"]]
    positives = [r for r in scored if not r["negative"]]
    guard_broken = any(not r["passed"] for r in scored if r["negative"])
    # Older approximation (kept for comparison with earlier runs): negative assertion = guardrail.
    aa_old = (
        0.0 if guard_broken else (sum(r["passed"] for r in positives) / len(positives) if positives else 1.0)
    )
    # Artificial Analysis rule: objectives are the checks not passing at the start; any broken guardrail scores 0.
    guards = [r for r in results if r["guard"]]
    broken = [r for r in guards if not r["passed"]]
    objectives = [r for r in scored if not r["guard"]]
    aa = 0.0 if broken else (sum(r["passed"] for r in objectives) / len(objectives) if objectives else 1.0)
    return {
        "pass": pc == 1.0,
        "partial_credit": pc,
        "aa": aa,
        "aa_style": aa_old,
        "n_guards": len(guards),
        "guards_broken": len(broken),
        "guard_broken_aa": bool(broken),
        "guard_broken": guard_broken,
        "n_scored": len(scored),
        "failed": [
            {k: r[k] for k in ("type", "negative", "guard", "params")} for r in scored if not r["passed"]
        ],
    }


# ── tools ────────────────────────────────────────────────────────────────────


def _decode(out: Any) -> Any:
    if isinstance(out, str):
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return out
    return out


def make_tool(fn: Callable, world, log: list[dict]):
    from langchain_core.tools import StructuredTool

    sig = inspect.signature(fn)
    needs_world = "world" in sig.parameters
    params = [p for n, p in sig.parameters.items() if n != "world"]
    public_sig = sig.replace(parameters=params, return_annotation=Any)
    hints = typing.get_type_hints(fn)

    def call(*args, **kwargs):
        # CUGA's generated code may pass arguments positionally.
        kwargs = dict(public_sig.bind(*args, **kwargs).arguments)
        if needs_world:
            kwargs["world"] = world
        started = time.monotonic()
        try:
            out = fn(**kwargs)
        except Exception as exc:  # the verifiers env also returns tool errors to the model
            out = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        log.append(
            {
                "tool": fn.__name__,
                "args": {k: v for k, v in kwargs.items() if k != "world"},
                "result": str(out)[:TOOL_LOG_LIMIT],
                "ms": round((time.monotonic() - started) * 1000),
            }
        )
        return _decode(out)

    call.__name__ = fn.__name__
    call.__doc__ = fn.__doc__
    call.__signature__ = public_sig
    call.__annotations__ = {k: v for k, v in hints.items() if k not in ("world", "return")}
    try:
        return StructuredTool.from_function(
            func=call, name=fn.__name__, parse_docstring=True, error_on_invalid_docstring=False
        )
    except ValueError:  # a docstring that documents an argument the signature hides (e.g. ``world``)
        return StructuredTool.from_function(
            func=call, name=fn.__name__, description=fn.__doc__ or fn.__name__
        )


def toolset_functions(toolset: str, info: dict) -> list[Callable]:
    if toolset == "api":
        from automationbench.tools.api import API_TOOLS

        return list(API_TOOLS)
    if toolset == "limited_zapier":
        from automationbench.tools import ALL_TOOLS

        allowed = set(info.get("zapier_tools", []))
        return [t for t in ALL_TOOLS if t.__name__ in allowed]
    if toolset == "full":  # every Zapier tool of all 47 apps; CUGA has to find the ones the task needs
        from automationbench.tools import ALL_TOOLS

        return list(ALL_TOOLS)
    raise ValueError(f"unknown toolset: {toolset}")


def tool_app(fn: Callable) -> str:
    """The app a tool belongs to, from its module path (automationbench.tools.zapier.<app>.<file>)."""
    parts = fn.__module__.split(".")
    if "zapier" in parts and parts.index("zapier") + 1 < len(parts):
        return parts[parts.index("zapier") + 1]
    return parts[-2] if len(parts) > 2 else "tools"
