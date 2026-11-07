"""What an adapter is, and what all adapters share. No benchmark and no ``cuga`` import at module level: the parent process
reads this in any Python, and each child imports ``cuga`` only after the snapshot is on its path.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from ..result import Score

if TYPE_CHECKING:
    from cuga.policy_layer.runtime import RunContext, RuntimeParts

HARNESS = Path(__file__).resolve().parents[1]
BENCHMARKS = HARNESS.parents[1]
GATE_PYTHON = Path.home() / "dev/cuga-agent-gate/.venv/bin/python"
TOOL_LOG_LIMIT = 4000
MAX_REPLIES = 20  # a component that keeps refusing a reply stops here, in a benchmark with one user turn


@dataclass
class RawOutcome:
    """What the agent did, before grading."""

    answer: Optional[str] = None
    error: Optional[str] = None  # the agent stopped on this; the state it left is still graded
    receipts: List[Dict[str, Any]] = field(default_factory=list)  # one per agent turn
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, Dict[str, Any]] = field(
        default_factory=dict
    )  # model calls the runtime does not see, by component
    extra: Dict[str, Any] = field(default_factory=dict)  # kept with the trajectory


@runtime_checkable
class BenchmarkAdapter(Protocol):
    """One benchmark. The parent reads ``python``, ``python_flags``, ``env_bench``, ``env_extra``, ``grace`` and calls
    ``task_ids``. Each task's child process calls ``prepare``, ``run``, ``grade`` and ``close``, in that benchmark's venv."""

    benchmark: str  # the name in results and in the set registry
    python: Path  # venv of this benchmark
    python_flags: Tuple[str, ...]  # "-I" where the child reads a download
    env_bench: str  # the bench layer of envs/compose_env.py
    env_extra: Dict[str, Any]  # the extra of envs/compose_env.py
    grace: float  # seconds past the timeout before the parent kills a child: starting and grading
    default_timeout: float  # agent time per task when --timeout is not given

    def task_ids(self, set_id: str) -> List[str]: ...

    async def prepare(self, task_id: str) -> "RunContext": ...

    async def run(self, parts: "RuntimeParts", ctx: "RunContext", timeout: float) -> RawOutcome: ...

    async def grade(self) -> Score: ...

    def close(self) -> None: ...


def set_entry(set_id: str, benchmarks: Tuple[str, ...]) -> Dict[str, Any]:
    from policy_eval.sets.build_registry import get_entry

    entry = get_entry(set_id)
    if entry["benchmark"] not in benchmarks:
        raise ValueError(f"set {set_id} is for {entry['benchmark']}, not for {' or '.join(benchmarks)}")
    return entry


def set_task_ids(entry: Dict[str, Any]) -> List[str]:
    from policy_eval.sets.build_registry import task_ids

    return task_ids(entry)


def with_note(prompt: str, note: str) -> str:
    """The system prompt with the policy layer's note. With no note the prompt is the same text: a baseline run must equal
    CUGA with no policy layer, byte for byte."""
    return f"{prompt}\n\n{note}" if note else prompt


def hooks_kwarg(parts: "RuntimeParts") -> Dict[str, Any]:
    return {"hooks": parts.hooks} if parts.hooks else {}


def logged_tools(tools: List[Any], log: List[Dict[str, Any]]) -> List[Any]:
    """The tools that the policy layer adds, with each call in the run's tool log. Arguments left at None are not part of
    the call."""
    from langchain_core.tools import StructuredTool

    def wrap(tool: Any) -> Any:
        async def call(**kwargs: Any) -> Any:
            args = {k: v for k, v in kwargs.items() if v is not None}
            started = time.monotonic()
            out = await tool.ainvoke(args)
            log.append(
                {
                    "tool": tool.name,
                    "args": args,
                    "result": str(out)[:TOOL_LOG_LIMIT],
                    "ms": round((time.monotonic() - started) * 1000),
                }
            )
            return out

        return StructuredTool.from_function(
            coroutine=call, name=tool.name, description=tool.description, args_schema=tool.args_schema
        )

    return [wrap(t) for t in tools]


def agent_tools(
    parts: "RuntimeParts",
    tools: List[Any],
    log: List[Dict[str, Any]],
    turns: List[Dict[str, Any]],
    live: List[Dict[str, Any]],
    logged: Callable[[List[Any], List[Dict[str, Any]]], List[Any]] = logged_tools,
) -> List[Any]:
    """What the agent is built with: the benchmark's tools, through ``wrap_tools`` when a component fills it, and the policy
    layer's tools."""
    wrapped = parts.wrap_tools(tools, turns, live) if parts.wrap_tools is not None else list(tools)
    return wrapped + logged(parts.tools, log)


def receipt_of(result: Any) -> Optional[Dict[str, Any]]:
    receipt = getattr(result, "receipt", None)
    return receipt.model_dump(exclude={"tool_timings"}) if receipt is not None else None


class _TurnErrors:
    """The agent, as a component that runs many turns sees it. The component reads the answer of a turn and goes on, so an
    error of a turn in the middle would be gone by the end of the run."""

    def __init__(self, agent: Any):
        self.agent = agent
        self.first: Optional[str] = None

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:
        result = await self.agent.invoke(*args, **kwargs)
        self.first = self.first or result.error
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self.agent, name)


async def drive_one_request(
    agent: Any,
    parts: "RuntimeParts",
    request: str,
    thread_id: str,
    timeout: float,
    turns: List[Dict[str, Any]],
    live: List[Dict[str, Any]],
    log: List[Dict[str, Any]],
) -> RawOutcome:
    """A benchmark with one user request: the loop when a component fills ``run``, else one invoke, with ``turn_note`` on the
    request and ``after_reply`` on each answer. An agent error of any turn is kept and ends the turns; the state it left is
    graded, as the old runners did (``run.py`` does not grade a gateway error). A wiring error raises."""
    from cuga.policy_layer.runtime import RuntimeWiringError

    out = RawOutcome(tool_calls=log)
    if parts.run is not None and (parts.turn_note is not None or parts.after_reply is not None):
        raise RuntimeWiringError(
            "a component fills the slot run, and another fills turn_note or after_reply: the run has no turns for them"
        )
    loop = parts.components.get("loop")
    watched = _TurnErrors(agent)
    try:
        if parts.run is not None:
            result = await parts.run(watched, request, thread_id, timeout)
            out.answer, out.error = result.answer, watched.first or result.error
        else:
            prompt = request
            turns.append({"role": "customer", "text": request})
            if parts.turn_note is not None:
                note = await asyncio.to_thread(parts.turn_note, list(turns))
                if note:
                    prompt = f"{prompt}\n\n{note}"
            for _ in range(MAX_REPLIES):
                result = await asyncio.wait_for(agent.invoke(prompt, thread_id=thread_id), timeout=timeout)
                receipt = receipt_of(result)
                if receipt is not None:
                    out.receipts.append(receipt)
                out.answer, out.error = result.answer, out.error or result.error
                if result.error or parts.after_reply is None or not result.answer:
                    break
                again = await asyncio.to_thread(parts.after_reply, result.answer, turns, live)
                if again is None:
                    break
                prompt = again
    except asyncio.TimeoutError:
        out.error = watched.first or f"timeout after {timeout:.0f}s"
    except RuntimeWiringError:
        raise
    except Exception as exc:  # noqa: BLE001 - grade whatever state the agent left
        out.error = watched.first or f"{type(exc).__name__}: {exc}"
    if loop is not None:
        out.receipts = list(loop.receipts)
        out.extra["sop_loop"] = loop.log
    return out


def save_trajectory(path: Path, task: str, extra: Dict[str, Any]) -> str:
    """CUGA's tracker holds this task's steps (one task per child process). The file also keeps what the result leaves out:
    the answer, the tool calls, the loop's log, a τ² conversation."""
    try:
        from cuga.backend.activity_tracker.tracker import ActivityTracker

        tracker = ActivityTracker()
        steps = [
            s.model_dump() if hasattr(s, "model_dump") else getattr(s, "__dict__", str(s))
            for s in (tracker.steps or [])
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"intent": tracker.intent, "task": task, "steps": steps, **extra}, default=str)
        )
        return str(path)
    except Exception as exc:  # noqa: BLE001 - a lost trajectory must not lose the result
        return f"not saved: {type(exc).__name__}: {exc}"
