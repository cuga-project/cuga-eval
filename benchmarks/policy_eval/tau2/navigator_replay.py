"""Offline test of a graph navigator on recorded τ²-Telecom runs (no agent runs).

Hypothesis: the agent ends or transfers with SOP sections it never handled, and those sections are reachable from
the case's section only through a reference ("Refer to the ... Mobile Data section"). A navigator that walks the
section tree and its reference links, and checks at the end which sections were not handled, would name the missed
fix before the agent gives up.

Inputs, all from the SOP the agent had and the conversation the agent saw:
- the section tree of the policy document (markdown headings) and the intake build's ``refers_to`` links;
- the tools each leaf section uses: tools its text names, plus the agent tools whose description matches its text
  (BM25), so rules like "check that the line is roaming enabled" map to ``enable_roaming``;
- the case: the chapter for the customer's first message, picked by Kev-4B (one yes/no question per chapter);
- the end point: the agent's transfer, or the last agent turn; "solved" asked of Kev on the last customer turns.

At the end point, when the customer has not said the problem is solved, the navigator lists the leaves of the walk
with no evidence (none of their tools called by the agent or the user, none named in an agent message). Scoring uses
the grader's missed actions (scoring only): a failed run is caught when a missed action's tool belongs to a listed
leaf. False flags: passed runs that would get a list.

    ~/dev/cuga-agent-gate/.venv/bin/python -I navigator_replay.py [--depth 2] [--no-links]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(sys.argv[0]).resolve().parent
EVAL = HERE.parents[2]
T2 = Path.home() / "dev/cuga-eval-tau2/benchmarks/tau2"
sys.path.insert(0, str(Path.home() / "dev/cuga-agent-gate/src"))
ESCALATION_Q = "Does the conversation show that {when}?"
SOLVED_Q = (
    "Has the customer confirmed that their original problem is now fixed (for example, service, mobile data or picture "
    "messages work again)?"
)
TOPIC_Q = "Is the customer's problem about this topic: {title}?"


def sections(text: str) -> list:
    """Markdown sections in order: level, title, body, parent index."""
    out, stack = [], []
    for line in text.split("\n"):
        m = re.match(r"^(#+)\s+(.*)", line)
        if m:
            lv = len(m.group(1))
            while stack and out[stack[-1]]["level"] >= lv:
                stack.pop()
            out.append(
                {"level": lv, "title": m.group(2).strip(), "body": "", "parent": stack[-1] if stack else None}
            )
            stack.append(len(out) - 1)
        elif out:
            out[-1]["body"] += line + "\n"
    for i, s in enumerate(out):
        s["children"] = [j for j, t in enumerate(out) if t["parent"] == i]
    return out


def load_tools() -> dict:
    out = {}
    for t in json.load(open(HERE / "telecom_tools.json")):
        t = t.get("function", t)
        out[t["name"].replace("user__", "")] = {
            "desc": t.get("description") or "",
            "user": t["name"].startswith("user__"),
        }
    return out


def leaf_tools(secs: list, tools: dict) -> dict:
    """Tools of each leaf section: names in its text, plus agent tools whose name words all occur in its text
    (by 5-letter prefix), so "check that the line is roaming enabled" maps to ``enable_roaming``."""
    out = {}
    for i, s in enumerate(secs):
        if s["children"] or not s["body"].strip():
            continue
        text = s["title"] + "\n" + s["body"]
        named = {n for n in tools if re.search(r"\b" + n + r"\b", text)}
        pre = {w[:5] for w in re.findall(r"[a-z]{3,}", text.lower())}
        matched = {
            n
            for n, t in tools.items()
            if not t["user"]
            and not n.startswith("get_")
            and n != "transfer_to_human_agents"
            and all(w[:5] in pre for w in n.split("_"))
        }
        if named or matched:
            out[i] = named | matched
    return out


def tools_in(text: str, tools: dict) -> set:
    named = {n for n in tools if re.search(r"\b" + n + r"\b", text)}
    pre = {w[:5] for w in re.findall(r"[a-z]{3,}", text.lower())}
    return named | {
        n
        for n, t in tools.items()
        if not t["user"]
        and not n.startswith("get_")
        and n != "transfer_to_human_agents"
        and all(w[:5] in pre for w in n.split("_"))
    }


def statement_items(build: dict, secs: list, tools: dict) -> dict:
    """Action statements per section index: the build's statements whose text uses a tool."""
    out = defaultdict(list)
    k = 0
    for d in build["policy_set"]["documents"]:
        for sec in d["sections"]:
            for st in sec.get("statements") or []:
                ts = tools_in(st["text"], tools)
                if ts:
                    out[k].append((st["id"], st["text"], ts))
            k += 1
    return out


def section_links(build: dict, secs: list) -> dict:
    """refers_to links as section index -> section indexes, mapped from build section ids by document order."""
    ids = [s["id"] for d in build["policy_set"]["documents"] for s in d["sections"]]
    if len(ids) != len(secs):
        raise SystemExit(f"build has {len(ids)} sections, document {len(secs)}")
    pos = {sid: i for i, sid in enumerate(ids)}
    out = defaultdict(set)
    for lk in build["build"].get("links") or []:
        if lk.get("type") != "refers_to":
            continue
        a = pos.get(lk["src"].split(":")[1])
        b = pos.get(lk["dst"].split(":", 1)[1])
        if a is not None and b is not None and a != b:
            out[a].add(b)
    return out


def subtree(secs: list, i: int) -> list:
    out = [i]
    for c in secs[i]["children"]:
        out += subtree(secs, c)
    return out


def walk(secs: list, links: dict, root: int, depth: int) -> list:
    """Sections of the case: the chapter's subtree, then the subtrees its sections refer to (up to depth hops)."""
    seen, frontier = [], [root]
    for _ in range(depth + 1):
        nxt = []
        for r in frontier:
            for i in subtree(secs, r):
                if i not in seen:
                    seen.append(i)
                    nxt += [j for j in links.get(i, ()) if j not in seen]
        frontier = nxt
    return seen


def chapter_of(i: int, secs: list) -> int:
    while secs[i]["parent"] is not None:
        i = secs[i]["parent"]
    return i


def runs(pattern: str = "test[12]_[AT]_s*") -> list:
    rows = []
    for f in sorted(glob.glob(str(T2 / f"logging_{pattern}/results/*.json"))):
        for r in json.load(open(f))["results"]:
            r["_run"] = Path(f).parts[-3].replace("logging_", "")
            rows.append(r)
    return rows


def visible(r: dict, user_calls: bool = False):
    """The end point and what the agent saw up to it: agent text, agent tool calls, user tool calls, customer text."""
    msgs = r["messages"]
    end = len(msgs)
    for k, m in enumerate(msgs):
        if m["role"] == "assistant" and any(
            tc["name"] == "transfer_to_human_agents" for tc in m.get("tool_calls") or []
        ):
            end = k
            break
    called, agent_text, customer, dialogue = set(), [], [], []
    for m in msgs[:end]:
        for tc in m.get("tool_calls") or []:
            if m["role"] == "assistant" or user_calls:  # the agent does not see the user's own tool calls
                called.add(tc["name"])
        if m["role"] == "tool" and m.get("requestor", "assistant") == "assistant":
            dialogue.append("tool result: " + (m.get("content") or "")[:300])
        elif (m.get("content") or "").strip() and m["role"] in ("assistant", "user"):
            dialogue.append(("agent: " if m["role"] == "assistant" else "customer: ") + m["content"][:600])
        c = (m.get("content") or "").strip()
        if c and m["role"] == "assistant":
            agent_text.append(c)
        elif c and m["role"] == "user":
            customer.append(c)
    if end < len(msgs):  # the navigator runs before the transfer call and sees its arguments
        tc = next(tc for tc in msgs[end]["tool_calls"] if tc["name"] == "transfer_to_human_agents")
        dialogue.append("agent asks to transfer: " + json.dumps(tc.get("arguments"))[:800])
    return end, called, "\n".join(agent_text), customer, "\n".join(dialogue)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=1)
    ap.add_argument("--no-links", action="store_true")
    ap.add_argument("--no-exits", action="store_true")
    ap.add_argument("--level", choices=["section", "statement"], default="statement")
    ap.add_argument("--runs", default="test[12]_[AT]_s*", help="run folders (logging_<glob>)")
    ap.add_argument("--user-calls", action="store_true", help="also count the user's tool calls as evidence")
    ap.add_argument("--out", default=str(HERE / "navigator_replay_results.json"))
    a = ap.parse_args()
    from dotenv import dotenv_values

    os.environ.setdefault("OPENROUTER_API_KEY", dotenv_values(EVAL / ".env").get("OPENROUTER_API_KEY") or "")
    from cuga.policy_layer.detectors import systemone_questions

    ask = systemone_questions()
    secs = sections((HERE / "telecom_policy.md").read_text())
    tools = load_tools()
    lt = leaf_tools(secs, tools)
    build = json.load(open(HERE / "builds/telecom.json"))
    links = {} if a.no_links else section_links(build, secs)
    ids = [x["id"] for d in build["policy_set"]["documents"] for x in d["sections"]]
    items = statement_items(build, secs, tools)
    if a.level == "section":
        items = {i: [(secs[i]["title"], secs[i]["title"], ts)] for i, ts in lt.items()}
    escalations = [
        (ids.index(e["from_section"]), re.sub(r"^(if|when)\s+", "", e["when"].strip(), flags=re.I))
        for p in build["build"]["procedures"]
        for e in p.get("escalations") or []
        if e.get("from_section") in ids and not a.no_exits
    ]
    print("escalation exits:", [(secs[i]["title"], w[:60]) for i, w in escalations])
    chapters = [
        i
        for i, s in enumerate(secs)
        if s["parent"] is None and sum(1 for j in subtree(secs, i) if j in lt) >= 3
    ]
    print("chapters:", [secs[i]["title"][:50] for i in chapters])
    for i, ts in lt.items():
        print(
            f"  leaf {secs[i]['title'][:45]:45} <- {secs[chapter_of(i, secs)]['title'][:30]:30} tools {sorted(ts)}"
        )

    rows = runs(a.runs)

    def judge(r):
        end, called, agent_text, customer, dialogue = visible(r, a.user_calls)
        first = "\n".join(customer[:2])
        p = ask(
            f"Customer messages:\n{first}",
            {f"c{i}": TOPIC_Q.format(title=secs[i]["title"]) for i in chapters},
        )
        root = max(chapters, key=lambda i: p.get(f"c{i}") if p.get(f"c{i}") is not None else -1)
        solved = ask("Last customer messages:\n" + "\n".join(customer[-2:]), {"solved": SOLVED_Q}).get(
            "solved"
        )
        walked = walk(secs, links, root, a.depth)
        steps = [it for i in walked for it in items.get(i, [])]
        exits = {f"e{k}": ESCALATION_Q.format(when=w) for k, (i, w) in enumerate(escalations) if i in walked}
        exit_p = (
            ask("Conversation (end):\n" + dialogue[-4000:], exits)
            if exits and (solved is None or solved < 0.5)
            else {}
        )
        if any(v is not None and v >= 0.5 for v in exit_p.values()):
            solved = 1.0  # a valid escalation exit: the transfer is what the SOP asks for
        handled = {
            it[0]
            for it in steps
            if any(t in called or re.search(r"\b" + t + r"\b", agent_text) for t in it[2])
        }
        pending = [it for it in steps if it[0] not in handled] if (solved is None or solved < 0.5) else []
        return {"root": root, "solved": solved, "steps": steps, "pending": pending, "end": end}

    with ThreadPoolExecutor(8) as pool:
        res = list(pool.map(judge, rows))

    t = Counter()
    per = []
    for r, j in zip(rows, res):
        passed = r["reward"] == 1.0
        kind = "pass" if passed else ("max_steps" if r["termination_reason"] == "max_steps" else "fail")
        missed = [
            c["action"]["name"]
            for c in (r["reward_info"] or {}).get("action_checks") or []
            if not c["action_match"]
        ]
        caught = any(m in it[2] for it in j["pending"] for m in missed)
        t[f"{kind}_n"] += 1
        t[f"{kind}_flagged"] += bool(j["pending"])
        t[f"{kind}_pending_leaves"] += len(j["pending"])
        if kind == "fail":
            t["fail_caught"] += caught
            t["fail_missed_leaf_in_walk"] += any(m in it[2] for it in j["steps"] for m in missed)
            t["fail_unsolved"] += bool(j["solved"] is None or j["solved"] < 0.5)
        per.append(
            {
                "run": r["_run"],
                "task": r["task_id"],
                "kind": kind,
                "missed": missed,
                "chapter": secs[j["root"]]["title"],
                "solved_p": j["solved"],
                "pending": [it[1][:120] for it in j["pending"]],
                "caught": caught,
            }
        )
    print(dict(t))
    n = t["fail_n"]
    print(
        f"failed runs (not max_steps): {n}; ended unsolved {t['fail_unsolved']}; missed section in walk "
        f"{t['fail_missed_leaf_in_walk']}; caught {t['fail_caught']} ({100 * t['fail_caught'] / max(n, 1):.0f}%)"
    )
    print(
        f"passed runs flagged: {t['pass_flagged']}/{t['pass_n']} (mean pending items when flagged "
        f"{t['pass_pending_leaves'] / max(t['pass_flagged'], 1):.1f}); failed runs mean pending "
        f"{t['fail_pending_leaves'] / max(t['fail_flagged'], 1):.1f}"
    )
    print("chapter picked:", Counter((p["task"].split("]")[0][1:], p["chapter"][:40]) for p in per))
    print("Kev:", dict(getattr(ask, "usage", {})))
    Path(a.out).write_text(json.dumps({"totals": dict(t), "per_run": per}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
