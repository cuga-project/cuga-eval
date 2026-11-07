"""One result schema for all benchmarks (design spec, section 13), and the reader of the old result files.

A result is one task of one trial of one run. ``score`` is ``None`` when the task was not graded: a wiring error, a task
whose policy version has no package, a run that never reached the grader. Such a result is not a 0, and the report does
not count it as a task failure.

``score.primary`` is the number the report compares, one per benchmark:

| Benchmark | primary | partial | pass | guardrails_broken |
|---|---|---|---|---|
| automationbench | partial credit | partial credit | every check passes | checks that passed at the start and fail at the end |
| itsm | 1 if every verifier passes, else 0 | verifiers passed / total | every verifier passes | none |
| handbook | rubric items passed / total | the same | the task's own pass | none |
| tau2-* | 1 if the reward is 1, else 0 | the reward | the reward is 1 | none |

``score.detail`` holds what only that benchmark has (the rubric counts, the AA scores, the termination reason).

``from_legacy(path)`` reads the four old formats and a new result file. Standard library only: this module runs in the
venv of each benchmark. Nothing here writes to an old result file.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

SCHEMA = "policy_eval.result.v1"


def package_identity(path: Union[str, Path], version: str) -> str:
    """Which package ran: ``<version>+<file hash>``. ``version`` comes from the policy text, and the packages of one policy
    share it, so the hash of the file goes with it. The decision tests of a package (``tests``) are a measurement input and
    do not change the rules, so they are left out of the hash: a package gets the same name with or without its tests. A file
    with no tests is hashed as it is; one with tests is hashed with ``tests`` set to ``[]``, in the format the package is
    written in (``save_package``)."""
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    if isinstance(data, dict) and data.get("tests"):
        data["tests"] = []
        raw = (json.dumps(data, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    return f"{version}+{hashlib.sha256(raw).hexdigest()[:12]}"


@dataclass
class Score:
    primary: float
    partial: Optional[float] = None
    passed: Optional[bool] = None  # "pass" in the file
    guardrails_broken: Optional[int] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary": self.primary,
            "partial": self.partial,
            "pass": self.passed,
            "guardrails_broken": self.guardrails_broken,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Score":
        return cls(
            primary=data["primary"],
            partial=data.get("partial"),
            passed=data.get("pass"),
            guardrails_broken=data.get("guardrails_broken"),
            detail=data.get("detail") or {},
        )


@dataclass
class Result:
    benchmark: str
    task: str
    profile: Optional[str] = None
    trial: Optional[int] = None
    run: str = ""
    agent_model: Optional[str] = None
    gate_model: Optional[str] = None
    code_sha: Optional[str] = None
    profile_hash: Optional[str] = None
    package_version: Optional[str] = None
    policy: Optional[str] = (
        None  # the policy version of the task (``ctx.policy_version``); old files do not have it
    )
    env_hash: Optional[str] = None  # the composed env file: the agent's settings
    score: Optional[Score] = None  # None: not graded. Never a 0.
    verdicts: List[Any] = field(default_factory=list)
    obligations: List[Any] = field(default_factory=list)
    usage_by_component: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # each row names its model
    cost_usd: Optional[float] = None
    wall_s: Optional[float] = None
    error: Optional[str] = None
    trajectory: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out = {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}
        out["score"] = self.score.to_dict() if self.score is not None else None
        return {"schema": SCHEMA, **out}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Result":
        names = {f.name for f in dataclasses.fields(cls)}
        known = {k: v for k, v in data.items() if k in names}
        known["score"] = Score.from_dict(data["score"]) if data.get("score") else None
        return cls(**known)

    def write(self, path: Union[str, Path]) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1, default=str, ensure_ascii=False))


# -- old formats ---------------------------------------------------------------------------------------------------------


class NotAResult(ValueError):
    """The file holds no task result in a format this module knows."""


def _trial(raw: Dict[str, Any], folder: str) -> Optional[int]:
    value = raw.get("trial")
    if value in (None, ""):
        found = re.search(r"_t(\d+)(?:_|$)", folder)
        value = found.group(1) if found else None
    return int(value) if value is not None else None


def _agent_rows(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The agent's tokens over all its turns, by its model. Old files keep one receipt per turn of a loop or oracle round."""
    receipts = [raw.get("receipt"), *(raw.get("loop_receipts") or []), *(raw.get("oracle_receipts") or [])]
    receipts = [r for r in receipts if r]
    if not receipts:
        return {}
    models = [m for r in receipts for m in r.get("models") or []]
    return {
        "agent": {
            "model": models[0] if models else raw.get("model") or raw.get("agent_model"),
            "input_tokens": sum(r.get("input_tokens", 0) or 0 for r in receipts),
            "output_tokens": sum(r.get("output_tokens", 0) or 0 for r in receipts),
        }
    }


def _usage_rows(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = _agent_rows(raw)
    for key, component, model_key in (
        ("policy_usage", "policy_layer", None),
        ("loop_usage", "loop", None),
        ("tracker_usage", "requirements_tracker", "tracker_model"),
        ("gate_usage", "gate", "gate_model"),
        ("detector_usage", "detector", None),
        ("decisions_usage", "decisions", None),
    ):
        usage = raw.get(key)
        if usage and any(usage.values()):
            rows[component] = {"model": usage.get("model") or raw.get(model_key or ""), **usage}
    return rows


def _common(raw: Dict[str, Any], benchmark: str, task: str, folder: str) -> Dict[str, Any]:
    trajectory = raw.get("trajectory")
    return {
        "benchmark": benchmark,
        "task": task,
        "trial": _trial(raw, folder),
        "run": raw.get("run") or folder,
        "wall_s": raw.get("wall_s"),
        "error": raw.get("error") or None,
        "trajectory": trajectory if isinstance(trajectory, str) else None,
        "verdicts": raw.get("gate") or [],
        "usage_by_component": _usage_rows(raw),
        "gate_model": raw.get("gate_model"),
    }


def automationbench_score(raw: Dict[str, Any]) -> Optional[Score]:
    """From what ``automationbench/ab_env.py:score`` gives."""
    if raw.get("partial_credit") is None:
        return None
    broken = raw.get("guards_broken")
    if broken is None:  # older files have only the flag
        broken = int(bool(raw.get("guard_broken")))
    return Score(
        primary=float(raw["partial_credit"]),
        partial=float(raw["partial_credit"]),
        passed=bool(raw.get("pass")),
        guardrails_broken=broken,
        detail={k: raw[k] for k in ("aa", "aa_style", "n_guards", "n_scored", "failed") if k in raw},
    )


def itsm_score(raw: Dict[str, Any]) -> Optional[Score]:
    """From what ``EOGTask.grade`` gives."""
    total = raw.get("verifiers_total")
    if raw.get("passed") is None or total is None:
        return None
    return Score(
        primary=float(bool(raw["passed"])),
        partial=(raw.get("verifiers_passed") or 0) / total if total else 0.0,
        passed=bool(raw["passed"]),
        detail={
            "verifiers_passed": raw.get("verifiers_passed"),
            "verifiers_total": total,
            "verifiers": raw.get("verifiers"),
        },
    )


def handbook_score(raw: Dict[str, Any]) -> Optional[Score]:
    """From what ``handbook/hb_env.py:grade`` gives."""
    total = raw.get("rubrics_total")
    if not total:
        return None
    share = (raw.get("rubrics_passed") or 0) / total
    return Score(
        primary=share,
        partial=share,
        passed=bool(raw.get("passed")),
        detail={
            "items_passed": raw.get("rubrics_passed") or 0,
            "items_total": total,
            "score": raw.get("score"),
            "rubrics": raw.get("rubrics"),
        },
    )


def tau2_score(reward: Optional[float], termination_reason: Optional[str] = None) -> Optional[Score]:
    if reward is None:
        return None
    solved = float(reward) >= 1
    return Score(
        primary=float(solved),
        partial=float(reward),
        passed=solved,
        detail={"termination_reason": termination_reason},
    )


def _automationbench(raw: Dict[str, Any], folder: str) -> Result:
    provenance = raw.get("provenance") or {}
    source = provenance.get("cuga_source") or []
    return Result(
        **_common(raw, "automationbench", raw["task"], folder),
        profile=f"legacy:{provenance.get('cell') or raw.get('arm') or ''}",
        agent_model=raw.get("model"),
        code_sha=source[0] if source else None,
        score=automationbench_score(raw),
    )


def _itsm(raw: Dict[str, Any], folder: str) -> Result:
    return Result(
        **_common(raw, "itsm", raw["task_id"], folder),
        profile=f"legacy:{raw.get('arm') or ''}",
        agent_model=raw.get("model"),
        package_version=raw.get("policy_version"),
        score=itsm_score(raw),
    )


def _handbook(raw: Dict[str, Any], folder: str) -> Result:
    common = _common(raw, "handbook", raw["task"], folder)
    return Result(
        **common,
        profile=f"legacy:{raw.get('arm') or ''}",
        agent_model=raw.get("model") or (common["usage_by_component"].get("agent") or {}).get("model"),
        score=handbook_score(raw),
    )


def _tau2(raw: Dict[str, Any], folder: str) -> Result:
    tag = folder.removeprefix("logging_")
    return Result(
        benchmark=f"tau2-{raw.get('domain') or 'unknown'}",
        task=raw["task_id"],
        profile=f"legacy:{re.sub(r'_s[0-9]+$', '', tag)}",
        trial=None,
        run=tag,
        agent_model=raw.get("agent_model"),
        score=tau2_score(raw.get("reward"), raw.get("termination_reason")),
        wall_s=raw.get("full_execution_time"),
        error=raw.get("error") or None,
    )


def _convert(raw: Any, folder: str) -> List[Result]:
    if not isinstance(raw, dict):
        raise NotAResult(f"not an object: {type(raw).__name__}")
    if str(raw.get("schema") or "").startswith("policy_eval.result."):
        return [Result.from_dict(raw)]
    if isinstance(raw.get("results"), list):  # a τ² results file holds every task of its shard
        return [
            _tau2(item, folder) for item in raw["results"] if isinstance(item, dict) and "task_id" in item
        ]
    if "reward" in raw and "task_id" in raw:  # one task of a τ² shard (results/partial)
        return [_tau2(raw, folder)]
    if "task_id" in raw:
        return [_itsm(raw, folder)]
    if "task" in raw and ({"toolset", "partial_credit", "n_tools", "provenance"} & set(raw)):
        if "mcp_port" not in raw and "container" not in raw:
            return [_automationbench(raw, folder)]
    if "task" in raw and ({"container", "mcp_port", "rubrics_total", "grader_error"} & set(raw)):
        return [_handbook(raw, folder)]
    raise NotAResult(f"unknown keys: {sorted(raw)[:12]}")


def _folder_of(path: Path) -> str:
    """The run's folder. A τ² file sits in ``logging_<tag>/results`` or ``logging_<tag>/results/partial``."""
    for parent in path.parents:
        if parent.name not in ("results", "partial"):
            return parent.name
    return path.parent.name


def all_from_legacy(path: Union[str, Path]) -> List[Result]:
    """Every result in a file: one, or for a τ² results file, one per task."""
    path = Path(path)
    return _convert(json.loads(path.read_text()), _folder_of(path))


def from_legacy(path: Union[str, Path], task: Optional[str] = None) -> Result:
    """The result in an old file (AutomationBench, ITSM, HANDBOOK, τ²) or a new one. A τ² results file holds a whole shard:
    name the ``task``, or use ``all_from_legacy``."""
    results = all_from_legacy(path)
    if task is not None:
        results = [r for r in results if r.task == task]
    if len(results) != 1:
        raise NotAResult(f"{path}: {len(results)} results; name the task, or use all_from_legacy")
    return results[0]
