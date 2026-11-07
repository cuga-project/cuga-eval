#!/usr/bin/env python3
"""Where hook feedback lands in the model input: the exact messages of every model call, captured at the LangChain
chat-model layer (what is sent to the API), in function-calling mode as the benchmark runs use it.

Scenario 1 (probe hook, the three feedback paths the policy layer uses):
- after read_counter, a note is queued and returned once by ``before_llm_call`` (as RuleSetHooks / intake reminders);
- ``before_tool_call`` blocks write_note('forbidden') (as a deny);
- ``before_reply`` sends the agent back once (as the reply checks).
Scenario 2 (the real ``DeliverablesHooks``, extraction stubbed, no policy-model cost): the first write_note is blocked
without advice, so the agent may stop; the deliverables reply check must then name the missing note.

For each marker: the first model call that contains it, the message type it is in, and the later calls that still
contain it.

  CUGA_ENV_FILE=cuga.fc.dsv4.env PYTHONPATH=~/dev/cuga_snapshots/dlv1/src ~/dev/cuga-agent-gate/.venv/bin/python \
      benchmarks/policy_eval/validate_injection.py
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
CAPTURE: List[List[Dict[str, str]]] = []


def _env() -> None:
    import run_cuga_eog as eog

    os.environ.update({k: v for k, v in eog.child_env().items() if k not in os.environ})


def _patch_capture() -> None:
    from langchain_core.language_models.chat_models import BaseChatModel

    def dump(messages) -> List[Dict[str, str]]:
        out = []
        for m in messages:
            c = m.content if isinstance(m.content, str) else json.dumps(m.content, default=str)
            calls = getattr(m, "tool_calls", None)
            out.append(
                {
                    "type": type(m).__name__,
                    "content": c,
                    "tool_calls": json.dumps(calls, default=str) if calls else "",
                }
            )
        return out

    orig_gen = BaseChatModel._agenerate_with_cache
    orig_stream = BaseChatModel.astream

    async def gen(self, messages, *a, **k):
        CAPTURE.append(dump(messages))
        return await orig_gen(self, messages, *a, **k)

    async def stream(self, input, *a, **k):
        msgs = input if isinstance(input, list) else getattr(input, "to_messages", lambda: [])()
        CAPTURE.append(dump(msgs))
        async for chunk in orig_stream(self, input, *a, **k):
            yield chunk

    BaseChatModel._agenerate_with_cache = gen
    BaseChatModel.astream = stream


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


class Probe:
    def __init__(
        self,
        block_first_write: bool = False,
        advise: bool = True,
        followup: bool = True,
        tool_note: bool = False,
    ):
        self.tool_note = (
            tool_note  # True: the note is returned by after_tool_call (attached to the tool result)
        )
        self.notes: List[str] = []
        self.replies = 0
        self.blocked = 0
        self.block_first_write, self.advise, self.followup = block_first_write, advise, followup

    def before_llm_call(self, thread_id):
        notes, self.notes = self.notes, []
        return "\n".join(notes) or None

    def before_tool_call(self, tool, args):
        if tool != "write_note":
            return None
        if self.advise and "forbidden" in json.dumps(args):
            return "MARK-BLOCK: write_note('forbidden') is not allowed. Call write_note with text 'allowed' instead."
        if self.block_first_write and self.blocked == 0:
            self.blocked += 1
            return "MARK-BLOCK2: write_note is not available right now."
        return None

    def after_tool_call(self, tool, args, result):
        if tool == "read_counter" and self.tool_note:
            return "MARK-TOOLNOTE: reminder attached to the read_counter result."
        if tool == "read_counter" and not self.notes:
            self.notes.append("MARK-NOTE: reminder queued after read_counter (shown on the next model call).")

    def before_reply(self, answer):
        self.replies += 1
        if self.followup and self.replies == 1:
            return "MARK-REPLY: call read_counter once more and include its value in the answer."
        return None


def report(markers: List[str]) -> List[Dict[str, Any]]:
    rows = []
    for mk in markers:
        where = []
        for i, call in enumerate(CAPTURE):
            for j, m in enumerate(call):
                if mk in m["content"]:
                    where.append({"call": i, "msg": j, "type": m["type"], "of": len(call)})
        first = where[0] if where else None
        rows.append(
            {
                "marker": mk,
                "found": bool(where),
                "first_call": first["call"] if first else None,
                "message_type": first["type"] if first else None,
                "position": f"{first['msg'] + 1} of {first['of']}" if first else None,
                "calls_containing": sorted({w["call"] for w in where}),
            }
        )
    return rows


async def scenario(name: str, hooks: List[Any], task: str) -> Dict[str, Any]:
    from cuga.sdk import CugaAgent
    from helpers.app_tools_provider import AppToolsProvider

    executed: List[Dict[str, Any]] = []
    tools = _tools(executed)
    CAPTURE.clear()
    agent = CugaAgent(
        tool_provider=AppToolsProvider(tools, lambda t: "notes"),
        hooks=hooks,
        cuga_folder=str(Path(tempfile.gettempdir()) / "validate_injection" / name),
        auto_load_policies=False,
        filesystem_sync=False,
        enable_knowledge=False,
    )
    result = await asyncio.wait_for(agent.invoke(task, thread_id=f"inject-{name}"), timeout=900)
    return {
        "name": name,
        "answer": result.answer,
        "error": result.error,
        "executed": executed,
        "model_calls": len(CAPTURE),
        "capture": list(CAPTURE),
    }


async def main_async() -> List[Dict[str, Any]]:
    from cuga.policy_layer.deliverables import DeliverablesHooks

    out = []
    r = await scenario(
        "probe",
        [Probe()],
        "Call read_counter. Then call write_note with the text 'forbidden'. If a call "
        "is refused, follow the instruction in the refusal. Finally answer with the counter value.",
    )
    r["markers"] = report(["MARK-NOTE", "MARK-BLOCK", "MARK-REPLY"])
    out.append(r)

    r = await scenario(
        "probe_tool_note",
        [Probe(tool_note=True, followup=False)],
        "Call read_counter, then answer with the counter value and repeat any reminder you were given.",
    )
    r["markers"] = report(["MARK-TOOLNOTE"])
    out.append(r)

    specs = [
        {"name": "write_note", "inputSchema": {"properties": {"text": {"type": "string"}}}},
        {"name": "read_counter", "inputSchema": {"properties": {}}},
    ]

    def stub(s, u):
        return json.dumps(
            {
                "items": [
                    {
                        "action": "save the note",
                        "tool": "write_note",
                        "args": {},
                        "targets": [],
                        "values": ["counter checked"],
                    }
                ]
            }
        )

    d = DeliverablesHooks(stub, specs, is_write=lambda n: n == "write_note")
    r = await scenario(
        "deliverables",
        [Probe(block_first_write=True, advise=False, followup=False), d],
        "Call read_counter, then save a note with the text 'counter checked' using write_note. "
        "If write_note is refused, do not retry it; just answer with the counter value.",
    )
    r["markers"] = report(["MARK-BLOCK2", "REQUEST CHECK"])
    r["deliverables_records"] = d.records
    out.append(r)
    return out


def main() -> None:
    _env()
    _patch_capture()
    results = asyncio.run(main_async())
    path = HERE / "injection_validation.json"
    path.write_text(json.dumps(results, indent=1, default=str))
    for r in results:
        print(
            f"\n== {r['name']}: {r['model_calls']} model calls; executed {[(e['tool'], e.get('text')) for e in r['executed']]}; "
            f"error={r['error']}; answer={str(r['answer'])[:90]!r}"
        )
        for m in r["markers"]:
            print(
                f"  {'FOUND' if m['found'] else 'MISSING':7} {m['marker']:14} first in call {m['first_call']} as "
                f"{m['message_type']} (message {m['position']}); calls containing it: {m['calls_containing']}"
            )
    print(f"\nsaved {path}")


if __name__ == "__main__":
    main()
