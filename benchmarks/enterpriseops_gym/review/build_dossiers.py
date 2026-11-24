"""Write one text dossier per failed task of a harness run, for the run review (policy_conformance_review.md, "Run review").

A dossier holds what a reviewer needs to judge each failed check: the task's policy, the request, the tools the agent
had, every check with its expected and actual value, every tool call with its result, and the agent's answer.

    python build_dossiers.py csm ../../policy_eval/harness/results/pc_csm_cbdsv41flash_t1 /tmp/review_csm

Reads the task files of this folder and the result files of the run. Writes only into the output folder.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, List

HOME = Path(__file__).resolve().parents[1]
TASKS = HOME / "tasks"
VENDOR = HOME / "vendor" / "EnterpriseOps-Gym"
SCHEMA_CHARS = 3500  # per tool
RESULT_CHARS = 2500  # per tool call


def _j(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _context(cfg: dict) -> str:
    """The login the server applies. The agent is not shown it; token values are left out."""
    shown = {k: ("<token>" if "token" in k.lower() else v) for k, v in (cfg.get("context") or {}).items()}
    return f"{json.dumps(shown)} user_info={json.dumps(cfg.get('user_info'))[:600]}"


def dossier(task: dict, verifiers: List[dict], result: dict, trajectory: dict, tools: dict) -> str:
    cfg = _j(task["gym_servers_config"])[0]
    lines = [
        f"TASK {task['task_id']}",
        "",
        "##### POLICY (system prompt given to the agent, complete)",
        task["system_prompt"],
        "",
        "##### USER REQUEST (complete)",
        task["user_prompt"],
        "",
        f"##### SEED DATABASE (SQL dump): {VENDOR / cfg['seed_database_file']}",
        f"##### LOGGED-IN USER CONTEXT (not shown to the agent as text; the server applies it): {_context(cfg)}",
        "",
        "##### TOOLS AVAILABLE TO THE AGENT (name, description, input schema)",
    ]
    for name in task["selected_tools"]:
        spec = tools.get(name) or {}
        shown = {"name": name, "description": spec.get("description"), "inputSchema": spec.get("inputSchema")}
        lines.append(json.dumps(shown)[:SCHEMA_CHARS])
    lines += ["", "##### GRADER CHECKS (all must pass; each is a SQL query on the final database)"]
    for i, (verifier, graded) in enumerate(zip(verifiers, result["score"]["detail"]["verifiers"])):
        config = verifier["validation_config"]
        lines.append(
            f"V{i} {'PASSED' if graded['passed'] else 'FAILED'} | name: {verifier.get('name')} | "
            f"description: {verifier.get('description')}\n"
            f"   query: {' '.join(config['query'].split())}\n"
            f"   comparison: {config['comparison_type']} expected: {config['expected_value']!r} "
            f"actual in this run: {graded['actual']!r} error: {graded['error']}"
        )
    lines += ["", "##### WHAT THE AGENT DID (every tool call in order)"]
    for i, call in enumerate(trajectory["tool_calls"]):
        lines.append(
            f"[{i}] {call['tool']} args={json.dumps(call['args'])}\n"
            f"     {'ERROR ' if call['error'] else ''}result={json.dumps(call['result'])[:RESULT_CHARS]}"
        )
    lines += ["", "##### AGENT'S FINAL ANSWER", trajectory.get("answer") or ""]
    if result.get("error"):
        lines += ["", "##### RUN ERROR", str(result["error"])[:500]]
    return "\n".join(lines)


def main(domain: str, run_dir: str, out_dir: str) -> None:
    tasks = {t["task_id"]: t for t in json.loads((TASKS / f"{domain}_oracle.json").read_text())}
    tools = {t["name"]: t for t in json.loads((TASKS / f"{domain}_tools.json").read_text())}
    revisions = json.loads((TASKS / "verifier_revisions.json").read_text())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    passed, failed, unscored = [], [], []
    for path in sorted(Path(run_dir).glob("*.json")):
        result = json.loads(path.read_text())
        task_id = result["task"]
        if result["score"] is None:  # a gateway error: the task has no score and needs a rerun, not a review
            unscored.append(task_id)
            continue
        if result["score"]["pass"]:
            passed.append(task_id)
            continue
        failed.append(task_id)
        task = tasks[task_id]
        verifiers = revisions[task_id]["verifiers"] if task_id in revisions else _j(task["verifiers"])
        trajectory = json.loads(Path(result["trajectory"]).read_text())
        (out / f"{task_id[-8:]}.txt").write_text(dossier(task, verifiers, result, trajectory, tools))
    print(f"passed {len(passed)}, failed {len(failed)}, no score {len(unscored)}")
    print("dossiers:", " ".join(t[-8:] for t in failed))
    if unscored:
        print("rerun (no score):", " ".join(unscored))


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
