#!/usr/bin/env python3
"""Live check of every CUGA lifecycle hook, with a real model, for both ways tools reach the agent
(``CugaAgent(tools=...)`` and ``CugaAgent(tool_provider=...)`` as the benchmark runners use it).

A probe hook records every call and uses each documented effect once:
- before_llm_call injects a code word the final answer must contain (proves the text reaches the model);
- after_plan blocks the first CodeAct block (it must not run; the agent must try again);
- before_tool_call blocks write_note('forbidden') (the tool must not run; write_note('allowed') must run);
- before_reply sends the agent back once (a second turn must happen);
- on_user_message answers a guarded message without running the agent.
Observe-only hooks (session_start, after_llm_call, after_tool_call, on_task_end) must be called with the right data.

  CUGA_ENV_FILE=cuga.gptoss.env ~/dev/cuga-agent-gate/.venv/bin/python benchmarks/policy_eval/validate_hooks.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "enterpriseops_gym"))

CODE_WORD = "ZEBRA-7731"


def _env() -> None:
    import run_cuga_eog as eog

    os.environ.update({k: v for k, v in eog.child_env().items() if k not in os.environ})


class Probe:
    """Records every hook call; uses each effect once."""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self.plans = 0
        self.replies = 0

    def _log(self, hook: str, **data: Any) -> None:
        self.calls.append({"hook": hook, **data})

    def session_start(self, thread_id):
        self._log("session_start", thread_id=thread_id)

    def on_user_message(self, message, thread_id):
        self._log("on_user_message", message=message[:80])
        if "PING-GUARD" in message:
            from cuga.backend.hooks import HookResult

            return HookResult(answer="guarded: the agent did not run")
        return None

    def before_llm_call(self, thread_id):
        self._log("before_llm_call")
        return f"PROBE NOTE: your final answer must contain the code word {CODE_WORD}."

    def after_llm_call(self, text):
        self._log("after_llm_call", text=str(text)[:120])

    def after_plan(self, code):
        self.plans += 1
        self._log("after_plan", n=self.plans, code=code[:200])
        if self.plans == 1:
            return "PROBE: this first code block was not run. Write it again and run it."
        return None

    def before_tool_call(self, tool, args):
        self._log("before_tool_call", tool=tool, args=dict(args))
        if tool == "write_note" and "forbidden" in json.dumps(args):
            return "PROBE-BLOCK: write_note('forbidden') is not allowed. Call write_note with text 'allowed' instead."
        return None

    def after_tool_call(self, tool, args, result):
        self._log("after_tool_call", tool=tool, args=dict(args), result=result)

    def before_reply(self, answer):
        self.replies += 1
        self._log("before_reply", n=self.replies, answer=str(answer)[:200])
        if self.replies == 1:
            return "PROBE-FOLLOWUP: call read_counter once more and include its value in the answer."
        return None

    def on_task_end(self, answer):
        self._log("on_task_end", answer=str(answer)[:200])


def _tools(executed: List[Dict[str, Any]]):
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    class NoteArgs(BaseModel):
        text: str = Field(..., description="The note text.")

    async def read_counter() -> dict:
        """Read the current counter value."""
        executed.append({"tool": "read_counter"})
        return {"value": 41}

    async def write_note(text: str) -> dict:
        """Save a note with the given text."""
        executed.append({"tool": "write_note", "text": text})
        return {"saved": text}

    return [
        StructuredTool.from_function(
            coroutine=read_counter, name="read_counter", description="Read the current counter value."
        ),
        StructuredTool.from_function(
            coroutine=write_note,
            name="write_note",
            description="Save a note with the given text.",
            args_schema=NoteArgs,
        ),
    ]


async def run(mode: str) -> Dict[str, Any]:
    from cuga.sdk import CugaAgent

    executed: List[Dict[str, Any]] = []
    probe = Probe()
    tools = _tools(executed)
    kw: Dict[str, Any] = {"tools": tools}
    if mode == "tool_provider":
        from helpers.app_tools_provider import AppToolsProvider

        kw = {"tool_provider": AppToolsProvider(tools, lambda t: "notes")}
    agent = CugaAgent(
        **kw,
        hooks=[probe],
        cuga_folder=str(Path(tempfile.gettempdir()) / "validate_hooks" / mode),
        auto_load_policies=False,
        filesystem_sync=False,
        enable_knowledge=False,
    )
    task = (
        "Call read_counter. Then call write_note with the text 'forbidden'. If a call is refused, follow the "
        "instruction in the refusal. Finally answer with the counter value."
    )
    result = await asyncio.wait_for(agent.invoke(task, thread_id=f"hooks-{mode}"), timeout=900)
    guard = await asyncio.wait_for(agent.invoke("PING-GUARD", thread_id=f"hooks-{mode}-guard"), timeout=120)
    return {
        "mode": mode,
        "answer": result.answer,
        "error": result.error,
        "guard_answer": guard.answer,
        "events": [(e.get("hook"), e.get("outcome")) for e in (result.hook_events or [])],
        "guard_events": [(e.get("hook"), e.get("outcome")) for e in (guard.hook_events or [])],
        "calls": probe.calls,
        "executed": executed,
    }


def check(r: Dict[str, Any]) -> List[tuple]:
    calls, executed = r["calls"], r["executed"]
    by = lambda h: [c for c in calls if c["hook"] == h]  # noqa: E731
    writes = [e["text"] for e in executed if e["tool"] == "write_note"]
    plans = by("after_plan")
    first_plan_tools = []  # tool calls between the first and second after_plan
    seen = False
    for c in calls:
        if c["hook"] == "after_plan":
            if seen:
                break
            seen = True
        elif seen and c["hook"] == "before_tool_call":
            first_plan_tools.append(c["tool"])
    after_tool = by("after_tool_call")
    reads_after_reply = (
        [c for c in calls[calls.index(by("before_reply")[0]) :] if c.get("tool") == "read_counter"]
        if by("before_reply")
        else []
    )
    guard_ran_llm = any(h == "before_llm_call" for h, _ in r["guard_events"])
    return [
        ("session_start", len(by("session_start")) >= 1, f"{len(by('session_start'))} call(s)"),
        ("on_user_message", len(by("on_user_message")) >= 1, "called for the task"),
        (
            "on_user_message answer",
            r["guard_answer"] == "guarded: the agent did not run" and not guard_ran_llm,
            f"answer={r['guard_answer']!r}, model called={guard_ran_llm}",
        ),
        (
            "before_llm_call inject",
            CODE_WORD in (r["answer"] or ""),
            f"code word in final answer: {CODE_WORD in (r['answer'] or '')}",
        ),
        ("after_llm_call", len(by("after_llm_call")) >= 1, f"{len(by('after_llm_call'))} call(s)"),
        (
            "after_plan block",
            len(plans) >= 2 and not first_plan_tools,
            f"{len(plans)} plan(s); tools run in blocked block: {first_plan_tools}",
        ),
        (
            "before_tool_call block",
            "forbidden" not in writes and "allowed" in writes,
            f"write_note executed with: {writes}",
        ),
        (
            "after_tool_call",
            bool(after_tool)
            and all(c["result"] is not None for c in after_tool)
            and not any(
                c["tool"] == "write_note" and "forbidden" in json.dumps(c["args"]) for c in after_tool
            ),
            f"{len(after_tool)} call(s), results: {[c['result'] for c in after_tool][:3]}",
        ),
        (
            "before_reply followup",
            len(by("before_reply")) >= 2 and bool(reads_after_reply),
            f"{len(by('before_reply'))} call(s); read_counter after first reply: {len(reads_after_reply)}",
        ),
        (
            "on_task_end",
            [c["answer"] for c in by("on_task_end")] == [(r["answer"] or "")[:200], r["guard_answer"]],
            f"{len(by('on_task_end'))} call(s), one per invoke, each with that invoke's answer",
        ),
    ]


def main() -> None:
    _env()
    out = HERE / "hook_validation.json"
    results = []
    for mode in ("tools", "tool_provider"):
        r = asyncio.run(run(mode))
        rows = check(r)
        results.append({**r, "checks": rows})
        print(f"\n== {mode}  (answer: {str(r['answer'])[:100]!r}, error: {r['error']})")
        for name, ok, info in rows:
            print(f"  {'PASS' if ok else 'FAIL'}  {name:24} {info}")
    out.write_text(json.dumps(results, indent=1, default=str))
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
