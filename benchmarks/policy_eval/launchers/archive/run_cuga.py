#!/usr/bin/env python3
"""Run CUGA on AutomationBench tasks and score them with the benchmark rubric.

The benchmark's own runner (verifiers) drives a model loop, so CUGA cannot be
plugged in as a model. Instead, per task this script:
  1. builds the task's WorldState exactly like AutomationBenchEnv.setup_state,
  2. exposes the toolset as LangChain tools with `world` bound,
  3. runs CugaAgent on the task prompt (system message -> special_instructions),
  4. scores the final world with automationbench.rubric.partial_credit.

Parent mode runs each task in its own subprocess (CUGA keeps process-global
state), N at a time, and skips tasks that already have a result file.

Usage:
  .venv/bin/python run_cuga.py --subset subset.json --run glm53flash_api -j 6
  .venv/bin/python run_cuga.py --tasks sales.multi_hop_lookup --run smoke
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import inspect
import json
import os
import sys
import time
import typing
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
EVAL_ROOT = HERE.parents[1]
RESULTS = HERE / "results"
SECRET_KEYS = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENROUTER_API_KEY")
sys.path.insert(0, str(HERE.parent))
import policy_pilot_costs as costs  # noqa: E402

TOOL_LOG_LIMIT = 4000


# ── task loading and scoring (no cuga import) ────────────────────────────────


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


ORACLE_INTRO = (
    "CHECK RESULTS: an automatic check of the finished work found these problems. Fix them now "
    "(do what is missing, correct what is wrong), then answer again:"
)  # upper-bound arm only (POLICY_ORACLE=1)


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


def provenance() -> dict:
    """What produced this result: cell label, code snapshot, env file and its CUGA flags, policy switches."""
    env_file = Path(os.environ.get("ENV_FILE", HERE / "cuga.env"))
    flags = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DYNACONF_") or line.startswith(("MODEL_NAME=", "AGENT_SETTING_CONFIG=")):
                k, _, v = line.partition("=")
                flags[k] = v
    src = os.environ.get("CUGA_SRC")
    source = Path(src).parent / "SOURCE.txt" if src else None
    return {
        "cell": os.environ.get("POLICY_EVAL_CELL"),
        "env_file": env_file.name,
        "env_flags": flags,
        "cuga_src": src,
        "cuga_source": source.read_text().split() if source and source.exists() else None,
        "switches": {
            k: v for k, v in os.environ.items() if k.startswith(("POLICY_", "SOP_")) and "KEY" not in k
        },
    }


def tool_app(fn: Callable) -> str:
    """The app a tool belongs to, from its module path (automationbench.tools.zapier.<app>.<file>)."""
    parts = fn.__module__.split(".")
    if "zapier" in parts and parts.index("zapier") + 1 < len(parts):
        return parts[parts.index("zapier") + 1]
    return parts[-2] if len(parts) > 2 else "tools"


# ── child: one task ──────────────────────────────────────────────────────────


def save_trajectory(out_dir, name: str) -> Any:
    """CUGA's tracker writes every task to one shared file; keep this task's steps (one task per child process)."""
    try:
        from cuga.backend.activity_tracker.tracker import ActivityTracker

        tr = ActivityTracker()
        steps = [
            s.model_dump() if hasattr(s, "model_dump") else getattr(s, "__dict__", str(s))
            for s in (tr.steps or [])
        ]
        path = Path(out_dir) / "trajectories" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"intent": tr.intent, "task": name, "steps": steps}, default=str))
        return str(path)
    except Exception as exc:  # noqa: BLE001 - a lost trajectory must not lose the result
        return f"not saved: {type(exc).__name__}: {exc}"


async def run_one(name: str, toolset: str, out_dir: Path, timeout: float, arm: str = "A") -> dict:
    task = load_task(name)
    world, info, initial = build_world(task["info"])
    system = "\n\n".join(m["content"] for m in task["prompt"] if m["role"] == "system")
    user = "\n\n".join(m["content"] for m in task["prompt"] if m["role"] == "user")

    from cuga.backend.activity_tracker.tracker import ActivityTracker
    from cuga.sdk import CugaAgent

    tool_log: list[dict] = []
    fns = toolset_functions(toolset, info)
    tools = [make_tool(fn, world, tool_log) for fn in fns]
    app_by_tool = {fn.__name__: tool_app(fn) for fn in fns}
    current_time = str(world.meta.current_time or "").replace("Z", "+00:00")
    ActivityTracker().current_date = current_time or None

    try:  # policy runtime trace: every LLM / decision-model call of the policy layer (older snapshots lack it)
        from cuga.policy_layer.trace import PolicyTrace

        ptrace = PolicyTrace()
    except ImportError:
        ptrace = None

    def traced(model, component):
        return ptrace.wrap_model(model, component) if ptrace is not None else model

    decisions_ask = None
    hooks = None
    if arm == "B":  # policy adherence layer: online intake + write verifier (cuga-agent-gate)
        from cuga.policy_layer.builder import openai_json_model
        from cuga.policy_layer.intake import OnlinePolicyIntake

        specs = [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.args_schema.model_json_schema() if t.args_schema else {},
                "app": app_by_tool.get(t.name),
            }
            for t in tools
        ]
        detector = None
        if os.environ.get("POLICY_DETECTOR", "kev") == "kev" and os.environ.get("OPENROUTER_API_KEY"):
            from cuga.policy_layer.detectors import systemone_detector

            detector = systemone_detector()  # Kev-4B, chosen by the detector probe (2026-10-31)
            if ptrace is not None:
                detector = ptrace.wrap_detector(detector)
        choice_path = os.environ.get("POLICY_METHOD_CHOICE")
        method_choice = json.loads(Path(choice_path).read_text()) if choice_path else None
        extra: dict[
            str, Any
        ] = {}  # options newer layer versions take; passed only when set (older snapshots)
        if os.environ.get("POLICY_READ_BEFORE_WRITE"):
            extra["read_before_write"] = os.environ["POLICY_READ_BEFORE_WRITE"]
        if os.environ.get("POLICY_SUPERSEDES") == "1":  # replaced rules leave the current list
            extra["track_supersedes"] = True
        if (
            os.environ.get("POLICY_DISCOVER") == "1"
        ):  # the layer searches message sources for rules at the start
            from cuga.policy_layer.intake import discovery_tools

            by_name = {fn.__name__: fn for fn in fns}
            extra["discover"] = [
                (n, (lambda q, fn=by_name[n]: fn(world=world, query=q))) for n in discovery_tools(fns)
            ]
        if (
            os.environ.get("POLICY_V4") == "1"
        ):  # decision-model write checks, block-once verdicts, skip after cap
            from cuga.policy_layer.decisions import Decisions
            from cuga.policy_layer.detectors import systemone_questions

            decisions_ask = systemone_questions()
            extra["decisions"] = Decisions(
                ptrace.wrap_ask(decisions_ask, "decisions") if ptrace is not None else decisions_ask
            )
            extra["model_effect"] = "block_once"
            extra["cap_effect"] = "skip"
            if (
                os.environ.get("POLICY_V5") == "1"
            ):  # record signals, missing facts, hold on recheck, content match
                extra["record_checks"] = True
                extra["retry_effect"] = "hold"
            if os.environ.get("POLICY_RETRY_EFFECT"):  # override: allow | hold
                extra["retry_effect"] = os.environ["POLICY_RETRY_EFFECT"]
        if os.environ.get("POLICY_BRIEF"):
            extra["brief"] = os.environ["POLICY_BRIEF"] != "0"
        if os.environ.get("POLICY_NOTES"):
            extra["note_channel"] = os.environ["POLICY_NOTES"]
        if os.environ.get("POLICY_GUARD_CODE"):
            extra["guard_code"] = os.environ["POLICY_GUARD_CODE"]
            extra["today"] = current_time[:10] or None
        hooks = OnlinePolicyIntake(
            traced(
                openai_json_model(os.environ.get("POLICY_MODEL_NAME") or os.environ.get("MODEL_NAME")),
                "policy_layer",
            ),
            detector=detector,
            tool_specs=specs,
            method_choice=method_choice,
            **extra,
        )
    deliverables = None
    if os.environ.get("POLICY_DELIVERABLES") == "1":  # request checklist checked at the reply (either arm)
        from cuga.policy_layer.builder import openai_json_model as _jm
        from cuga.policy_layer.deliverables import DeliverablesHooks

        dspecs = [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.args_schema.model_json_schema() if t.args_schema else {},
            }
            for t in tools
        ]
        deliverables = DeliverablesHooks(
            traced(_jm(os.environ.get("POLICY_MODEL_NAME") or os.environ.get("MODEL_NAME")), "deliverables"),
            dspecs,
            **({"note_channel": os.environ["POLICY_NOTES"]} if os.environ.get("POLICY_NOTES") else {}),
        )
    tracker = None
    if os.environ.get("POLICY_TRACKER") == "1":  # requirements checklist compiled and checked at the reply
        from cuga.policy_layer.tracker import tracker_from_env

        tracker = tracker_from_env()
        tracker.model = traced(tracker.model, "tracker")
    loop = rec = None
    if (
        os.environ.get("SOP_LOOP") == "1"
    ):  # SOP-aware loop: phases + typed questions (no SOP graph: rules from data)
        from cuga.policy_layer.llm import openai_json_model as _ojm
        from cuga.policy_layer.sop_loop import LoopHooks, SopLoop

        rec = LoopHooks()
        loop = SopLoop(
            _ojm(
                os.environ.get("POLICY_LOOP_MODEL") or "azure/DeepSeek-V4-Pro", timeout=300, max_tokens=8000
            ),
            [],
        )
    hook_list = [h for h in (rec, hooks, deliverables, tracker) if h is not None]
    record: dict[str, Any] = {
        "task": name,
        "arm": arm,
        "domain": task["domain"],
        "toolset": toolset,
        "model": os.environ.get("MODEL_NAME"),
        "world_time": current_time,
        "n_tools": len(tools),
        "apps": sorted(set(app_by_tool.values())),
        "task_apps": sorted({tool_app(fn) for fn in toolset_functions("limited_zapier", info)}),
        "provenance": provenance(),
    }
    started = time.monotonic()
    try:
        from helpers.app_tools_provider import AppToolsProvider

        agent = CugaAgent(
            tool_provider=AppToolsProvider(
                tools, lambda t: app_by_tool[t.name]
            ),  # real app names, as in AppWorld
            special_instructions=system or None,
            cuga_folder=str(out_dir / ".cuga"),
            auto_load_policies=False,
            filesystem_sync=False,
            enable_knowledge=False,
            **({"hooks": hook_list} if hook_list else {}),
        )
        if loop is not None:
            result = await loop.run(agent, user, f"ab-{name}", rec, timeout)
            record["sop_loop"] = loop.log
            record["loop_receipts"] = loop.receipts[:-1]
            record["loop_usage"] = dict(getattr(loop.model, "usage", {}) or {})
        else:
            result = await asyncio.wait_for(agent.invoke(user, thread_id=f"ab-{name}"), timeout=timeout)
        if os.environ.get("POLICY_ORACLE") in (
            "1",
            "names",
        ):  # upper bound: the grader's failed checks go back
            record["oracle_rounds"], record["oracle_receipts"] = [], []
            for rnd in range(2):
                s = score(world, info, initial)
                record["oracle_rounds"].append({"round": rnd + 1, "failed": len(s["failed"])})
                if not s["failed"]:
                    break
                if os.environ["POLICY_ORACLE"] == "names":  # which check failed, without its expected values
                    lines = [
                        ("Something was done that must not be done: " if f["negative"] else "")
                        + f["type"].replace("_", " ")
                        + (f" (checked: {', '.join(sorted(f['params']))})" if f["params"] else "")
                        for f in s["failed"]
                    ]
                else:
                    lines = [
                        ("MUST NOT: " if f["negative"] else "")
                        + f"{f['type']} {json.dumps(f['params'], default=str)}"
                        for f in s["failed"]
                    ]
                if getattr(result, "receipt", None) is not None:
                    record["oracle_receipts"].append(result.receipt.model_dump(exclude={"tool_timings"}))
                result = await asyncio.wait_for(
                    agent.invoke(
                        ORACLE_INTRO + "\n" + "\n".join(f"- {x}" for x in lines), thread_id=f"ab-{name}"
                    ),
                    timeout=timeout,
                )
        record["answer"] = result.answer
        record["error"] = result.error
        receipt = getattr(result, "receipt", None)
        if receipt is not None:
            record["receipt"] = receipt.model_dump(exclude={"tool_timings"})
    except asyncio.TimeoutError:
        record["error"] = f"timeout after {timeout:.0f}s"
    except Exception as exc:  # noqa: BLE001 — score whatever state the agent left
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["wall_s"] = round(time.monotonic() - started, 1)
    record["trajectory"] = save_trajectory(out_dir, f"{arm}_{name}")
    if ptrace is not None and ptrace.events:
        tpath = Path(out_dir) / "policy_trace" / f"{arm}_{name}.json"
        tpath.parent.mkdir(parents=True, exist_ok=True)
        tpath.write_text(json.dumps(ptrace.events, indent=1, default=str))
        record["policy_trace"] = str(tpath)
        record["policy_trace_summary"] = ptrace.summary()
    if decisions_ask is not None:
        record["decisions_usage"] = dict(decisions_ask.usage)
    record.update(score(world, info, initial))
    record["tool_calls"] = tool_log
    record["trial"] = os.environ.get("POLICY_EVAL_TRIAL")
    record["gate"] = (
        (hooks.records if hooks else [])
        + (deliverables.records if deliverables else [])
        + (tracker.records if tracker else [])
    )
    record["policy_usage"] = (
        {**dict(getattr(hooks.model, "usage", {}) or {}), "model": getattr(hooks.model, "model_name", None)}
        if hooks
        else {}
    )
    if tracker is not None:
        record["tracker_usage"] = dict(getattr(tracker.model, "usage", {}) or {})
        record["tracker_model"] = getattr(tracker.model, "model_name", None)
    if (
        deliverables is not None
    ):  # same policy model: its tokens are added to policy_usage for the cost ledger
        du = dict(getattr(deliverables.model, "usage", {}) or {})
        record["deliverables_usage"] = du
        pu = record["policy_usage"]
        pu.setdefault("model", getattr(deliverables.model, "model_name", None))
        for k, v in du.items():
            pu[k] = pu.get(k, 0) + v if isinstance(v, (int, float)) else pu.get(k, v)
    if hooks is not None and getattr(hooks, "detector", None) is not None:
        record["detector_usage"] = dict(getattr(hooks.detector, "usage", {}) or {})
    if hooks is not None:
        from cuga.policy_layer.model import to_json

        record["overlay"] = to_json(hooks.overlay)
    return record


# ── parent: many tasks ───────────────────────────────────────────────────────


def child_env(proxy: str | None) -> dict[str, str]:
    from dotenv import dotenv_values

    env = dict(os.environ)
    secrets = dotenv_values(EVAL_ROOT / ".env")
    for key in SECRET_KEYS:
        if secrets.get(key) and key not in env:
            env[key] = secrets[key]
    if proxy:
        env["OPENAI_BASE_URL"] = proxy  # retry_proxy.py waits out gateway 429s
    env["ENV_FILE"] = str(HERE / os.environ.get("CUGA_ENV_FILE", "cuga.env"))
    if os.environ.get("CUGA_SRC"):  # run another cuga checkout (e.g. the policy-gate worktree) for both arms
        env["PYTHONPATH"] = os.environ["CUGA_SRC"] + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    return env


INFRA_ERRORS = ("RateLimit", "429", "APIConnection", "APITimeout", "retry_proxy")


def is_done(path: Path) -> bool:
    """A result counts as done unless it ended on a gateway/infra error."""
    if not path.exists():
        return False
    error = json.loads(path.read_text()).get("error") or ""
    return not any(marker in error for marker in INFRA_ERRORS)


async def run_many(names: list[str], args: argparse.Namespace) -> None:
    run_dir = RESULTS / args.run
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    todo = [n for n in names if not is_done(run_dir / f"{n}.json")]
    print(f"{len(names)} tasks, {len(names) - len(todo)} done, {len(todo)} to run (-j {args.jobs})")
    env = child_env(args.proxy)
    sem = asyncio.Semaphore(args.jobs)

    async def one(name: str) -> None:
        async with sem:
            if costs.over_budget():
                print(f"SKIP {name}: budget reached ({costs.line()})")
                return
            with open(run_dir / "logs" / f"{name}.log", "w") as log:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    __file__,
                    "--child",
                    name,
                    "--run",
                    args.run,
                    "--arm",
                    args.arm,
                    "--toolset",
                    args.toolset,
                    "--timeout",
                    str(args.timeout),
                    cwd=HERE,
                    env=env,
                    stdout=log,
                    stderr=asyncio.subprocess.STDOUT,
                )
                try:
                    await asyncio.wait_for(proc.wait(), timeout=args.timeout + 300)
                except asyncio.TimeoutError:
                    proc.kill()
            path = run_dir / f"{name}.json"
            if path.exists():
                r = json.loads(path.read_text())
                status = "PASS" if r["pass"] else "fail"
                c = costs.record(
                    f"automationbench_{args.arm}",
                    f"{args.run}/{name}",
                    agent=r.get("receipt"),
                    policy=r.get("policy_usage"),
                )
                for rc in r.get("oracle_receipts") or []:  # earlier rounds of the oracle arm
                    c += costs.record("automationbench_oracle_round", f"{args.run}/{name}", agent=rc)
                for rc in r.get("loop_receipts") or []:  # earlier turns of the SOP loop
                    c += costs.record("automationbench_loop_turn", f"{args.run}/{name}", agent=rc)
                if r.get("loop_usage"):
                    c += costs.record(
                        "automationbench_loop_questions",
                        f"{args.run}/{name}",
                        policy={
                            **r["loop_usage"],
                            "model": os.environ.get("POLICY_LOOP_MODEL") or "azure/DeepSeek-V4-Pro",
                        },
                    )
                if r.get("tracker_usage"):  # the tracker may use another model than the policy layer
                    c += costs.record(
                        "automationbench_tracker",
                        f"{args.run}/{name}",
                        policy={**r["tracker_usage"], "model": r.get("tracker_model")},
                    )
                print(
                    f"{status} {name} pc={r['partial_credit']:.2f} {r['wall_s']}s ${c:.2f} [{costs.line()}] {r.get('error') or ''}"
                )
            else:
                print(f"CRASH {name} (see logs/{name}.log)")

    await asyncio.gather(*(one(n) for n in todo))
    summarize(run_dir)


def summarize(run_dir: Path) -> None:
    rows = [json.loads(p.read_text()) for p in sorted(run_dir.glob("*.json"))]
    if not rows:
        return
    by_domain: dict[str, list[dict]] = {}
    for r in rows:
        by_domain.setdefault(r["domain"], []).append(r)
    print(f"\n{'domain':<12}{'n':>4}{'pass':>8}{'partial':>9}{'aa_style':>10}")
    for dom, rs in sorted(by_domain.items()) + [("ALL", rows)]:
        n = len(rs)
        print(
            f"{dom:<12}{n:>4}{100 * sum(r['pass'] for r in rs) / n:>7.1f}%"
            f"{100 * sum(r['partial_credit'] for r in rs) / n:>8.1f}%"
            f"{100 * sum(r['aa_style'] for r in rs) / n:>9.1f}%"
        )
    errors = [r for r in rows if r.get("error")]
    tokens_in = sum((r.get("receipt") or {}).get("input_tokens", 0) for r in rows)
    tokens_out = sum((r.get("receipt") or {}).get("output_tokens", 0) for r in rows)
    print(f"errors: {len(errors)}  tokens in/out: {tokens_in:,}/{tokens_out:,}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subset", type=Path)
    parser.add_argument("--tasks", help="comma-separated task names")
    parser.add_argument("--run", required=True)
    parser.add_argument("--toolset", default="api", choices=["api", "limited_zapier", "full"])
    parser.add_argument("-j", "--jobs", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--proxy", default="http://127.0.0.1:8799", help="'' to call the gateway directly")
    parser.add_argument("--arm", default="A", choices=["A", "B"], help="B adds the policy adherence layer")
    parser.add_argument("--policy-pilot", type=Path, help="policy_pilot.json from select_policy_pilot.py")
    parser.add_argument(
        "--set", choices=["tune", "unseen", "xref"], help="task set from policy_eval/policy_eval_tasks.json"
    )
    parser.add_argument("--trial", type=int, help="trial number (recorded; use one --run per trial)")
    parser.add_argument("--child", help=argparse.SUPPRESS)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    if args.summary:
        summarize(RESULTS / args.run)
        return
    if args.child:
        run_dir = RESULTS / args.run
        record = asyncio.run(run_one(args.child, args.toolset, run_dir, args.timeout, args.arm))
        (run_dir / f"{args.child}.json").write_text(json.dumps(record, indent=2, default=str))
        return

    names: list[str] = []
    if args.subset:
        names += [n for tasks in json.loads(args.subset.read_text())["tasks"].values() for n in tasks]
    if args.policy_pilot:
        names += [t["task"] for t in json.loads(args.policy_pilot.read_text())["tasks"]]
    if args.set:
        names += json.loads((HERE.parent / "policy_eval" / "policy_eval_tasks.json").read_text())[
            "automationbench"
        ][args.set]
    if args.trial is not None:
        os.environ["POLICY_EVAL_TRIAL"] = str(args.trial)
    if args.tasks:
        names += [n.strip() for n in args.tasks.split(",") if n.strip()]
    if not names:
        parser.error("give --subset or --tasks")
    asyncio.run(run_many(names, args))


if __name__ == "__main__":
    main()
