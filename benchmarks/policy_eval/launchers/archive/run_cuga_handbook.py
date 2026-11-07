#!/usr/bin/env python3
"""Run CUGA on HANDBOOK.md tasks and grade them with each task's own rubric verifier.

HANDBOOK.md ships a Harbor + OpenHands harness that runs the agent inside the task container. CUGA runs on the
host instead; per task and trial this script:
  1. starts the task container (image ``handbook_task:<task>``, built from the task's environment/Dockerfile on
     ``handbook_base`` = Dockerfile.base here) with the task.toml environment variables;
  2. starts the task's MCP proxy in it (``/app/scripts/start.sh --method http --port 8000``, as the harness does)
     and a TCP forwarder (the proxy binds 127.0.0.1 only) on a published port;
  3. loads the MCP tools on the host (langchain-mcp-adapters), logs every call, and shows them to CUGA under their
     app names (``google_mail__send_email`` -> app ``google_mail``) through ``helpers.app_tools_provider``;
  4. runs CugaAgent with special_instructions = system_prompt.md and the user message = instruction.md
     (as the harness: tool-call cap 200 is the harness's; CUGA's own caps come from the env file);
  5. copies the task's tests/ into the container, runs tests/test.sh (the task's sop_verifier.py) and reads
     /tests/results.json: one pass/fail per rubric item.
Hooks: POLICY_DELIVERABLES=1 adds policy_layer.deliverables.DeliverablesHooks; HOOKS_MODULE=/path/file.py:factory
adds whatever ``factory(ctx)`` returns (a hook or a list), with ctx = {task, task_dir, instruction, system_prompt,
tool_specs, workspace_files}. The sample is downloaded content: files are only read here; the agent's code tools
(executeBash, executePython) run inside the container.

  CUGA_SRC=~/dev/cuga_snapshots/<snap>/src ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/handbook/run_cuga_handbook.py \
      --tasks all --run hb_A_t1 --arm A --trial 1 -j 3
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import json
import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
EVAL_ROOT = BENCH.parent
SAMPLE = Path(os.environ.get("HANDBOOK_SAMPLE", str(Path.home() / "dev/untrusted/handbook-sample")))
TASKS = SAMPLE / "tasks"
RESULTS = HERE / "results"
SECRET_KEYS = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENROUTER_API_KEY")
TOOL_LOG_LIMIT = 4000
if os.environ.get("CUGA_SRC"):  # -I ignores PYTHONPATH: put the code snapshot first by hand
    if not Path(os.environ["CUGA_SRC"]).is_dir():  # else cuga would silently resolve to the live gate tree
        raise SystemExit(f"no snapshot {os.environ['CUGA_SRC']}")
    sys.path.insert(0, os.environ["CUGA_SRC"])
sys.path.insert(0, str(BENCH))
import policy_pilot_costs as costs  # noqa: E402
from handbook.sop_text import html_text, largest_sop_file  # noqa: E402


def task_names(spec: str) -> List[str]:
    names = sorted(p.name for p in TASKS.iterdir() if (p / "task.toml").exists())
    if spec == "all":
        return names
    want = [s.strip() for s in spec.split(",") if s.strip()]
    return [n for n in names if any(n == w or n.startswith(w) for w in want)]


def image(task: str) -> str:
    return f"handbook_task:{task.lower()[:60]}"


def sh(cmd: List[str], timeout: float = 120, check: bool = True) -> subprocess.CompletedProcess:
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and out.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:4])} failed ({out.returncode}): {out.stderr[-500:]}")
    return out


# ── container ────────────────────────────────────────────────────────────────


def start_container(task: str, name: str) -> int:
    cfg = tomllib.loads((TASKS / task / "task.toml").read_text())
    env = (cfg.get("environment") or {}).get("env") or {}
    sh(["docker", "rm", "-f", name], check=False)
    cmd = ["docker", "run", "-d", "--name", name, "-p", "127.0.0.1::8001"]
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    sh(cmd + [image(task), "sleep", "infinity"])
    sh(["docker", "cp", str(HERE / "tcp_forward.py"), f"{name}:/tmp/tcp_forward.py"])
    sh(
        [
            "docker",
            "exec",
            "-d",
            name,
            "bash",
            "-c",
            "mkdir -p /logs/agent && nohup /app/scripts/start.sh --method http --port 8000 </dev/null >>/logs/agent/mcp-proxy.log 2>&1 &",
        ]
    )
    sh(["docker", "exec", "-d", name, "python3", "/tmp/tcp_forward.py", "8001", "8000"])  # noqa: S108 - path inside the container
    port = int(sh(["docker", "port", name, "8001/tcp"]).stdout.strip().rsplit(":", 1)[1])
    import urllib.request

    for _ in range(90):
        with contextlib.suppress(Exception):  # not up yet
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    return port
        time.sleep(2)
    raise RuntimeError("MCP proxy did not become healthy in 180 s")


def grade(task: str, name: str) -> Dict[str, Any]:
    sh(["docker", "exec", name, "rm", "-rf", "/tests"], check=False)
    sh(["docker", "cp", str(TASKS / task / "tests"), f"{name}:/tests"])
    run = sh(["docker", "exec", name, "bash", "/tests/test.sh"], timeout=900, check=False)
    got = sh(["docker", "exec", name, "cat", "/tests/results.json"], check=False)
    try:
        res = json.loads(got.stdout)
    except ValueError:
        return {"grader_error": (run.stdout + run.stderr)[-2000:]}
    rubrics = {r["id"]: r for r in json.loads((TASKS / task / "tests/rubrics.json").read_text())}
    items = [
        {
            "id": r["id"],
            "pass": r.get("pass"),
            "text": (rubrics.get(r["id"]) or {}).get("rubric_text", "")[:300],
            "feedback": str(r.get("feedback", ""))[:300],
        }
        for r in res.get("rubric_results") or []
    ]
    return {
        "passed": res.get("passed"),
        "rubrics_passed": res.get("rubrics_passed"),
        "rubrics_total": res.get("rubrics_total"),
        "score": res.get("score"),
        "rubrics": items,
    }


# ── agent (child process) ────────────────────────────────────────────────────


def _trunc(value: Any) -> Any:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= TOOL_LOG_LIMIT else text[:TOOL_LOG_LIMIT] + f"... [{len(text)} chars]"


def input_model(name: str, schema: Any) -> Any:
    """A pydantic input model from an MCP tool's JSON schema (CUGA reads ``args_schema.model_fields``), with the same
    type mapping CUGA's registry provider uses."""
    from typing import Optional

    from pydantic import BaseModel, Field, create_model

    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema
    from cuga.backend.tools_env.registry.utils.schema_utils import python_type_for_schema

    props = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or [])
    fields: Dict[str, Any] = {}
    for pname, ps in props.items():
        typ = python_type_for_schema(ps)
        desc = ps.get("description", "")
        if pname in required:
            fields[pname] = (typ, Field(..., description=desc))
        else:
            default = ps.get("default")
            fields[pname] = (
                Optional[typ],
                Field(default=None if isinstance(default, (list, dict)) else default, description=desc),
            )
    return create_model(f"{name}Input", **fields)


def unwrap(out: Any) -> Any:
    """MCP results come as content blocks; text blocks are joined into the plain text the server sent."""
    if isinstance(out, list) and out and all(isinstance(b, dict) and b.get("type") == "text" for b in out):
        return "\n".join(str(b.get("text", "")) for b in out)
    return out


def logged_tools(tools: List[Any], log: List[Dict[str, Any]]) -> List[Any]:
    from langchain_core.tools import StructuredTool

    def wrap(t: Any) -> Any:
        async def _call(**kwargs: Any) -> Any:
            started = time.monotonic()
            try:
                out = unwrap(await t.ainvoke(kwargs))
            except Exception as exc:  # noqa: BLE001 - a tool error is returned to the agent, as in the other runners
                out = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
            log.append(
                {
                    "tool": t.name,
                    "args": kwargs,
                    "result": _trunc(out),
                    "s": round(time.monotonic() - started, 2),
                }
            )
            return out

        model = input_model(t.name, t.args_schema)

        async def _call_set(
            **kwargs: Any,
        ) -> Any:  # schema defaults are not part of the call (as the hooks wrapper)
            return await _call(**{k: v for k, v in kwargs.items() if v is not None})

        return StructuredTool.from_function(
            coroutine=_call_set, name=t.name, description=t.description or "", args_schema=model
        )

    return [wrap(t) for t in tools]


def specs_of(tools: List[Any]) -> List[Dict[str, Any]]:
    out = []
    for t in tools:
        schema = (
            t.args_schema
            if isinstance(t.args_schema, dict)
            else (t.args_schema.model_json_schema() if t.args_schema else {})
        )
        out.append({"name": t.name, "description": t.description or "", "inputSchema": schema})
    return out


def build_hooks(ctx: Dict[str, Any]) -> List[Any]:
    hooks: List[Any] = []
    if os.environ.get("POLICY_DELIVERABLES") == "1":
        from cuga.policy_layer.deliverables import DeliverablesHooks
        from cuga.policy_layer.llm import openai_json_model

        hooks.append(
            DeliverablesHooks(
                openai_json_model(os.environ.get("POLICY_MODEL_NAME") or "aws/gpt-oss-120b"),
                ctx["tool_specs"],
                **({"note_channel": os.environ["POLICY_NOTES"]} if os.environ.get("POLICY_NOTES") else {}),
            )
        )
    if os.environ.get("HOOKS_MODULE"):
        path, _, factory = os.environ["HOOKS_MODULE"].partition(":")
        spec = importlib.util.spec_from_file_location("handbook_hooks_module", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        made = getattr(mod, factory or "make_hooks")(ctx)
        hooks.extend(made if isinstance(made, list) else [made])
    return hooks


def save_trajectory(out_dir: Path, name: str) -> Any:
    try:
        from cuga.backend.activity_tracker.tracker import ActivityTracker

        tr = ActivityTracker()
        steps = [
            s.model_dump() if hasattr(s, "model_dump") else getattr(s, "__dict__", str(s))
            for s in (tr.steps or [])
        ]
        path = out_dir / "trajectories" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"intent": tr.intent, "task": name, "steps": steps}, default=str))
        return str(path)
    except Exception as exc:  # noqa: BLE001
        return f"not saved: {type(exc).__name__}: {exc}"


async def run_one(task: str, run: str, arm: str, timeout: float) -> Dict[str, Any]:
    out_dir = RESULTS / run
    tdir = TASKS / task
    instruction = (tdir / "instruction.md").read_text()
    system_prompt = (tdir / "system_prompt.md").read_text()
    cfg = tomllib.loads((tdir / "task.toml").read_text())
    now = ((cfg.get("environment") or {}).get("env") or {}).get("HANDBOOK_CURRENT_TIME", "")
    cname = f"hb_{run}_{task[-8:]}".replace("/", "_")
    record: Dict[str, Any] = {
        "task": task,
        "arm": arm,
        "run": run,
        "trial": os.environ.get("POLICY_EVAL_TRIAL"),
        "model": os.environ.get("MODEL_NAME"),
        "world_time": now,
        "container": cname,
    }
    started = time.monotonic()
    tool_log: List[Dict[str, Any]] = []
    hooks: List[Any] = []
    store = None
    try:
        port = start_container(task, cname)
        record["mcp_port"] = port
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient(
            {"handbook": {"url": f"http://127.0.0.1:{port}/mcp", "transport": "streamable_http"}}
        )
        raw = await client.get_tools()
        tools = logged_tools(raw, tool_log)
        store = None
        store_path = Path(os.environ.get("POLICY_STORE_DIR", "/nonexistent")) / f"{task}.json"
        if store_path.exists():  # the SOP as a procedure graph, queried through policy__ tools
            from cuga.policy_layer.procedure_store import POLICY_TOOLS_NOTE, ProcedureStore, policy_tools

            store = ProcedureStore.load(str(store_path))
            tools = tools + logged_tools(policy_tools(store), tool_log)
            system_prompt = f"{system_prompt}\n\n{POLICY_TOOLS_NOTE}"
            record["policy_store"] = str(store_path)
        record["n_tools"] = len(tools)
        app_of = lambda t: t.name.split("__", 1)[0] if "__" in t.name else "handbook"  # noqa: E731
        record["apps"] = sorted({app_of(t) for t in tools})
        ctx = {
            "task": task,
            "task_dir": str(tdir),
            "instruction": instruction,
            "system_prompt": system_prompt,
            "tool_specs": specs_of(raw),
            "world_time": now,
            "workspace_files": sorted(p.name for p in (tdir / "environment/initial_workspace").iterdir()),
        }
        hooks = build_hooks(ctx)
        if store is not None and os.environ.get("POLICY_STORE_GATE") == "1":
            from cuga.policy_layer.llm import openai_json_model
            from cuga.policy_layer.store_gate import StoreGate

            hooks.append(
                StoreGate(
                    store,
                    openai_json_model(
                        os.environ.get("POLICY_GATE_MODEL") or "gcp/gemini-3.8-flash",
                        timeout=180,
                        max_tokens=4000,
                    ),
                    today=(now or "")[:10],
                )
            )
        if (
            store is None and os.environ.get("POLICY_GATE_SOP") == "1"
        ):  # ablation: the gate over the raw SOP text
            from cuga.policy_layer.llm import openai_json_model
            from cuga.policy_layer.store_gate import StoreGate

            sop_file = largest_sop_file(tdir)
            if sop_file is not None:
                hooks.append(
                    StoreGate(
                        None,
                        openai_json_model(
                            os.environ.get("POLICY_GATE_MODEL") or "gcp/gemini-3.8-flash",
                            timeout=180,
                            max_tokens=4000,
                        ),
                        today=(now or "")[:10],
                        sop_text=html_text(sop_file.read_text(errors="replace")),
                    )
                )
                record["gate_sop"] = sop_file.name
        for removed in filter(
            os.environ.get, ("POLICY_STORE_VERIFY", "POLICY_VERIFIER_MODEL")
        ):  # removed (change 137)
            if os.environ[removed] != "0":
                raise SystemExit(
                    f"{removed} was removed with the end verifier: the obligation ledger replaces it"
                )
        loop = rec = None
        if (
            os.environ.get("SOP_LOOP") == "1"
        ):  # SOP-aware loop (policy_layer.sop_loop): phases + typed questions
            from cuga.policy_layer.llm import openai_json_model
            from cuga.policy_layer.sop_loop import LoopHooks, SopLoop

            build = (
                HERE.parent
                / "policy_eval/builds_handbook"
                / os.environ.get("HB_BUILDS", "v3")
                / f"{task}.json"
            )
            procs = json.loads(build.read_text())["build"].get("procedures") or [] if build.exists() else []
            rec = LoopHooks()
            hooks = [rec] + hooks
            loop = SopLoop(
                openai_json_model(
                    os.environ.get("POLICY_LOOP_MODEL") or "azure/DeepSeek-V4-Pro",
                    timeout=300,
                    max_tokens=8000,
                ),
                procs,
                **(  # advisory / discovery mode + evidence-gated decisions (newer snapshots only)
                    {"mode": os.environ["SOP_LOOP_MODE"], "require_evidence": True}
                    if os.environ.get("SOP_LOOP_MODE")
                    else {}
                ),
                **({"index": _sop_index(build)} if os.environ.get("SOP_LOOP_MODE") == "discovery" else {}),
            )
        record["hooks"] = [type(h).__name__ for h in hooks]

        from cuga.backend.activity_tracker.tracker import ActivityTracker
        from cuga.sdk import CugaAgent
        from helpers.app_tools_provider import AppToolsProvider

        ActivityTracker().current_date = now or None
        agent = CugaAgent(
            tool_provider=AppToolsProvider(tools, app_of),
            special_instructions=system_prompt,
            cuga_folder=str(out_dir / ".cuga" / f"{arm}_{task[-8:]}"),
            auto_load_policies=False,
            filesystem_sync=False,
            enable_knowledge=False,
            **({"hooks": hooks} if hooks else {}),
        )
        try:
            if loop is not None:
                result = await loop.run(agent, instruction, f"hb-{run}-{task}", rec, timeout)
                record["sop_loop"] = loop.log
                record["loop_receipts"] = loop.receipts[:-1]  # the last turn's receipt is record["receipt"]
                record["loop_usage"] = dict(getattr(loop.model, "usage", {}) or {})
            else:
                result = await asyncio.wait_for(
                    agent.invoke(instruction, thread_id=f"hb-{run}-{task}"), timeout=timeout
                )
            record["answer"] = result.answer
            record["error"] = result.error
            receipt = getattr(result, "receipt", None)
            if receipt is not None:
                record["receipt"] = receipt.model_dump(exclude={"tool_timings"})
        except asyncio.TimeoutError:
            record["error"] = f"timeout after {timeout:.0f}s"
        except Exception as exc:  # noqa: BLE001 - grade whatever state the agent left
            record["error"] = f"{type(exc).__name__}: {exc}"
        record["wall_s"] = round(time.monotonic() - started, 1)
        record["trajectory"] = save_trajectory(out_dir, f"{arm}_{task}")
        record.update(grade(task, cname))
    except Exception as exc:  # noqa: BLE001 - infrastructure failure: no grade
        record["error"] = f"infra: {type(exc).__name__}: {exc}"
        record["wall_s"] = round(time.monotonic() - started, 1)
    finally:
        record["tool_calls"] = tool_log
        record["gate"] = [r for h in hooks for r in getattr(h, "records", [])]
        if store is not None:
            record["policy_store_calls"] = store.calls
        usage: Dict[str, Any] = {}
        for h in hooks:  # policy-model calls of the hooks, for the cost ledger
            model = getattr(h, "model", None)
            for k, v in (getattr(model, "usage", {}) or {}).items():
                usage[k] = usage.get(k, 0) + v if isinstance(v, (int, float)) else usage.get(k, v)
            if getattr(model, "model_name", None):
                usage.setdefault("model", model.model_name)
        record["policy_usage"] = usage
        if os.environ.get("KEEP_CONTAINER") != "1":
            sh(["docker", "rm", "-f", cname], check=False)
    return record


# ── parent ───────────────────────────────────────────────────────────────────


def _sop_index(build: Path) -> Any:
    """SOP long-document discovery index (policy_layer.sop_retrieval); Kev re-ranks when an OpenRouter key is set."""
    from cuga.policy_layer.sop_retrieval import SopIndex

    ask = None
    if os.environ.get("OPENROUTER_API_KEY"):
        from cuga.policy_layer.detectors import systemone_questions

        ask = systemone_questions()
    return SopIndex(json.loads(build.read_text()), ask=ask)


def child_env() -> Dict[str, str]:
    from dotenv import dotenv_values

    env = dict(os.environ)
    secrets = dotenv_values(EVAL_ROOT / ".env")
    for key in SECRET_KEYS:
        if secrets.get(key) and key not in env:
            env[key] = secrets[key]
    env["ENV_FILE"] = str(HERE / os.environ.get("CUGA_ENV_FILE", "cuga.fc.dsv4.env"))
    return env


def is_done(path: Path) -> bool:
    if not path.exists():
        return False
    r = json.loads(path.read_text())
    return r.get("rubrics_total") is not None and not str(r.get("error") or "").startswith("infra")


async def run_many(names: List[str], args: argparse.Namespace) -> None:
    run_dir = RESULTS / args.run
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    todo = [n for n in names if not is_done(run_dir / f"{n}.json")]
    print(
        f"{len(names)} tasks, {len(names) - len(todo)} done, {len(todo)} to run (-j {args.jobs})", flush=True
    )
    env = child_env()
    sem = asyncio.Semaphore(args.jobs)

    async def one(name: str) -> None:
        async with sem:
            if costs.over_budget():
                print(f"SKIP {name}: budget reached ({costs.line()})", flush=True)
                return
            with open(run_dir / "logs" / f"{name}.log", "w") as log:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-I",
                    __file__,
                    "--child",
                    name,
                    "--run",
                    args.run,
                    "--arm",
                    args.arm,
                    "--timeout",
                    str(args.timeout),
                    cwd=HERE,
                    env=env,
                    stdout=log,
                    stderr=asyncio.subprocess.STDOUT,
                )
                try:
                    await asyncio.wait_for(proc.wait(), timeout=args.timeout + 1200)
                except asyncio.TimeoutError:
                    proc.kill()
            path = run_dir / f"{name}.json"
            if path.exists():
                r = json.loads(path.read_text())
                c = costs.record(
                    f"handbook_{args.arm}",
                    f"{args.run}/{name}",
                    agent=r.get("receipt"),
                    policy=r.get("policy_usage"),
                )
                for rc in r.get("loop_receipts") or []:  # earlier turns of the SOP loop
                    c += costs.record("handbook_loop_turn", f"{args.run}/{name}", agent=rc)
                if r.get("loop_usage"):
                    c += costs.record(
                        "handbook_loop_questions",
                        f"{args.run}/{name}",
                        policy={
                            **r["loop_usage"],
                            "model": os.environ.get("POLICY_LOOP_MODEL") or "azure/DeepSeek-V4-Pro",
                        },
                    )
                print(
                    f"{name}: rubrics {r.get('rubrics_passed')}/{r.get('rubrics_total')} score={r.get('score')} "
                    f"{r.get('wall_s')}s {len(r.get('tool_calls') or [])} calls ${c:.2f} [{costs.line()}] {r.get('error') or ''}",
                    flush=True,
                )
            else:
                print(f"CRASH {name} (see logs/{name}.log)", flush=True)

    await asyncio.gather(*(one(n) for n in todo))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="all", help="'all' or comma-separated task names (prefixes allowed)")
    ap.add_argument("--run", required=True)
    ap.add_argument(
        "--arm", default="A", help="label only; hooks come from POLICY_DELIVERABLES / HOOKS_MODULE"
    )
    ap.add_argument("--trial", type=int)
    ap.add_argument("-j", "--jobs", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=3600, help="agent time per task (task.toml: 3600)")
    ap.add_argument("--child", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.trial is not None:
        os.environ["POLICY_EVAL_TRIAL"] = str(a.trial)
    if a.child:
        rec = asyncio.run(run_one(a.child, a.run, a.arm, a.timeout))
        (RESULTS / a.run / f"{a.child}.json").write_text(json.dumps(rec, indent=2, default=str))
        return
    names = task_names(a.tasks)
    if not names:
        ap.error(f"no task matches {a.tasks!r} in {TASKS}")
    asyncio.run(run_many(names, a))


if __name__ == "__main__":
    main()
