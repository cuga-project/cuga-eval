"""What the brief of a rule list shows, from a package, with no model call (Task 5.3).

    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/tools/rule_list_brief.py [--json]

For each package below, the brief that ``build_runtime`` gives the rule hooks, in three settings: ``measured`` (the brief as it
was: no exceptions, no guidance without a tool), ``rule list`` (``shapes: [rules]``, so each rule shows its ``exception_of``
exceptions) and ``rule list + guidance`` (also ``notes.brief_guidance``). It counts the rules, the guidance items, the exception
lines and the characters of the brief. The ITSM row reads the policy build of the best ITSM arm, for the figure "22 of 23 guidance
rules never appear". Nothing here calls a model: the verifier, the gate and the organizers are off.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
POLICY_EVAL = HERE.parent
sys.path[:0] = [str(POLICY_EVAL.parent)]

from cuga.policy_layer.package import load_package  # noqa: E402
from cuga.policy_layer.policy_config import PolicyConfig  # noqa: E402
from cuga.policy_layer.ruleset import RuleSetHooks  # noqa: E402
from cuga.policy_layer.runtime import RunContext, build_runtime  # noqa: E402

PACKAGES = {
    "airline": (
        POLICY_EVAL / "packages/tau2_airline/airline/skill_v1/package.json",
        POLICY_EVAL / "tau2/airline_tools.json",
    ),
    "retail": (
        POLICY_EVAL / "packages/tau2_retail/retail/skill_v1/package.json",
        POLICY_EVAL / "tau2/retail_tools.json",
    ),
    "itsm v4A": (
        POLICY_EVAL / "packages/itsm/e2891a7b98/builds_v4_v4A/package.json",
        POLICY_EVAL.parent / "enterpriseops_gym/tasks/itsm_tools.json",
    ),
}
ORGANIZERS = {
    k: "off" for k in ("procedure_tools", "guide", "loop", "sop_tracker", "navigator", "requirements_tracker")
}
SETTINGS = {
    "measured": {"shapes": ["procedures"], "notes": {}},
    "rule list": {"shapes": ["rules"], "notes": {}},
    "rule list + guidance": {"shapes": ["rules"], "notes": {"brief_guidance": True}},
}


def config(setting: Dict[str, Any]) -> PolicyConfig:
    return PolicyConfig.from_dict(
        {
            "package": "p.json",
            "shapes": setting["shapes"],
            "notes": setting["notes"],
            "checkers": {
                "rules": "on",
                "gate": {"mode": "off"},
                "verifier": {"mode": "off"},
                "write_checks": "off",
            },
            # one component left to auto, so that the declared shape is read (and is not refused)
            "organizers": {**ORGANIZERS, "guide": "auto"},
            "decisions": {"mode": "off"},
        }
    )


def parts_for(pkg: Any, specs: List[Dict[str, Any]], setting: Dict[str, Any]) -> Any:
    ctx = RunContext(task_id="rule-list-brief", policy_version="v1", tool_specs=specs, agent_model="")
    return build_runtime(config(setting), pkg, ctx, models=None)


def brief_for(pkg: Any, specs: List[Dict[str, Any]], setting: Dict[str, Any]) -> str:
    hooks = [h for h in parts_for(pkg, specs, setting).hooks if isinstance(h, RuleSetHooks)]
    if len(hooks) != 1:
        raise AssertionError("the run has one rule hook")
    return hooks[0].before_llm_call(None).message or ""


def pending_parts(pkg: Any, specs: List[Dict[str, Any]], setting: Dict[str, Any]) -> List[str]:
    """The parts that send a message about work still to do (the procedure monitor's missing steps, the SOP tracker's note)."""
    parts = parts_for(pkg, specs, setting)
    names = [type(h).__name__ for h in parts.hooks] + list(parts.components)
    return sorted({n for n in names if n in ("ProcedureMonitor", "sop_tracker", "navigator")})


def tracker_rows() -> List[Dict[str, Any]]:
    """The SOP tracker under ``auto`` on every ``skill_v1`` package, at levels 1 to 3: with the shapes inferred, and with
    ``shapes: [flow]`` declared. The tracker's model is a name only; nothing is called."""
    from cuga.policy_layer.levels import resolve

    rows = []
    for path in sorted(POLICY_EVAL.glob("packages/**/skill_v1/package.json")):
        pkg = load_package(path)
        row: Dict[str, Any] = {"package": str(path.relative_to(POLICY_EVAL / "packages").parent.parent)}
        for label, shapes in (("inferred", []), ("declared flow", ["flow"])):
            for level in (1, 2, 3):
                cfg = PolicyConfig.from_dict(
                    {
                        "package": "p.json",
                        "shapes": shapes,
                        "control": {"level": level},
                        "checkers": {"rules": "off", "gate": {"mode": "off"}, "verifier": {"mode": "off"}},
                        "organizers": {
                            **{k: "off" for k in ORGANIZERS},
                            "sop_tracker": {"mode": "auto", "model": "m/tracker"},
                        },
                        "decisions": {"mode": "off"},
                    }
                )
                out = resolve(cfg, pkg, "m/agent", policy_text="Policy text.")
                row[f"{label} level {level}"] = out.cfg.organizers.sop_tracker.mode
        row["inferred shapes"] = resolve(
            PolicyConfig.from_dict({"package": "p.json"}), pkg, "m/agent", policy_text="x"
        ).shapes
        rows.append(row)
    return rows


def measure(name: str) -> Dict[str, Any]:
    package, tools = PACKAGES[name]
    pkg = load_package(package)
    specs = json.loads(tools.read_text())
    guidance = [r for r in pkg.rules if r.type == "guidance"]
    with_tool = [r for r in guidance if r.rule.get("tools") or r.rule.get("tool")]
    row: Dict[str, Any] = {
        "package": name,
        "rules": len(pkg.rules),
        "guidance": len(guidance),
        "guidance_with_tool": len(with_tool),
        "exception_links": len(
            [lk for lk in pkg.links if str(getattr(lk.type, "value", lk.type)) == "exception_of"]
        ),
    }
    texts = {r.rule.get("text", "") for r in guidance}
    for label, setting in SETTINGS.items():
        brief = brief_for(pkg, specs, setting)
        lines = brief.splitlines()[1:]
        row[label] = {
            "chars": len(brief),
            "items": len([x for x in lines if x.startswith("- ")]),
            "exception_lines": len([x for x in lines if x.lstrip().startswith("- exception [")]),
            "guidance_shown": len([t for t in texts if t and t in brief]),
            "pending_parts": pending_parts(pkg, specs, setting),
        }
    return row


def main() -> int:
    rows = [measure(n) for n in PACKAGES if PACKAGES[n][0].exists()]
    trackers = tracker_rows()
    if "--json" in sys.argv:
        print(json.dumps({"rows": rows, "trackers": trackers}, indent=1))
        return 0
    for row in rows:
        print(
            f"{row['package']}: {row['rules']} rules, {row['guidance']} guidance ({row['guidance_with_tool']} name a tool), "
            f"{row['exception_links']} exception_of links"
        )
        for label in SETTINGS:
            m = row[label]
            print(
                f"  {label:22} {m['items']:3} items, {m['exception_lines']} exception lines, "
                f"{m['guidance_shown']} of {row['guidance']} guidance shown, {m['chars']} characters; "
                f"pending-check parts built: {', '.join(m['pending_parts']) or 'none'}"
            )
    on = [t["package"] for t in trackers if any(t[f"inferred level {n}"] == "on" for n in (1, 2, 3))]
    flow = [
        t["package"]
        for t in trackers
        if t["declared flow level 2"] == "on" and t["declared flow level 3"] == "on"
    ]
    print(
        f"SOP tracker under auto, {len(trackers)} skill_v1 packages: on with inferred shapes (levels 1 to 3): {len(on)}; "
        f"on at levels 2 and 3 with shapes: [flow]: {len(flow)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
