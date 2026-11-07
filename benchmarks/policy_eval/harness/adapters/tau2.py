"""τ²: tau2-bench drives the conversation and the user simulator on a thread, CUGA answers on the event loop, as in
``benchmarks/tau2/cuga_runner.py``. Runs in the venv and with the code of the ``~/dev/cuga-eval-tau2`` worktree; that venv
imports ``cuga`` from ``~/dev/cuga-agent`` unless the snapshot comes first, which the harness checks in every child.

The set says the domain. The one user turn of the other benchmarks is many turns here, so this adapter has its own loop:
``turn_note`` goes with each customer message, ``after_reply`` sees each answer, ``wrap_tools`` gets the decoys. A loop in the
slot ``run`` has no meaning here and raises.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ...envs.compose_env import TAU2_AGENT
from ..result import Score, tau2_score
from .base import RawOutcome, agent_tools, hooks_kwarg, receipt_of, set_entry, set_task_ids, with_note

if TYPE_CHECKING:
    from cuga.policy_layer.runtime import RunContext, RuntimeParts

WORKTREE = Path.home() / "dev/cuga-eval-tau2"
DOMAINS = ("tau2-telecom", "tau2-airline")
USER_SIMULATOR = "openai/Azure/gpt-4.1"
MAX_STEPS = 100  # as the old launcher (launchers/archive/run_arm_a.py)
JOIN_TIMEOUT = 120.0


def _is_cancellation(exc: BaseException) -> bool:
    """τ² ended the conversation in the middle of a tool call: closing the bridge cancels the awaited tool, and langgraph
    gives that as ``NodeCancelledError``. This is the only exception of a conversation that is no failure."""
    return isinstance(exc, asyncio.CancelledError) or type(exc).__name__ == "NodeCancelledError"


def _on_path() -> None:
    if str(WORKTREE) not in sys.path:
        sys.path.insert(1, str(WORKTREE))


class Tau2Adapter:
    python = WORKTREE / ".venv" / "bin" / "python"
    python_flags = ()
    env_bench = "tau2"
    env_extra: Dict[str, Any] = TAU2_AGENT
    grace = 300.0
    default_timeout = 1800.0  # the old runner had no limit; its longest run of 430 took 826 s

    def __init__(self, run_dir: Optional[Path] = None, set_id: Optional[str] = None, run: str = ""):
        self.run_dir, self.run_name = run_dir, run
        self.benchmark = set_entry(set_id, DOMAINS)["benchmark"] if set_id else "tau2"
        self.domain = self.benchmark.removeprefix("tau2-")
        self.bridge: Any = None
        self.sim: Any = None
        self.log: List[Dict[str, Any]] = []

    def task_ids(self, set_id: str) -> List[str]:
        return set_task_ids(set_entry(set_id, DOMAINS))

    async def prepare(self, task_id: str) -> "RunContext":
        from cuga.policy_layer.runtime import RunContext

        _on_path()
        from benchmarks.tau2.cuga_runner import _MESSAGE_TOOL
        from tau2.registry import registry
        from tau2.runner.helpers import get_tasks

        tasks = get_tasks(self.domain, task_ids=[task_id], num_tasks=None)
        if not tasks:
            raise ValueError(f"no task {task_id} in the τ² domain {self.domain}")
        self.task = tasks[0]
        self.task_id = task_id
        env = registry.get_env_constructor(self.domain)()
        self.tau2_tools, self.policy = env.get_tools(), env.get_policy()
        return RunContext(
            task_id=task_id,
            system_prompt=self.policy,
            tool_specs=[
                {
                    "name": t.name,
                    "description": getattr(t, "short_desc", "") or "",
                    "inputSchema": t.params.model_json_schema(),
                }
                for t in self.tau2_tools
            ],
            policy_version=self.domain,
            message_tool=_MESSAGE_TOOL,
        )

    async def run(self, parts: "RuntimeParts", ctx: "RunContext", timeout: float) -> RawOutcome:
        from benchmarks.tau2.cuga_runner import (
            _patch_tau2_nl_assertion_model,
            _populate_sim_outputs,
        )
        from benchmarks.tau2.tau2_bridge import ConversationBridge, make_decoy_tools
        from benchmarks.tau2.tau2_proxy import make_cuga_factory, set_current_bridge
        from cuga.backend.activity_tracker.tracker import ActivityTracker
        from cuga.policy_layer.runtime import RuntimeWiringError
        from cuga.sdk import CugaAgent
        from tau2.data_model.simulation import TextRunConfig
        from tau2.registry import registry
        from tau2.runner.batch import run_single_task

        if parts.run is not None:
            raise RuntimeWiringError(
                f"task {self.task_id}, component loop: τ² is a conversation; a loop over one request does not fit"
            )
        out = RawOutcome(tool_calls=self.log)
        args = {"api_base": os.environ.get("OPENAI_BASE_URL"), "api_key": os.environ.get("OPENAI_API_KEY")}
        judge = _patch_tau2_nl_assertion_model(USER_SIMULATOR, args)
        out.extra["nl_judge_model"] = judge
        ActivityTracker().reset(intent=str(self.task.description or self.task.id), task_id=self.task.id)

        self.bridge = ConversationBridge(tau2_tools=self.tau2_tools, domain_policy=self.policy)
        set_current_bridge(self.bridge)
        if "cuga_proxy" not in registry.get_agents():
            registry.register_agent_factory(make_cuga_factory(), "cuga_proxy")
        config = TextRunConfig(
            domain=self.domain,
            agent="cuga_proxy",
            user="user_simulator",
            llm_agent="gpt-4.1",  # ignored by the proxy, which runs no model
            llm_user=USER_SIMULATOR,
            llm_args_user=args,
            max_steps=MAX_STEPS,
        )
        scored: Dict[str, Any] = {}

        def tau2_thread() -> None:
            try:
                scored["sim"] = run_single_task(config, self.task)
            except Exception as exc:  # noqa: BLE001 - surface it, then still unblock CUGA
                scored["error"] = exc
            finally:
                self.bridge.close()

        thread = threading.Thread(target=tau2_thread, name="tau2-run", daemon=True)
        thread.start()
        cancelled: Optional[BaseException] = None
        try:
            await asyncio.wait_for(
                self._conversation(CugaAgent, make_decoy_tools, parts, ctx, out), timeout=timeout
            )
        except asyncio.TimeoutError:
            out.error = f"timeout after {timeout:.0f}s"
            self.bridge.close()
        except RuntimeWiringError:
            raise
        except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001
            if _is_cancellation(exc):
                cancelled = exc  # matters only when τ² has no score either
            else:  # a gateway failure in the middle of a conversation: also when τ² then scored what was left
                out.error = out.error or f"{type(exc).__name__}: {exc}"
            self.bridge.close()
        await asyncio.to_thread(thread.join, JOIN_TIMEOUT)
        if thread.is_alive():
            out.error = out.error or f"the τ² thread did not finish within {JOIN_TIMEOUT:.0f}s"
        set_current_bridge(None)
        self.sim = scored.get("sim")
        if "error" in scored:
            out.error = out.error or f"{type(scored['error']).__name__}: {scored['error']}"
        elif cancelled is not None and self.sim is None:
            out.error = out.error or f"{type(cancelled).__name__}: {cancelled}"
        _populate_sim_outputs(self.sim, out.extra)
        out.usage = self._simulator_usage()
        return out

    async def _conversation(
        self,
        agent_class: Any,
        make_decoy_tools: Any,
        parts: "RuntimeParts",
        ctx: "RunContext",
        out: RawOutcome,
    ) -> None:
        """Each turn is one invoke on one thread. The answer goes to the user simulator, and its reply is the next prompt."""
        bridge = self.bridge
        loop = asyncio.get_running_loop()
        bridge.bind_loop(loop)
        turns: List[Dict[str, Any]] = []  # the conversation as the components read it
        live: List[Dict[str, Any]] = []  # tool calls of the current turn, as they happen
        agent = agent_class(
            tools=agent_tools(parts, make_decoy_tools(bridge.tau2_tools, bridge), self.log, turns, live),
            special_instructions=with_note(ctx.system_prompt, parts.system_note),
            **hooks_kwarg(parts),
        )
        thread_id = f"tau2-{self.domain}-{self.task_id}"
        seen: List[Dict[str, Any]] = []
        try:
            prompt = await loop.run_in_executor(None, bridge.first_observation)
            if prompt is None:
                return
            is_note = False
            for _ in range(MAX_STEPS + 20):
                turns.append({"role": "note" if is_note else "customer", "text": prompt})
                live.clear()
                if parts.turn_note is not None and not is_note:
                    note = await loop.run_in_executor(None, parts.turn_note, list(turns))
                    if note:
                        prompt = f"{prompt}\n\n{note}"
                result = await agent.invoke(prompt, thread_id=thread_id, track_tool_calls=True)
                receipt = receipt_of(result)
                if receipt is not None:
                    out.receipts.append(receipt)
                calls = list(getattr(result, "tool_calls", None) or [])
                new = calls[len(seen) :] if calls[: len(seen)] == seen else calls
                seen = calls if calls[: len(seen)] == seen else seen + calls
                for call in new:
                    turns.append(
                        {
                            "role": "tool",
                            "name": call.get("name"),
                            "args": call.get("arguments") or call.get("args"),
                            "result": call.get("result"),
                        }
                    )
                    self.log.append(call)
                out.answer = result.answer
                # The SDK gives "Error: ..." as the answer together with the error. That text must not reach the customer.
                out.error = out.error or result.error
                if result.error or not result.answer:  # an error, or nothing to say: τ² ends the task
                    break
                if parts.after_reply is not None:
                    again = await loop.run_in_executor(None, parts.after_reply, result.answer, turns, live)
                    if (
                        again is not None
                    ):  # the reply is not sent, and the agent gets the note as its next input
                        prompt, is_note = again, True
                        continue
                is_note = False
                turns.append({"role": "agent", "text": result.answer})
                try:
                    prompt = await bridge.register_message(result.answer)
                except asyncio.CancelledError:
                    break  # τ² closed the bridge: the conversation is over
                if prompt is None:
                    break
        finally:
            bridge.close()

    def _simulator_usage(self) -> Dict[str, Dict[str, Any]]:
        """The user simulator's model calls, from τ²'s messages."""
        rows = [m for m in (getattr(self.sim, "messages", None) or []) if getattr(m, "role", "") == "user"]
        usages = [getattr(m, "usage", None) or {} for m in rows]
        return {
            "user_simulator": {
                "model": USER_SIMULATOR,
                "calls": len(rows),
                "input_tokens": sum(u.get("prompt_tokens", 0) or 0 for u in usages),
                "output_tokens": sum(u.get("completion_tokens", 0) or 0 for u in usages),
            }
        }

    async def grade(self) -> Score:
        info = getattr(self.sim, "reward_info", None)
        reason = getattr(self.sim, "termination_reason", None)
        score = tau2_score(info.reward if info else None, getattr(reason, "value", reason))
        if score is None:
            raise RuntimeError("τ² gave no reward")
        return score

    def close(self) -> None:
        if self.bridge is not None:
            self.bridge.close()
