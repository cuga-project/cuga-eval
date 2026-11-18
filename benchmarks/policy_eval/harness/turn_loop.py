"""Turn loop: one agent, one conversation thread, three switchable parts around each turn. No polisys and no ``cuga`` import.

    turn start -> [survey: read, writes locked] -> work -> [write check at each change] -> end check -> reply
                                                                                             ^    |
                                                                                             +----+ it changed something

Nothing here names a benchmark, a task or a value. Every switch is off by default, so a run can measure each one.
The harness turns it on with ``TURN_LOOP`` (``adapters/base.py``), for example ``TURN_LOOP=survey,end2``.

Stand-alone use with CUGA:

    from cuga.sdk import CugaAgent
    agent = TurnLoopAgent(lambda tools, note: CugaAgent(tools=tools, special_instructions=note or None), tools,
                          is_write=label_from_the_adapter, settings=Settings(survey=True, end_rounds=2))
    answer = await agent.turn(request)            # one request = one turn; a conversation calls turn() per message

Mechanics test (scripted fake agent, no model call):  python turn_loop.py
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, TypedDict

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import END, START, StateGraph

# The survey instruction is a note for the agent's system prompt, not a part of the first user message: CUGA's tool search
# reads the first user message of the thread as the task context in every later turn, and "make no change" there made
# it return only read tools in the work turn (smoke run of 2026-11-11).
SURVEY_NOTE = (
    "This work has two parts. Part 1, from the request until the user tells you to do the work: read only. Tools that "
    "change data are locked and make no change. Find and read everything that can change this work: the procedure or "
    "policy the request points to, later messages that correct, pause or extend it, earlier examples of the same work, "
    "and the present state of each record you will change. End part 1 with the list of sources you opened and what "
    "each one changes. Part 2 starts when the user tells you to do the work."
)
WORK = (
    "Now do the work with what you read; the tools that change data are open. A newer instruction replaces only the "
    "part of an older one that it speaks about; the rest of the older one still holds."
)
END_CHECK = (
    "Before the final answer, check your work against the systems, not against your notes. The list below is every "
    "change you made, taken from the tool log. First, match each thing the request and the procedure ask for to a "
    "change in the list, and make the changes that are missing. Second, read back each changed record and correct "
    "what is wrong: the wrong record, a wrong value, or the same change made twice. Add nothing that the request or "
    "the procedure did not ask for. Then give the final answer."
)
# Tuning round 2 (2026-11-12), switch ``keep``. In round 1 the end check reopened decisions of the work that were right (it
# acted on records the work had left out on purpose) and sent messages that cannot be taken back, some of them
# "corrections" of its own messages; the agent itself called them sent in error. The read-back comes first here.
END_CHECK_KEEP = (
    "Before the final answer, check your work against the systems, not against your notes. The list below is every "
    "change you made, taken from the tool log. First, read back each changed record and correct what is wrong: the "
    "wrong record, a wrong value, or the same change made twice. Second, match each thing the request and the "
    "procedure ask for to a change in the list, and make a change that is missing. Keep the decisions of your work: a "
    "record you left out on purpose stays out, unless you now name a source or a value that you had not read. A "
    "message to a person cannot be taken back: send one now only when the request or the procedure requires it and "
    "none was sent for it; do not send a second message to correct or update one you sent, say in your answer what is "
    "wrong in it. Add nothing that the request or the procedure did not ask for. Then give the final answer."
)
WRITE_CHECK = (
    "An agent is about to make this change:\n{tool}({args})\n\nThis is what it has read about the records "
    "involved:\n{evidence}\n\nDoes the text forbid this change, or require something first that the text shows is "
    'not done? Answer with JSON only: {{"block": true or false, "quote": "the exact words copied from the text", '
    '"why": "one sentence"}}. Block only when you can copy the words. When you are not sure, do not block.'
)
LOCKED = (
    "No call was made: tools that can change data are locked while you read (part 1). They open when the user tells "
    "you to do the work."
)
MAX_READ, MAX_EVIDENCE = 6000, 12000
Ask = Callable[
    [str], Awaitable[Optional[str]]
]  # one invoke on the thread: the answer, or None when the run must stop


@dataclass
class Settings:
    survey: bool = False  # read with writes locked before the first work turn
    write_check: bool = (
        False  # one call of `judge` per change; blocks a change once, only with a copied quote
    )
    end_rounds: int = (
        0  # end-check turns: 1 = a read-back turn, 2 = one more if the first one changed something
    )
    end_when: str = (
        "always"  # "always": one request is one turn; "on_write": a conversation, check after a change
    )
    keep: bool = False  # the end-check text of tuning round 2: keep the work's decisions, no second message


def parse(value: str) -> Settings:
    """``survey,end2`` -> Settings(survey=True, end_rounds=2). Words: survey, check, end<N>, on_write, keep. Others refused."""
    s = Settings()
    for word in [w.strip() for w in value.split(",") if w.strip()]:
        if word == "survey":
            s.survey = True
        elif word == "check":
            s.write_check = True
        elif word == "on_write":
            s.end_when = "on_write"
        elif word == "keep":
            s.keep = True
        elif re.fullmatch(r"end[1-9]", word):
            s.end_rounds = int(word[3:])
        else:
            raise ValueError(f"TURN_LOOP: unknown word {word!r} (use survey, check, end<N>, on_write, keep)")
    return s


def system_note(settings: Settings) -> str:
    return SURVEY_NOTE if settings.survey else ""


def related(reads: List[str], args: Dict[str, Any]) -> str:
    """Read results that mention a value of the planned change (whole words, 4 to 80 characters), newest first."""
    values = {str(v) for v in _leaves(args) if 4 <= len(str(v)) <= 80}
    hits = [r for r in reversed(reads) if any(re.search(rf"(?<!\w){re.escape(v)}(?!\w)", r) for v in values)]
    return "\n---\n".join(hits)[:MAX_EVIDENCE]


def _leaves(value: Any) -> List[Any]:
    if isinstance(value, dict):
        return [leaf for v in value.values() for leaf in _leaves(v)]
    if isinstance(value, (list, tuple)):
        return [leaf for v in value for leaf in _leaves(v)]
    return [value]


def make_check(judge: Callable[[str], Awaitable[str]]) -> Callable[..., Awaitable[Optional[str]]]:
    """A check for one planned change. It returns the reason to block, or None. No copied quote means no block."""

    async def check(tool: str, args: Dict[str, Any], reads: List[str]) -> Optional[str]:
        evidence = related(reads, args)
        if not evidence:
            return None  # nothing read about these records: unknown, so do not guess
        raw = await judge(
            WRITE_CHECK.format(tool=tool, args=json.dumps(args, default=str)[:2000], evidence=evidence)
        )
        try:
            verdict = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
        except ValueError:
            return None
        quote = " ".join(str(verdict.get("quote", "")).split())
        if verdict.get("block") is not True or len(quote) < 20 or quote not in " ".join(evidence.split()):
            return None
        return f'What you read says: "{quote}". {verdict.get("why", "")}'.strip()

    return check


def write_table(writes: List[Dict[str, Any]]) -> str:
    if not writes:
        return "Changes you made, from the tool log: none."
    rows = [
        f"{n}. {w['tool']}({json.dumps(w['args'], default=str)[:300]}) -> {w['result'][:120]}"
        for n, w in enumerate(writes, 1)
    ]
    return "Changes you made, from the tool log:\n" + "\n".join(rows)


class Turn(TypedDict, total=False):
    message: str
    first: bool
    start: int  # number of logged changes when the turn began
    answer: Optional[str]
    rounds: int
    changed: bool


class TurnLoop:
    """The loop and its tool guard. ``is_write(name)`` is the adapter's label of the tools that change data. ``digest``
    (optional, for audits) returns a fingerprint of the systems' state: a call labeled as a read that changes it is
    recorded in ``label_errors``."""

    def __init__(
        self,
        settings: Settings,
        is_write: Callable[[str], bool],
        judge: Optional[Callable[[str], Awaitable[str]]] = None,
        digest: Optional[Callable[[], str]] = None,
    ) -> None:
        if settings.write_check and judge is None:
            raise ValueError("write_check is on and no judge is given")
        self.s, self.is_write, self.digest = settings, is_write, digest
        self.check = make_check(judge) if settings.write_check and judge else None
        self.locked = False
        self.reads: List[str] = []  # tool results the agent has seen
        self.writes: List[Dict[str, Any]] = []  # {tool, args, result}
        self.blocked: Set[str] = set()  # changes already blocked once
        self.refused: List[Dict[str, Any]] = []  # changes refused by the survey lock or the write check
        self.label_errors: List[str] = []
        self.phases: List[Dict[str, Any]] = []
        self.first = True
        self._ask: Optional[Ask] = None
        self.graph = self._build()

    @property
    def system_note(self) -> str:
        """Text for the agent's system prompt (empty when the survey is off)."""
        return system_note(self.s)

    # ---- tools ----

    def guard_tools(self, tools: List[BaseTool]) -> List[BaseTool]:
        return [self._guard(t) for t in tools]

    def _guard(self, tool: BaseTool) -> BaseTool:
        """The same tool (name, description, schema, metadata), with the read log, the survey lock, the write check and
        the write log around it."""
        schema = tool.args_schema
        order = list(getattr(schema, "model_fields", {}) or {}) if isinstance(schema, type) else []

        async def run(*pos: Any, **kwargs: Any) -> Any:
            if len(pos) > len(order):  # CodeAct calls the coroutine directly, with positional arguments
                raise TypeError(
                    f"{tool.name}() takes at most {len(order)} positional arguments ({len(pos)} given)"
                )
            kwargs = {**dict(zip(order, pos)), **kwargs}
            args = {
                k: v for k, v in kwargs.items() if v is not None
            }  # schema defaults are not part of the call
            if not self.is_write(tool.name):
                before = self.digest() if self.digest else None
                out = await tool.ainvoke(args)
                if before is not None and self.digest() != before:
                    self.label_errors.append(tool.name)
                self.reads.append(f"[{tool.name}] {out}"[:MAX_READ])
                return out
            if self.locked:
                self.refused.append({"tool": tool.name, "by": "survey"})
                return LOCKED
            key = tool.name + json.dumps(args, sort_keys=True, default=str)
            if self.check and key not in self.blocked:
                reason = await self.check(tool.name, args, self.reads)
                if reason:
                    self.blocked.add(key)  # block once; the same call passes the second time
                    self.refused.append({"tool": tool.name, "by": "write_check", "reason": reason})
                    return f"No change was made. {reason} If the change is still right, say why and make the call again."
            out = await tool.ainvoke(args)
            self.writes.append({"tool": tool.name, "args": args, "result": str(out)[:300]})
            return out

        return StructuredTool.from_function(
            coroutine=run,
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema,
            metadata=tool.metadata,
        )

    # ---- the loop ----

    async def _phase(self, name: str, text: str) -> Optional[str]:
        before, refused = len(self.writes), len(self.refused)
        answer = await self._ask(text) if self._ask else None
        self.phases.append(
            {
                "phase": name,
                "changes": len(self.writes) - before,
                "refused": len(self.refused) - refused,
                "answered": answer is not None,
            }
        )
        return answer

    def _build(self) -> Any:
        s = self.s

        async def survey(st: Turn) -> Turn:
            self.locked = True
            try:
                answer = await self._phase("survey", st["message"])  # the request as it is
            finally:
                self.locked = False
            return {"message": WORK, "answer": answer}  # the request is already in the thread

        async def work(st: Turn) -> Turn:
            return {"answer": await self._phase("work", st["message"]), "rounds": 0}

        async def end_check(st: Turn) -> Turn:
            before = len(self.writes)
            answer = await self._phase(
                "end_check",
                (END_CHECK_KEEP if s.keep else END_CHECK) + "\n\n" + write_table(self.writes[st["start"] :]),
            )
            return {
                "answer": answer
                if answer is not None
                else st["answer"],  # a stopped check keeps the work's answer
                "rounds": st["rounds"] + 1,
                "changed": answer is not None and len(self.writes) > before,
            }

        def after_work(st: Turn) -> str:
            if st["answer"] is None or s.end_rounds < 1:
                return END
            if s.end_when == "on_write" and len(self.writes) == st["start"]:
                return END
            return "end_check"

        def after_check(st: Turn) -> str:
            return "end_check" if st["changed"] and st["rounds"] < s.end_rounds else END

        g = StateGraph(Turn)
        g.add_node("survey", survey)
        g.add_node("work", work)
        g.add_node("end_check", end_check)
        g.add_conditional_edges(
            START, lambda st: "survey" if s.survey and st["first"] else "work", ["survey", "work"]
        )
        g.add_conditional_edges("survey", lambda st: END if st["answer"] is None else "work", ["work", END])
        g.add_conditional_edges("work", after_work, ["end_check", END])
        g.add_conditional_edges("end_check", after_check, ["end_check", END])
        return g.compile()

    async def turn(self, ask: Ask, message: str) -> Optional[str]:
        """One user message through the loop. ``ask(text)`` makes one agent call on the thread and returns its answer,
        or None when the run must stop (an agent error, no answer): the loop then ends with the last answer it has."""
        first, self.first, self._ask = self.first, False, ask
        state: Turn = {"message": message, "first": first, "start": len(self.writes), "answer": None}
        return (await self.graph.ainvoke(state)).get("answer")

    def report(self) -> Dict[str, Any]:
        """What the loop did, for the trajectory file."""
        return {
            "settings": asdict(self.s),
            "phases": self.phases,
            "changes": len(self.writes),
            "refused": self.refused,
            "label_errors": self.label_errors,
        }


class TurnLoopAgent:
    """Stand-alone form. ``make_agent(tools, system_note)`` returns an object with ``await invoke(message,
    thread_id=...)`` whose result has ``.answer`` and ``.error``. The note belongs in the agent's system prompt; the first
    user message stays the request as it is."""

    def __init__(
        self,
        make_agent: Callable[[List[BaseTool], str], Any],
        tools: List[BaseTool],
        is_write: Callable[[str], bool],
        settings: Optional[Settings] = None,
        judge: Optional[Callable[[str], Awaitable[str]]] = None,
    ) -> None:
        self.loop = TurnLoop(settings or Settings(), is_write, judge)
        self.agent = make_agent(self.loop.guard_tools(tools), self.loop.system_note)

    async def turn(self, message: str, thread_id: str = "t1") -> Optional[str]:
        async def ask(text: str) -> Optional[str]:
            result = await self.agent.invoke(text, thread_id=thread_id)
            return None if getattr(result, "error", None) or not result.answer else result.answer

        return await self.loop.turn(ask, message)


# ---- mechanics test: a scripted fake agent and invented data; no model is called ----


async def _test() -> None:
    from types import SimpleNamespace

    from langchain_core.tools import tool

    world: List[str] = []

    @tool
    async def read_order(order: str) -> str:
        """Read an order and its notes."""
        return f"Order {order}: refund requested. Notice: refunds for order {order} are paused until the audit ends."

    @tool
    async def find_or_make_note(order: str) -> str:
        """Find the note of an order, or make one."""
        world.append(f"note {order}")
        return f"note made for {order}"

    @tool
    async def send_refund(order: str, memo: Optional[str] = None) -> str:
        """Send the refund for an order."""
        world.append(order)
        return f"refund sent for {order}"

    class FakeAgent:
        """Each invoke plays the next script: a list of (tool name, args) calls. A script of None is an agent error."""

        def __init__(self, tools: List[BaseTool], scripts: List[Any]) -> None:
            self.tools, self.scripts, self.seen, self.results = {t.name: t for t in tools}, scripts, [], []

        async def invoke(self, message: str, thread_id: str = "") -> Any:
            self.seen.append(message)
            script = self.scripts[len(self.seen) - 1]
            if script is None:
                return SimpleNamespace(answer="", error="model error")
            for name, args in script:
                self.results.append(str(await self.tools[name].ainvoke(args)))
            return SimpleNamespace(answer=f"answer {len(self.seen)}", error=None)

    async def judge(prompt: str) -> str:
        return json.dumps(
            {
                "block": True,
                "quote": "refunds for order A-1001 are paused until the audit ends",
                "why": "Paused.",
            }
        )

    plain_note = system_note

    def expect(ok: bool, what: str) -> None:
        if not ok:
            raise AssertionError(what)

    def build(scripts: List[Any], settings: Settings, **kw: Any) -> Any:
        holder: Dict[str, Any] = {}

        def make(tools: List[BaseTool], note: str) -> FakeAgent:
            holder["a"], holder["note"] = FakeAgent(tools, scripts), note
            return holder["a"]

        agent = TurnLoopAgent(
            make,
            [read_order, find_or_make_note, send_refund],
            is_write=lambda name: name.startswith("send_"),
            settings=settings,
            **kw,
        )
        return agent, holder["a"]

    refund = ("send_refund", {"order": "A-1001"})
    agent, fake = build(
        [
            [("read_order", {"order": "A-1001"}), refund],  # survey: the change is locked
            [refund, refund],  # work: blocked once with the quote, then the same call passes
            [("send_refund", {"order": "B-2002"})],  # end check 1 changes something -> one more round
            [],  # end check 2 changes nothing -> stop
            [],  # never reached
        ],
        Settings(survey=True, write_check=True, end_rounds=2),
        judge=judge,
    )
    answer = await agent.turn("Refund order A-1001.")
    expect(answer == "answer 4" and len(fake.seen) == 4, f"four agent calls, got {fake.seen}")
    expect(fake.seen[0] == "Refund order A-1001.", "the first user message is the request as it is")
    expect(
        agent.loop.system_note == SURVEY_NOTE and plain_note(Settings(end_rounds=2)) == "", "the system note"
    )
    expect(fake.seen[1] == WORK, "the work message")
    expect(fake.results[1] == LOCKED, "the survey lock")
    expect(
        "paused until the audit ends" in fake.results[2] and "No change was made" in fake.results[2],
        "block once",
    )
    expect(
        fake.results[3] == "refund sent for A-1001" and world == ["A-1001", "B-2002"],
        "the second call passes",
    )
    expect("1. send_refund" in fake.seen[2] and "2. send_refund" in fake.seen[3], "the table of changes")
    expect([p["phase"] for p in agent.loop.phases] == ["survey", "work", "end_check", "end_check"], "phases")
    expect(agent.loop.report()["refused"][0] == {"tool": "send_refund", "by": "survey"}, "the report")

    plain, fake = build([[]], Settings())
    expect(
        await plain.turn("Read order A-1001.") == "answer 1" and len(fake.seen) == 1, "switches off: one call"
    )
    expect(fake.seen[0] == "Read order A-1001.", "switches off: the same message")

    stopped, fake = build([[refund], None, []], Settings(end_rounds=2))
    expect(
        await stopped.turn("Refund order A-1001.") == "answer 1", "an error in the end check keeps the answer"
    )
    expect(len(fake.seen) == 2, "an error ends the loop")

    quiet, fake = build([[], []], Settings(end_rounds=2, end_when="on_write"))
    expect(
        await quiet.turn("Hello.") == "answer 1" and len(fake.seen) == 1, "on_write: no change, no end check"
    )

    world.clear()
    audited = TurnLoop(Settings(), is_write=lambda name: name.startswith("send_"), digest=lambda: str(world))
    tools = {t.name: t for t in audited.guard_tools([read_order, find_or_make_note, send_refund])}
    await tools["read_order"].ainvoke({"order": "A-1001"})
    await tools["find_or_make_note"].ainvoke({"order": "A-1001"})
    expect(audited.label_errors == ["find_or_make_note"], "a read that changes the state is recorded")
    await tools["send_refund"].coroutine("C-3003", memo=None)  # positional call, as CodeAct does
    expect(
        audited.writes
        == [{"tool": "send_refund", "args": {"order": "C-3003"}, "result": "refund sent for C-3003"}],
        "args",
    )
    expect(parse("survey,end2") == Settings(survey=True, end_rounds=2), "parse")
    expect(parse("end1,keep") == Settings(end_rounds=1, keep=True), "parse keep")
    kept, fake = build([[refund], []], parse("end1,keep"))
    await kept.turn("Refund order A-1001.")
    expect(
        fake.seen[1].startswith(END_CHECK_KEEP) and len(fake.seen) == 2, "keep: the round-2 text, one round"
    )
    old, fake = build([[refund], []], parse("end1"))
    await old.turn("Refund order A-1001.")
    expect(
        fake.seen[1].startswith(END_CHECK) and END_CHECK != END_CHECK_KEEP, "without keep: the round-1 text"
    )
    try:
        parse("survey,plan")
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown word is refused")
    print("mechanics ok")


if __name__ == "__main__":
    asyncio.run(_test())
