#!/usr/bin/env python3
"""Run CUGA on EnterpriseOps-Gym ITSM tasks, without (arm A) and with (arm B) the policy adherence layer.

Per task and arm, in its own subprocess (CUGA keeps process-global state):
  1. seed a fresh copy of the task database on the gym server (EOGTask)
  2. expose the task's selected MCP tools as LangChain tools
  3. arm B only: load the rule set built offline from this task's policy text (build_rules.py) and add
     RuleSetHooks; the user's role is looked up by the platform side (get_user), not shown to the agent
  4. run CugaAgent with the policy as special instructions and the task prompt as the user message
  5. grade with the benchmark's VerifierEngine (all SQL verifiers must pass)

Run with the cuga-agent-gate venv (it has the hooks API):
  ~/dev/cuga-agent-gate/.venv/bin/python benchmarks/enterpriseops_gym/run_cuga_eog.py --pilot --arms A,B --run pilot1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
EVAL_ROOT = HERE.parents[1]
RESULTS = HERE / "results"
RULES = HERE / "rules"
ORACLE_INTRO = (
    "CHECK RESULTS: an automatic check of the finished work found these problems. Fix them now "
    "(do what is missing, correct what is wrong), then answer again:"
)  # upper-bound arm only (POLICY_ORACLE=1)
BUILDS = Path(
    os.environ.get("POLICY_BUILDS_DIR") or HERE.parent / "policy_eval" / "builds"
)  # pipeline builds (build_rules.py); used when present
TASK_SETS = HERE.parent / "policy_eval" / "policy_eval_tasks.json"
SECRET_KEYS = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENROUTER_API_KEY")
sys.path.insert(0, str(HERE.parent))
import policy_pilot_costs as costs  # noqa: E402

INFRA_ERRORS = ("RateLimit", "429", "APIConnection", "APITimeout", "403", "team_model_access_denied")


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


async def run_one(task_id: str, arm: str, out_dir: Path, timeout: float) -> Dict[str, Any]:
    sys.path.insert(0, str(HERE))
    from eog_env import EOGTask, load_task

    task = load_task(task_id)
    calls: List[Dict[str, Any]] = []
    env = EOGTask(task, sink=calls.append)
    record: Dict[str, Any] = {
        "task_id": task_id,
        "arm": arm,
        "policy_version": task["_policy_hash"],
        "model": os.environ.get("MODEL_NAME"),
        "tools": task["selected_tools"],
    }
    started = time.monotonic()
    await env.start()
    hooks = None
    extra_hooks: List[Any] = []
    policy_model = None
    gate = None
    try:
        from cuga.sdk import CugaAgent

        if arm == "B":
            from cuga.policy_layer.ruleset import RuleSetHooks

            build_path = BUILDS / f"{task['_policy_hash']}.json"
            built = json.loads(
                (build_path if build_path.exists() else RULES / f"{task['_policy_hash']}.json").read_text()
            )
            record["build"] = str(build_path if build_path.exists() else "legacy rules/")
            sink, env.sink = env.sink, None  # platform-side lookup: not part of the agent's trajectory
            me = await env.call("get_user", {"user_id": env.user_info.get("user_id")})
            env.sink = sink
            principal = {
                "id": env.user_info.get("user_id"),
                "role": (me or {}).get("role") if isinstance(me, dict) else None,
            }
            all_specs = json.loads((HERE / "tasks/itsm_tools.json").read_text())
            choice_path = os.environ.get("POLICY_METHOD_CHOICE")
            method_choice = json.loads(Path(choice_path).read_text()) if choice_path else None
            verifier = policy_model = None
            if any(r.get("type") == "verify" for r in built["rules"]):
                from cuga.policy_layer.llm import openai_json_model
                from cuga.policy_layer.verifier import Verifier

                policy_model = openai_json_model(os.environ.get("POLICY_MODEL_NAME") or "aws/gpt-oss-120b")
                verifier = Verifier(policy_model)
            verifier_for = None
            if verifier is not None and method_choice:
                from cuga.policy_layer.llm import openai_json_model, openrouter_json_model
                from cuga.policy_layer.verifier import Verifier

                cache: Dict[str, Any] = {}

                def verifier_for(name: str) -> Any:  # the measured best model per statement type
                    if name not in cache:
                        m = (
                            openrouter_json_model(name.split(":", 1)[1])
                            if name.startswith("openrouter:")
                            else openai_json_model(name)
                        )
                        cache[name] = Verifier(m)
                    return cache[name]

            extra = {"brief": os.environ["POLICY_BRIEF"] != "0"} if os.environ.get("POLICY_BRIEF") else {}
            if os.environ.get("POLICY_NOTES"):
                extra["note_channel"] = os.environ["POLICY_NOTES"]
            hooks = RuleSetHooks(
                built["rules"],
                all_specs,
                principal=principal,
                tools_in_run=task["selected_tools"],
                method_choice=method_choice,
                verifier=verifier,
                verifier_for=verifier_for,
                **extra,
            )
            extra_hooks = []
            if built.get("procedures"):
                from cuga.policy_layer.model import Procedure, from_json
                from cuga.policy_layer.procedure_monitor import ProcedureMonitor

                extra_hooks.append(
                    ProcedureMonitor(
                        [from_json(Procedure, p) for p in built["procedures"]],
                        tools_in_run=task["selected_tools"],
                    )
                )
            record["rules"] = len(built["rules"])
            record["principal_role"] = principal["role"]
        if (
            os.environ.get("POLICY_DELIVERABLES") == "1"
        ):  # request checklist checked at the reply (either arm)
            from cuga.policy_layer.deliverables import DeliverablesHooks
            from cuga.policy_layer.llm import openai_json_model as _jm

            dspecs = json.loads((HERE / "tasks/itsm_tools.json").read_text())
            dspecs = [t for t in dspecs if t["name"] in set(task["selected_tools"])]
            extra_hooks.append(
                DeliverablesHooks(
                    _jm(os.environ.get("POLICY_MODEL_NAME") or "aws/gpt-oss-120b"),
                    dspecs,
                    **(
                        {"note_channel": os.environ["POLICY_NOTES"]} if os.environ.get("POLICY_NOTES") else {}
                    ),
                )
            )
        if (
            os.environ.get("POLICY_TRACKER") == "1"
        ):  # requirements checklist compiled and checked at the reply
            from cuga.policy_layer.tracker import tracker_from_env

            extra_hooks.append(tracker_from_env(policy=task["system_prompt"]))
        if (
            os.environ.get("POLICY_GATE_SOP") == "1"
        ):  # must-not check at write time over the policy text (no graph)
            from cuga.policy_layer.llm import openai_json_model as _gm
            from cuga.policy_layer.store_gate import StoreGate

            gate_name = os.environ.get("POLICY_GATE_MODEL") or "aws/gpt-oss-120b"
            gate = StoreGate(
                None,
                _gm(gate_name, timeout=180, max_tokens=16000 if "gpt-oss" in gate_name else 4000),
                sop_text=task["system_prompt"],
            )
            gate.reads.append(f"user request: {task['user_prompt']}")  # the request is part of the case data
            extra_hooks.append(gate)
            record["gate_model"] = gate_name
        loop = rec = None
        if os.environ.get("SOP_LOOP") == "1":  # SOP-aware loop over the policy's procedures and general rules
            from cuga.policy_layer.llm import openai_json_model as _ojm
            from cuga.policy_layer.sop_loop import LoopHooks, SopLoop

            bp = BUILDS / f"{task['_policy_hash']}.json"
            procs = (json.loads(bp.read_text()).get("procedures") or []) if bp.exists() else []
            rec = LoopHooks()
            extra_hooks.insert(0, rec)
            loop = SopLoop(
                _ojm(
                    os.environ.get("POLICY_LOOP_MODEL") or "azure/DeepSeek-V4-Pro",
                    timeout=300,
                    max_tokens=8000,
                ),
                procs,
                rules_from_data=False,
            )
        from helpers.app_tools_provider import AppToolsProvider

        agent = CugaAgent(
            tool_provider=AppToolsProvider(env.langchain_tools(), lambda t: env.app_name()),  # real app name
            special_instructions=task["system_prompt"],
            hooks=([h for h in [hooks] + extra_hooks if h is not None]) or None,
            cuga_folder=str(out_dir / ".cuga" / f"{arm}_{task_id[-8:]}"),
            auto_load_policies=False,
            filesystem_sync=False,
            enable_knowledge=False,
        )
        if loop is not None:
            result = await loop.run(agent, task["user_prompt"], f"eog-{arm}-{task_id}", rec, timeout)
            record["sop_loop"] = loop.log
            record["loop_receipts"] = loop.receipts[:-1]
            record["loop_usage"] = dict(getattr(loop.model, "usage", {}) or {})
        else:
            result = await asyncio.wait_for(
                agent.invoke(task["user_prompt"], thread_id=f"eog-{arm}-{task_id}"), timeout=timeout
            )
        if os.environ.get("POLICY_ORACLE") in (
            "1",
            "names",
        ):  # upper bound: the grader's failed checks go back
            record["oracle_rounds"], record["oracle_receipts"] = [], []
            for rnd in range(2):
                g = await env.grade()
                bad = [(v, env.task["verifiers"][i]) for i, v in enumerate(g["verifiers"]) if not v["passed"]]
                record["oracle_rounds"].append({"round": rnd + 1, "failed": [v["name"] for v, _ in bad]})
                if not bad:
                    break
                if (
                    os.environ["POLICY_ORACLE"] == "names"
                ):  # which check failed and the table, without the SQL condition
                    lines = [
                        f"{v['name']} (table: "
                        + ", ".join(
                            sorted(set(re.findall(r"\b(?:FROM|JOIN)\s+([a-z_]+)", json.dumps(t), re.I)))
                        )
                        + ")"
                        for v, t in bad
                    ]
                else:
                    lines = [
                        f"{v['name']}: "
                        + " ".join(re.findall(r'"query":\s*"(.*?)(?<!\\)"', json.dumps(t)))[:500]
                        for v, t in bad
                    ]
                if getattr(result, "receipt", None) is not None:
                    record["oracle_receipts"].append(result.receipt.model_dump(exclude={"tool_timings"}))
                result = await asyncio.wait_for(
                    agent.invoke(
                        ORACLE_INTRO + "\n" + "\n".join(f"- {x}" for x in lines),
                        thread_id=f"eog-{arm}-{task_id}",
                    ),
                    timeout=timeout,
                )
        record["answer"] = result.answer
        record["error"] = result.error
        record["hook_events"] = len(getattr(result, "hook_events", None) or [])
        receipt = getattr(result, "receipt", None)
        if receipt is not None:
            record["receipt"] = receipt.model_dump(exclude={"tool_timings"})
    except asyncio.TimeoutError:
        record["error"] = f"timeout after {timeout:.0f}s"
    except Exception as exc:  # noqa: BLE001 - grade whatever state the agent left
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["wall_s"] = round(time.monotonic() - started, 1)
    record["trajectory"] = save_trajectory(out_dir, f"{arm}_{task_id}")
    try:
        record.update(await env.grade())
    finally:
        env.close()
    record["tool_calls"] = calls
    record["gate"] = (hooks.records if hooks else []) + [
        r for h in extra_hooks for r in getattr(h, "records", [])
    ]
    record["policy_usage"] = (
        {**dict(getattr(policy_model, "usage", {}) or {}), "model": getattr(policy_model, "model_name", None)}
        if policy_model
        else {}
    )
    for h in extra_hooks:
        if type(h).__name__ == "RequirementsTracker":
            record["tracker_usage"] = dict(getattr(h.model, "usage", {}) or {})
            record["tracker_model"] = getattr(h.model, "model_name", None)
    for h in extra_hooks:  # the deliverables hook's own policy-model calls, for the cost ledger
        if type(h).__name__ == "DeliverablesHooks":
            pu = record["policy_usage"]
            pu.setdefault("model", getattr(h.model, "model_name", None))
            for k, v in (getattr(h.model, "usage", {}) or {}).items():
                pu[k] = pu.get(k, 0) + v if isinstance(v, (int, float)) else pu.get(k, v)
    if gate is not None:
        record["gate_usage"] = {**dict(getattr(gate.model, "usage", {}) or {}), "model": record["gate_model"]}
    record["trial"] = os.environ.get("POLICY_EVAL_TRIAL")
    return record


def child_env() -> Dict[str, str]:
    from dotenv import dotenv_values

    env = dict(os.environ)
    secrets = dotenv_values(EVAL_ROOT / ".env")
    for key in SECRET_KEYS:
        if secrets.get(key) and key not in env:
            env[key] = secrets[key]
    env_file = HERE / os.environ.get(
        "CUGA_ENV_FILE", "cuga.env"
    )  # e.g. cuga.gptoss.env for the gpt-oss agent
    env["ENV_FILE"] = str(env_file)
    for line in env_file.read_text().splitlines():  # also set directly: cuga reads some at import
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip())
    env["PYTHONUNBUFFERED"] = "1"
    return env


def is_done(path: Path) -> bool:
    if not path.exists():
        return False
    error = json.loads(path.read_text()).get("error") or ""
    return not any(m in error for m in INFRA_ERRORS)


async def run_many(jobs: List[tuple], args: argparse.Namespace) -> None:
    run_dir = RESULTS / args.run
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    todo = [(t, a) for t, a in jobs if not is_done(run_dir / f"{a}_{t}.json")]
    print(f"{len(jobs)} runs, {len(jobs) - len(todo)} done, {len(todo)} to run (-j {args.jobs})")
    env = child_env()
    sem = asyncio.Semaphore(args.jobs)

    async def one(task_id: str, arm: str) -> None:
        async with sem:
            name = f"{arm}_{task_id}"
            if costs.over_budget():
                print(f"SKIP {name}: budget reached ({costs.line()})")
                return
            with open(run_dir / "logs" / f"{name}.log", "w") as log:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    __file__,
                    "--child",
                    task_id,
                    "--arm",
                    arm,
                    "--run",
                    args.run,
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
                denies = sum(
                    g.get("outcome") == "deny" or bool(g.get("grounded") and not g.get("repeat"))
                    for g in r.get("gate", [])
                )
                c = costs.record("eog", name, agent=r.get("receipt"), policy=r.get("policy_usage"))
                for rc in r.get("oracle_receipts") or []:  # earlier rounds of the oracle arm
                    c += costs.record("eog_oracle_round", name, agent=rc)
                for rc in r.get("loop_receipts") or []:  # earlier turns of the SOP loop
                    c += costs.record("eog_loop_turn", name, agent=rc)
                if r.get("loop_usage"):
                    c += costs.record(
                        "eog_loop_questions",
                        name,
                        policy={
                            **r["loop_usage"],
                            "model": os.environ.get("POLICY_LOOP_MODEL") or "azure/DeepSeek-V4-Pro",
                        },
                    )
                if r.get("gate_usage"):  # the write-time SOP gate's own model calls
                    c += costs.record("eog_gate", name, policy=r["gate_usage"])
                if r.get("tracker_usage"):  # the tracker may use another model than the policy layer
                    c += costs.record(
                        "eog_tracker", name, policy={**r["tracker_usage"], "model": r.get("tracker_model")}
                    )
                print(
                    f"{'PASS' if r.get('passed') else 'fail'} {name} {r.get('verifiers_passed')}/{r.get('verifiers_total')} "
                    f"{r['wall_s']}s denies={denies} ${c:.2f} [{costs.line()}] {r.get('error') or ''}"
                )
            else:
                print(f"CRASH {name} (see logs/{name}.log)")

    await asyncio.gather(*(one(t, a) for t, a in todo))
    summarize(run_dir)


def summarize(run_dir: Path) -> None:
    rows = [json.loads(p.read_text()) for p in sorted(run_dir.glob("*.json"))]
    if not rows:
        return
    print(
        f"\n{'arm':<4}{'n':>3}{'pass':>6}{'verifiers':>11}{'denies':>8}{'errors':>8}{'tok in':>11}{'tok out':>9}"
    )
    for arm in sorted({r["arm"] for r in rows}):
        rs = [r for r in rows if r["arm"] == arm]
        vp = sum(r.get("verifiers_passed", 0) for r in rs)
        vt = sum(r.get("verifiers_total", 0) for r in rs)
        tin = sum((r.get("receipt") or {}).get("input_tokens", 0) for r in rs)
        tout = sum((r.get("receipt") or {}).get("output_tokens", 0) for r in rs)
        print(
            f"{arm:<4}{len(rs):>3}{sum(bool(r.get('passed')) for r in rs):>6}{f'{vp}/{vt}':>11}"
            f"{sum(g.get('outcome') == 'deny' or bool(g.get('grounded') and not g.get('repeat')) for r in rs for g in r.get('gate', [])):>8}"
            f"{sum(bool(r.get('error')) for r in rs):>8}{tin:>11,}{tout:>9,}"
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true", help="the 5 tasks in tasks/pilot.json")
    ap.add_argument("--tasks", help="comma-separated task ids")
    ap.add_argument(
        "--set", choices=["tune", "unseen", "xref"], help="ITSM task set from policy_eval_tasks.json"
    )
    ap.add_argument("--trial", type=int, help="trial number (recorded; use one --run per trial)")
    ap.add_argument("--arms", default="A,B")
    ap.add_argument("--run", required=True)
    ap.add_argument("-j", "--jobs", type=int, default=2)
    ap.add_argument("--timeout", type=float, default=1200)
    ap.add_argument("--child", help=argparse.SUPPRESS)
    ap.add_argument("--arm", help=argparse.SUPPRESS)
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()
    if args.summary:
        summarize(RESULTS / args.run)
        return
    if args.child:
        run_dir = RESULTS / args.run
        rec = asyncio.run(run_one(args.child, args.arm, run_dir, args.timeout))
        (run_dir / f"{args.arm}_{args.child}.json").write_text(json.dumps(rec, indent=2, default=str))
        return
    ids: List[str] = []
    if args.pilot:
        ids += [p["task_id"] for p in json.loads((HERE / "tasks/pilot.json").read_text())["tasks"]]
    if args.tasks:
        ids += [t.strip() for t in args.tasks.split(",") if t.strip()]
    if args.set:
        ids += json.loads(TASK_SETS.read_text())["itsm"][args.set]
    if args.trial is not None:
        os.environ["POLICY_EVAL_TRIAL"] = str(args.trial)
    if not ids:
        ap.error("give --pilot, --tasks or --set")
    arms = [a.strip() for a in args.arms.split(",")]
    asyncio.run(run_many([(t, a) for t in ids for a in arms], args))


if __name__ == "__main__":
    main()
