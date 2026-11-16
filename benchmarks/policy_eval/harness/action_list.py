"""Action list of a policy version at run time. An experiment, off by default.

The list (``policy_eval/action_lists/<bench>_base.draft.json``) is built offline from the policy text and the tool schemas:
what the policy requires as a call or as a value, and who must act. A rule is used only when it has a sentence (``say``)
and a checkable form (``rt``), and when every tool it names is in the task's tool list. A rule with ``version`` holds for
that policy version only. A rule with ``review`` is one a person has not decided; it is used only with
``<PREFIX>_ACTION_LIST_REVIEW=1``.

``<PREFIX>_ACTION_LIST=prompt``  the sentences are added to the system prompt, nothing else changes.
``<PREFIX>_ACTION_LIST=tool``    the sentences are shown when they apply:
  - action rule: after the trigger call succeeds and the required call is not in the run yet, the sentence is added to that
    tool's result, once per rule;
  - argument rule: the first call of a tool with a value that differs from the policy value is not executed and returns the
    policy values, once per tool. The next call runs as sent. Nothing else is stopped.

Code decides only what is exact (tool names, argument values). It never decides whether the request gives a value: the
note says what the policy value is and leaves that to the agent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

LISTS = Path(__file__).resolve().parents[1] / "action_lists"
HEAD = "Actions and values that this policy requires from you (the system does not do them for you):"


def _tools_of(rt: Dict[str, Any]) -> List[str]:
    names = [t["tool"] for t in rt.get("trigger") or []]
    if rt.get("required"):
        names.append(rt["required"]["tool"])
    if rt.get("tool"):
        names.append(rt["tool"])
    return names


def load(bench: str, version: str, tools_in_run: List[str], review: bool) -> List[Dict[str, Any]]:
    path = LISTS / f"{bench}_base.draft.json"
    if not path.exists():
        raise FileNotFoundError(f"no action list for benchmark {bench!r}: {path}")
    out = []
    for rule in json.loads(path.read_text())["rules"]:
        if not rule.get("say") or not rule.get("rt"):
            continue
        if rule.get("version") and rule["version"] != version:
            continue
        if rule.get("review") and not review:
            continue
        if all(name in tools_in_run for name in _tools_of(rule["rt"])):
            out.append(rule)
    return out


def _match(args: Dict[str, Any], when: Dict[str, Any]) -> bool:
    for key, want in (when or {}).items():
        got = args.get(key)
        if want == "*":
            if got in (None, ""):
                return False
        elif isinstance(want, list):
            if got not in want:
                return False
        elif got != want:
            return False
    return True


class ActionList:
    """The rules of one run and what was shown. ``before`` and ``after`` hold all the logic, so a saved tool log can be
    replayed through them with no model and no tool."""

    def __init__(self, rules: List[Dict[str, Any]], mode: str):
        self.rules, self.mode = rules, mode
        self.calls: List[Dict[str, Any]] = []  # successful calls of the run
        self.noted: set = set()
        self.stopped: set = set()
        self.events: List[Dict[str, Any]] = []

    # -- prompt ---------------------------------------------------------------------------------------------------
    def prompt_text(self) -> str:
        if not self.rules:
            return ""
        return HEAD + "\n" + "\n".join(f"- {r['say']} [policy section {r['section']}]" for r in self.rules)

    # -- tool time ------------------------------------------------------------------------------------------------
    def _deviations(self, tool: str, args: Dict[str, Any]) -> List[Dict[str, Any]]:
        found = []
        for rule in self.rules:
            rt = rule["rt"]
            if rule["kind"] != "argument" or rt.get("tool") != tool or not _match(args, rt.get("when") or {}):
                continue
            lines = []
            for arg, default in (rt.get("defaults") or {}).items():
                if arg in args and args[arg] != default:
                    lines.append(
                        f"{arg}={args[arg]!r}: the policy default is {default!r} when the request gives no value"
                    )
            for arg, value in (rt.get("fixed") or {}).items():
                if args.get(arg) != value:
                    lines.append(f"{arg}={args.get(arg)!r}: the policy value is {value!r}")
            for arg, allowed in (rt.get("one_of") or {}).items():
                if args.get(arg) not in allowed:
                    lines.append(
                        f"{arg}={args.get(arg)!r}: the policy allows {', '.join(map(repr, allowed))}"
                    )
            for arg in rt.get("present") or []:
                if args.get(arg) in (None, ""):
                    lines.append(f"{arg} is missing")
            matrix = rt.get("matrix")
            if matrix:
                key = "|".join(str(args.get(a)) for a in matrix["args"])
                want = matrix["table"].get(key)
                if want is not None and args.get(matrix["target"]) != want:
                    given = ", ".join(f"{a}={args.get(a)!r}" for a in matrix["args"])
                    lines.append(
                        f"{matrix['target']}={args.get(matrix['target'])!r}: the policy matrix gives {want!r} for {given}"
                    )
            if lines:
                found.append({"rule": rule, "lines": lines})
        return found

    def before(self, tool: str, args: Dict[str, Any]) -> Optional[str]:
        """Text that replaces the call, or None when the call runs."""
        if self.mode != "tool" or tool in self.stopped:
            return None
        found = self._deviations(tool, args)
        if not found:
            return None
        self.stopped.add(tool)
        say = " ".join(f["rule"]["say"] for f in found)
        lines = "; ".join(line for f in found for line in f["lines"])
        text = (
            f"NOT EXECUTED YET (policy check, shown once). {say} In this call: {lines}. "
            f"Call {tool} again with your final values; the next call runs as you send it."
        )
        self.events.append(
            {
                "kind": "stop",
                "tool": tool,
                "rules": [f["rule"]["id"] for f in found],
                "text": text,
                "at_call": len(self.calls),
            }
        )
        return text

    def after(self, tool: str, args: Dict[str, Any], ok: bool) -> Optional[str]:
        """Text added to the result of a successful call, or None."""
        if not ok:
            return None
        self.calls.append({"tool": tool, "args": args})
        if self.mode != "tool":
            return None
        notes = []
        for rule in self.rules:
            rt = rule["rt"]
            if rule["kind"] != "action" or rule["id"] in self.noted:
                continue
            if not any(t["tool"] == tool and _match(args, t.get("when") or {}) for t in rt["trigger"]):
                continue
            req = rt["required"]
            if any(c["tool"] == req["tool"] and _match(c["args"], req.get("args") or {}) for c in self.calls):
                continue
            self.noted.add(rule["id"])
            notes.append(f"{rule['say']} [policy section {rule['section']}]")
            self.events.append(
                {
                    "kind": "note",
                    "tool": tool,
                    "rules": [rule["id"]],
                    "text": notes[-1],
                    "at_call": len(self.calls),
                }
            )
        return "POLICY: this call requires more work. " + " ".join(notes) if notes else None

    def wrap(self, tools: List[Any]) -> List[Any]:
        from langchain_core.tools import StructuredTool

        def one(tool: Any) -> Any:
            async def call(**kwargs: Any) -> Any:
                args = {k: v for k, v in kwargs.items() if v is not None}
                stop = self.before(tool.name, args)
                if stop is not None:
                    return {"executed": False, "policy_note": stop}
                out = await tool.ainvoke(args)
                note = self.after(tool.name, args, not (isinstance(out, dict) and "error" in out))
                if note is None:
                    return out
                return {**out, "policy_note": note} if isinstance(out, dict) else f"{out}\n\n{note}"

            return StructuredTool.from_function(
                coroutine=call, name=tool.name, description=tool.description, args_schema=tool.args_schema
            )

        return [one(t) for t in tools]

    def report(self) -> Dict[str, Any]:
        return {"mode": self.mode, "rules": [r["id"] for r in self.rules], "events": self.events}


def from_env(prefix: str, bench: str, version: str, tools_in_run: List[str]) -> Optional[ActionList]:
    """The action list of this run when ``<prefix>_ACTION_LIST`` is set, else None and the run is unchanged."""
    mode = os.environ.get(f"{prefix}_ACTION_LIST", "")
    if not mode:
        return None
    if mode not in ("prompt", "tool"):
        raise ValueError(f"{prefix}_ACTION_LIST={mode!r}: use prompt or tool")
    review = os.environ.get(f"{prefix}_ACTION_LIST_REVIEW") == "1"
    return ActionList(load(bench, version, list(tools_in_run), review), mode)
