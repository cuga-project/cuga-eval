"""AutomationBench: the world, tools and rubric of ``automationbench/ab_env.py``. Rules come from the task's data."""

from __future__ import annotations

import datetime as _dt
import functools
import json
import os
import sys
import time
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from ...envs.compose_env import FC_DYNAMIC
from ..result import Score, automationbench_score
from .base import (
    BENCHMARKS,
    RawOutcome,
    agent_tools,
    drive_one_request,
    hooks_kwarg,
    set_entry,
    set_task_ids,
    with_note,
)

if TYPE_CHECKING:
    from cuga.policy_layer.runtime import RunContext, RuntimeParts

HOME = BENCHMARKS / "automationbench"


def _bench() -> Any:
    if str(HOME) not in sys.path:
        sys.path.insert(1, str(HOME))
    import ab_env

    return ab_env


RULE_FILES = {  # general instructions for the agent, each behind a flag that is off by default
    "AB_AGENT_RULES": "automationbench_agent_rules.md",  # read the procedure first, list worksheets, change only what was asked
    "AB_SPAWN_RULES": "automationbench_spawn_rules.md",  # read-only sub-agents (needs DYNACONF_AGENT_SPAWN__ENABLED=true)
}


def _world_clock(world_time: str) -> Callable[[], Any]:
    """Run the benchmark's clock at the task's world time. AutomationBench records and tools read ``datetime.now()``
    (and ``time.time()`` for Slack ``ts``), so records the task leaves undated and every write got the wall-clock date
    (a QuickBooks estimate made "today" looked months past its world-time expiry). Only ``automationbench.*`` modules
    are patched; CUGA, polisys and the harness keep the real clock. Each task runs in its own process.

    Returns a function that sets the world-time value on undated fields filled by a bare ``default_factory=
    datetime.now`` (bound at class creation, so the module patch cannot reach it). ``AB_WORLD_CLOCK=0`` turns it off."""
    real, base = _dt.datetime, _dt.datetime.fromisoformat(world_time.replace("Z", "+00:00"))
    base = base if base.tzinfo else base.replace(tzinfo=_dt.timezone.utc)
    start = time.monotonic()

    def world_now(tz: Optional[_dt.tzinfo] = None) -> _dt.datetime:
        t = base + _dt.timedelta(seconds=time.monotonic() - start)
        return t.astimezone(tz) if tz else t.astimezone(_dt.timezone.utc).replace(tzinfo=None)

    class _Meta(type):  # isinstance / issubclass behave as for the real class
        def __instancecheck__(cls, obj: Any) -> bool:
            return isinstance(obj, real)

        def __subclasscheck__(cls, sub: type) -> bool:
            return issubclass(sub, real)

    class WorldDatetime(real, metaclass=_Meta):
        @classmethod
        def now(cls, tz: Optional[_dt.tzinfo] = None) -> _dt.datetime:  # type: ignore[override]
            return world_now(tz)

        @classmethod
        def utcnow(cls) -> _dt.datetime:  # type: ignore[override]
            return world_now()

        @classmethod
        def today(cls) -> _dt.datetime:  # type: ignore[override]
            return world_now()

    world_time_mod = types.SimpleNamespace(
        **{k: getattr(time, k) for k in dir(time) if not k.startswith("__")}
    )
    world_time_mod.time = lambda: world_now(_dt.timezone.utc).timestamp()
    for name, mod in list(sys.modules.items()):
        if not (name == "automationbench" or name.startswith("automationbench.")) or mod is None:
            continue
        if getattr(mod, "datetime", None) is real:
            mod.datetime = WorldDatetime
        if getattr(mod, "time", None) is time:
            mod.time = world_time_mod

    from pydantic import BaseModel

    def fix(obj: Any, seen: set) -> None:
        if id(obj) in seen:
            return
        seen.add(id(obj))
        if isinstance(obj, BaseModel):
            for field, info in type(obj).model_fields.items():
                if field not in obj.model_fields_set and info.default_factory == real.now:
                    obj.__dict__[field] = world_now()  # no validators; marked as set so it keeps this value
                    obj.model_fields_set.add(field)
            for field in type(obj).model_fields:
                fix(getattr(obj, field, None), seen)
        elif isinstance(obj, dict):
            for v in obj.values():
                fix(v, seen)
        elif isinstance(obj, (list, tuple, set)):
            for v in obj:
                fix(v, seen)

    return lambda world: fix(world, set())


def _after(fn: Callable, then: Callable[[], None]) -> Callable:
    @functools.wraps(fn)
    def call(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        finally:
            then()

    return call


def _with_agent_rules(system: str) -> str:
    """Add the instruction files whose flag is set. Added to the agent's instructions only; policy checks do not read
    them as policy."""
    extra = [
        (Path(__file__).parent / name).read_text().strip()
        for flag, name in RULE_FILES.items()
        if os.environ.get(flag)
    ]
    return "\n\n".join([system, *extra] if system else extra)


class AutomationBenchAdapter:
    benchmark = "automationbench"
    python = HOME / ".venv" / "bin" / "python"
    python_flags = ()
    env_bench = "automationbench"
    env_extra: Dict[
        str, Any
    ] = {  # every tool of each app the agent searches for (audit: AB_FC_BIND, AB_SHORTLISTER)
        **FC_DYNAMIC,
        **(
            {"DYNACONF_ADVANCED_FEATURES__CUGA_LITE_FC_DYNAMIC_TOOLS": os.environ["AB_FC_BIND"]}
            if os.environ.get("AB_FC_BIND")
            else {}
        ),
        **(
            {
                "DYNACONF_SHORTLISTER__STRATEGY": os.environ["AB_SHORTLISTER"],
                "DYNACONF_SHORTLISTER__THRESHOLD": "0",
                "DYNACONF_SHORTLISTER__MAX_RESULTS": "5",
            }
            if os.environ.get("AB_SHORTLISTER")
            else {}
        ),
    }
    grace = 300.0
    default_timeout = 1800.0  # as the old runner
    toolset = (
        os.environ.get("AB_TOOLSET") or "full"
    )  # all 549 tools; CUGA has to find the ones the task needs (audit: limited_zapier)

    def __init__(self, run_dir: Optional[Path] = None, set_id: Optional[str] = None, run: str = ""):
        self.run_dir, self.run_name = run_dir, run
        self.log: List[Dict[str, Any]] = []

    def task_ids(self, set_id: str) -> List[str]:
        return set_task_ids(set_entry(set_id, (self.benchmark,)))

    async def prepare(self, task_id: str) -> "RunContext":
        from cuga.backend.activity_tracker.tracker import ActivityTracker
        from cuga.policy_layer.intake import discovery_tools
        from cuga.policy_layer.runtime import RunContext

        bench = _bench()
        self.task_id = task_id
        task = bench.load_task(task_id)
        system = "\n\n".join(m["content"] for m in task["prompt"] if m["role"] == "system")
        user = "\n\n".join(m["content"] for m in task["prompt"] if m["role"] == "user")
        fns = bench.toolset_functions(self.toolset, task["info"])  # imports the tool and schema modules first
        task_time = ((task["info"].get("initial_state") or {}).get("meta") or {}).get("current_time")
        fix = None
        if task_time and os.environ.get("AB_WORLD_CLOCK", "1") != "0":
            import automationbench.runner  # noqa: F401  (build_world imports it; patch it too)
            import automationbench.schema.world  # noqa: F401

            fix = _world_clock(str(task_time))
        self.world, self.info, self.initial = bench.build_world(task["info"])
        if fix:
            fix(self.world)
            fns = [_after(fn, lambda: fix(self.world)) for fn in fns]
        self.tools = [bench.make_tool(fn, self.world, self.log) for fn in fns]
        self.app_by_tool = {fn.__name__: bench.tool_app(fn) for fn in fns}
        world_time = str(self.world.meta.current_time or "").replace("Z", "+00:00")
        ActivityTracker().current_date = world_time or None
        if os.environ.get("AB_SHOW_DATE") and world_time:  # audit: the agent sees the world's date
            system = f"Current date and time: {world_time}\n\n{system}"
        by_name = {fn.__name__: fn for fn in fns}
        extra: Dict[str, Any] = {}
        if "data_list" in getattr(
            RunContext, "__dataclass_fields__", {}
        ):  # snapshots before sources.listing lack it
            from cuga.policy_layer.ruleset import is_write_tool

            from .automationbench_listing import list_world

            world = self.world
            extra["data_list"] = lambda: list_world(fns, world, bench.tool_app, is_write_tool)[0]
        return RunContext(
            task_id=task_id,
            request=user,
            system_prompt=system,
            tool_specs=[
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": t.args_schema.model_json_schema() if t.args_schema else {},
                    "app": self.app_by_tool.get(t.name),
                }
                for t in self.tools
            ],
            world_time=world_time,
            data_search=[
                (n, (lambda q, fn=by_name[n]: fn(world=self.world, query=q))) for n in discovery_tools(fns)
            ],
            policy_version=task_id,
            message_tool="",
            **extra,
        )

    async def run(self, parts: "RuntimeParts", ctx: "RunContext", timeout: float) -> RawOutcome:
        from cuga.sdk import CugaAgent
        from helpers.app_tools_provider import AppToolsProvider

        turns: List[Dict[str, Any]] = []
        live: List[Dict[str, Any]] = []
        agent = CugaAgent(
            tool_provider=AppToolsProvider(
                agent_tools(parts, self.tools, self.log, turns, live),
                lambda t: self.app_by_tool.get(t.name, "policy"),  # real app names, as in AppWorld
                # audit: one line per app, made once from tool names and descriptions only (AB_APP_DESC)
                json.loads((Path(__file__).parents[3] / "automationbench/app_descriptions.json").read_text())
                if os.environ.get("AB_APP_DESC")
                else None,
            ),
            special_instructions=with_note(_with_agent_rules(ctx.system_prompt), parts.system_note) or None,
            cuga_folder=str(Path(self.run_dir) / ".cuga" / self.task_id),
            auto_load_policies=False,
            filesystem_sync=False,
            enable_knowledge=False,
            **hooks_kwarg(parts),
        )
        thread = f"ab-{self.task_id}"
        return await drive_one_request(agent, parts, ctx.request, thread, timeout, turns, live, self.log)

    async def grade(self) -> Score:
        score = automationbench_score(_bench().score(self.world, self.info, self.initial))
        if score is None:
            raise RuntimeError("the rubric gave no partial credit")
        return score

    def close(self) -> None:
        return None
