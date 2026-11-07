#!/usr/bin/env python3
"""Scan run folders for an agent that read answers or looked outside its workspace (it happened on 2026-11-01: benchmark mode
relaxes the sandbox).

  python3 -I benchmarks/policy_eval/tools/scan_run.py <run folder or name in harness/results> ...

Looks in ``trajectories/*.json``, in everything but the prompts, and in ``logs/*.log``. The lines where the code reports its
own paths are left out of the log scan (``OWN_LINES``). Prints each hit with its file and a short piece of the text (every hit but grep, then the first 20 grep hits). Exit code
1 if there is any hit. Reads only. A hit is a thing to read, not a verdict: a ``grep`` in a container on the task's own files
is a hit and is fine; a read of a grader's folder or file is not.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterator, List, Tuple

RESULTS = Path(__file__).resolve().parents[1] / "harness" / "results"
# Regular expressions, case-insensitive except where a pattern says (?-i:...). A hit is a thing to read, not a verdict. Three
# groups:
#  - ways to look at code or outside the workspace;
#  - words of a grader: a rubric, an answer or solution as a file, a key or an attribute, a grader's own folder;
#  - the folders of the four benchmarks that hold grader data.
# A bare "answer" or "solution" is no pattern: every final answer has one. The grader words are the shapes of files, keys and
# attributes. A name is "\b"-free on purpose: "\b" treats "_" as a letter, so it would miss expected_answer.json, and a
# letter before the word is what must not match, so the patterns use (?<![a-z]) and (?![a-z]).
PATTERNS = (
    r"inspect\.getsource",
    r"sys\.modules",
    r"subprocess",
    r"__import__",
    r"(?<![a-z])[ef]?grep(?![a-z])",  # also the agent's own search of its task files in a container: read it
    r"(?-i:/Users/)",  # a path, in this case: "GET /users/12" is not one
    r"~/dev",
    r"tasks\.py",
    r"results\.json",
    r"rubric",
    r"grader",
    r"(?<![a-z])oracle(?![a-z])",
    r"sop_verifier",
    r"answers?[._-]?(?:key|file|sheet)(?![a-z])",
    r"(?<![a-z])answers?\.(?:json|txt|csv|md|ya?ml)(?![a-z])",
    r"\.answers?(?![a-z])",
    r"""['"](?:answers?|solutions?)['"]""",
    r"ground[_ -]?truth(?![a-z])",
    r"gold[_-](?:answers?|labels?|state|standard)(?![a-z])",
    r"(?<![a-z])solutions?/",
    r"(?<![a-z])solutions?\.(?:sh|py|json|txt|md|ya?ml)(?![a-z])",
    r"(?<![a-z])solve\.sh(?![a-z])",
    # the audit of a package holds decision tests and the verdicts on real runs; the package file holds the tests
    r"AUDIT\.md",
    r"package\.json",
    # grader data of the four benchmarks
    r"automationbench/",  # AutomationBench: the repository and its domains with the assertions
    r"enterpriseops_gym",  # IT service: the tasks, the oracle and the verifiers
    r"itsm_oracle",
    r"handbook-sample",  # HANDBOOK: the tasks, with tests/ in each
    r"/tests(?![a-z])",
    r"(?<![a-z])tests/[\w.-]+\.[a-z]{1,5}(?![a-z])",  # a file in a tests folder; "unit tests/integration tests" is not one
    r"(?<![a-z])(?:ls|cd|cat|find|head|tail|less|open|sed|rg)(?![a-z])[^|;&\n]*(?<![a-z])tests/?(?![\w])",
    r"(?<![a-z])test\.sh(?![a-z])",
    r"task_prompt\.txt",
    r"tau2-bench",  # τ²: the tasks with their evaluation criteria
    r"(?:tau2/data|data/tau2)",
    r"evaluation_criteria",
)
FOUND = re.compile("|".join(f"(?:{p})" for p in PATTERNS), re.I)
# Lines of the code, not of the agent: where its settings and data come from, a library's warning about itself.
OWN_LINES = re.compile(
    r"cuga\.config:<module>|tau2\.utils\.utils:<module>|find_tools:_load_default_find_tools_few_shot"
    r"|/site-packages/|^\s*warnings\.warn"
)
SNIPPET = 160
QUIET = {
    "grep",
    "egrep",
    "fgrep",
}  # the agent searches its own files with these: shown last, and not all of them


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if key != "prompts":  # the system prompt and the policy text: not what the agent did
                yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _hits_in(text: str) -> Iterator[Tuple[str, str]]:
    for match in FOUND.finditer(text):
        start = max(0, match.start() - SNIPPET // 2)
        yield match.group(0), text[start : start + SNIPPET].replace("\n", " ")


def scan(folder: Path) -> List[Tuple[str, str, str]]:
    """Hits as (file, pattern, snippet)."""
    hits: List[Tuple[str, str, str]] = []
    for path in sorted((folder / "trajectories").glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except ValueError:
            hits.append((path.name, "unreadable", ""))
            continue
        for text in _strings(data):
            hits += [(path.name, pattern, snippet) for pattern, snippet in _hits_in(text)]
    for path in sorted((folder / "logs").glob("*.log")):
        for line in path.read_text(errors="replace").splitlines():
            if not OWN_LINES.search(line):
                hits += [(path.name, pattern, snippet) for pattern, snippet in _hits_in(line)]
    return hits


def main(argv: List[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    total = 0
    for name in argv:
        folder = Path(name) if Path(name).is_dir() else RESULTS / name
        if not (folder / "logs").is_dir() and not (folder / "trajectories").is_dir():
            print(f"{name}: no logs and no trajectories here")
            return 2
        hits = scan(folder)
        total += len(hits)
        print(f"{folder.name}: {len(hits)} hits {dict(Counter(pattern for _, pattern, _ in hits))}")
        loud = [h for h in hits if h[1].lower() not in QUIET]
        quiet = [h for h in hits if h[1].lower() in QUIET]
        for file, pattern, snippet in loud:  # every hit but grep: grep must not hide one of them
            print(f"  {file[:60]} [{pattern}] {snippet}")
        for file, pattern, snippet in quiet[:20]:
            print(f"  {file[:60]} [{pattern}] {snippet}")
        if len(quiet) > 20:
            print(f"  ... and {len(quiet) - 20} more grep hits")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
