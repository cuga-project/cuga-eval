#!/usr/bin/env python3
"""One runner: a benchmark, a profile and a task set give one result file per task, in the common schema.

  ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/harness/run.py \
      --bench automationbench --profile automationbench-gptoss-b4tf --set ab-policy-types-holdout \
      --snapshot stable-ba8474dd6 --trial 1 --run ph_B4TF -j 5

The results are in ``harness/results/<run>_t<trial>/``: ``<task>.json`` (``result.py``), ``logs/``, ``trajectories/``, and
``work/<task>/``, the task's working folder, with ``audit.jsonl`` when the profile has a policy (``trace.py`` in the gate repo).
Compare runs with ``report.py``. Arms of an experiment are runs started at the
same time, from one snapshot.

Parent: picks the tasks, starts one child per task in the benchmark's venv, adds each child's usage to the ledger. A task
with a result is skipped, unless the result has no score or ended on a gateway error. A folder holds one code and one profile:
a scored result of another ``code_sha`` or ``profile_hash`` stops the run before any task starts, unless ``--rerun-mismatch``
says to run that task again and replace the file.

Child (one task, its own process, because CUGA keeps process-global state): the adapter prepares the task, the runtime is
built from the profile file and the task's package, the agent runs, the adapter grades.

Rules of the harness:

- A run needs a snapshot under ``~/dev/cuga_snapshots/<name>`` (``snapshot_src.sh``). ``code_sha`` comes from it. A child
  whose ``cuga`` would come from anywhere else refuses to start.
- The experiment is set by the profile file only. Policy switches in the environment are removed for the child.
- ``RuntimeWiringError`` is not a task failure. The task is not run and not graded: the result has ``error`` and no score, the
  report does not count it, and the parent exits with code 2. The same for a task whose policy version has no package, a
  task that cannot be prepared, and a run that ended on a gateway error.
- An agent error or a timeout is graded: the state the agent left is what it did, as in the old runners.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

HARNESS = Path(__file__).resolve().parent
POLICY_EVAL = HARNESS.parent
BENCHMARKS = POLICY_EVAL.parent
EVAL_ROOT = BENCHMARKS.parent
if (
    sys.path and Path(sys.path[0]).resolve() == HARNESS
):  # result.py and report.py are not modules of anything else
    sys.path.pop(0)
if str(BENCHMARKS) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS))

import policy_pilot_costs as costs  # noqa: E402
from policy_eval.envs.compose_env import compose, parse_runner  # noqa: E402
from policy_eval.harness.adapters.automationbench import AutomationBenchAdapter  # noqa: E402
from policy_eval.harness.adapters.base import BenchmarkAdapter, save_trajectory  # noqa: E402
from policy_eval.harness.adapters.handbook import HandbookAdapter  # noqa: E402
from policy_eval.harness.adapters.itsm import CsmAdapter, HrAdapter, ItsmAdapter  # noqa: E402
from policy_eval.harness.adapters.tau2 import Tau2Adapter  # noqa: E402
from policy_eval.harness.result import Result, package_identity  # noqa: E402

RESULTS = HARNESS / "results"
PROFILES = POLICY_EVAL / "profiles"
SNAPSHOTS = Path(os.environ.get("CUGA_SNAPSHOT_ROOT") or Path.home() / "dev/cuga_snapshots")
ADAPTERS = {
    "automationbench": AutomationBenchAdapter,
    "itsm": ItsmAdapter,
    "csm": CsmAdapter,
    "hr": HrAdapter,
    "handbook": HandbookAdapter,
    "tau2": Tau2Adapter,
}
SECRET_KEYS = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENROUTER_API_KEY")
OLD_SWITCHES = ("POLICY_", "SOP_", "HOOKS_", "HB_")
KEPT_SWITCHES = ("POLICY_PILOT_BUDGET",)
# A gateway stopped the agent. A number alone counts (old ITSM list: 401, 403, 408; old report: 502, 503, 504): a false match
# gives "no score" and a rerun, which shows, and a missed one gives a graded failure, which does not. "after 500s" and
# "limit of 135" are no match: a number counts only as a whole word.
INFRA_ERRORS = re.compile(
    r"RateLimit|\b40[138]\b|\b429\b|\b5\d\d\b|InternalServerError|BadGateway|ServiceUnavailable|GatewayTimeout|Server error"
    r"|APIConnection|APITimeout|Request timed out|ReadTimeout|ConnectTimeout|PoolTimeout|Connection error"
    r"|RemoteProtocolError|ECONNREFUSED|team_model_access_denied|retry_proxy"
    r"|litellm\.Timeout|Connection timed out|Server disconnected"
)


class HarnessError(ValueError):
    """The run cannot start, or a child cannot run this task. Nothing is graded."""


# -- what the run stands on ----------------------------------------------------------------------------------------------


def snapshot_src(name: str, root: Optional[Path] = None) -> Path:
    src = (root or SNAPSHOTS) / name / "src"
    if not src.is_dir():
        raise HarnessError(f"no snapshot {src}: create it with policy_eval/snapshot_src.sh {name}")
    return src


def code_sha(src: Path) -> str:
    """From the snapshot's SOURCE.txt: its commit, and when it was taken from a dirty tree, the number of uncommitted
    entries (then the sha alone does not describe the code)."""
    source = src.parent / "SOURCE.txt"
    if not source.is_file():
        raise HarnessError(f"snapshot {src.parent} has no SOURCE.txt: it did not come from snapshot_src.sh")
    words = source.read_text().split()
    if not words:
        raise HarnessError(f"{source} is empty")
    return f"{words[0]}+{words[1]}" if len(words) > 1 and words[1] != "0" else words[0]


def use_snapshot(src: Path) -> None:
    """Put the snapshot first on this process's path and refuse if ``cuga`` still comes from elsewhere. Editable installs in
    two of the venvs point at ``~/dev/cuga-agent``, and ``-I`` makes Python ignore ``PYTHONPATH``."""
    sys.path.insert(0, str(src))
    spec = importlib.util.find_spec("cuga")
    origin = Path(spec.origin).resolve() if spec and spec.origin else None
    if origin is None or not origin.is_relative_to(src.resolve()):
        raise HarnessError(f"cuga would be imported from {origin}, not from the snapshot {src}")


def profile_path(name: str) -> Path:
    path = PROFILES / f"{name}.yaml"
    if not path.is_file():
        known = ", ".join(
            sorted(str(p.relative_to(PROFILES).with_suffix("")) for p in PROFILES.rglob("*.yaml"))
        )
        raise HarnessError(f"no profile {name}; known: {known}")
    return path


def profile_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def safe_name(task: str) -> str:
    """A file name for a task id. τ² ids hold ``|`` and ``[]`` and can pass the length limit of a file name."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", task)
    if safe == task and len(safe) <= 150:
        return safe
    return f"{safe[:150]}.{hashlib.sha256(task.encode()).hexdigest()[:8]}"


def run_folder(run: str, trial: int) -> str:
    return f"{run}_t{trial}"


def is_infra(error: Optional[str]) -> bool:
    return bool(INFRA_ERRORS.search(error or ""))


def is_done(path: Path, sha: str, phash: str, rerun_mismatch: bool = False) -> bool:
    """Does this task need no run? It has a scored result of this code and this profile. A scored result of another one
    raises: skipping it would mix two systems in one folder, which one number then reports. With ``rerun_mismatch`` the task
    runs again, and its file is replaced. A file with no ``code_sha`` or ``profile_hash`` is read as before."""
    if not path.exists():
        return False
    result = Result.from_dict(json.loads(path.read_text()))
    if result.score is None:
        return False
    differs = [
        f"{name} {have}, and this run has {want}"
        for name, have, want in (
            ("code_sha", result.code_sha, sha),
            ("profile_hash", result.profile_hash, phash),
        )
        if have is not None and have != want
    ]
    if not differs:
        return True
    if rerun_mismatch:
        return False
    raise HarnessError(
        f"{path} has {'; '.join(differs)}. A run folder holds one code and one profile: use a new --run, or "
        "--rerun-mismatch to run such tasks again and replace their files"
    )


def package_path(cfg: Any, ctx: Any) -> Optional[Path]:
    """The package of this task: ``{policy}`` filled with the task's policy."""
    if not cfg.package:
        return None
    return POLICY_EVAL / cfg.package.replace("{policy}", ctx.policy_version or "{policy}")


def open_package(cfg: Any, ctx: Any) -> Any:
    """The opened package, or ``None`` when this task's policy has no file: ``build_runtime`` then stops with the task and
    the version. A profile fixed on one policy cannot run on another one."""
    from cuga.policy_layer.package import load_package
    from cuga.policy_layer.runtime import RuntimeWiringError

    path = package_path(cfg, ctx)
    if path is None:
        return None
    if "{policy}" not in cfg.package and ctx.policy_version not in Path(cfg.package).parts:
        raise RuntimeWiringError(
            f"task {ctx.task_id}, policy version {ctx.policy_version}, component package: the profile's package "
            f"{cfg.package} is for another policy"
        )
    return load_package(path) if path.is_file() else None


def env_hash() -> Optional[str]:
    """The composed env file of this child. Two runs with the same code and profile differ if ``base.env`` changed."""
    path = os.environ.get("ENV_FILE")
    if not path or not Path(path).is_file():
        return None
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def agent_timeout(given: Optional[float], adapter: BenchmarkAdapter) -> float:
    """``--timeout``, or what the benchmark has used. One default for all would stop long runs of one benchmark, and
    grade what they left, with no error."""
    return adapter.default_timeout if given is None else given


def package_version(path: Path, pkg: Any) -> str:
    """Which package ran (see ``result.package_identity``: decision tests are not part of it)."""
    return package_identity(path, pkg.version)


def usage_rows(raw: Any, parts: Any) -> Dict[str, Dict[str, Any]]:
    """Usage per component. Each row names its model: the ledger refuses one that does not."""
    rows: Dict[str, Dict[str, Any]] = {}
    if raw.receipts:
        models = [m for r in raw.receipts for m in r.get("models") or []]
        rows["agent"] = {
            "model": models[0] if models else os.environ.get("MODEL_NAME"),
            "calls": len(raw.receipts),
            "input_tokens": sum(r.get("input_tokens", 0) or 0 for r in raw.receipts),
            "output_tokens": sum(r.get("output_tokens", 0) or 0 for r in raw.receipts),
        }
    rows.update(parts.usage())
    rows.update(raw.usage)
    return rows


def component_facts(parts: Any, run_dir: Optional[Path] = None) -> Dict[str, Any]:
    """What components know after the run and the verdict records do not hold. Kept with the trajectory. The audit file is
    named relative to the run folder: an absolute path would show in the scan for paths outside the workspace."""
    facts: Dict[str, Any] = {}
    components = parts.components
    if "navigator" in components:
        facts["navigator_blocks"] = components["navigator"].blocks
    if "procedure_tools" in components:
        facts["procedure_store_calls"] = components["procedure_tools"].calls
    if "intake" in components:
        from cuga.policy_layer.model import to_json

        facts["overlay"] = to_json(components["intake"].overlay)
    if getattr(parts, "audit", None) is not None:
        path = parts.audit.path  # None: it could not be written
        facts["audit_file"] = (
            None if path is None else str(path.relative_to(run_dir) if run_dir else path.name)
        )
        facts["audit_lines"] = len(parts.audit.lines)
        facts["policy_trace_summary"] = parts.trace.summary()  # calls, time and tokens by purpose
    return facts


# -- child: one task -----------------------------------------------------------------------------------------------------


async def run_task(args: argparse.Namespace, adapter: BenchmarkAdapter, run_dir: Path, sha: str) -> Result:
    from cuga.policy_layer.policy_config import load_config
    from cuga.policy_layer.runtime import RuntimeWiringError, build_runtime

    task = args.child
    path = profile_path(args.profile)
    started = time.monotonic()
    result = Result(
        benchmark=adapter.benchmark,
        task=task,
        profile=args.profile,
        trial=args.trial,
        run=run_folder(args.run, args.trial),
        agent_model=os.environ.get("MODEL_NAME"),
        code_sha=sha,
        profile_hash=profile_hash(path),
        env_hash=env_hash(),
    )
    extra: Dict[str, Any] = {}
    try:
        cfg = load_config(path)  # the profile file, and nothing from the environment
        if (
            cfg.checkers.method_choice
        ):  # relative to benchmarks/, as for the old runners: a child runs in its own folder
            cfg.checkers.method_choice = str(BENCHMARKS / cfg.checkers.method_choice)
        result.gate_model = cfg.checkers.gate.model if cfg.checkers.gate.mode == "on" else None
        ctx = await adapter.prepare(task)
        # The level switch reads the agent's model from the context: with no model every task would run at the default level.
        if cfg.control.by_model and not result.agent_model:
            raise RuntimeWiringError(
                "control.by_model is set, and the run names no agent model (MODEL_NAME is empty), so the level cannot be chosen"
            )
        ctx.agent_model = result.agent_model or ""
        result.policy = ctx.policy_version
        pkg = open_package(cfg, ctx)
        result.package_version = package_version(package_path(cfg, ctx), pkg) if pkg is not None else None
        ctx.package_version = (
            result.package_version or ""
        )  # the audit lines name the same version as the result
        ctx.out_dir = run_dir / "work" / safe_name(task)  # the task's own folder: audit.jsonl goes here
        parts = build_runtime(cfg, pkg, ctx)
        raw = await adapter.run(parts, ctx, agent_timeout(args.timeout, adapter))
        result.error = raw.error
        result.usage_by_component = usage_rows(raw, parts)
        result.cost_usd = round(
            sum(costs.usage_cost(row.get("model"), row) for row in result.usage_by_component.values()), 6
        )
        result.verdicts = parts.records()
        extra = {
            "answer": raw.answer,
            "tool_calls": raw.tool_calls,
            **raw.extra,
            **component_facts(parts, run_dir),
        }
        if is_infra(raw.error):
            result.error = f"gateway: {raw.error}"  # the agent was stopped from outside: not a measurement
        else:
            try:
                result.score = await adapter.grade()
            except Exception as exc:  # noqa: BLE001 - a grader that fails is no score, and no 0
                result.error = f"grader: {type(exc).__name__}: {exc}"
    except RuntimeWiringError as exc:
        result.error = f"wiring: {exc}"
    except Exception as exc:  # noqa: BLE001 - it did not run: no score
        result.error = f"not run: {type(exc).__name__}: {exc}"
    finally:
        result.wall_s = round(time.monotonic() - started, 1)
        result.trajectory = save_trajectory(run_dir / "trajectories" / f"{safe_name(task)}.json", task, extra)
        try:
            adapter.close()
        except Exception as exc:  # noqa: BLE001 - the result stands
            print(f"close: {type(exc).__name__}: {exc}", flush=True)
    return result


def child(args: argparse.Namespace) -> None:
    run_dir = RESULTS / run_folder(args.run, args.trial)
    src = snapshot_src(args.snapshot)
    sha = code_sha(src)
    out = run_dir / f"{safe_name(args.child)}.json"
    adapter = ADAPTERS[args.bench](run_dir=run_dir, set_id=args.set, run=run_folder(args.run, args.trial))
    try:
        use_snapshot(src)
    except HarnessError as exc:
        Result(
            benchmark=adapter.benchmark,
            task=args.child,
            profile=args.profile,
            trial=args.trial,
            run=run_dir.name,
            code_sha=sha,
            error=f"not run: {exc}",
        ).write(out)
        raise SystemExit(str(exc)) from exc
    from policy_eval.harness.langfuse_trace import task_trace

    meta = {"run": run_dir.name, "profile": args.profile, "trial": str(args.trial), "set": args.set,
            "model": os.environ.get("MODEL_NAME"), "code_sha": sha, "snapshot": args.snapshot}
    with task_trace(adapter.benchmark, args.child, meta) as trace:
        result = asyncio.run(run_task(args, adapter, run_dir, sha))
        trace.finish(result)
    result.write(out)


# -- parent: many tasks --------------------------------------------------------------------------------------------------


def child_env(adapter: BenchmarkAdapter, args: argparse.Namespace, src: Path) -> Dict[str, str]:
    """The environment of each child: settings from the composed file, keys from cuga-eval/.env, no policy switch."""
    from dotenv import dotenv_values

    env = {
        k: v
        for k, v in os.environ.items()
        if (not k.startswith(OLD_SWITCHES) or k in KEPT_SWITCHES) and not k.startswith("LANGFUSE_")
    }
    secrets = dotenv_values(EVAL_ROOT / ".env")
    for key in SECRET_KEYS:
        if secrets.get(key) and key not in env:
            env[key] = secrets[key]
    if args.proxy:
        env["OPENAI_BASE_URL"] = args.proxy  # automationbench/retry_proxy.py waits out gateway 429s
    extra = dict(adapter.env_extra or {})
    if args.langfuse:  # in the composed file: cuga reloads it with override, and base.env turns tracing off
        extra["DYNACONF_ADVANCED_FEATURES__LANGFUSE_TRACING"] = "true"
    env_file = compose(args.model, adapter.env_bench, extra)
    env["ENV_FILE"] = str(env_file)
    env.update(parse_runner(env_file.read_text(), env_file.name))  # cuga reads some of them at import
    env["PYTHONPATH"] = str(src)
    env["CUGA_SRC"] = str(src)
    env["PYTHONUNBUFFERED"] = "1"
    if args.langfuse:  # the keys of the local Langfuse; without the flag the child gets no LANGFUSE_ variable
        from policy_eval.harness.langfuse_trace import env_for_child

        env.update(env_for_child())
    return env


def record_costs(result: Result, kind: str) -> float:
    """One ledger line per component."""
    total = 0.0
    name = f"{result.run}/{result.task}"
    for component, row in result.usage_by_component.items():
        side = {"agent": {**row, "models": [row.get("model")]}} if component == "agent" else {"policy": row}
        total += costs.record(kind, name, component=component, **side)
    return total


async def run_many(tasks: List[str], adapter: BenchmarkAdapter, args: argparse.Namespace) -> int:
    folder = run_folder(args.run, args.trial)
    run_dir = RESULTS / folder
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    src = snapshot_src(args.snapshot)
    sha, phash = code_sha(src), profile_hash(profile_path(args.profile))
    path = {t: run_dir / f"{safe_name(t)}.json" for t in tasks}
    todo = [t for t in tasks if not is_done(path[t], sha, phash, args.rerun_mismatch)]
    print(
        f"{len(tasks)} tasks, {len(tasks) - len(todo)} done, {len(todo)} to run (-j {args.jobs})", flush=True
    )
    env = child_env(adapter, args, src)
    sem = asyncio.Semaphore(args.jobs)
    not_graded: List[str] = []

    async def one(task: str) -> None:
        async with sem:
            name = safe_name(task)
            if costs.over_budget():
                print(f"SKIP {task}: budget reached ({costs.line()})", flush=True)
                not_graded.append(f"{task}: budget reached")
                return
            work = run_dir / "work" / name
            work.mkdir(parents=True, exist_ok=True)
            started = time.time()
            with open(run_dir / "logs" / f"{name}.log", "w") as log:
                proc = await asyncio.create_subprocess_exec(
                    str(adapter.python),
                    *adapter.python_flags,
                    str(Path(__file__).resolve()),
                    "--child",
                    task,
                    "--bench",
                    args.bench,
                    "--profile",
                    args.profile,
                    "--set",
                    args.set,
                    "--snapshot",
                    args.snapshot,
                    "--trial",
                    str(args.trial),
                    "--run",
                    args.run,
                    "--timeout",
                    str(args.timeout),
                    cwd=work,
                    env=env,
                    stdout=log,
                    stderr=asyncio.subprocess.STDOUT,
                )
                try:
                    await asyncio.wait_for(proc.wait(), timeout=args.timeout + adapter.grace)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            if (
                not path[task].exists() or path[task].stat().st_mtime < started
            ):  # the file of an earlier start is paid for
                print(f"CRASH {task} (see logs/{name}.log)", flush=True)
                not_graded.append(f"{task}: no result, see logs/{name}.log")
                return
            result = Result.from_dict(json.loads(path[task].read_text()))
            try:
                cost = record_costs(result, f"harness_{args.bench}")
            except ValueError as exc:
                print(f"LEDGER {exc}", flush=True)
                not_graded.append(f"{task}: {exc}")
                return
            if result.score is None:
                not_graded.append(f"{task}: {result.error}")
            shown = "no score" if result.score is None else f"score={result.score.primary:.3f}"
            print(
                f"{shown} {task} {result.wall_s}s ${cost:.3f} [{costs.line()}] {result.error or ''}",
                flush=True,
            )

    await asyncio.gather(*(one(t) for t in todo))
    if not_graded:
        print(f"\n{len(not_graded)} tasks not graded (not counted by the report):")
        for line in not_graded:
            print(f"- {line[:400]}")
        return 2
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench", required=True, choices=sorted(ADAPTERS))
    ap.add_argument(
        "--profile",
        required=True,
        help="a file name in policy_eval/profiles, without .yaml; experiments/<name> for a variant that is not a best profile",
    )
    ap.add_argument("--set", required=True, help="a set id of policy_eval/sets/registry.json")
    ap.add_argument("--snapshot", required=True, help="a name under ~/dev/cuga_snapshots")
    ap.add_argument("--trial", type=int, default=1)
    ap.add_argument("--run", required=True, help="the results go to harness/results/<run>_t<trial>")
    ap.add_argument("-j", "--jobs", type=int, default=2)
    ap.add_argument(
        "--timeout",
        type=float,
        help="agent time per task, in seconds; by default what the benchmark has used (adapter.default_timeout)",
    )
    ap.add_argument(
        "--model", default="gptoss", help="the model layer of policy_eval/envs: gptoss, dsv4, gemini38"
    )
    ap.add_argument("--tasks", nargs="*", help="only these tasks of the set")
    ap.add_argument("--proxy", help="OPENAI_BASE_URL for the children, for example http://127.0.0.1:8799")
    ap.add_argument(
        "--rerun-mismatch",
        action="store_true",
        help="a task whose result has another code_sha or profile_hash runs again and its file is replaced; "
        "by default such a result stops the run",
    )
    ap.add_argument(
        "--langfuse",
        action="store_true",
        help="trace each task in the local Langfuse (keys from LANGFUSE_ENV_FILE, default ~/dev/langfuse-latest/cuga.env)",
    )
    ap.add_argument("--child", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.child:
        child(args)
        return 0
    try:
        snapshot_src(args.snapshot)
        profile_path(args.profile)
        adapter = ADAPTERS[args.bench](set_id=args.set)
        if not adapter.python.exists():
            raise HarnessError(f"no venv at {adapter.python}")
        args.timeout = agent_timeout(args.timeout, adapter)
        tasks = adapter.task_ids(args.set)
        if args.tasks:
            unknown = sorted(set(args.tasks) - set(tasks))
            if unknown:
                raise HarnessError(f"not in set {args.set}: {unknown}")
            tasks = [t for t in tasks if t in set(args.tasks)]
    except (HarnessError, ValueError, KeyError) as exc:
        print(f"run: {exc}", file=sys.stderr)
        return 2
    try:
        return asyncio.run(run_many(tasks, adapter, args))
    except HarnessError as exc:
        print(f"run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
