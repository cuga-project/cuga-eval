"""IT service tasks of EnterpriseOps-Gym: the database, tools and verifiers of ``enterpriseops_gym/eog_env.py``. Each task is
on one policy version; the profile's ``{policy}`` is that version."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..result import Score, itsm_score
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

HOME = BENCHMARKS / "enterpriseops_gym"


class ItsmAdapter:
    benchmark = "itsm"
    python = GATE_PYTHON
    python_flags = ()
    env_bench = "itsm"
    env_extra: Dict[str, Any] = {}
    grace = 300.0
    default_timeout = 1200.0  # as the old runner

    def __init__(self, run_dir: Optional[Path] = None, set_id: Optional[str] = None, run: str = ""):
        self.run_dir, self.run_name = run_dir, run
        self.log: List[Dict[str, Any]] = []
        self.env: Any = None

    def task_ids(self, set_id: str) -> List[str]:
        return set_task_ids(set_entry(set_id, (self.benchmark,)))

    async def prepare(self, task_id: str) -> "RunContext":
        from cuga.policy_layer.runtime import RunContext

        if str(HOME) not in sys.path:
            sys.path.insert(1, str(HOME))
        from eog_env import EOGTask, load_task

        self.task_id = task_id
        task = load_task(task_id)
        self.env = EOGTask(task, sink=self.log.append)
        await self.env.start()
        self.env.sink = None  # platform-side lookup: not part of the agent's trajectory
        me = await self.env.call("get_user", {"user_id": self.env.user_info.get("user_id")})
        self.env.sink = self.log.append
        return RunContext(
            task_id=task_id,
            request=task["user_prompt"],
            system_prompt=task["system_prompt"],
            tool_specs=json.loads((HOME / f"tasks/{task.get('domain') or 'itsm'}_tools.json").read_text()),
            tools_in_run=task["selected_tools"],
            principal={
                "id": self.env.user_info.get("user_id"),
                "role": me.get("role") if isinstance(me, dict) else None,
            },
            policy_version=task["_policy_hash"],
            message_tool="",
        )

    async def run(self, parts: "RuntimeParts", ctx: "RunContext", timeout: float) -> RawOutcome:
        from cuga.sdk import CugaAgent
        from helpers.app_tools_provider import AppToolsProvider

        turns: List[Dict[str, Any]] = []
        live: List[Dict[str, Any]] = []
        added = {t.name for t in parts.tools}
        agent = CugaAgent(
            tool_provider=AppToolsProvider(
                agent_tools(parts, self.env.langchain_tools(), self.log, turns, live),
                lambda t: "policy" if t.name in added else self.env.app_name(),
            ),
            special_instructions=with_note(ctx.system_prompt, parts.system_note),
            cuga_folder=str(Path(self.run_dir) / ".cuga" / self.task_id[-8:]),
            auto_load_policies=False,
            filesystem_sync=False,
            enable_knowledge=False,
            **hooks_kwarg(parts),
        )
        thread = f"eog-{self.task_id}"
        return await drive_one_request(agent, parts, ctx.request, thread, timeout, turns, live, self.log)

    async def grade(self) -> Score:
        score = itsm_score(await self.env.grade())
        if score is None:
            raise RuntimeError("the verifiers gave no result")
        return score

    def close(self) -> None:
        if self.env is not None:
            self.env.close()


class CsmAdapter(ItsmAdapter):
    """Customer service (CSM) tasks of EnterpriseOps-Gym: same environment and grading, the CSM server and tools."""

    benchmark = "csm"
    env_bench = "csm"


class HrAdapter(ItsmAdapter):
    """HR service delivery tasks of EnterpriseOps-Gym: same environment and grading, the HR server and tools."""

    benchmark = "hr"
    env_bench = "hr"
