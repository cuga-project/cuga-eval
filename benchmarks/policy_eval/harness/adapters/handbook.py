"""HANDBOOK.md: the task container, MCP tools and rubric of ``handbook/hb_env.py``. The agent's code tools run
inside the container. The sample is downloaded content: files are only read, and the child runs with ``-I``."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..result import Score, handbook_score
from .base import (
    BENCHMARKS,
    GATE_PYTHON,
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

HOME = BENCHMARKS / "handbook"


def _bench() -> Any:
    if str(HOME) not in sys.path:
        sys.path.insert(1, str(HOME))
    import hb_env

    return hb_env


def sop_text_of(task_dir: Path) -> str:
    """The task's SOP as text. No SOP file raises: with an empty ``policy_text`` the runtime falls back to the system prompt,
    and a gate would run over the role prompt with no error."""
    from handbook.sop_text import html_text, largest_sop_file

    sop = largest_sop_file(task_dir)
    if sop is None:
        raise ValueError(f"task {Path(task_dir).name} has no file named as an SOP in its workspace")
    return html_text(sop.read_text(errors="replace"))


class HandbookAdapter:
    benchmark = "handbook"
    python = GATE_PYTHON
    python_flags = ("-I",)
    env_bench = "handbook"
    env_extra: Dict[str, Any] = {}
    grace = 1200.0  # the container start and the task's grader
    default_timeout = 3600.0  # as the old runner and task.toml; 4 of 414 old runs took longer than 1800 s

    def __init__(self, run_dir: Optional[Path] = None, set_id: Optional[str] = None, run: str = ""):
        self.run_dir, self.run_name = run_dir, run
        self.log: List[Dict[str, Any]] = []
        self.container: Optional[str] = None

    def task_ids(self, set_id: str) -> List[str]:
        return set_task_ids(set_entry(set_id, (self.benchmark,)))

    async def prepare(self, task_id: str) -> "RunContext":
        from cuga.backend.activity_tracker.tracker import ActivityTracker
        from cuga.policy_layer.runtime import RunContext
        from langchain_mcp_adapters.client import MultiServerMCPClient

        bench = _bench()
        self.task_id = task_id
        task_dir = bench.TASKS / task_id
        instruction = (task_dir / "instruction.md").read_text()
        system_prompt = (task_dir / "system_prompt.md").read_text()
        policy_text = sop_text_of(task_dir)  # before a container starts
        config = tomllib.loads((task_dir / "task.toml").read_text())
        world_time = ((config.get("environment") or {}).get("env") or {}).get("HANDBOOK_CURRENT_TIME", "")
        self.container = f"hb_{self.run_name}_{task_id[-8:]}".replace("/", "_")
        port = bench.start_container(task_id, self.container)
        client = MultiServerMCPClient(
            {"handbook": {"url": f"http://127.0.0.1:{port}/mcp", "transport": "streamable_http"}}
        )
        raw = await client.get_tools()
        self.tools = bench.logged_tools(raw, self.log)
        ActivityTracker().current_date = world_time or None
        return RunContext(
            task_id=task_id,
            request=instruction,
            system_prompt=system_prompt,
            policy_text=policy_text,
            tool_specs=bench.specs_of(raw),
            world_time=world_time,
            policy_version=task_id,
            message_tool="",
        )

    async def run(self, parts: "RuntimeParts", ctx: "RunContext", timeout: float) -> RawOutcome:
        from cuga.sdk import CugaAgent
        from helpers.app_tools_provider import AppToolsProvider

        bench = _bench()
        turns: List[Dict[str, Any]] = []
        live: List[Dict[str, Any]] = []
        agent = CugaAgent(
            tool_provider=AppToolsProvider(
                agent_tools(parts, self.tools, self.log, turns, live, logged=bench.logged_tools),
                lambda t: t.name.split("__", 1)[0] if "__" in t.name else "handbook",
            ),
            special_instructions=with_note(ctx.system_prompt, parts.system_note),
            cuga_folder=str(Path(self.run_dir) / ".cuga" / self.task_id[-8:]),
            auto_load_policies=False,
            filesystem_sync=False,
            enable_knowledge=False,
            **hooks_kwarg(parts),
        )
        thread = f"hb-{self.run_name}-{self.task_id}"
        return await drive_one_request(agent, parts, ctx.request, thread, timeout, turns, live, self.log)

    async def grade(self) -> Score:
        graded = _bench().grade(self.task_id, self.container)
        score = handbook_score(graded)
        if score is None:
            raise RuntimeError(f"the task's grader gave no result: {str(graded.get('grader_error'))[-500:]}")
        return score

    def close(self) -> None:
        if self.container:
            _bench().sh(["docker", "rm", "-f", self.container], check=False)
