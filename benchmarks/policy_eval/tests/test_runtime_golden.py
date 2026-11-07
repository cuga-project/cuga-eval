"""``build_runtime`` gives the wiring that the old runners gave (the frozen ``profiles/golden_hooks.json``), and a run with no
package stops.

The code is in the gate repo, so the checks run with the gate repo's Python. No agent and no model call.
"""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

POLICY_EVAL = Path(__file__).resolve().parents[1]
BENCHMARKS = POLICY_EVAL.parent
TOOL = POLICY_EVAL / "tools" / "golden_hooks.py"
GOLDEN = POLICY_EVAL / "profiles" / "golden_hooks.json"
GATE_PYTHON = os.environ.get("POLICY_GATE_PYTHON") or str(
    Path.home() / "dev/cuga-agent-gate/.venv/bin/python"
)
GATE_SRC = Path(GATE_PYTHON).parents[2] / "src"
SAMPLE = Path.home() / "dev/untrusted/handbook-sample/tasks"
TAU2 = Path.home() / "dev/cuga-eval-tau2/benchmarks/tau2"
PROFILES = sorted(p.stem for p in (POLICY_EVAL / "profiles").glob("*.yaml"))
needs_all_inputs = pytest.mark.skipif(
    not SAMPLE.is_dir() or not TAU2.is_dir(), reason="the HANDBOOK sample or the τ² worktree is missing"
)


def run(*args, python=GATE_PYTHON, env=None, timeout=900):
    return subprocess.run(
        [python, "-I", *args],
        cwd=BENCHMARKS,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, **(env or {})},
    )


def run_python(code, *args):
    done = run("-c", code, *args)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-3000:]
    return done.stdout


def golden():
    return json.loads(GOLDEN.read_text())["cases"]


def test_the_golden_file_has_every_profile_and_every_policy_of_each():
    cases = golden()
    assert sorted({c["profile"] for c in cases.values() if c["profile"]}) == PROFILES
    assert len([c for c in cases.values() if c["profile"] == "itsm-rules"]) == 8
    assert len([c for c in cases.values() if c["profile"] == "handbook-gemini-graph-gate"]) == 3
    assert {c["runner"] for c in cases.values() if c["profile"] == "baseline"} == {
        "automationbench",
        "itsm",
        "handbook",
        "tau2",
    }


def test_the_golden_file_says_what_each_measured_profile_wired():
    cases = golden()

    def classes(name):
        return [h["class"] for h in cases[name]["description"]["hooks"]]

    def models(name):
        return sorted(
            (m["kind"], m["model"], m["timeout"], m.get("max_tokens"))
            for m in cases[name]["description"]["models"]
        )

    def slots(name):
        return sorted(k for k, v in cases[name]["description"]["slots"].items() if v)

    crestwood = "hr_crestwood_university_79786c46"
    assert classes("automationbench-gptoss-b4tf") == ["OnlinePolicyIntake", "RequirementsTracker"]
    assert models("automationbench-gptoss-b4tf") == [
        ("detector", "jaredpalmer/kev-4b", 60.0, None),
        ("json", "aws/gpt-oss-120b", 90.0, None),
        ("json", "aws/gpt-oss-120b", 400, 16000),
        ("questions", "jaredpalmer/kev-4b", 60.0, None),
    ]
    assert classes(f"handbook-dsv4-loop-guide/{crestwood}") == ["LoopHooks", "ProcedureGuide"]
    assert slots(f"handbook-dsv4-loop-guide/{crestwood}") == ["run"]
    assert models(f"handbook-dsv4-loop-guide/{crestwood}") == [("json", "azure/DeepSeek-V4-Pro", 300, 8000)]
    assert models(f"handbook-gptoss-loop-guide-evidence/{crestwood}") == [
        ("json", "aws/gpt-oss-120b", 180, None),
        ("json", "aws/gpt-oss-120b", 300, 8000),
    ]
    gate = cases[f"handbook-gemini-graph-gate/{crestwood}"]["description"]
    assert [h["class"] for h in gate["hooks"]] == ["StoreGate"]
    assert gate["gate_reads_tools_store"] == {
        "StoreGate": True
    }  # the old wiring shares its store, and this must stay
    assert [t["name"] for t in gate["tools"]][:2] == ["policy__list_procedures", "policy__get_procedure"]
    assert gate["system_note"].startswith("The SOP is also available as a procedure graph")
    assert models(f"handbook-gemini-graph-gate/{crestwood}") == [("json", "gcp/gemini-3.8-flash", 180, 4000)]
    # the SOP tracker and the navigator create no hook
    assert classes("tau2-telecom-dsv4-sop-tracker") == [] and slots("tau2-telecom-dsv4-sop-tracker") == [
        "turn_note"
    ]
    assert models("tau2-telecom-dsv4-sop-tracker") == [("json", "aws/gpt-oss-120b", 90, 8000)]
    assert classes("tau2-telecom-gptoss-navigator") == []
    assert slots("tau2-telecom-gptoss-navigator") == ["after_reply", "wrap_tools"]
    navigator = cases["tau2-telecom-gptoss-navigator"]["description"]["slots"]
    assert (
        navigator["wrap_tools"]["message_tool"]
        == navigator["after_reply"]["message_tool"]
        == "send_message_to_user"
    )
    assert classes("itsm-rules/e2891a7b98") == ["RuleSetHooks"]
    # the IT service runner seeds the gate with the request, HANDBOOK does not
    assert cases["other/itsm-gate-over-policy-text"]["description"]["hooks"][0]["attrs"]["reads"] != []
    assert cases["other/handbook-gate-over-sop-file"]["description"]["hooks"][0]["attrs"]["reads"] == []


@needs_all_inputs
def test_every_profile_gives_the_description_in_the_golden_file():
    done = run(str(TOOL), "check")
    assert done.returncode == 0, done.stdout[-6000:] + done.stderr[-3000:]
    assert "differences: 0" in done.stdout
    match = re.search(r"cases: (\d+); profiles that match: (\d+) of (\d+)", done.stdout)
    assert int(match.group(1)) == len(golden())
    assert match.group(2) == match.group(3) == str(len(PROFILES))


@needs_all_inputs
def test_the_check_finds_a_changed_wiring(tmp_path):
    changed = json.loads(GOLDEN.read_text())
    gate = changed["cases"]["handbook-gemini-graph-gate/hr_crestwood_university_79786c46"]["description"]
    gate["hooks"][0]["attrs"]["model"]["model"]["max_tokens"] = 8000
    gate["gate_reads_tools_store"] = {"StoreGate": False}
    changed["cases"]["tau2-telecom-gptoss-navigator"]["description"]["slots"]["wrap_tools"][
        "message_tool"
    ] = ""
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(changed))
    done = run(str(TOOL), "check", "--golden", str(path))
    assert done.returncode == 1
    for word in ("max_tokens", "gate_reads_tools_store", "message_tool", "differences: 3"):
        assert word in done.stdout


def test_the_golden_file_is_frozen_and_the_capture_path_is_gone():
    """It was written from the old runners, which left with task 6.1. A new write could only come from ``build_runtime``, and
    would prove nothing. ``policy/pre-migration-removal`` holds the command that wrote it."""
    assert (
        hashlib.sha256(GOLDEN.read_bytes()).hexdigest()
        == "bf6b49b91d8e63d0dcf50b6575c87cc02da60374009ef1ebeb097c5636440890"
    )
    done = run(str(TOOL), "capture")
    assert done.returncode == 2 and "invalid choice" in done.stderr


@pytest.mark.parametrize(
    "runner, python",
    [
        ("automationbench", BENCHMARKS / "automationbench" / ".venv" / "bin" / "python"),
        ("tau2", Path.home() / "dev/cuga-eval-tau2/.venv/bin/python"),
    ],
)
def test_build_runtime_runs_in_the_venv_of_the_benchmark(runner, python):
    if not python.exists():
        pytest.skip(f"no venv at {python}")
    done = run(str(TOOL), "check", "--runner", runner, python=str(python), env={"CUGA_SRC": str(GATE_SRC)})
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    assert "differences: 0" in done.stdout


GUARD_PARITY = r"""
import asyncio, importlib.util, json, sys
from langchain_core.tools import StructuredTool
from pydantic import BaseModel
from cuga.policy_layer.sop_navigator import HandoffGuard

spec = importlib.util.spec_from_file_location("cuga_runner_old", sys.argv[1])
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)


class Args(BaseModel):
    message: str = ""


class Navigator:
    def __init__(self):
        self.notes, self.seen = ["first note", "second note", None], []

    def check_handoff(self, turns, call_args=None):
        self.seen.append(json.loads(json.dumps([turns, call_args])))
        return self.notes.pop(0)


def decoys(ran):
    def decoy(name):
        async def run(message=""):
            ran.append((name, message))
            return f"{name} ran"
        return StructuredTool(name=name, description=name, args_schema=Args, coroutine=run)
    return [decoy(n) for n in ("get_line", "send_message_to_user", "transfer_to_human_agents")]


async def scenario(wrap):
    ran, turns, live, nav = [], [{"role": "customer", "text": "help"}], [], Navigator()
    get_line, send, transfer = wrap(decoys(ran), nav, turns, live)
    results = [
        await get_line.ainvoke({"message": "line 1"}),
        await send.ainvoke({"message": "Is it fixed?"}),
        await transfer.ainvoke({"message": "to a human"}),
        await get_line.ainvoke({"message": "line 2"}),
        await transfer.ainvoke({"message": "to a human"}),
        await transfer.ainvoke({"message": "to a human"}),
    ]
    return {"results": results, "ran": ran, "live": live, "seen": nav.seen}


def old_wrap(tools, nav, turns, live):
    return old._guard_handoffs(tools, nav, turns, live, {"nav_blocks": 0}, {"blocks": 0, "max": 2})


def new_wrap(tools, nav, turns, live):
    guard = HandoffGuard(nav, handoff_tools=["transfer_to_human_agents"], max_blocks=2, message_tool="send_message_to_user")
    return guard.wrap_tools(tools, turns, live)


first, second = asyncio.run(scenario(old_wrap)), asyncio.run(scenario(new_wrap))
print(json.dumps({"same": first == second, "old": first, "new": second}))
"""


@pytest.mark.skipif(not TAU2.is_dir(), reason="the τ² worktree is missing")
def test_the_guard_does_what_the_old_guard_does_now_that_the_old_guard_works():
    """The old guard raised on every call until its ``live +=`` was fixed, so this comparison needs that fix."""
    result = json.loads(run_python(GUARD_PARITY, str(TAU2 / "cuga_runner.py")))
    assert result["same"], result
    assert result["old"]["results"][:3] == ["get_line ran", "send_message_to_user ran", "first note"]
    assert result["old"]["results"][4:] == ["second note", "transfer_to_human_agents ran"]
    assert [t["role"] for t in result["old"]["live"]] == ["tool", "agent", "customer", "tool", "tool"]


NO_PACKAGE = r"""
import json, sys
from pathlib import Path
from cuga.policy_layer.dry_run import RecordingModels
from cuga.policy_layer.policy_config import load_config
from cuga.policy_layer.runtime import RunContext, RuntimeWiringError, build_runtime

root = Path(sys.argv[1])
cfg = load_config(root / "profiles" / "itsm-rules.yaml")
tasks = [t for t in json.loads(Path(sys.argv[2]).read_text()) if t["_policy_hash"] == "80cd3ebb50"]
print(len(tasks))
assert not (root / cfg.package.format(policy="80cd3ebb50")).exists()
for t in tasks:
    ctx = RunContext(task_id=t["task_id"], policy_version=t["_policy_hash"], system_prompt=t["system_prompt"])
    try:
        build_runtime(cfg, None, ctx, models=RecordingModels())
    except RuntimeWiringError as exc:
        print(exc)
    else:
        print("NO ERROR " + t["task_id"])
"""


def test_a_task_whose_policy_version_has_no_package_stops_with_task_and_version():
    tasks = BENCHMARKS / "enterpriseops_gym" / "tasks" / "itsm_oracle.json"
    lines = run_python(NO_PACKAGE, str(POLICY_EVAL), str(tasks)).splitlines()
    assert lines[0] == "4"  # the 4 tasks of the policy version with no build
    assert "NO ERROR" not in "\n".join(lines)
    expected = [t["task_id"] for t in json.loads(tasks.read_text()) if t["_policy_hash"] == "80cd3ebb50"]
    for task_id, line in zip(expected, lines[1:]):
        assert task_id in line and "80cd3ebb50" in line and "package" in line


GRAPH_GUIDE = r"""
import sys
from pathlib import Path
from cuga.policy_layer.dry_run import RecordingModels
from cuga.policy_layer.package import load_package
from cuga.policy_layer.policy_config import load_config
from cuga.policy_layer.runtime import RunContext, RuntimeWiringError, build_runtime

root = Path(sys.argv[1])
for policy in sys.argv[2:]:
    cfg = load_config(root / "profiles" / "handbook-dsv4-loop-guide.yaml")
    pkg = load_package(root / f"packages/handbook/{policy}/claude_v1/package.json")
    try:
        build_runtime(cfg, pkg, RunContext(task_id=policy, policy_version=policy), models=RecordingModels())
    except RuntimeWiringError as exc:
        print(exc)
    else:
        print("NO ERROR")
"""


def test_the_guide_on_a_real_graph_package_raises():
    policies = sorted(p.name for p in (POLICY_EVAL / "packages" / "handbook").iterdir() if p.is_dir())
    assert len(policies) == 3
    lines = run_python(GRAPH_GUIDE, str(POLICY_EVAL), *policies).splitlines()
    assert len(lines) == 3 and all(
        "component guide" in line and "no tool to stop on" in line for line in lines
    )


REAL_MODELS_NEED_KEY = r"""
import sys
from pathlib import Path
from cuga.policy_layer.policy_config import load_config
from cuga.policy_layer.runtime import RunContext, RuntimeWiringError, build_runtime

root = Path(sys.argv[1])
cfg = load_config(root / "profiles" / "automationbench-gptoss-b4tf.yaml")
ctx = RunContext(task_id="t", policy_version="v", tool_specs=[{"name": "x"}], data_search=[("x", print)])
try:
    build_runtime(cfg, None, ctx)
except RuntimeWiringError as exc:
    print(exc)
"""


def test_the_decision_model_with_no_key_stops_the_run():
    env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
    env["OPENAI_API_KEY"] = "not-used"
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", REAL_MODELS_NEED_KEY, str(POLICY_EVAL)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert "OPENROUTER_API_KEY" in done.stdout and "task t" in done.stdout


BASELINE = r"""
import json, sys
from pathlib import Path
from cuga.policy_layer.policy_config import load_config
from cuga.policy_layer.runtime import RunContext, build_runtime

parts = build_runtime(load_config(Path(sys.argv[1]) / "profiles" / "baseline.yaml"), None, RunContext(task_id="t"))
print(json.dumps([parts.hooks, parts.tools, parts.system_note, parts.run, parts.turn_note, parts.wrap_tools,
                  parts.after_reply, parts.usage(), parts.records()]))
"""


def test_the_baseline_profile_adds_nothing_with_the_real_model_factory():
    assert json.loads(run_python(BASELINE, str(POLICY_EVAL))) == [[], [], "", None, None, None, None, {}, []]
