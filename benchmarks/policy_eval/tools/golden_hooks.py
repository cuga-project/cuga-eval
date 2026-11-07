"""Check of ``build_runtime`` against the golden description of the policy wiring. Offline: no agent, no model call.

    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/tools/golden_hooks.py check

``profiles/golden_hooks.json`` is the frozen reference. It was written from the wiring code of the four old runners, never from
``build_runtime``. The command that wrote it left with those runners: it lives at the local tag ``policy/pre-migration-removal``
(``policy_eval/tools/golden_hooks.py capture``, with the old runners and ``config_from_env``). The file must not be written again
from here, because a description written from ``build_runtime`` proves nothing about the old wiring.

check    For every case, builds the same case with ``build_runtime`` from its profile and its package, and compares the two
         descriptions. Prints each difference. Exit code 1 if anything differs. ``--runner R`` checks only the cases of one
         runner, for a run in that benchmark's venv with ``CUGA_SRC=<gate repo>/src`` set, which is where ``build_runtime``
         runs in a real run.

A case is a profile on one policy, or an "other wiring": a config that no profile uses, in a runner that differs from the others
there. Those keep the moved code honest where no profile looks (the gate that the IT service runner seeds with the request, for
example). Their configs are frozen in ``profiles/golden_other_configs.json``, written once by ``config_from_env`` of their old
switches plus the fields a switch cannot say, before that function was removed.

Downloads under ``~/dev/untrusted`` are only read, and this runs with ``-I`` because of that.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
POLICY_EVAL = HERE.parent
BENCHMARKS = POLICY_EVAL.parent
PROFILES = POLICY_EVAL / "profiles"
GOLDEN = PROFILES / "golden_hooks.json"
OTHER_CONFIGS = PROFILES / "golden_other_configs.json"
ITSM_TASKS = BENCHMARKS / "enterpriseops_gym" / "tasks" / "itsm_oracle.json"
ITSM_TOOLS = BENCHMARKS / "enterpriseops_gym" / "tasks" / "itsm_tools.json"
HANDBOOK_TASKS = (
    Path(os.environ.get("HANDBOOK_SAMPLE", str(Path.home() / "dev/untrusted/handbook-sample"))) / "tasks"
)
HANDBOOK_TOOLS = BENCHMARKS / "handbook" / "tools"
TELECOM_POLICY = Path.home() / "dev/cuga-eval-tau2/benchmarks/tau2/tau2-bench/data/tau2/domains/telecom"
TELECOM_TOOLS = POLICY_EVAL / "tau2" / "telecom_tools.json"
sys.path.insert(0, str(BENCHMARKS))  # the shared SOP parser
if os.environ.get("CUGA_SRC"):  # -I ignores PYTHONPATH: the code to check goes first by hand
    sys.path.insert(0, os.environ["CUGA_SRC"])

ITSM_POLICIES = [
    "2e555b5177",
    "7bb25d850c",
    "933219af01",
    "a5e328395b",
    "c47f8ceef3",
    "cb2d4ee021",
    "d5ab75ff0f",
    "e2891a7b98",
]
HANDBOOK_POLICIES = [
    "hr_crestwood_university_79786c46",
    "insurance_vanguard_shield_mutual_9b2f7a29",
    "medical_careig_specialty_pharmacy_f5947c33",
]
RUNNERS = ("automationbench", "handbook", "itsm", "tau2")
GOLDEN_PRINCIPAL = {"id": "golden-user", "role": "itil"}
GOLDEN_TIME = "2026-01-15T09:00:00+00:00"
AB_TASK = "golden.dry_run"
AB_SYSTEM = "You work for a company."
AB_REQUEST = "Do the work the company asks for."


def _ab_tools() -> List[Any]:
    def gmail_find_email(world: Any, query: str) -> str:
        """Find emails.

        Args:
            query: What to search for.
        """
        return ""

    def gmail_send_email(world: Any, to: str, body: str) -> str:
        """Send an email.

        Args:
            to: The address.
            body: The text.
        """
        return ""

    return [gmail_find_email, gmail_send_email]


def _make(profile: Optional[str], runner: str, policy: str) -> Dict[str, Any]:
    return {"profile": profile, "runner": runner, "policy": policy}


def cases() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {
        "baseline/automationbench": _make("baseline", "automationbench", AB_TASK),
        "baseline/itsm": _make("baseline", "itsm", ITSM_POLICIES[-1]),
        "baseline/handbook": _make("baseline", "handbook", HANDBOOK_POLICIES[0]),
        "baseline/tau2": _make("baseline", "tau2", "telecom"),
        "automationbench-gemini-alone": _make("automationbench-gemini-alone", "automationbench", AB_TASK),
        "automationbench-gptoss-b4tf": _make("automationbench-gptoss-b4tf", "automationbench", AB_TASK),
        "tau2-telecom-dsv4-sop-tracker": _make("tau2-telecom-dsv4-sop-tracker", "tau2", "telecom"),
        "tau2-telecom-gptoss-navigator": _make("tau2-telecom-gptoss-navigator", "tau2", "telecom"),
    }
    for profile in (
        "handbook-dsv4-loop-guide",
        "handbook-gptoss-loop-guide-evidence",
        "handbook-gemini-graph-gate",
    ):
        for policy in HANDBOOK_POLICIES:
            out[f"{profile}/{policy}"] = _make(profile, "handbook", policy)
    for policy in ITSM_POLICIES:
        out[f"itsm-rules/{policy}"] = _make("itsm-rules", "itsm", policy)
    for name, runner, policy in (
        ("other/itsm-gate-over-policy-text", "itsm", ITSM_POLICIES[0]),
        ("other/itsm-gate-gemini", "itsm", ITSM_POLICIES[0]),
        ("other/handbook-gate-over-sop-file", "handbook", HANDBOOK_POLICIES[0]),
        ("other/itsm-checklists", "itsm", ITSM_POLICIES[0]),
        ("other/automationbench-checklists", "automationbench", AB_TASK),
        ("other/automationbench-b5-guard-code", "automationbench", AB_TASK),
        ("other/automationbench-loop", "automationbench", AB_TASK),
        ("other/itsm-rules-and-loop", "itsm", ITSM_POLICIES[0]),
        ("other/handbook-loop-discovery", "handbook", HANDBOOK_POLICIES[0]),
    ):
        out[name] = _make(None, runner, policy)
    return out


# -- the inputs of a case ----------------------------------------------------------------------------------------------


def itsm_task(policy: str) -> Dict[str, Any]:
    tasks = [t for t in json.loads(ITSM_TASKS.read_text()) if t["_policy_hash"] == policy]
    return sorted(tasks, key=lambda t: t["task_id"])[0]


def telecom_policy_text() -> str:
    """As tau2's telecom environment builds its policy (``get_environment``)."""
    main = (TELECOM_POLICY / "main_policy.md").read_text()
    tech = (TELECOM_POLICY / "tech_support_manual.md").read_text()
    return f"<main_policy>\n{main}\n</main_policy>\n<tech_support_policy>\n{tech}\n</tech_support_policy>"


def telecom_tool_names() -> List[str]:
    return [t["name"] for t in json.loads(TELECOM_TOOLS.read_text()) if not t["name"].startswith("user__")]


def handbook_world_time(task: str) -> str:
    config = tomllib.loads((HANDBOOK_TASKS / task / "task.toml").read_text())
    return ((config.get("environment") or {}).get("env") or {}).get("HANDBOOK_CURRENT_TIME", "")


def handbook_sop_text(task: str) -> str:
    """The text the old runner gave the gate over the raw SOP: the visible text of the largest file named as an SOP."""
    from handbook.sop_text import html_text, largest_sop_file

    return html_text(largest_sop_file(HANDBOOK_TASKS / task).read_text(errors="replace"))


# -- check: the same cases from build_runtime --------------------------------------------------------------------------


def _differences(old: Any, new: Any, path: str = "") -> List[str]:
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for key in sorted(set(old) | set(new)):
            if key not in old:
                out.append(f"{path}.{key}: only in build_runtime: {json.dumps(new[key])[:200]}")
            elif key not in new:
                out.append(f"{path}.{key}: only in the old wiring: {json.dumps(old[key])[:200]}")
            else:
                out += _differences(old[key], new[key], f"{path}.{key}")
        return out
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        return [d for i, (a, b) in enumerate(zip(old, new)) for d in _differences(a, b, f"{path}[{i}]")]
    return [] if old == new else [f"{path}: old {json.dumps(old)[:300]} / new {json.dumps(new)[:300]}"]


def config_of(name: str, case: Dict[str, Any]) -> Any:
    """The config of a case: its profile, or the frozen config of an other wiring."""
    from cuga.policy_layer.policy_config import PolicyConfig, load_config

    if case["profile"]:
        return load_config(PROFILES / f"{case['profile']}.yaml")
    return PolicyConfig.from_dict(json.loads(OTHER_CONFIGS.read_text())[name])


def package_of(case: Dict[str, Any], cfg: Any) -> Any:
    """The opened package of a case, or ``None`` when this policy has none (as the harness will do)."""
    from cuga.policy_layer.package import load_package

    if not cfg.package:
        return None
    path = POLICY_EVAL / cfg.package.format(policy=case["policy"])
    return load_package(path) if path.is_file() else None


def context_of(case: Dict[str, Any]) -> Any:
    from cuga.policy_layer.runtime import RunContext

    if case["runner"] == "automationbench":
        from langchain_core.tools import StructuredTool

        specs = []
        for fn in _ab_tools():
            tool = StructuredTool.from_function(
                func=fn, name=fn.__name__, parse_docstring=True, error_on_invalid_docstring=False
            )
            specs.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": _without_world(tool.args_schema.model_json_schema()),
                    "app": fn.__name__.split("_", 1)[0],
                }
            )
        search = [(s["name"], (lambda q: "")) for s in specs if s["name"] == "gmail_find_email"]
        return RunContext(
            task_id=AB_TASK,
            request=AB_REQUEST,
            system_prompt=AB_SYSTEM,
            tool_specs=specs,
            world_time=GOLDEN_TIME,
            data_search=search,
            policy_version=case["policy"],
        )
    if case["runner"] == "itsm":
        task = itsm_task(case["policy"])
        return RunContext(
            task_id=task["task_id"],
            request=task["user_prompt"],
            system_prompt=task["system_prompt"],
            tool_specs=json.loads(ITSM_TOOLS.read_text()),
            tools_in_run=task["selected_tools"],
            principal=dict(GOLDEN_PRINCIPAL),
            policy_version=case["policy"],
        )
    if case["runner"] == "handbook":
        task = case["policy"]
        return RunContext(
            task_id=task,
            request=(HANDBOOK_TASKS / task / "instruction.md").read_text(),
            system_prompt=(HANDBOOK_TASKS / task / "system_prompt.md").read_text(),
            policy_text=handbook_sop_text(task),
            tool_specs=json.loads((HANDBOOK_TOOLS / f"{task}.json").read_text()),
            world_time=handbook_world_time(task),
            policy_version=task,
        )
    return RunContext(
        task_id="telecom-golden",
        system_prompt=telecom_policy_text(),
        tool_specs=[{"name": n} for n in telecom_tool_names()],
        policy_version=case["policy"],
        message_tool="send_message_to_user",  # the bridge's decoy: it is in no tool spec of the benchmark
    )


def _without_world(schema: Dict[str, Any]) -> Dict[str, Any]:
    """The schema the old runner's make_tool gives: its tools hide the ``world`` argument."""
    schema = json.loads(json.dumps(schema))
    schema.get("properties", {}).pop("world", None)
    if "required" in schema:
        schema["required"] = [r for r in schema["required"] if r != "world"]
    return schema


def check_all(source: Path = GOLDEN, runner: Optional[str] = None) -> int:
    from cuga.policy_layer.dry_run import RecordingModels, describe_parts
    from cuga.policy_layer.runtime import build_runtime

    golden = json.loads(source.read_text())["cases"]
    all_cases = cases()
    if sorted(golden) != sorted(all_cases):
        print(f"cases differ from the golden file: {sorted(set(golden) ^ set(all_cases))}")
        return 1
    wrong = 0
    profiles_ok: Dict[str, bool] = {}
    for name, case in all_cases.items():
        if runner and case["runner"] != runner:
            continue
        models = RecordingModels()
        cfg = config_of(name, case)
        parts = build_runtime(cfg, package_of(case, cfg), context_of(case), models=models)
        differ = _differences(golden[name]["description"], describe_parts(parts, models))
        print(f"{name:<75} differences {len(differ)}")
        for line in differ:
            print(f"    {line}")
        wrong += len(differ)
        if case["profile"]:
            profiles_ok[case["profile"]] = profiles_ok.get(case["profile"], True) and not differ
    print(f"cases: {len(all_cases)}; profiles that match: {sum(profiles_ok.values())} of {len(profiles_ok)}")
    print(f"differences: {wrong}")
    return 1 if wrong else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["check"])
    ap.add_argument("--golden", type=Path, default=GOLDEN, help="what to compare with")
    ap.add_argument("--runner", choices=RUNNERS, help="only the cases of this runner")
    args = ap.parse_args()
    return check_all(args.golden, args.runner)


if __name__ == "__main__":
    sys.exit(main())
