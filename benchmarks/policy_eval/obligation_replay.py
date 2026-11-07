#!/usr/bin/env python3
"""Obligation replay (stabilization task 4.3): may the obligation ledger send follow-ups?

The ledger (``cuga.policy_layer.obligations``, design spec section 5) checks at the final reply what must exist. It is off by
default. This offline replay decides whether it may send follow-ups (level 2) or only record (level 1). No agent runs and no
benchmark is started: finished arm-A runs are read, their tool calls are given to the real ledger, and a real model binds the
cases at the final reply, as a real run would.

    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/obligation_replay.py plan    # which runs, no model call
    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/obligation_replay.py replay  [--bench B] [--limit N]
    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/obligation_replay.py judge   [--bench B]
    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/obligation_replay.py measure  # results.json
    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/obligation_replay.py report   # REPORT.md

Steps, in files of ``obligation_replay/``:

``replay``  one ledger per run and producer (``package``, ``request``, ``duty``), built by ``build_runtime`` on a profile with
            that one producer and every item at level ``follow_up``: what would be sent at level 2. The run's tool calls go to
            ``after_tool_call`` in order and the final answer to ``before_reply``. The binding call and the request producer's
            call use the real prompts and ``aws/gpt-oss-120b`` (``max_tokens`` 16000 for the binding). Nothing from a grader
            enters here. Written to ``replay.jsonl``.
``judge``   labels, for measurement only. A model maps each item that would be sent to the checks of the run (the grader's
            rubric items, verifiers or assertions), blind to which checks passed; for a check that failed and that no sent item
            names, a second call says which items of the ledger cover it and the cause. ``writable`` says whether a write of
            the agent could have met a check. Written to ``judge.jsonl``.
``measure`` the numbers per benchmark and producer: false-open rate, recall, run-level rates, status counts, value origins,
            cost, and the level that the rule allows. Written to ``results.json``.
``report``  ``REPORT.md``, the whole file, made from ``results.json`` alone, so the numbers cannot drift.

The rule (design section 5): false-open rate <= 10% of the checks the run passed and recall >= 30% of the failed checks that a
write could have met, per benchmark and producer: level 2. Otherwise level 1. A pass here is on tuning or seen sets (marked with
``audit_report.basis_of``), so it is never a held-out result.

Cost: every new model call goes to the ledger of ``benchmarks/policy_pilot_ledger.jsonl`` and counts against ``CAP``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import sys
import threading
import time
import warnings
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
EVAL = BENCH.parent
OUT = HERE / "obligation_replay"
PACKAGES = HERE / "packages"
for p in (str(BENCH), str(HERE), str(HERE / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

HANDBOOK_TASKS = Path.home() / "dev/untrusted/handbook-sample/tasks"
TAU2 = Path.home() / "dev/cuga-eval-tau2/benchmarks/tau2"

DEEPSEEK = "azure/DeepSeek-V4-Pro"
MODEL = "aws/gpt-oss-120b"  # the binder, the request producer and the judge
BINDER_TOKENS = 16000
TOKEN_LIMIT_SHARE = 0.98  # an answer of this share of ``max_tokens`` or more was cut
HANDCHECK_SALT = "v3"  # an earlier judge prompt and an earlier gate commit each had their own sample; this one is on the final data
HANDCHECK_PER_BENCH = {  # sent items read by hand, per benchmark and producer
    "handbook|package": 10,
    "itsm|request": 14,
    "itsm|duty": 6,
    "itsm|package": 5,
    "tau2-telecom|request": 1,
}
FLUSH_EVERY = 40  # new calls between two lines of the cost ledger
CAP = 4.0  # dollars for the whole task, the judge included
BASELINE_LEDGER = 1631.5558  # the ledger total before this task
PRODUCERS = ("package", "request", "duty")
BENCHMARKS = ("handbook", "itsm", "tau2-telecom")
FALSE_OPEN_MAX = (1, 10)  # <= 10%
RECALL_MIN = (3, 10)  # >= 30%
MIN_RECALL_DENOMINATOR = (
    5  # fewer failed checks a write could meet: recall is not known, whatever the count of hits
)
STATUSES = ("met", "open", "held", "unknown", "wrong", "unbound", "not_applicable")


# -- model: a cache, a meter and the ledger of the cost -----------------------------------------------------------------


class BudgetStop(RuntimeError):
    """The cap of the task is reached."""


class Meter:
    """What the new calls of this process cost. A cached answer costs nothing here: its tokens were paid for when it was made,
    and the cache holds them, so the cost per run is still known."""

    def __init__(self, cap: float = CAP, price: Optional[Callable[[str, int, int], float]] = None):
        self.cap, self.price = cap, price or price_of
        self.spent = 0.0
        self.pending: Dict[str, Dict[str, int]] = {}
        self.lock = threading.Lock()
        self.new_calls = 0
        self.failed_calls = 0
        self.flush_to_ledger = False  # the command line turns it on; a test never writes the cost ledger

    def charge(self, model: str, tokens_in: int, tokens_out: int) -> None:
        with self.lock:
            self.spent += self.price(model, tokens_in, tokens_out)
            self.new_calls += 1
            row = self.pending.setdefault(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
            row["calls"] += 1
            row["input_tokens"] += tokens_in
            row["output_tokens"] += tokens_out
            due = self.new_calls % FLUSH_EVERY == 0
        if due and self.flush_to_ledger:
            self.flush()

    def check(self) -> None:
        if self.spent >= self.cap:
            raise BudgetStop(f"the cap of ${self.cap} for this task is reached (${self.spent:.3f} spent)")

    def flush(self, kind: str = "obligation_replay", name: str = "task 4.3") -> None:
        with self.lock:
            pending, self.pending = self.pending, {}
        if not pending:
            return
        import policy_pilot_costs as costs

        for model, row in pending.items():
            costs.record(kind, name, policy={**row, "model": model})


GATE_SRC: Optional[Path] = (
    None  # a copy of the gate repo's src/ at one commit (``git archive``), put before the installed one
)


def use_gate_src(src: Path) -> None:
    """Run the replay on the ledger of a clean copy of one commit. The copy is made with ``git archive <sha> src | tar -x -C
    <dir>`` and holds ``GATE_COMMIT`` next to ``src``. The working tree of the gate repo may hold unfinished changes."""
    global GATE_SRC
    GATE_SRC = Path(src).resolve()
    sys.path.insert(0, str(GATE_SRC))


def gate_commit() -> str:
    """The commit of the gate repo that the replay ran on (the code of the ledger)."""
    import subprocess

    if GATE_SRC is not None:
        marker = GATE_SRC.parent / "GATE_COMMIT"
        return marker.read_text().strip() if marker.exists() else "unknown"

    done = subprocess.run(
        ["git", "-C", str(Path.home() / "dev/cuga-agent-gate"), "rev-parse", "--short=9", "HEAD"],
        capture_output=True,
        text=True,
    )
    return done.stdout.strip() or "unknown"


def ledger_spent() -> float:
    import policy_pilot_costs as costs

    return costs.spent() - BASELINE_LEDGER


def price_of(model: str, tokens_in: int, tokens_out: int) -> float:
    import policy_pilot_costs as costs

    return costs.usage_cost(model, {"input_tokens": tokens_in, "output_tokens": tokens_out})


class Cache:
    """Answers by the hash of the whole call (model, ``max_tokens``, system and user text), in a JSON-lines file."""

    def __init__(self, path: Optional[Path]):
        self.path, self.lock = path, threading.Lock()
        self.data: Dict[str, Dict[str, Any]] = {}
        if path is not None and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.data[row["k"]] = row

    @staticmethod
    def key(model: str, max_tokens: Optional[int], system: str, user: str) -> str:
        return hashlib.sha256(f"{model}\n{max_tokens}\n{system}\n{user}".encode()).hexdigest()[:32]

    def get(self, k: str) -> Optional[Dict[str, Any]]:
        return self.data.get(k)

    def put(self, row: Dict[str, Any]) -> None:
        with self.lock:
            self.data[row["k"]] = row
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")


Transport = Callable[
    [str, str, str, Optional[int]], Tuple[str, int, int]
]  # (model, system, user, max_tokens)


def gateway_transport(timeout: float = 75.0) -> Transport:
    """The OpenAI-compatible gateway, with a read timeout, as the policy layer calls it (``llm.openai_json_model``)."""
    from openai import OpenAI

    client = OpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL"),
        api_key=os.environ.get("OPENAI_API_KEY"),
        timeout=timeout,
        max_retries=0,
    )

    def call(model: str, system: str, user: str, max_tokens: Optional[int]) -> Tuple[str, int, int]:
        extra = {"max_tokens": max_tokens} if max_tokens else {}
        r = client.chat.completions.create(
            model=model,
            temperature=0,
            **extra,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        usage = r.usage
        return (
            r.choices[0].message.content or "",
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )

    return call


class CachedModel:
    """``(system, user) -> text``. ``usage`` counts every call of this object, cached or new, so a run's cost is the same on a
    second pass. A call that fails after its retries raises: the ledger counts that as a failed binding."""

    def __init__(
        self,
        name: str,
        cache: Cache,
        meter: Meter,
        transport: Optional[Transport],
        max_tokens: Optional[int] = None,
        retries: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.model_name, self.cache, self.meter, self.transport = name, cache, meter, transport
        self.max_tokens, self.retries, self.sleep = max_tokens, retries, sleep
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        self.failed = 0

    def __call__(self, system: str, user: str) -> str:
        k = Cache.key(self.model_name, self.max_tokens, system, user)
        row = self.cache.get(k)
        if row is None:
            if self.transport is None:
                raise RuntimeError(
                    "no model call is possible here (no transport) and the answer is not in the cache"
                )
            last: Optional[Exception] = None
            for attempt in range(self.retries):
                self.meter.check()
                try:
                    text, tokens_in, tokens_out = self.transport(
                        self.model_name, system, user, self.max_tokens
                    )
                    break
                except BudgetStop:
                    raise
                except Exception as exc:  # noqa: BLE001 - a gateway hang or a 5xx: wait, ask again
                    last = exc
                    self.sleep(3 * (attempt + 1))
            else:
                self.failed += 1
                self.meter.failed_calls += 1
                raise RuntimeError(
                    f"the gateway call failed after {self.retries} tries: {type(last).__name__}"
                )
            row = {"k": k, "text": text, "in": tokens_in, "out": tokens_out}
            self.cache.put(row)
            self.meter.charge(self.model_name, tokens_in, tokens_out)
        self.usage["calls"] += 1
        self.usage["input_tokens"] += row["in"]
        self.usage["output_tokens"] += row["out"]
        return row["text"]


class ReplayModels:
    """The model factory of ``build_runtime``: every model the wiring asks for is the one cached, metered gateway model."""

    def __init__(
        self,
        cache: Cache,
        meter: Meter,
        transport: Optional[Transport],
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.cache, self.meter, self.transport, self.sleep = cache, meter, transport, sleep
        self.made: List[CachedModel] = []

    def json_model(self, model: str, **kwargs: Any) -> CachedModel:
        made = CachedModel(
            model, self.cache, self.meter, self.transport, kwargs.get("max_tokens"), sleep=self.sleep
        )
        self.made.append(made)
        return made

    def openrouter_json_model(self, model: str, **kwargs: Any) -> Any:
        raise RuntimeError("the replay uses the gateway only")

    def questions(self, model: str) -> Any:
        raise RuntimeError("the replay builds no checker")

    detector = questions


# -- the runs: one common shape ------------------------------------------------------------------------------------------


@dataclass
class Check:
    id: str
    text: str
    passed: bool
    writable: Optional[bool] = (
        None  # set where the benchmark says it (a user action is not a write of the agent)
    )


@dataclass
class Run:
    bench: str
    run: str  # the folder, or the file for tau2
    task: str
    trial: Optional[int]
    agent_model: str
    policy: str  # the policy id that names the package
    package: Path
    request: str
    specs: List[Dict[str, Any]]
    tools_in_run: Optional[List[str]]
    calls: List[Dict[str, Any]]
    answer: str
    today: str
    checks: List[Check]
    passed: bool
    source: str = ""

    @property
    def uid(self) -> str:
        return f"{self.bench}|{self.run}|{self.task}"


def _hash_order(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _result_text(value: Any, error: bool = False) -> Any:
    """What a hook gets after a call. A call that the saved file marks as an error becomes an error result."""
    if error:
        return {"error": value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)[:500]}
    return value


def handbook_runs(root: Optional[Path] = None) -> List[Run]:
    """The saved arm-A runs ``hba_*_A`` (Gemini 3.8) and ``hbq_*_A`` (gpt-oss): 3 tasks, 3 trials each."""
    from harness.result import from_legacy

    root = root or BENCH / "handbook" / "results"
    runs: List[Run] = []
    folders = sorted(root.glob("hba_*_A_t*")) + sorted(root.glob("hbq_*_A_t*"))
    for folder in folders:
        for path in sorted(folder.glob("*.json")):
            raw = _json(path)
            res = from_legacy(path)
            task = raw["task"]
            package = PACKAGES / "handbook" / task / "skill_v1" / "package.json"
            if not package.exists() or res.score is None:
                continue
            specs = _json(BENCH / "handbook" / "tools" / f"{task}.json")
            specs = specs if isinstance(specs, list) else specs.get("tools", [])
            request = (HANDBOOK_TASKS / task / "instruction.md").read_text(encoding="utf-8")
            checks = [
                Check(str(r.get("id") or f"r{i}"), str(r.get("text") or ""), bool(r.get("pass")))
                for i, r in enumerate(raw.get("rubrics") or [])
            ]
            runs.append(
                Run(
                    bench="handbook",
                    run=folder.name,
                    task=task,
                    trial=res.trial,
                    agent_model=str(res.agent_model),
                    policy=task,
                    package=package,
                    request=request,
                    specs=specs,
                    tools_in_run=None,
                    calls=[
                        {"tool": c["tool"], "args": c.get("args") or {}, "result": c.get("result")}
                        for c in raw.get("tool_calls") or []
                    ],
                    answer=str(raw.get("answer") or ""),
                    today=str(raw.get("world_time") or "")[:10],
                    checks=checks,
                    passed=bool(res.score.passed),
                    source=str(path.relative_to(BENCH)),
                )
            )
    return runs


def itsm_runs(models: Sequence[str] = (MODEL,), root: Optional[Path] = None) -> List[Run]:
    """Saved arm-A runs of the IT service tasks, by agent model. A run whose policy has no package is left out."""
    from harness.result import from_legacy

    eog = BENCH / "enterpriseops_gym"
    root = root or eog / "results"
    tasks = {t["task_id"]: t for t in _json(eog / "tasks" / "itsm_oracle.json")}
    specs = _json(eog / "tasks" / "itsm_tools.json")
    runs: List[Run] = []
    for path in sorted(root.glob("*/A_*.json")):
        raw = _json(path)
        task = tasks.get(raw.get("task_id"))
        if task is None or str(raw.get("model")) not in models or not raw.get("verifiers"):
            continue
        version = str(raw.get("policy_version") or task["_policy_hash"])
        package = PACKAGES / "itsm" / version / "skill_v1" / "package.json"
        if not package.exists():
            continue
        oracle = task["verifiers"]
        oracle = json.loads(oracle) if isinstance(oracle, str) else oracle
        checks = []
        for i, v in enumerate(raw["verifiers"]):
            query = ""
            if i < len(oracle) and oracle[i].get("name") == v.get("name"):
                query = str((oracle[i].get("validation_config") or {}).get("query") or "")
            text = f"{v.get('name')}: the database holds this ({v.get('expected')} expected): {query}".strip()
            checks.append(Check(f"v{i}", text, bool(v.get("passed"))))
        res = from_legacy(path)
        calls = [
            {
                "tool": c["tool"],
                "args": c.get("args") or {},
                "result": _result_text(c.get("result"), bool(c.get("error"))),
            }
            for c in raw.get("tool_calls") or []
        ]
        runs.append(
            Run(
                bench="itsm",
                run=path.parent.name,
                task=raw["task_id"],
                trial=res.trial,
                agent_model=str(raw.get("model")),
                policy=version,
                package=package,
                request=task["user_prompt"],
                specs=specs,
                tools_in_run=list(raw.get("tools") or task["selected_tools"]),
                calls=calls,
                answer=str(raw.get("answer") or ""),
                today="",
                checks=checks,
                passed=bool(raw.get("passed")),
                source=str(path.relative_to(BENCH)),
            )
        )
    return runs


def tau2_runs(
    tags: Sequence[str] = ("dev1_A", "dev2_A", "test1_A", "test2_A"), root: Optional[Path] = None
) -> List[Run]:
    """Saved arm-A runs of τ² Telecom. The agent's tools only: the user's tools (``user__``) belong to the customer's phone,
    so the specs hold none. Checks are the environment assertions of the grader (the reward's basis)."""
    root = root or TAU2
    spec_file = HERE / "tau2" / "telecom_tools.json"
    specs = [t for t in _json(spec_file) if not str(t.get("name", "")).startswith("user__")]
    package = PACKAGES / "tau2_telecom" / "telecom" / "skill_v1" / "package.json"
    runs: List[Run] = []
    for tag in tags:
        for path in sorted(root.glob(f"logging_{tag}_s*/results/tau2_*.json")):
            data = _json(path)
            for r in data.get("results") or []:
                msgs, pending, calls = r.get("messages") or [], [], []
                user_text: List[str] = []
                answer = ""
                for m in msgs:
                    role = m.get("role")
                    if role == "assistant":
                        if m.get("content"):
                            answer = str(m["content"])
                        pending += [
                            c
                            for c in m.get("tool_calls") or []
                            if c.get("requestor", "assistant") == "assistant"
                        ]
                    elif role == "tool" and m.get("requestor") == "assistant" and pending:
                        c = pending.pop(0)
                        calls.append(
                            {"tool": c["name"], "args": c.get("arguments") or {}, "result": m.get("content")}
                        )
                    elif (
                        role == "user"
                        and isinstance(m.get("content"), str)
                        and not m["content"].startswith("###")
                    ):
                        user_text.append(m["content"])
                info = r.get("reward_info") or {}
                checks = []
                for i, e in enumerate(info.get("env_assertions") or []):
                    a = e.get("env_assertion") or {}
                    checks.append(
                        Check(
                            f"e{i}",
                            f"the customer's device state: {a.get('func_name')}({json.dumps(a.get('arguments') or {})}) is "
                            f"{a.get('assert_value')}",
                            bool(e.get("met")),
                        )
                    )
                if not checks or r.get("reward") is None:
                    continue
                runs.append(
                    Run(
                        bench="tau2-telecom",
                        run=path.parent.parent.name,
                        task=str(r["task_id"]),
                        trial=None,
                        agent_model=str(r.get("agent_model")),
                        policy="telecom",
                        package=package,
                        request="\n".join(user_text),
                        specs=specs,
                        tools_in_run=None,
                        calls=calls,
                        answer=answer,
                        today="",
                        checks=checks,
                        passed=float(r["reward"]) >= 1,
                        source=str(path.relative_to(root.parent.parent)),
                    )
                )
    return runs


def sample(runs: Sequence[Run], n: Optional[int]) -> List[Run]:
    """``n`` runs by the hash of their identity, never by an outcome; all of them when ``n`` is ``None`` or large enough."""
    order = sorted(runs, key=lambda r: _hash_order(r.uid + "|" + r.source))
    return order if n is None else order[:n]


# -- the ledger on one run ----------------------------------------------------------------------------------------------


def profile(producer: str, package: bool) -> Dict[str, Any]:
    """The profile of one replay: one producer, every item at ``follow_up`` (what level 2 would send). Nothing else is on."""
    return {
        "package": "package.json" if package else None,
        "sources": {"request": True},
        "decisions": {"mode": "off"},
        "checkers": {"rules": "off", "gate": {"mode": "off"}, "verifier": {"mode": "off"}},
        "organizers": {
            "procedure_tools": "off",
            "guide": "off",
            "loop": "off",
            "sop_tracker": "off",
            "navigator": "off",
            "requirements_tracker": "off",
        },
        "obligations": {"producers": [producer], "model": MODEL, "item_level": "follow_up"},
    }


class EmptyProducer(Exception):
    """The package gives this producer no obligation (a policy with no duty rule)."""


def build_ledger(run: Run, producer: str, models: Any) -> Any:
    from cuga.policy_layer.package import load_package
    from cuga.policy_layer.policy_config import PolicyConfig
    from cuga.policy_layer.runtime import RunContext, RuntimeWiringError, build_runtime

    uses_package = producer in ("package", "duty")
    pkg = load_package(run.package) if uses_package else None
    ctx = RunContext(
        task_id=run.task,
        request=run.request,
        tool_specs=run.specs,
        tools_in_run=run.tools_in_run,
        world_time=run.today,
        policy_version=run.policy,
        message_tool="",
    )
    cfg = PolicyConfig.from_dict(profile(producer, uses_package))
    try:
        parts = build_runtime(cfg, pkg, ctx, models=models)
    except RuntimeWiringError as exc:
        if "give no obligation" in str(exc) or "no obligations" in str(exc):
            raise EmptyProducer(str(exc)) from exc
        raise
    return parts.components["obligations"]


def _case_name(item: Any) -> str:
    from cuga.policy_layer.obligations import _case_label

    return _case_label(item.case) or item.case.name or ""


def snapshot(ledger: Any, producer: str = "package") -> Dict[str, Any]:
    """The items of a ledger after the final reply, as plain data. ``sent``: open and of a level that sends; the follow-up
    would name it (the follow-up text lists 40, and then counts the rest)."""
    from cuga.policy_layer.obligations import OPEN, UNBOUND, _known_values, _line

    items: List[Dict[str, Any]] = []
    for n, it in enumerate(ledger.items):
        sent = it.status == OPEN and ledger._may_send(it)
        defined = len(it.values)
        known = sum(1 for v in it.values.values() if v.get("value") not in (None, ""))
        row = {
            "n": n,
            "ob": it.ob.id,
            "case": _case_name(it),
            "status": it.status,
            "tools": list((it.ob.effect or {}).get("tools") or []),
            "kind": (it.ob.effect or {}).get("kind"),
            "sent": sent,
            "values": defined,
            "known": known,
            "shown": bool(_known_values(it)),
            "origins": sorted({str(v.get("from")) for v in it.values.values()}),
        }
        if sent:
            row["line"] = _line(it)[:500]
        if (
            producer != "package"
        ):  # these obligations are made in the run, so the package has no text for them
            source = it.ob.source if isinstance(it.ob.source, dict) else {}
            quote = re.sub(r"\s+", " ", str(source.get("quote") or "")).strip()[:140]
            row["text"] = f"{','.join(row['tools']) or row['kind']}: {quote}"
        items.append(row)
    unbound = [r for r in ledger.records if r.get("outcome") == UNBOUND]
    return {"items": items, "unbound": len(unbound)}


def replay_run(run: Run, producer: str, models: ReplayModels) -> Dict[str, Any]:
    """One ledger on one run. A failed binding or request call is kept as the result, never a crash."""
    from cuga.policy_layer.obligations import UNBOUND  # noqa: F401  (import check)

    out: Dict[str, Any] = {
        "uid": run.uid,
        "producer": producer,
        "bench": run.bench,
        "run": run.run,
        "task": run.task,
    }
    mark = len(models.made)
    try:
        ledger = build_ledger(run, producer, models)
    except EmptyProducer as exc:
        return {**out, "status": "empty", "why": str(exc)[:200], "items": [], "unbound": 0, "cost_usd": 0.0}
    errors: List[str] = []
    ledger.on_user_message(run.request, None)
    for call in run.calls:
        ledger.after_tool_call(call["tool"], call["args"], call["result"])
    result = ledger.before_reply(run.answer)
    for rec in ledger.records:
        if rec.get("outcome") == "error":
            errors.append(f"{rec.get('rule_id')}: {rec.get('reason')}"[:300])
    snap = snapshot(ledger, producer)
    from cuga.policy_layer.obligations import _failed_call

    worked = {
        c["tool"] for c in run.calls if not _failed_call(c["result"])
    }  # tools with a successful call in this run
    for it in snap["items"]:
        it["prior_call"] = bool(set(it["tools"]) & worked)
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    for made in models.made[mark:]:
        for k in usage:
            usage[k] += made.usage[k]
    cost = price_of(MODEL, usage["input_tokens"], usage["output_tokens"])
    binding = "n/a"
    if producer == "package":
        binding = "failed" if any(e.startswith("binding:") for e in errors) else "ok"
    if producer == "request":
        binding = "failed" if any(e.startswith("request:") for e in errors) else "ok"
    return {
        **out,
        "status": "ok",
        "binding": binding,
        "errors": errors,
        "follow_up": bool(getattr(result, "message", None)),
        **snap,
        "usage": usage,
        "cost_usd": round(cost, 5),
    }


# -- the labels: a judge, for measurement only ---------------------------------------------------------------------------

MAP_SYSTEM = (
    "You compare work items with the checks of a grader. A check tests one fact of the final state of a task: a record, a "
    "file, a message or an action. For each item give two lists of check ids. \"meets\": the checks that the work of the "
    "item would help to pass: the same kind of action on the same kind of record for the same case (person, ticket, "
    "customer, file). Ignore the exact values the item shows, they are a reviewer's guess; a check that tests more details "
    "than the item names still matches. \"breaks\": the checks that say the work must NOT exist (no event, no row, no "
    "message, no email) for the case that the item asks to act on, so that doing the item would make them fail. A check "
    "about another case, another kind of record or another action is in neither list. Use only the text given. Answer "
    "JSON only."
)
MAP_USER = """Checks:
{checks}

Items (work a reviewer says is still missing):
{items}

Return {{"items": {{"<item number>": {{"meets": ["<check id>", ...], "breaks": ["<check id>", ...]}}}}}}. Use [] for a list with none."""

COVER_SYSTEM = (
    "You decide which items of a list ask for the work that a grader's check tests. A check tests one fact of the final "
    "state of a task. An item covers a check when doing the item correctly would be what the check looks for: the same "
    "object and the same action. A related topic is not enough. Answer JSON only."
)
COVER_USER = """Checks that the agent did not meet:
{checks}

Items of the ledger (number, status, tool, text):
{items}

Return {{"checks": {{"<check id>": [<item number>, ...]}}}}. Use [] for a check that no item covers."""

WRITABLE_SYSTEM = (
    "You label the checks of a grader. For each check, say whether the agent could have made it true by calling one of its "
    "write tools (a tool that creates, updates, sends, posts or writes something), given only the tool names. Say false for "
    "a check that is about a reply text, that is about what must not happen, that only reads, or that needs an action of "
    "the user or of another party. Answer JSON only."
)
WRITABLE_USER = """Write tools of the agent:
{tools}

Checks:
{checks}

Return {{"checks": {{"<check id>": true or false}}}}."""


def _check_lines(checks: Sequence[Check], limit: int = 900) -> str:
    flat = [(c.id, re.sub(r"\s+", " ", c.text)[:limit]) for c in checks]
    return "\n".join(f"{cid}: {text}" for cid, text in flat)


def _json_of(text: str) -> Dict[str, Any]:
    from cuga.policy_layer.llm import parse_json

    data = parse_json(text)
    return data if isinstance(data, dict) else {}


def write_tools(run: Run) -> List[str]:
    from cuga.policy_layer.ruleset import is_write_tool

    in_run = set(run.tools_in_run) if run.tools_in_run is not None else None
    return sorted(
        t["name"] for t in run.specs if (in_run is None or t["name"] in in_run) and is_write_tool(t["name"])
    )


def label_writable(run: Run, model: Callable[[str, str], str]) -> Dict[str, bool]:
    """Which checks a write of the agent could have met. The benchmark's own say (``Check.writable``) wins."""
    labels = {c.id: c.writable for c in run.checks if c.writable is not None}
    todo = [c for c in run.checks if c.id not in labels]
    if todo:
        data = _json_of(
            model(
                WRITABLE_SYSTEM,
                WRITABLE_USER.format(tools=", ".join(write_tools(run)), checks=_check_lines(todo)),
            )
        )
        got = data.get("checks") if isinstance(data.get("checks"), dict) else {}
        for c in todo:
            labels[c.id] = bool(got.get(c.id)) if c.id in got else False
    return {k: bool(v) for k, v in labels.items()}


def map_sent(
    run: Run, sent: Sequence[Dict[str, Any]], model: Callable[[str, str], str]
) -> Dict[int, Dict[str, List[str]]]:
    """For each sent item, the checks its work would help to pass (``meets``) and the checks it would make fail (``breaks``),
    judged without the outcome of the checks."""
    if not sent:
        return {}
    items = "\n".join(f"{i['n']}: {i['line']}" for i in sent)
    data = _json_of(model(MAP_SYSTEM, MAP_USER.format(checks=_check_lines(run.checks), items=items)))
    got = data.get("items") if isinstance(data.get("items"), dict) else {}
    known = {c.id for c in run.checks}
    out: Dict[int, Dict[str, List[str]]] = {}
    for i in sent:
        entry = got.get(str(i["n"]))
        entry = entry if isinstance(entry, dict) else {}
        out[i["n"]] = {
            kind: [c for c in (entry.get(kind) or []) if isinstance(c, str) and c in known]
            if isinstance(entry.get(kind), list)
            else []
            for kind in ("meets", "breaks")
        }
    return out


def ob_text(pkg_obs: Dict[str, Any], ob_id: str) -> str:
    ob = pkg_obs.get(ob_id)
    if ob is None:
        return ""
    source = ob.source if isinstance(ob.source, dict) else {}
    quote = re.sub(r"\s+", " ", str(source.get("quote") or "")).strip()[:140]
    tools = ",".join((ob.effect or {}).get("tools") or []) or str((ob.effect or {}).get("kind") or "")
    return f"{tools}: {quote}"


def cover(
    run: Run,
    failed: Sequence[Check],
    items: Sequence[Dict[str, Any]],
    texts: Dict[str, str],
    model: Callable[[str, str], str],
) -> Dict[str, List[int]]:
    """For failed checks that no sent item names: which items of the ledger (any status) test the same work."""
    if not failed or not items:
        return {c.id: [] for c in failed}
    seen, lines = set(), []
    for it in items:
        key = (it["ob"], it["status"])
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"{it['n']} ({it['status']}) {it.get('text') or texts.get(it['ob'], it['ob'])}")
    data = _json_of(
        model(COVER_SYSTEM, COVER_USER.format(checks=_check_lines(failed), items="\n".join(lines)))
    )
    got = data.get("checks") if isinstance(data.get("checks"), dict) else {}
    by_key: Dict[Tuple[str, str], List[int]] = defaultdict(list)
    for it in items:
        by_key[(it["ob"], it["status"])].append(it["n"])
    out: Dict[str, List[int]] = {}
    for c in failed:
        ids = got.get(c.id)
        picked = [x for x in ids if isinstance(x, int)] if isinstance(ids, list) else []
        expand: List[int] = []
        for n in picked:
            row = next((i for i in items if i["n"] == n), None)
            if row is not None:
                expand += by_key[(row["ob"], row["status"])]
        out[c.id] = sorted(set(expand))
    return out


# -- the numbers -------------------------------------------------------------------------------------------------------


def wilson(k: int, n: int, z: float = 1.96) -> Tuple[Optional[float], Optional[float]]:
    if n == 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def decide(false_open: Tuple[int, int], recall: Tuple[int, int]) -> Tuple[int, str]:
    """The rule, with whole numbers so that 10% and 30% are exact: level 2 when false-open <= 10% of passed checks and recall
    >= 30% of the failed checks that a write could have met; otherwise level 1. A rate with no denominator cannot be shown,
    so it does not pass, and recall over fewer than ``MIN_RECALL_DENOMINATOR`` checks is not known. The numbers may be
    ``Fraction`` or float (the views per task use them); the test is the same."""
    fk, fn = false_open
    rk, rn = recall
    if fn == 0:
        return 1, "no passed check, so the false-open rate is not known"
    if rn == 0:
        return 1, "no failed check that a write could have met, so recall is not known"
    ok_false = fk * FALSE_OPEN_MAX[1] <= fn * FALSE_OPEN_MAX[0]
    ok_recall = rk * RECALL_MIN[1] >= rn * RECALL_MIN[0]
    why = []
    if not ok_false:
        why.append("false-open above 10%")
    if rn < MIN_RECALL_DENOMINATOR:
        why.append(f"recall is not known: only {rn} failed checks that a write could have met")
    elif not ok_recall:
        why.append("recall below 30%")
    if ok_false and ok_recall and rn >= MIN_RECALL_DENOMINATOR:
        return 2, "false-open <= 10% and recall >= 30%"
    return 1, " and ".join(why)


def binding_reason(rep: Dict[str, Any]) -> str:
    """Why a binding or request call failed, from what the row holds: the answer that hit the output-token limit, or one that is
    not a JSON list of cases (malformed or empty)."""
    out_tokens = (rep.get("usage") or {}).get("output_tokens", 0)
    if rep.get("producer") == "package" and out_tokens >= TOKEN_LIMIT_SHARE * BINDER_TOKENS:
        return f"hit the {BINDER_TOKENS}-token output limit"
    return "answer is not a JSON list of cases (malformed or empty)"


def row_counts(r: Dict[str, Any]) -> Dict[str, int]:
    """The counts of one run that the rule uses: ``pc`` passed checks, ``fo`` of them given an item (meets or breaks), ``fw``
    failed checks a write could meet, ``rc`` of them given an item that meets, ``fa`` failed checks of any kind and ``ra`` of
    them given an item that meets."""
    meets: Counter = Counter()
    touched: Counter = Counter()
    for m in r["maps"].values():
        for cid in m["meets"]:
            meets[cid] += 1
            touched[cid] += 1
        for cid in m["breaks"]:
            touched[cid] += 1
    out = {"pc": 0, "fo": 0, "fw": 0, "rc": 0, "fa": 0, "ra": 0}
    for c in r["checks"]:
        if c["passed"]:
            out["pc"] += 1
            out["fo"] += int(touched.get(c["id"], 0) > 0)
        else:
            hit = int(meets.get(c["id"], 0) > 0)
            out["fa"] += 1
            out["ra"] += hit
            if c["writable"]:
                out["fw"] += 1
                out["rc"] += hit
    return out


def measure_group(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """One benchmark and producer. ``rows``: one per run with ``replay`` (the ledger result), ``checks`` (id, passed,
    writable), ``maps`` (sent item -> check ids), ``run_passed`` and, for the checks no sent item names, ``cover``."""
    n_runs = len(rows)
    passed_checks = failed_checks = failed_writable = 0
    opened_passed = opened_failed = opened_failed_writable = 0
    sent_runs = sent_passed_runs = passed_runs = useful_runs = wrong_runs = 0
    sent_items = sent_useful = sent_on_passed = sent_unmapped = sent_breaks = 0
    status: Counter = Counter()
    items = values_items = known_items = shown_items = 0
    known_all = 0
    s_items = s_values = s_known = s_shown = 0
    cost = 0.0
    failed_bindings = empty = 0
    causes: Counter = Counter()
    sent_prior = sent_nocheck_passed = recalled_no_prior = recalled_prior = 0
    binding_reasons: Counter = Counter()
    for r in rows:
        rep = r["replay"]
        cost += rep.get("cost_usd", 0.0)
        passed_runs += int(r["run_passed"])
        if rep.get("status") == "empty":
            empty += 1
        if rep.get("binding") == "failed":
            failed_bindings += 1
            binding_reasons[binding_reason(rep)] += 1
        for it in rep.get("items", []):
            status[it["status"]] += 1
            items += 1
            if it["values"]:
                values_items += 1
                known_items += int(it["known"] > 0)
                known_all += int(it["known"] == it["values"])
            shown_items += int(it["shown"])
            if it["sent"]:
                s_items += 1
                s_values += int(it["values"] > 0)
                s_known += int(it["known"] > 0)
                s_shown += int(it["shown"])
        status["unbound"] += rep.get("unbound", 0)
        by_id = {c["id"]: c for c in r["checks"]}
        meets: Counter = Counter()
        touched: Counter = Counter()  # an item that meets or breaks the check
        for m in r["maps"].values():
            for cid in m["meets"]:
                meets[cid] += 1
                touched[cid] += 1
            for cid in m["breaks"]:
                touched[cid] += 1
        sent = [it for it in rep.get("items", []) if it["sent"]]
        sent_items += len(sent)
        run_useful = run_wrong = False
        for it in sent:
            m = r["maps"].get(str(it["n"]), r["maps"].get(it["n"], {"meets": [], "breaks": []}))
            meets_kinds = {by_id[c]["passed"] for c in m["meets"] if c in by_id}
            breaks_passed = any(by_id[c]["passed"] for c in m["breaks"] if c in by_id)
            if it.get("prior_call"):
                sent_prior += 1
            if not m["meets"] and not m["breaks"]:
                sent_unmapped += 1
                sent_nocheck_passed += int(r["run_passed"])
            if False in meets_kinds:
                sent_useful += 1
                run_useful = True
            if True in meets_kinds or breaks_passed:
                sent_on_passed += 1
                run_wrong = True
            if breaks_passed:
                sent_breaks += 1
        if sent:
            sent_runs += 1
            sent_passed_runs += int(r["run_passed"])
            useful_runs += int(run_useful)
            wrong_runs += int(run_wrong)
        for c in r["checks"]:
            if c["passed"]:
                passed_checks += 1
                opened_passed += int(touched.get(c["id"], 0) > 0)
            else:
                hit = meets.get(c["id"], 0) > 0
                failed_checks += 1
                opened_failed += int(hit)
                if c["writable"]:
                    failed_writable += 1
                    opened_failed_writable += int(hit)
                    if hit:
                        by_n = {i["n"]: i for i in rep.get("items", [])}
                        hitters = [
                            by_n[int(n)]
                            for n, m in r["maps"].items()
                            if c["id"] in m["meets"] and int(n) in by_n
                        ]
                        if any(not h.get("prior_call") for h in hitters):
                            recalled_no_prior += 1
                        else:
                            recalled_prior += 1
                    if not hit:
                        causes[r.get("causes", {}).get(c["id"], "not diagnosed")] += 1
    level, why = decide((opened_passed, passed_checks), (opened_failed_writable, failed_writable))
    return {
        "sent_items_prior_call": sent_prior,
        "sent_items_no_check_on_passed_run": sent_nocheck_passed,
        "recalled_no_prior_call": recalled_no_prior,
        "recalled_prior_call": recalled_prior,
        "binding_failures": dict(sorted(binding_reasons.items())),
        "runs": n_runs,
        "passed_runs": passed_runs,
        "empty_runs": empty,
        "failed_bindings": failed_bindings,
        "passed_checks": passed_checks,
        "false_open": opened_passed,
        "false_open_ci": wilson(opened_passed, passed_checks),
        "failed_checks": failed_checks,
        "failed_writable": failed_writable,
        "recalled": opened_failed_writable,
        "recall_ci": wilson(opened_failed_writable, failed_writable),
        "failed_all_recalled": opened_failed,
        "runs_with_follow_up": sent_runs,
        "passed_runs_with_follow_up": sent_passed_runs,
        "follow_ups_naming_failed_work": useful_runs,
        "follow_ups_naming_passed_work": wrong_runs,
        "sent_items": sent_items,
        "sent_items_failed_work": sent_useful,
        "sent_items_passed_work": sent_on_passed,
        "sent_items_break_passed_work": sent_breaks,
        "sent_items_no_check": sent_unmapped,
        "status": {s: status.get(s, 0) for s in STATUSES},
        "items": items,
        "items_with_values": values_items,
        "items_value_known": known_items,
        "items_all_values_known": known_all,
        "items_value_shown": shown_items,
        "sent_with_values": s_values,
        "sent_value_known": s_known,
        "sent_value_shown": s_shown,
        "cost_usd": round(cost, 4),
        "causes": dict(sorted(causes.items())),
        "level": level,
        "why": why,
    }


BOOT_DRAWS, BOOT_SEED = 2000, 20261105


def rate_rule(fo: Fraction, rec: Fraction) -> bool:
    return fo * FALSE_OPEN_MAX[1] <= FALSE_OPEN_MAX[0] and rec * RECALL_MIN[1] >= RECALL_MIN[0]


def set_meta() -> Tuple[Dict[str, List[str]], Dict[str, Dict[str, Any]]]:
    """``task -> set ids`` and ``set id -> {status, seen}`` from ``sets/registry.json``. ``seen``: some agent model has run a task
    of the set (the rule of ``audit_report.basis_of``: a set that was run is never ``held-out``)."""
    sys.path.insert(0, str(HERE / "sets"))
    import build_registry as reg

    registry = reg.load_registry()
    members: Dict[str, List[str]] = defaultdict(list)
    meta: Dict[str, Dict[str, Any]] = {}
    for entry in registry["sets"]:
        if entry["benchmark"] not in BENCHMARKS:
            continue
        meta[entry["id"]] = {
            "status": entry["status"],
            "benchmark": entry["benchmark"],
            "seen": any(n > 0 for n in (entry.get("seen_n") or {}).values()),
        }
        for task in reg.task_ids(entry):
            members[task].append(entry["id"])
    return dict(members), meta


def views_of(rows: Sequence[Dict[str, Any]], meta: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """The same rule on four counts of one group: pooled over runs, one count per task (a task weighs 1, and its runs share
    the weight), the mean of the task rates, and a bootstrap over tasks. Then the pooled count of each task set. ``firm``: the
    pooled count, the one count per task and the mean of the task rates all pass the rule. Runs of one task are not independent,
    so the pooled count is the one most likely to look better than it is."""
    by_task: Dict[str, List[Dict[str, int]]] = defaultdict(list)
    task_sets: Dict[str, List[str]] = {}
    for r in rows:
        by_task[r["task"]].append(row_counts(r))
        task_sets[r["task"]] = r.get("sets", [])
    sums = {
        t: {k: sum(c[k] for c in cs) for k in ("pc", "fo", "fw", "rc", "fa", "ra")}
        for t, cs in by_task.items()
    }
    runs = {t: len(cs) for t, cs in by_task.items()}
    tot = {k: sum(v[k] for v in sums.values()) for k in ("pc", "fo", "fw", "rc", "fa", "ra")}
    w = {k: sum(Fraction(v[k], runs[t]) for t, v in sums.items()) for k in ("pc", "fo", "fw", "rc")}
    fo_rates = [Fraction(v["fo"], v["pc"]) for v in sums.values() if v["pc"]]
    rec_rates = [Fraction(v["rc"], v["fw"]) for v in sums.values() if v["fw"]]
    mean_fo = sum(fo_rates) / len(fo_rates) if fo_rates else None
    mean_rec = sum(rec_rates) / len(rec_rates) if rec_rates else None
    rng = random.Random(BOOT_SEED)
    names = sorted(sums)
    boot_fo: List[float] = []
    boot_rec: List[float] = []
    for _ in range(BOOT_DRAWS if names else 0):
        pick = [sums[names[rng.randrange(len(names))]] for _ in names]
        pc, fo = sum(v["pc"] for v in pick), sum(v["fo"] for v in pick)
        fw, rc = sum(v["fw"] for v in pick), sum(v["rc"] for v in pick)
        if pc:
            boot_fo.append(fo / pc)
        if fw:
            boot_rec.append(rc / fw)

    def pct_of(xs: List[float], q: float) -> Optional[float]:
        if not xs:
            return None
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(q * len(xs)))]

    pooled_ok = decide((tot["fo"], tot["pc"]), (tot["rc"], tot["fw"]))[0] == 2
    per_task_ok = bool(w["pc"] and w["fw"]) and rate_rule(w["fo"] / w["pc"], w["rc"] / w["fw"])
    mean_ok = mean_fo is not None and mean_rec is not None and rate_rule(mean_fo, mean_rec)
    set_rows: Dict[str, Dict[str, Any]] = {}
    for set_id in sorted({sid for ids in task_sets.values() for sid in ids}):
        tasks = [t for t, ids in task_sets.items() if set_id in ids]
        sub = {k: sum(sums[t][k] for t in tasks) for k in ("pc", "fo", "fw", "rc")}
        set_rows[set_id] = {
            "status": meta[set_id]["status"],
            "seen": meta[set_id]["seen"],
            "runs": sum(runs[t] for t in tasks),
            "tasks": len(tasks),
            "fo": [sub["fo"], sub["pc"]],
            "rec": [sub["rc"], sub["fw"]],
        }
    no_set = [t for t, ids in task_sets.items() if not ids]
    if no_set:
        sub = {k: sum(sums[t][k] for t in no_set) for k in ("pc", "fo", "fw", "rc")}
        set_rows["(in no set)"] = {
            "status": "-",
            "seen": True,
            "runs": sum(runs[t] for t in no_set),
            "tasks": len(no_set),
            "fo": [sub["fo"], sub["pc"]],
            "rec": [sub["rc"], sub["fw"]],
        }
    return {
        "tasks": len(sums),
        "pooled": {"fo": [tot["fo"], tot["pc"]], "rec": [tot["rc"], tot["fw"]], "ok": pooled_ok},
        "per_task": {
            "fo": [float(w["fo"]), float(w["pc"])],
            "rec": [float(w["rc"]), float(w["fw"])],
            "ok": per_task_ok,
        },
        "mean_task": {
            "fo": None if mean_fo is None else float(mean_fo),
            "rec": None if mean_rec is None else float(mean_rec),
            "tasks_fo": len(fo_rates),
            "tasks_rec": len(rec_rates),
            "ok": mean_ok,
        },
        "boot": {
            "fo": [pct_of(boot_fo, 0.025), pct_of(boot_fo, 0.975)],
            "rec": [pct_of(boot_rec, 0.025), pct_of(boot_rec, 0.975)],
        },
        "firm": bool(pooled_ok and per_task_ok and mean_ok),
        "sets": set_rows,
    }


# -- run and judge: the work of the commands -----------------------------------------------------------------------------


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_jsonl(path: Path, lock: threading.Lock, row: Dict[str, Any]) -> None:
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_all(bench: Optional[str] = None) -> List[Run]:
    runs: List[Run] = []
    if bench in (None, "handbook"):
        runs += handbook_runs()
    if bench in (None, "itsm"):
        runs += itsm_runs()
    if bench in (None, "tau2-telecom"):
        runs += tau2_runs()
    return runs


def _env() -> None:
    from dotenv import dotenv_values

    secrets = dotenv_values(EVAL / ".env")
    for k in ("OPENAI_BASE_URL", "OPENAI_API_KEY"):
        if secrets.get(k) and not os.environ.get(k):
            os.environ[k] = secrets[k]


def do_replay(
    runs: Sequence[Run],
    models_for: Callable[[], ReplayModels],
    workers: int = 6,
    path: Optional[Path] = None,
    producers: Sequence[str] = PRODUCERS,
) -> int:
    path = path or OUT / "replay.jsonl"
    done = {(r["uid"], r["producer"]) for r in read_jsonl(path)}
    lock = threading.Lock()
    todo = [(r, p) for r in runs for p in producers if (r.uid, p) not in done]

    def one(job: Tuple[Run, str]) -> None:
        run, producer = job
        try:
            row = replay_run(run, producer, models_for())
        except BudgetStop:
            raise
        except Exception as exc:  # noqa: BLE001 - one run must not stop the rest; it is written down as an error
            row = {
                "uid": run.uid,
                "producer": producer,
                "bench": run.bench,
                "run": run.run,
                "task": run.task,
                "status": "crash",
                "why": f"{type(exc).__name__}: {exc}"[:300],
                "items": [],
                "unbound": 0,
                "cost_usd": 0.0,
            }
        append_jsonl(path, lock, row)

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(one, todo))
    return len(todo)


def do_judge(
    runs: Sequence[Run],
    model: Callable[[str, str], str],
    workers: int = 6,
    replay_path: Optional[Path] = None,
    path: Optional[Path] = None,
    producers: Sequence[str] = PRODUCERS,
) -> int:
    from cuga.policy_layer.package import load_package

    replay_path = replay_path or OUT / "replay.jsonl"
    path = path or OUT / "judge.jsonl"
    done = {(r["uid"], r["producer"]) for r in read_jsonl(path)}
    by_uid = {r.uid: r for r in runs}
    replays = [
        r
        for r in read_jsonl(replay_path)
        if r["uid"] in by_uid and r["producer"] in producers and (r["uid"], r["producer"]) not in done
    ]
    lock = threading.Lock()
    writable: Dict[str, Dict[str, bool]] = {}
    packages: Dict[Path, Dict[str, str]] = {}

    def texts_of(run: Run) -> Dict[str, str]:
        with lock:
            if run.package not in packages:
                pkg = load_package(run.package)
                packages[run.package] = {o.id: ob_text({o.id: o}, o.id) for o in pkg.obligations}
            return packages[run.package]

    def one(rep: Dict[str, Any]) -> None:
        run = by_uid[rep["uid"]]
        key = f"{run.task}|{run.uid}"
        with lock:
            cached = writable.get(run.uid)
        if cached is None:
            cached = label_writable(run, model)
            with lock:
                writable[run.uid] = cached
        sent = [i for i in rep.get("items", []) if i["sent"]]
        maps = map_sent(run, sent, model)
        named = {c for m in maps.values() for c in m["meets"]}
        failed = [c for c in run.checks if not c.passed and cached.get(c.id) and c.id not in named]
        causes: Dict[str, str] = {}
        if failed:
            texts = texts_of(run) if rep["producer"] == "package" else {}
            covered = cover(run, failed, rep.get("items", []), texts, model)
            for c in failed:
                ids = covered.get(c.id) or []
                if not ids:
                    causes[c.id] = (
                        "no item"
                        if rep.get("status") == "ok" and rep.get("binding") != "failed"
                        else "no binding"
                    )
                else:
                    by_n = {i["n"]: i for i in rep["items"]}
                    states = sorted({by_n[n]["status"] for n in ids if n in by_n})
                    causes[c.id] = "covered, " + "/".join(states)
        if rep.get("binding") == "failed":
            for c in failed:
                causes[c.id] = "binding failed"
        row = {
            "uid": rep["uid"],
            "producer": rep["producer"],
            "writable": cached,
            "maps": {str(k): v for k, v in maps.items()},
            "causes": causes,
        }
        append_jsonl(path, lock, row)
        _ = key

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(one, replays))
    return len(replays)


def handcheck_sample(
    runs: Sequence[Run],
    replay: Sequence[Dict[str, Any]],
    judged: Sequence[Dict[str, Any]],
    per_bench: Dict[str, int],
) -> List[Dict[str, Any]]:
    """Sent items to check by hand, by the hash of their identity (no outcome is read), ``per_bench`` of each benchmark. Each
    row has the item, the checks of its run without their outcome, and what the judge mapped."""
    by_uid = {r.uid: r for r in runs}
    judge = {(j["uid"], j["producer"]): j for j in judged}
    pool: Dict[str, List[Tuple[str, Dict[str, Any]]]] = defaultdict(list)
    for rep in replay:
        run, j = by_uid.get(rep["uid"]), judge.get((rep["uid"], rep["producer"]))
        if run is None or j is None:
            continue
        for it in rep.get("items", []):
            if it["sent"]:
                pool[f"{run.bench}|{rep['producer']}"].append(
                    (
                        _hash_order(f"{HANDCHECK_SALT}|{rep['uid']}|{rep['producer']}|{it['n']}"),
                        {"rep": rep, "it": it, "j": j},
                    )
                )
    out: List[Dict[str, Any]] = []
    for bench, want in per_bench.items():
        for _, row in sorted(pool.get(bench, []), key=lambda x: x[0])[:want]:
            run = by_uid[row["rep"]["uid"]]
            out.append(
                {
                    "uid": run.uid,
                    "producer": row["rep"]["producer"],
                    "n": row["it"]["n"],
                    "item": row["it"]["line"],
                    "checks": {c.id: re.sub(r"\s+", " ", c.text)[:400] for c in run.checks},
                    "judge": row["j"]["maps"].get(str(row["it"]["n"]), {"meets": [], "breaks": []}),
                }
            )
    return out


def handcheck_stats(rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """The judge's pairs against the hand-made ones. A pair is (kind, check id) with kind ``meets`` or ``breaks``; ``true`` has
    the hand-checked lists in the same form."""
    right = missed = judged = same = 0
    for r in rows:
        j = {(k, c) for k in ("meets", "breaks") for c in r["judge"].get(k, [])}
        t = {(k, c) for k in ("meets", "breaks") for c in r["true"].get(k, [])}
        judged += len(j)
        right += len(j & t)
        missed += len(t - j)
        same += int(j == t)
    return {
        "items": len(rows),
        "judge_pairs": judged,
        "right_pairs": right,
        "missed_pairs": missed,
        "same_set": same,
    }


def limits_of(
    replay: Sequence[Dict[str, Any]], in_run: Optional[Dict[str, Optional[set]]] = None
) -> Dict[str, Dict[str, int]]:
    """What the known limits mean in this replay, counted on the items of the producer ``package``: by kind of item and by the
    tools it names, with the status each ended in. ``code_only``: every tool is ``executePython`` or ``executeBash``.
    ``user_only``: every tool is the customer's (``user__``). ``no_tool``: the item names no tool (a file or a reply). ``tool_not_in_task_list``: the task gave the agent a
    shorter tool list than the package names."""
    out: Dict[str, Counter] = defaultdict(Counter)
    for rep in replay:
        if rep.get("producer") != "package" or rep.get("status") != "ok":
            continue
        for it in rep.get("items", []):
            tools = it.get("tools") or []
            if not tools:
                shape = f"no_tool:{it.get('kind')}"
            elif all(t.startswith("user__") for t in tools):
                shape = "user_only"
            elif all(re.search(r"execute_?(python|bash)", t, re.I) for t in tools):
                shape = "code_only"
            else:
                shape = "tool"
                allowed = (in_run or {}).get(rep["uid"])
                if allowed is not None and not (set(tools) & allowed):
                    shape = "tool_not_in_task_list"  # the run's tool list lacks every tool the item names
            out[f"{rep['bench']}|{shape}"][it["status"]] += 1
    return {k: dict(sorted(v.items())) for k, v in sorted(out.items())}


def build_rows(
    runs: Sequence[Run],
    replay: Sequence[Dict[str, Any]],
    judged: Sequence[Dict[str, Any]],
    members: Optional[Dict[str, List[str]]] = None,
) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    by_uid = {r.uid: r for r in runs}
    judge = {(j["uid"], j["producer"]): j for j in judged}
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for rep in replay:
        run = by_uid.get(rep["uid"])
        j = judge.get((rep["uid"], rep["producer"]))
        if run is None or j is None or rep.get("status") == "crash":
            continue
        groups[(run.bench, rep["producer"])].append(
            {
                "replay": rep,
                "checks": [
                    {"id": c.id, "passed": c.passed, "writable": bool(j["writable"].get(c.id))}
                    for c in run.checks
                ],
                "maps": j["maps"],
                "causes": j.get("causes", {}),
                "run_passed": run.passed,
                "task": run.task,
                "sets": (members or {}).get(run.task, []),
                "policy": run.policy,
                "model": run.agent_model,
            }
        )
    return groups


def basis_counts(runs: Sequence[Run]) -> Dict[str, Dict[str, int]]:
    """``audit_report.basis_of`` for the policy of each run: the kind of numbers (tuning, seen, held-out)."""
    import audit_report

    out: Dict[str, Counter] = defaultdict(Counter)
    for r in runs:
        bench_key = {"tau2-telecom": "tau2_telecom"}.get(r.bench, r.bench)
        kind, _ = audit_report.basis_of(bench_key, r.policy, "skill_v1")
        out[r.bench][kind] += 1
    return {b: dict(c) for b, c in out.items()}


STOP_WORDS = set(
    "about after again being could every exist exists given least might must other should their there these those through "
    "under until where which while would".split()
)


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z]{5,}", text.lower()) if w not in STOP_WORDS}


TRUNCATED = re.compile(r"\.\.\. \[\d+ chars\]$")


def itsm_model_counts(root: Optional[Path] = None) -> Dict[str, Dict[str, int]]:
    """Saved ITSM arm-A runs by agent model: runs with verifiers and how many passed. Counts only; nothing is replayed."""
    root = root or BENCH / "enterpriseops_gym" / "results"
    out: Dict[str, Dict[str, int]] = defaultdict(lambda: {"runs": 0, "passed": 0})
    for path in sorted(root.glob("*/A_*.json")):
        raw = _json(path)
        if not raw.get("verifiers"):
            continue
        row = out[str(raw.get("model"))]
        row["runs"] += 1
        row["passed"] += int(bool(raw.get("passed")))
    return dict(sorted(out.items()))


def truncation_counts(runs: Sequence[Run]) -> Dict[str, Dict[str, int]]:
    """Tool results of the saved runs that the runner cut (``... [N chars]``): the ledger of a live run reads up to 80,000."""
    out: Dict[str, Counter] = defaultdict(Counter)
    for run in runs:
        cut = 0
        for call in run.calls:
            text = (
                call["result"]
                if isinstance(call["result"], str)
                else json.dumps(call["result"], ensure_ascii=False)
            )
            out[run.bench]["calls"] += 1
            if TRUNCATED.search(text):
                cut += 1
        out[run.bench]["truncated"] += cut
        out[run.bench]["runs"] += 1
        out[run.bench]["runs_with_truncation"] += int(cut > 0)
    return {b: dict(c) for b, c in out.items()}


def package_diagnosis(
    runs: Sequence[Run], groups: Dict[Tuple[str, str], List[Dict[str, Any]]]
) -> Dict[str, Dict[str, Any]]:
    """Why the producer ``package`` finds so little: how many obligation-runs no case bound, how many cases a run has, and, for
    failed checks that no item covers, whether the package holds an obligation that shares words with the check (a word-overlap
    estimate, not a judgement: a check with such an obligation points to binding or status, one without to content)."""
    from cuga.policy_layer.package import load_package

    by_uid = {r.uid: r for r in runs}
    texts: Dict[Path, List[set]] = {}
    counts: Dict[Path, int] = {}
    out: Dict[str, Dict[str, Any]] = {}
    for bench in BENCHMARKS:
        rows = groups.get((bench, "package"), [])
        agg: Counter = Counter()
        for r in rows:
            run = by_uid[r["replay"]["uid"]]
            if run.package not in texts:
                pkg = load_package(run.package)
                texts[run.package] = [_words(ob_text({o.id: o}, o.id)) for o in pkg.obligations]
                counts[run.package] = len(pkg.obligations)
            agg["runs"] += 1
            agg["obligation_runs"] += counts[run.package]
            agg["unbound_obligation_runs"] += r["replay"].get("unbound", 0)
            agg["cases"] += len({i["case"] for i in r["replay"].get("items", []) if i.get("case")})
            by_id = {c.id: c for c in run.checks}
            for cid, cause in (r.get("causes") or {}).items():
                if cause != "no item":
                    continue
                agg["no_item_checks"] += 1
                words = _words(by_id[cid].text)
                agg["no_item_with_overlap"] += int(any(len(words & t) >= 2 for t in texts[run.package]))
                agg["no_item_notification"] += int("notification" in by_id[cid].text.lower())
        out[bench] = dict(agg)
    return out


def hand_distinct(rows: Sequence[Dict[str, Any]]) -> int:
    """Distinct items of the hand-check sample: the same obligation for another case or run is one."""
    seen = set()
    for r in rows:
        text = re.sub(r"^- (\[case [^\]]*\] )?", "", r["item"])
        text = re.sub(r" (Values|For information|The code must hold):.*$", "", text)
        seen.add((r["producer"], text))
    return len(seen)


def previous_summary(
    runs: Sequence[Run], members: Dict[str, List[str]], meta: Dict[str, Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """ITSM ``request`` on gate ``61699250e``, before the change that gives a request item no keys: the replay rows and judge
    rows of that gate are kept in ``before_key_fix.jsonl``. Shown so that the report can say what that gate would have told
    the agent. Nothing is replayed here."""
    from cuga.policy_layer.obligations import _failed_call

    path = OUT / "before_key_fix.jsonl"
    if not path.exists():
        return None
    lines = read_jsonl(path)
    replay = [{k: v for k, v in x.items() if k != "kind"} for x in lines if x["kind"] == "replay"]
    judged = [{k: v for k, v in x.items() if k != "kind"} for x in lines if x["kind"] == "judge"]
    by_uid = {r.uid: r for r in runs}
    for rep in replay:
        run = by_uid.get(rep["uid"])
        worked = {c["tool"] for c in run.calls if not _failed_call(c["result"])} if run else set()
        for it in rep["items"]:
            it["prior_call"] = bool(set(it["tools"]) & worked)
    rows = build_rows(runs, replay, judged, members).get(("itsm", "request"), [])
    g = measure_group(rows)
    examples: List[Dict[str, str]] = []
    for r in rows:
        run = by_uid[r["replay"]["uid"]]
        passed = {c["id"] for c in r["checks"] if c["passed"]}
        for n, m in r["maps"].items():
            hit = [c for c in m["meets"] + m["breaks"] if c in passed]
            item = next((i for i in r["replay"]["items"] if i["n"] == int(n) and i["sent"]), None)
            if not hit or item is None:
                continue
            check = next(c for c in run.checks if c.id == hit[0])
            calls = [c for c in run.calls if c["tool"] in item["tools"] and not _failed_call(c["result"])]
            shown = json.dumps(calls[0]["args"], ensure_ascii=False)[:120] if calls else "none"
            examples.append(
                {
                    "item": re.sub(r"\s+", " ", item["line"].replace("[section request] ", ""))[:150],
                    "check": re.sub(r"\s+", " ", check.text)[:110],
                    "prior": (f"{calls[0]['tool']}({shown})" if calls else "none"),
                    "run": run.run,
                }
            )
    return {
        "gate_commit": "61699250e",
        "false_open": g["false_open"],
        "passed_checks": g["passed_checks"],
        "recalled": g["recalled"],
        "failed_writable": g["failed_writable"],
        "sent_items": g["sent_items"],
        "sent_with_prior_call": g["sent_items_prior_call"],
        "sent_with_prior_call_in_hits": g["recalled_prior_call"],
        "runs_with_follow_up": g["runs_with_follow_up"],
        "level": g["level"],
        "views": views_of(rows, meta),
        "examples": examples,
    }


def do_measure(
    runs: Sequence[Run], replay: Sequence[Dict[str, Any]], judged: Sequence[Dict[str, Any]]
) -> Dict[str, Any]:
    members, meta = set_meta()
    groups = build_rows(runs, replay, judged, members)
    used = {r["uid"] for rows in groups.values() for r in (x["replay"] for x in rows)}
    used_runs = [r for r in runs if r.uid in used]
    results: Dict[str, Any] = {"groups": {}, "views": {}, "basis": basis_counts(used_runs)}
    for (bench, producer), rows in sorted(groups.items()):
        results["groups"][f"{bench}|{producer}"] = measure_group(rows)
        results["views"][f"{bench}|{producer}"] = views_of(rows, meta)
    results["runs"] = {b: len({r.uid for r in used_runs if r.bench == b}) for b in BENCHMARKS}
    used_replay = [r for r in replay if r["uid"] in used]
    results["limits"] = limits_of(
        used_replay, {r.uid: (set(r.tools_in_run) if r.tools_in_run is not None else None) for r in used_runs}
    )
    results["sample"] = {
        b: {
            "runs": len({r.uid for r in used_runs if r.bench == b}),
            "tasks": len({r.task for r in used_runs if r.bench == b}),
            "models": dict(Counter(r.agent_model for r in used_runs if r.bench == b)),
            "by_set": dict(
                sorted(
                    Counter(
                        sid
                        for r in used_runs
                        if r.bench == b
                        for sid in (members.get(r.task) or ["(in no set)"])
                    ).items()
                )
            ),
        }
        for b in BENCHMARKS
    }
    results["sets"] = {k: v for k, v in meta.items()}
    results["itsm_models"] = itsm_model_counts()
    results["truncation"] = truncation_counts(used_runs)
    results["package_diagnosis"] = package_diagnosis(used_runs, groups)
    results["previous"] = previous_summary(runs, members, meta)
    results["meta"] = {"gate_commit": gate_commit()}
    results["spent_usd"] = round(ledger_spent(), 3)
    hand = OUT / "handcheck.json"
    if hand.exists():
        rows = json.loads(hand.read_text(encoding="utf-8"))
        results["handcheck"] = {**handcheck_stats(rows), "distinct_items": hand_distinct(rows)}
    return results


# -- the report: tables made from results.json alone ------------------------------------------------------------------

BENCH_NAMES = {"handbook": "HANDBOOK", "itsm": "ITSM", "tau2-telecom": "τ² Telecom"}
BENCH_LABELS = {**BENCH_NAMES, "tau2-telecom": "τ² Telecom †"}


def pct(k: int, n: int) -> str:
    return "n/a" if n == 0 else f"{100 * k / n:.1f}%"


def frac(k: int, n: int) -> str:
    return f"{k} of {n} ({pct(k, n)})" if n else "0 of 0 (n/a)"


def interval(ci: Sequence[Optional[float]]) -> str:
    lo, hi = ci
    return "" if lo is None or hi is None else f" [{100 * lo:.0f}-{100 * hi:.0f}%]"


def basis_text(counts: Dict[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none"


def _groups(results: Dict[str, Any]) -> List[Tuple[str, str, Dict[str, Any]]]:
    rows = []
    for key, g in results["groups"].items():
        bench, producer = key.split("|")
        rows.append((bench, producer, g))
    order = {b: i for i, b in enumerate(BENCHMARKS)}
    rows.sort(key=lambda r: (order.get(r[0], 99), PRODUCERS.index(r[1])))
    return rows


def _label(bench: str) -> str:
    return BENCH_LABELS.get(bench, bench)


def _frac_f(k: float, n: float) -> str:
    """A count that may be weighted (one count per task): the rate and the weighted counts."""
    return "n/a" if not n else f"{100 * k / n:.1f}% ({k:.1f} of {n:.1f})"


def _pct_f(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _range(pair: Sequence[Optional[float]]) -> str:
    lo, hi = pair
    return "n/a" if lo is None or hi is None else f"{100 * lo:.0f}-{100 * hi:.0f}%"


def _level_cell(g: Dict[str, Any], v: Optional[Dict[str, Any]]) -> str:
    if g["level"] == 1:
        return f"1: {g['why']}"
    return "2 (firm)" if v and v["firm"] else "2, **not firm**: " + _disagreement(v)


def _disagreement(v: Optional[Dict[str, Any]]) -> str:
    if not v:
        return "no views"
    bad = [
        n
        for n, k in (("one count per task", "per_task"), ("mean of task rates", "mean_task"))
        if not v[k]["ok"]
    ]
    return "fails under " + " and ".join(bad)


def render_tables(results: Dict[str, Any]) -> str:
    """Markdown tables from ``results.json``. Pure: the same input gives the same text."""
    rows = _groups(results)
    views = results.get("views", {})
    basis = results.get("basis", {})
    out: List[str] = []
    out.append("### Result and level, per benchmark and producer\n")
    out.append(
        "| Benchmark | Basis of the runs (`basis_of`, runs) | Producer | Runs | False-open: passed checks given an item | "
        "Recall: failed checks a write could meet, given an item | Failed checks of any kind, given an item | "
        "Sent items that break a passed check | Level by the pooled rule |"
    )
    out.append("|---|---|---|---:|---|---|---|---:|---|")
    for bench, producer, g in rows:
        out.append(
            f"| {_label(bench)} | {basis_text(basis.get(bench, {}))} | {producer} | {g['runs']} | "
            f"{frac(g['false_open'], g['passed_checks'])}{interval(g['false_open_ci'])} | "
            f"{frac(g['recalled'], g['failed_writable'])}{interval(g['recall_ci'])} | "
            f"{frac(g['failed_all_recalled'], g['failed_checks'])} | {g['sent_items_break_passed_work']} | "
            f"{_level_cell(g, views.get(f'{bench}|{producer}'))} |"
        )
    out.append(
        "\n† τ² Telecom is a conversation, and a conversation cannot run these configurations live: `build_runtime` refuses the "
        "producer `request` in a conversation, and the one `package` item that would be sent asks for the hand-off tool itself, "
        "which the ledger never asks for before a hand-off. These rows are what the saved runs give when the end of the "
        "conversation is taken as the final reply. They are not a measure of a live run.\n"
    )
    out.append("### What the sent items would tell the agent\n")
    out.append(
        "| Benchmark | Producer | Items sent | on a failed check (meets) | on a passed check | of those, break a passed check | "
        "sent while a successful call of the item's tool exists | name no check | name no check, on a passed run |"
    )
    out.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for bench, producer, g in rows:
        out.append(
            f"| {_label(bench)} | {producer} | {g['sent_items']} | {g['sent_items_failed_work']} | {g['sent_items_passed_work']} | "
            f"{g['sent_items_break_passed_work']} | {g['sent_items_prior_call']} | {g['sent_items_no_check']} | "
            f"{g['sent_items_no_check_on_passed_run']} |"
        )
    out.append(
        "\nAn item sent while a successful call of its tool exists says that no successful call did the work, and that is false "
        "for the call that exists (it may have another target or value). The columns count items, not checks. A passed check "
        "is given an item if the item meets or breaks it; a failed check counts for recall only through `meets`.\n"
    )
    out.append("### Run level\n")
    out.append(
        "| Benchmark | Producer | Runs (passed) | Runs with a follow-up | Passed runs with a follow-up | "
        "Follow-ups that name work of a failed check | Follow-ups that name work of a passed check |"
    )
    out.append("|---|---|---|---:|---|---|---|")
    for bench, producer, g in rows:
        out.append(
            f"| {_label(bench)} | {producer} | {g['runs']} ({g['passed_runs']}) | {g['runs_with_follow_up']} | "
            f"{frac(g['passed_runs_with_follow_up'], g['passed_runs'])} | "
            f"{frac(g['follow_ups_naming_failed_work'], g['runs_with_follow_up'])} | "
            f"{frac(g['follow_ups_naming_passed_work'], g['runs_with_follow_up'])} |"
        )
    out.append(
        "\n\"Names work of a failed check\" means the item names the work that the check tests. It does not mean the work can be "
        "recovered: see the section on recall.\n"
    )
    out.append("### Status of the items after the final reply\n")
    out.append("| Benchmark | Producer | Items | " + " | ".join(STATUSES) + " |")
    out.append("|---|---|---:|" + "---:|" * len(STATUSES))
    for bench, producer, g in rows:
        out.append(
            f"| {_label(bench)} | {producer} | {g['items']} | "
            + " | ".join(str(g["status"][s]) for s in STATUSES)
            + " |"
        )
    out.append("\n### Value origin\n")
    out.append(
        "| Benchmark | Producer | Items | Items that name values | with a known value | with every value known | "
        "Items with a value shown | Items sent | Sent with a value shown |"
    )
    out.append("|---|---|---:|---:|---|---|---|---:|---|")
    for bench, producer, g in rows:
        out.append(
            f"| {_label(bench)} | {producer} | {g['items']} | {g['items_with_values']} | "
            f"{frac(g['items_value_known'], g['items_with_values'])} | {frac(g['items_all_values_known'], g['items_with_values'])} | "
            f"{frac(g['items_value_shown'], g['items'])} | {g['sent_items']} | {frac(g['sent_value_shown'], g['sent_items'])} |"
        )
    out.append("\n### Cost, with the model `" + MODEL + "`\n")
    out.append(
        "| Benchmark | Producer | Runs | Cost | Per run | Failed bindings or request calls | Runs with no obligation |"
    )
    out.append("|---|---|---:|---:|---:|---:|---:|")
    for bench, producer, g in rows:
        per = f"${g['cost_usd'] / g['runs']:.4f}" if g["runs"] else "n/a"
        failures = "; ".join(f"{n} {why}" for why, n in g["binding_failures"].items()) or "0"
        out.append(
            f"| {_label(bench)} | {producer} | {g['runs']} | ${g['cost_usd']:.3f} | {per} | {failures} | {g['empty_runs']} |"
        )
    out.append("\n### Why failed checks that a write could meet got no item\n")
    causes = sorted({c for _, _, g in rows for c in g["causes"]})
    out.append("| Benchmark | Producer | Failed checks (writable) | " + " | ".join(causes) + " |")
    out.append("|---|---|---:|" + "---:|" * len(causes))
    for bench, producer, g in rows:
        out.append(
            f"| {_label(bench)} | {producer} | {g['failed_writable']} | "
            + " | ".join(str(g["causes"].get(c, 0)) for c in causes)
            + " |"
        )
    limits = results.get("limits") or {}
    if limits:
        out.append(
            "\n### Items of the producer `package` by the tools they name, and the status they ended in\n"
        )
        out.append("| Benchmark | Shape | Items | " + " | ".join(STATUSES) + " |")
        out.append("|---|---|---:|" + "---:|" * len(STATUSES))
        for key, counts in limits.items():
            bench, shape = key.split("|")
            out.append(
                f"| {_label(bench)} | {shape} | {sum(counts.values())} | "
                + " | ".join(str(counts.get(s, 0)) for s in STATUSES)
                + " |"
            )
    if views:
        out.append("\n### The rule on four counts, per benchmark and producer\n")
        out.append(
            "Pooled over runs is the count of the rule. One count per task: a task weighs 1 and its runs share the weight (the "
            "counts are weighted). Mean of task rates: the rate of each task, then the mean. Bootstrap: tasks drawn with "
            f"replacement, {BOOT_DRAWS} draws, 95% range. \"Firm\": the pooled count, one count per task and the mean of task "
            "rates all pass the rule.\n"
        )
        out.append(
            "| Benchmark | Producer | Tasks | Pooled: false-open / recall | One count per task: false-open / recall | "
            "Mean of task rates: false-open / recall | Task bootstrap: false-open / recall | Firm |"
        )
        out.append("|---|---|---:|---|---|---|---|---|")
        for bench, producer, g in rows:
            v = views[f"{bench}|{producer}"]
            p, w, m, b = v["pooled"], v["per_task"], v["mean_task"], v["boot"]
            out.append(
                f"| {_label(bench)} | {producer} | {v['tasks']} | "
                f"{pct(*p['fo'])} / {pct(*p['rec'])} | {_frac_f(*w['fo']).split(' ')[0]} / {_frac_f(*w['rec']).split(' ')[0]} | "
                f"{_pct_f(m['fo'])} / {_pct_f(m['rec'])} | {_range(b['fo'])} / {_range(b['rec'])} | "
                f"{'yes' if v['firm'] else 'no'} |"
            )
        out.append("\n### Runs and counts by task set\n")
        out.append(
            "A set is named by `sets/registry.json`. \"Status\" is the role it was made for. A set with status `heldout` that an "
            "agent model has run (`seen`) is \"status heldout, label seen\": it is no held-out set for this replay. A task can be "
            "in two sets, and a run of the sample in none.\n"
        )
        out.append("| Benchmark | Producer | Set | Status and label | Runs | Tasks | False-open | Recall |")
        out.append("|---|---|---|---|---:|---:|---|---|")
        for bench, producer, g in rows:
            for set_id, x in views[f"{bench}|{producer}"]["sets"].items():
                label = (
                    x["status"]
                    if x["status"] in ("tuning", "-")
                    else ("status heldout, label seen" if x["seen"] else "heldout")
                )
                out.append(
                    f"| {_label(bench)} | {producer} | {set_id} | {label} | {x['runs']} | {x['tasks']} | "
                    f"{frac(*x['fo'])} | {frac(*x['rec'])} |"
                )
    hand = results.get("handcheck")
    if hand:
        out.append("\n### The mapping of items to checks, against a hand check\n")
        out.append(
            "| Items checked | Distinct items | Pairs the judge made | of which right | Pairs missed by the judge | Items with the same set |"
        )
        out.append("|---:|---:|---:|---|---:|---|")
        out.append(
            f"| {hand['items']} | {hand['distinct_items']} | {hand['judge_pairs']} | "
            f"{frac(hand['right_pairs'], hand['judge_pairs'])} | {hand['missed_pairs']} | {frac(hand['same_set'], hand['items'])} |"
        )
    return "\n".join(out) + "\n"


def _lim(results: Dict[str, Any], bench: str, shape: str) -> Dict[str, int]:
    return (results.get("limits") or {}).get(f"{bench}|{shape}", {})


def _lim_text(counts: Dict[str, int]) -> str:
    return ", ".join(f"{v} {k}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])) or "none"


def report_text(results: Dict[str, Any]) -> str:
    """The whole of ``REPORT.md``, from ``results.json`` alone: every number in it comes from there, so it cannot drift. The
    command ``obligation_replay.py report`` writes it."""
    groups = {tuple(k.split("|")): g for k, g in results["groups"].items()}
    views = {tuple(k.split("|")): v for k, v in results["views"].items()}
    sample = results["sample"]
    passes = [(b, p) for (b, p), g in groups.items() if g["level"] == 2]
    previous = results.get("previous")
    out: List[str] = ["# Obligation replay: may the ledger send follow-ups? (task 4.3)\n"]
    if passes:
        named = "; ".join(
            f"{BENCH_NAMES[b]} `{p}`"
            + ("" if views[(b, p)]["firm"] else " (not firm: " + _disagreement(views[(b, p)]) + ")")
            for b, p in passes
        )
        out.append(
            f"**Result.** Level 2 is allowed by the pooled rule for: {named}. Every other benchmark and producer stays at "
            "level 1. "
        )
    else:
        out.append("**Result.** No producer passes the rule on any benchmark: all stay at level 1. ")
    out[-1] += (
        "Every number is on tuning policies or on sets that are held-out only in status (`audit_report.basis_of`, and the table "
        "of runs by set): none is a held-out result, and the replay gives no score gain. **The ledger cannot send on `package` "
        "today**: see the section on why.\n"
    )
    itsm_request = groups[("itsm", "request")]
    out.append(
        f"**ITSM `request`, on gate `{results['meta']['gate_commit']}`:** false-open "
        f"{frac(itsm_request['false_open'], itsm_request['passed_checks'])}, recall "
        f"{frac(itsm_request['recalled'], itsm_request['failed_writable'])}, "
        f"{itsm_request['runs_with_follow_up']} of {itsm_request['runs']} runs get a follow-up, level {itsm_request['level']}."
        + (
            f" On the gate before the change that gives request items no keys, it passed: false-open "
            f"{frac(previous['false_open'], previous['passed_checks'])}, recall {frac(previous['recalled'], previous['failed_writable'])}, "
            f"level 2, {'firm' if previous['views']['firm'] else 'not firm'}: one count per task gave "
            f"{_pct_f(previous['views']['per_task']['fo'][0] / previous['views']['per_task']['fo'][1])} false-open and "
            f"{_pct_f(previous['views']['per_task']['rec'][0] / previous['views']['per_task']['rec'][1])} recall, the mean of task "
            f"rates {_pct_f(previous['views']['mean_task']['fo'])} and {_pct_f(previous['views']['mean_task']['rec'])}; by set, "
            + "; ".join(
                f"`{sid}` {frac(*x['fo'])} false-open, {frac(*x['rec'])} recall"
                for sid, x in previous["views"]["sets"].items()
                if sid in ("itsm-tune", "itsm-unseen")
            )
            + f". {previous['sent_with_prior_call']} of its {previous['sent_items']} sends were made while a successful call "
            "of the item's tool existed: the follow-up then said that no successful call did the work, which is false. The "
            "section on that change shows it.\n"
            if previous
            else "\n"
        )
    )
    out.append("## What was replayed\n")
    out.append(
        "No agent ran. Finished arm-A runs were read, their tool calls were given to the real ledger (`ObligationLedger`, gate "
        f"commit `{results['meta']['gate_commit']}`, a clean copy of that commit) through `build_runtime`, and the final answer "
        f"went to `before_reply`. The binding call and the request producer's call use the real prompts with `{MODEL}` "
        f"(`max_tokens` {BINDER_TOKENS} for the binding), on the data that run read. Every item is at level `follow_up`: the "
        "tables show what level 2 would send. One ledger per producer, so producers do not mix.\n"
    )
    out.append(
        "| Benchmark | Runs | Distinct tasks | Agent models | Basis (`basis_of`, runs) | Runs by set |"
    )
    out.append("|---|---:|---:|---|---|---|")
    for b in BENCHMARKS:
        info = sample[b]
        models = ", ".join(f"{m} {n}" for m, n in sorted(info["models"].items()))
        by_set = ", ".join(f"{k} {n}" for k, n in info["by_set"].items())
        out.append(
            f"| {_label(b)} | {info['runs']} | {info['tasks']} | {models} | {basis_text(results['basis'].get(b, {}))} | {by_set} |"
        )
    out.append(
        "\nThe runs are every saved arm-A run in these folders, with no choice by outcome: HANDBOOK `hba_*_A` and `hbq_*_A`; ITSM "
        "every `A_*.json` of the gpt-oss-120b runs; τ² Telecom `dev1_A`, `dev2_A`, `test1_A`, `test2_A` with environment "
        "assertions. A failed binding counts as a failure and is in the tables. `obligation_replay/sample.json` lists the run "
        "ids. \"tuning\" in `basis_of` hides what the sets are: `itsm-unseen` and `tau2-telecom-test` have status heldout, and "
        "an agent model has run them, so they are \"status heldout, label seen\" (see the table by set). HANDBOOK is "
        "in-sample: the packages were written from the same documents that the tasks use.\n"
    )
    models = results.get("itsm_models") or {}
    out.append(
        "**The level for ITSM applies to the gpt-oss-120b agent only.** Only that agent's runs were replayed, and it is the "
        "weakest of the three that have saved ITSM arm-A runs (runs, passed): "
        + "; ".join(f"{m} {v['passed']} of {v['runs']}" for m, v in models.items())
        + ". A stronger agent passes more checks, so more passed checks can be given an item (false-open) and fewer failed ones "
        "can be recovered. No saved binding exists for the other two, and none was paid for.\n"
    )
    out.append("## Result and level\n")
    out.append(
        "Rule (spec section 5): false-open <= 10% of the checks the run passed, and recall >= 30% of the failed checks, per "
        "benchmark and producer. **The replay narrows the second denominator**: it counts only the failed checks that a write of "
        "the agent could have met (the brief's rule), and the table gives recall over all failed checks beside it. The "
        "denominators were fixed before the numbers were seen. A rate with no denominator does not pass, and recall over fewer "
        f"than {MIN_RECALL_DENOMINATOR} failed checks a write could meet is \"not known\". The intervals are 95% Wilson on the "
        "pooled count; runs of one task are not independent, so read them as too narrow. The level uses the pooled count, as "
        "the spec states the rule. A level 2 is marked **not firm** when the counts by task disagree.\n"
    )
    out.append(render_tables(results))
    out.append("## What recall means here\n")
    r = groups[("itsm", "request")]
    out.append(
        "Recall is the share of the failed checks that the sent items *name*: an item for the work that the check tests. It is "
        "not the share of failed work that a follow-up would get done. For ITSM `request`: "
        f"{r['recalled_no_prior_call']} of the {r['recalled']} recalled checks are named by an item sent when the run has no "
        f"successful call of the item's tool (the agent never tried, or gave up), and {r['recalled_prior_call']} by an item sent "
        "while such a call exists (the agent wrote to another target or with other values, or stopped short). A recalled "
        "check on a run where the agent gave up is not work that one more turn would finish. The reading of runs by hand (the "
        "controller counted 31 of 57 pairs on runs where the agent gave up or wrote to another incident) is not reproduced by "
        "this table: the split above is the one that the data gives by code.\n"
    )
    if previous:
        out.append("## The change that gives request items no keys\n")
        out.append(
            "On gate `61699250e` a request item had the keys of its case (an empty list), so a call of its tool with another "
            "target or with the value left out did not count as the item's work, and the item stayed open. "
            f"{previous['sent_with_prior_call']} of {previous['sent_items']} sends were of that kind, "
            f"{previous['sent_with_prior_call_in_hits']} of the {previous['recalled']} recall hits rest on one, and all "
            f"{previous['false_open']} false opens are among them. The follow-up said that no successful call did the work. The "
            "three false opens, as that gate would have told the agent:\n"
        )
        for ex in previous["examples"]:
            out.append(
                f"- `{ex['item']}` against the passed check \"{ex['check']}\". A successful call existed: `{ex['prior']}`."
            )
        out.append(
            "\nOn gate `9ab6935cd` (a request or duty item takes no keys) a call that leaves out an enum value is `unknown`, and "
            "the item is not asked for again.\n"
        )
    out.append("## Why the ledger cannot send on `package` today\n")
    pd = results["package_diagnosis"]
    hb, it = pd["handbook"], pd["itsm"]
    pg = {b: groups[(b, "package")] for b in BENCHMARKS}
    out.append(
        f"- **HANDBOOK: binding.** {hb['cases'] / hb['runs']:.2f} cases are bound per run; {hb['unbound_obligation_runs']} of "
        f"{hb['obligation_runs']} obligation-runs (each obligation of the package, in each run) are unbound. Of the "
        f"{pg['handbook']['failed_writable']} failed checks a write could meet, {pg['handbook']['recalled']} are named by a sent "
        f"item; {sum(n for c, n in pg['handbook']['causes'].items() if c.startswith('covered'))} more are covered by an item "
        f"that is not sent (met, unknown, held), {pg['handbook']['causes'].get('binding failed', 0)} were lost to failed bindings, "
        f"and {pg['handbook']['causes'].get('no item', 0)} have no item. So at most about "
        f"{100 * (pg['handbook']['recalled'] + sum(n for c, n in pg['handbook']['causes'].items() if c.startswith('covered'))) / pg['handbook']['failed_writable']:.1f}% "
        "of them could be named even if every covering item were open (a ceiling on recall).\n"
        f"- **ITSM: content.** {_lim(results, 'itsm', 'no_tool:reply') and sum(_lim(results, 'itsm', 'no_tool:reply').values())} "
        f"items name no tool (`reply`) and are never sent. `request` names {groups[('itsm', 'request')]['recalled']} of "
        f"{groups[('itsm', 'request')]['failed_writable']} failed checks, `package` {pg['itsm']['recalled']}. "
        f"{pg['itsm']['causes'].get('no item', 0)} failed checks have no item in the package, and {it['no_item_notification']} of "
        "the checks without an item are on notifications, which the package does not name.\n"
        f"- **Telecom: the customer's tools.** {sum(_lim(results, 'tau2-telecom', 'user_only').values())} items name only `user__` "
        "tools, work that only the customer's phone can do; none is sent, and the checks are customer-device states, so "
        f"{pg['tau2-telecom']['failed_writable']} failed checks could be met by a write of the agent.\n"
        "- **The split between binding and content is an estimate.** For the failed checks with no item, the replay asks whether "
        "the package holds an obligation that shares two or more words (five letters or more) with the check: "
        f"HANDBOOK {hb['no_item_with_overlap']} of {hb['no_item_checks']}, ITSM {it['no_item_with_overlap']} of "
        f"{it['no_item_checks']}. A check with such an obligation points to binding or status, one without to content. It is a "
        "word-overlap estimate, not a judgement.\n"
    )
    hand = results.get("handcheck")
    out.append("## Labels (measurement only) and their error\n")
    out.append(
        "Nothing from a grader enters a package, a prompt or the ledger. The graders' checks (HANDBOOK rubric items, ITSM verifiers "
        "with their SQL, Telecom environment assertions) are read after the replay, by one model call of "
        f"`{MODEL}` per run and producer. It sees the checks without whether they passed, and the items that would be sent, and "
        "gives for each item `meets` (the work would help the check pass: the same kind of action on the same kind of record for "
        "the same case) and `breaks` (the check says that work must not exist). A passed check that gets an item of either kind is "
        "a false-open; a failed check counts for recall only through `meets`. A second call per task says which failed checks a "
        "write of the agent could have met (the denominator of recall; a reply text, a must-not check, a read or an action of "
        "another party is false). A third says, for a failed check no sent item names, which items of the ledger cover it "
        "(the `why` table).\n"
    )
    if hand:
        out.append(
            f"**Error, by hand.** I read {hand['items']} sent items ({hand['distinct_items']} distinct: the same obligation for "
            "another case or run counts once; chosen by the hash of their identity, per benchmark and producer: HANDBOOK package, "
            "ITSM request, duty and package, Telecom request) and wrote the checks each one concerns. "
            f"The judge made {hand['judge_pairs']} pairs and {hand['right_pairs']} are right "
            f"({pct(hand['right_pairs'], hand['judge_pairs'])}); it missed {hand['missed_pairs']} pairs that I made (pair recall "
            f"{pct(hand['right_pairs'], hand['right_pairs'] + hand['missed_pairs'])}); {hand['same_set']} of {hand['items']} items "
            "have the same set. So false-open and recall are a little low. The misses are items whose address or target differs from "
            "the check's, or a generic item such as `create_incident` that is one of several checks. The wrong pair maps a read "
            "(`retrieve_knowledge_articles`) to a check on a link. The sample is mostly HANDBOOK Crestwood and ITSM tasks of the "
            "gpt-oss runs; Telecom has one sent item in all. A first judge prompt (same object and same action) had 6 of 18 pairs "
            "missed on a first sample of 23 package items; I changed the prompt to ignore the values the item shows, and checked a "
            "new sample on the final data. The hand check is mine and one reader's: a pair can be disputed (the label for a "
            "mark-as-read item rests on the email's folder).\n"
        )
    out.append("## Known limits and what each does to the numbers\n")
    hb_code, hb_file = _lim(results, "handbook", "code_only"), _lim(results, "handbook", "no_tool:file")
    tel_user, itsm_nl = (
        _lim(results, "tau2-telecom", "user_only"),
        _lim(results, "itsm", "tool_not_in_task_list"),
    )
    itsm_reply, tel_reply = (
        _lim(results, "itsm", "no_tool:reply"),
        _lim(results, "tau2-telecom", "no_tool:reply"),
    )
    trunc = results["truncation"]["handbook"]
    out.append("| Limit | What the replay shows (producer `package` unless said) |")
    out.append("|---|---|")
    out.append(
        f"| HANDBOOK file obligations that name only `executePython` and `executeBash` (138) | {sum(hb_code.values())} such items: "
        f"{_lim_text(hb_code)}. The false-open risk (a file written with `writeFile`) shows in the `open` ones; the main cost is "
        "recall: an `unknown` item is never sent |"
    )
    out.append(
        f"| Telecom obligations that name only `user__` tools (17) | The replay uses the agent's tools only. {sum(tel_user.values())} "
        f"items of that shape: {_lim_text(tel_user)}; none sent. A real run that lists `user__` tools could ask the agent for work "
        "only the customer can do |"
    )
    out.append(
        f"| ITSM items often `unknown` when a tool is not in the task's list | {sum(itsm_nl.values())} items name only tools that the "
        f"task did not give the agent: {_lim_text(itsm_nl)} |"
    )
    out.append(
        f"| Items with no tool (`reply`) | ITSM {sum(itsm_reply.values())}: {_lim_text(itsm_reply)}; Telecom {sum(tel_reply.values())}: "
        f"{_lim_text(tel_reply)}. Never sent |"
    )
    out.append(
        f"| Spreadsheet and file items with no tool | HANDBOOK {sum(hb_file.values())}: {_lim_text(hb_file)}; none sent, so no "
        "recall from them |"
    )
    out.append(
        "| A block that names only an employee id is not attached when the binder's keys hold only the name; a corrected retry leaves "
        "other tools' items held | Not exercised: the saved arm-A runs have no blocks, so no `tool_blocked` and no retry |"
    )
    out.append(
        "| `held` is barely exercised | There were no blocks. `held` still shows, because the binder's decision for a case can be "
        f"`hold` with a quote (HANDBOOK {groups[('handbook', 'package')]['status']['held']}, ITSM "
        f"{groups[('itsm', 'package')]['status']['held']}, Telecom {groups[('tau2-telecom', 'package')]['status']['held']} items) |"
    )
    out.append(
        "| Saved tool results are cut | The HANDBOOK runner keeps 4,000 characters of a result (`TOOL_LOG_LIMIT`): "
        f"{trunc['truncated']} of {trunc['calls']} results are cut, in {trunc['runs_with_truncation']} of {trunc['runs']} runs. "
        "The live ledger reads up to 80,000 characters of each read. A live binding sees more of the SOP and the records, so it "
        "can find more cases and more values: **both rates could rise**, the false-open as well as the recall. ITSM and Telecom "
        "results are not cut |"
    )
    out.append(
        "| A request item made from a mention (`contact alice@corp.com` named in passing, `asked: true`) | Covered by the false-open "
        f"of `request`: ITSM {frac(groups[('itsm', 'request')]['false_open'], groups[('itsm', 'request')]['passed_checks'])}, "
        f"Telecom {frac(groups[('tau2-telecom', 'request')]['false_open'], groups[('tau2-telecom', 'request')]['passed_checks'])}, "
        f"HANDBOOK {frac(groups[('handbook', 'request')]['false_open'], groups[('handbook', 'request')]['passed_checks'])}. The "
        "Telecom item is of this kind, and it is kept only as an example of the `asked: true` risk: a customer's question "
        "(\"is there any way to get my service restored?\") became an item to resume the line, and the passed check says the "
        "service must stay off. That follow-up would have been harmful. Telecom cannot run this configuration live (†) |"
    )
    out.append("")
    out.append(
        "`wrong` is recorded and never sent. `unbound` counts obligations that no case bound, once for each run; it is not part of "
        "the item count.\n"
    )
    out.append("## The honest ceiling\n")
    out.append(
        "Spec section 5: with names only, expect about +4 to +6 points; anything above that depends on how many expected values "
        "can be derived, and the value table gives that share for these items. The oracle's +25 to +36 is an upper bound with "
        "grader values, not a forecast. A replay gives no score gain, and none is estimated here beyond that range.\n"
    )
    out.append("## Levels and profiles\n")
    levels = ", ".join(
        f"{BENCH_NAMES[b]} `{p}`: {g['level']}"
        for (b, p), g in sorted(
            groups.items(), key=lambda kv: (BENCHMARKS.index(kv[0][0]), PRODUCERS.index(kv[0][1]))
        )
    )
    out.append(f"Levels by the pooled rule: {levels}.\n")
    out.append(
        "No profile is changed or added. The measured best profiles stay as measured, and every profile has `producers: []` today. "
        "A level 2 would be a note, not a setting: a later profile would hold `obligations: {producers: [<producer>], "
        "item_level: follow_up}` for that benchmark; level 1 is the state of every profile now. None of these numbers is a "
        "held-out result. Spec section 5 says item levels are never set from held-out tasks, and (ruling of the controller, "
        "added to section 5 with this task) a tuning pass needs a held-out check before any profile sends.\n"
    )
    for b, p in passes:
        g, info = groups[(b, p)], sample[b]
        out.append(
            f"**On the pass.** {BENCH_NAMES[b]} `{p}`: false-open {frac(g['false_open'], g['passed_checks'])}, recall "
            f"{frac(g['recalled'], g['failed_writable'])}, over {info['runs']} runs of {info['tasks']} distinct tasks, of which "
            f"{g['passed_runs']} runs passed and {g['runs_with_follow_up']} would get a follow-up ({g['passed_runs_with_follow_up']} "
            "of the passed runs).\n"
        )
    out.append("## Cost\n")
    out.append(
        f"Spent on this task: ${results['spent_usd']:.3f} of ${CAP:.0f} (model `{MODEL}`, list price: binding, request producer "
        "and judge). The per-run cost of each producer is in the cost table. Cached answers are re-used when the prompt is "
        "unchanged, so a re-run costs little.\n"
    )
    return "\n".join(out)


def plan_runs() -> List[Run]:
    """Every run that the plan may name: HANDBOOK hba/hbq, ITSM gpt-oss and DeepSeek, τ² Telecom."""
    return handbook_runs() + itsm_runs((MODEL, DEEPSEEK)) + tau2_runs()


def plan_sample(itsm_deepseek: int) -> List[Run]:
    """All HANDBOOK, all τ² Telecom and all ITSM gpt-oss arm-A runs, and ``itsm_deepseek`` ITSM DeepSeek runs by the hash
    of their identity. No outcome is read."""
    runs = plan_runs()
    chosen = [r for r in runs if r.bench != "itsm" or r.agent_model == MODEL]
    chosen += sample([r for r in runs if r.bench == "itsm" and r.agent_model == DEEPSEEK], itsm_deepseek)
    return chosen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "replay", "judge", "handcheck", "measure", "report"])
    ap.add_argument("--bench", choices=BENCHMARKS)
    ap.add_argument(
        "--itsm-deepseek",
        type=int,
        default=0,
        help="plan: ITSM DeepSeek runs to add to the gpt-oss ones, by hash",
    )
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--producers", default=",".join(PRODUCERS), help="replay and judge only these producers")
    ap.add_argument("--gate-src", help="src/ of a clean copy of the gate repo at the commit to replay on")
    args = ap.parse_args()
    if args.gate_src:
        use_gate_src(Path(args.gate_src))
    sample_file = OUT / "sample.json"
    if args.cmd == "plan":
        chosen = plan_sample(args.itsm_deepseek)
        sample_file.parent.mkdir(parents=True, exist_ok=True)
        sample_file.write_text(
            json.dumps({"uids": [r.uid for r in chosen], "itsm_deepseek": args.itsm_deepseek}, indent=1)
            + "\n",
            encoding="utf-8",
        )
        for b in BENCHMARKS:
            rs = [r for r in chosen if r.bench == b]
            print(
                b,
                len(rs),
                "runs;",
                sum(len(r.checks) for r in rs),
                "checks;",
                dict(Counter(r.agent_model for r in rs)),
            )
        return 0
    wanted = set(json.loads(sample_file.read_text(encoding="utf-8"))["uids"])
    runs = [r for r in plan_runs() if r.uid in wanted]
    chosen = [r for r in runs if args.bench in (None, r.bench)]
    if args.cmd in ("replay", "judge"):
        _env()
        cache = Cache(OUT / "model_cache.jsonl")
        meter = Meter()
        meter.flush_to_ledger = True
        meter.spent = ledger_spent()  # what this task has spent so far, from every earlier process
        transport = gateway_transport()
        try:
            if args.cmd == "replay":
                n = do_replay(
                    chosen,
                    lambda: ReplayModels(cache, meter, transport),
                    args.workers,
                    producers=args.producers.split(","),
                )
            else:
                judge_model = CachedModel(MODEL, cache, meter, transport, BINDER_TOKENS)
                n = do_judge(chosen, judge_model, args.workers, producers=args.producers.split(","))
        finally:
            meter.flush(name=f"task 4.3 {args.cmd}")
        print(
            f"{args.cmd}: {n} jobs, new calls {meter.new_calls}, failed {meter.failed_calls}, spent ${meter.spent:.3f}"
        )
        return 0
    if args.cmd == "handcheck":
        sample_rows = handcheck_sample(
            runs, read_jsonl(OUT / "replay.jsonl"), read_jsonl(OUT / "judge.jsonl"), HANDCHECK_PER_BENCH
        )
        (OUT / "handcheck_sample.json").write_text(
            json.dumps(sample_rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(len(sample_rows), "items to check by hand")
        return 0
    if args.cmd == "measure":
        replay, judged = read_jsonl(OUT / "replay.jsonl"), read_jsonl(OUT / "judge.jsonl")
        (OUT / "results.json").write_text(
            json.dumps(do_measure(runs, replay, judged), indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return 0
    (OUT / "REPORT.md").write_text(
        report_text(json.loads((OUT / "results.json").read_text(encoding="utf-8"))), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
