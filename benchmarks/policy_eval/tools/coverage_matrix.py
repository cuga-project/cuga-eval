"""Write ``packages/COVERAGE.md``: one row per package, what it holds and both parts of its audit.

    ~/dev/cuga-agent-gate/.venv/bin/python -I benchmarks/policy_eval/tools/coverage_matrix.py [--out FILE]

Rows: every ``skill_v1`` package (made with the skill from the policy text only) and every AutomationBench ``gold`` build
(audit only: the AutomationBench runtime stays online intake, and a gold build is not made from text). Nothing is typed by
hand except the tool and run files of each benchmark (``INPUTS``) and the notes at the end of the file, which are checked
facts of this task. The numbers come from:

  counts       ``cuga.policy_layer.counts.package_counts`` (what the package holds)
  part 1       ``rule_audit.static`` (validator, grounding, rules that never fire) and the saved back-translation result of
               this package version (``rule_audit.py backtrans``; the one paid step)
  part 2       ``rule_audit.tests_run`` (the package's own decision tests, by layer) and ``rule_audit.replay`` (saved runs of
               the policy: denies on passed runs)
  label        ``audit_report.basis_of`` (the ``policies`` section of ``sets/registry.json``)

``--md FILE`` replaces the text between the two table markers of the file and leaves the notes around them as they are.

The tool schema is a layer of its own in part 2. A test whose call the tool's own schema rejects (an argument outside an enum,
or a string that does not match the argument's ``pattern``) says nothing about a rule: it is counted apart (``schema``), and
the rule numbers beside it are for the tests the schema accepts.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent.parent
BENCH = HERE.parent
sys.path.insert(0, str(HERE))

import audit_report  # noqa: E402
import rule_audit as ra  # noqa: E402
from cuga.policy_layer.counts import package_counts  # noqa: E402
from cuga.policy_layer.validate import statement_outcomes  # noqa: E402

PACKAGES = HERE / "packages"
START, END = "<!-- tables:start (tools/coverage_matrix.py) -->", "<!-- tables:end -->"
TAU2 = Path.home() / "dev/cuga-eval-tau2/benchmarks/tau2"
ITSM_TOOLS = BENCH / "enterpriseops_gym" / "tasks" / "itsm_tools.json"
ITSM_RUNS = [str(BENCH / "enterpriseops_gym/results/*/A_*.json")]
ITSM_ROLES = [str(BENCH / "enterpriseops_gym/results/*/B_*.json")]


def _hb(policy: str) -> Tuple[str, List[str], List[str]]:
    return (
        str(BENCH / "handbook" / "tools" / f"{policy}.json"),
        [str(BENCH / f"handbook/results/*_A_t*/{policy}.json")],
        [],
    )


def _inputs() -> Dict[str, Tuple[str, List[str], List[str]]]:
    inputs: Dict[str, Tuple[str, List[str], List[str]]] = {}
    for policy in sorted(p.name for p in (PACKAGES / "handbook").iterdir() if (p / "skill_v1").is_dir()):
        inputs[f"handbook/{policy}/skill_v1"] = _hb(policy)
    for policy in sorted(p.name for p in (PACKAGES / "itsm").iterdir() if (p / "skill_v1").is_dir()):
        inputs[f"itsm/{policy}/skill_v1"] = (str(ITSM_TOOLS), ITSM_RUNS, ITSM_ROLES)
    runs = lambda *tags: [str(TAU2 / f"logging_{t}_A_s*/results/tau2_*.json") for t in tags]  # noqa: E731
    inputs["tau2_telecom/telecom/skill_v1"] = (
        str(HERE / "tau2/telecom_tools.json"),
        runs("dev1", "dev2", "test1", "test2") + [str(TAU2 / "logging_t20_ds/results/tau2_*.json")],
        [],
    )
    inputs["tau2_airline/airline/skill_v1"] = (
        str(HERE / "tau2/airline_tools.json"),
        runs("air1") + [str(TAU2 / f"logging_{t}/results/tau2_*.json") for t in ("a20_ds", "a20_oss")],
        [],
    )
    inputs["tau2_retail/retail/skill_v1"] = (str(HERE / "tau2/retail_tools.json"), [], [])
    for policy in sorted(p.name for p in (PACKAGES / "automationbench").iterdir() if (p / "gold").is_dir()):
        inputs[f"automationbench/{policy}/gold"] = (
            str(HERE / "gold" / "ab" / policy / "tools.json"),
            [str(BENCH / f"automationbench/results/*_A_t*/{policy}.json")],
            [],
        )
    return inputs


def measure(spec: str, tools: str, runs: List[str], roles: List[str]) -> Dict[str, Any]:
    t = ra.load_target(spec)
    specs = ra.read_specs(tools)
    counts = package_counts(t.pkg)
    st = ra.static(t, specs)
    out: Dict[str, Any] = {"package": spec, "counts": counts, "static": st}
    out["label"] = audit_report.basis_of(t.bench, t.policy, t.build)
    bts, _ = ra.current_results("backtrans", t, [])
    bts = [r for r in bts if r.get("status") == "ok" and "judged" in r]
    out["backtrans"] = (
        {k: bts[-1][k] for k in ("counts", "judged", "not_judged", "file", "ran_at")} if bts else None
    )
    tr = ra.tests_run(t, specs, save=False) if t.pkg.tests else {"status": "no tests"}
    out["tests"] = _test_numbers(tr)
    if tr.get("status") == "ok":
        known = {st["id"] for st in ra.statements_of(t.pkg)}
        out["tests"]["statement_ids_known"] = sum(
            1 for r in tr["rows"] if r["case"].get("statement_id") in known
        )
        out["causes"] = deny_causes(t.pkg, tr["rows"])
        outcomes = statement_outcomes(t.pkg)
        bare = [
            c.get("statement_id")
            for c in t.pkg.tests
            if c.get("expected") == "deny"
            and c.get("statement_id") in outcomes
            and not outcomes[c["statement_id"]]
        ]
        out["tests"]["deny_on_no_outcome"] = {"tests": len(bare), "statements": len(set(bare))}
    out["replay"] = (
        _replay_numbers(ra.replay(t, specs, runs, roles, save=False)) if runs else {"status": "no runs"}
    )
    ce = ra.cedar(t, specs, save=False)
    out["cedar"] = {
        "status": ce.get("status"),
        "differences": ce.get("differences"),
        "reason": ce.get("reason", ""),
    }
    return out


def _test_numbers(tr: Dict[str, Any]) -> Dict[str, Any]:
    if tr.get("status") != "ok":
        return {"status": tr.get("status")}
    rows = tr["rows"]
    s = tr["summary"]
    clean = [r for r in rows if not r.get("schema")]
    deny = [r for r in clean if r["case"]["expected"] == "deny"]
    allow = [r for r in clean if r["case"]["expected"] == "allow"]
    return {
        "status": "ok",
        "cases": tr["cases"],
        "deny_cases": s["deny_cases"],
        "allow_cases": s["allow_cases"],
        "schema_deny": sum(1 for r in rows if r.get("schema") and r["case"]["expected"] == "deny"),
        "schema_allow": s["schema_on_allow"],
        "clean_deny_cases": len(deny),
        "clean_allow_cases": len(allow),
        "caught_by_rules": sum(r["decision"] in ("deny", "remind") for r in deny),
        "caught_deny": sum(r["decision"] == "deny" for r in deny),
        "false_deny": sum(r["decision"] == "deny" for r in allow),
        "false_remind": sum(r["decision"] == "remind" for r in allow),
        "errors": s["errors"],
        "layers": {k: v["caught"] for k, v in s["layers"].items()},
    }


def _replay_numbers(rp: Dict[str, Any]) -> Dict[str, Any]:
    if rp.get("status") != "ok":
        return {"status": rp.get("status"), "reason": rp.get("reason", "")}
    r = rp["replayed"]
    by_rule = r["by_rule"]
    return {
        "status": "ok",
        "runs": r["runs"],
        "passed_runs": r["passed_runs"],
        "denies_on_passed": r["denies_on_passed"],
        "passed_runs_with_deny": r["passed_runs_with_deny"],
        "denies_on_failed": r["denies_on_failed"],
        "reminds_on_failed": r["reminds_on_failed"],
        "reminds_on_passed": r["reminds_on_passed"],
        "passed_runs_with_remind": r["passed_runs_with_remind"],
        "outliers": sorted(
            f"{k} (denies on passed {v['deny_on_passed']}, reminds on passed {v['remind_on_passed']})"
            for k, v in by_rule.items()
            if v["deny_on_passed"] >= 5 or v["remind_on_passed"] >= 5
        ),
        "errors": rp.get("errors", 0),
    }


CAUSE_ORDER = (
    "code rule",
    "verify",
    "obligation or step",
    "guidance, duty or global rule",
    "definition",
    "question only",
    "no outcome",
    "statement id not in the package",
)
NOT_CODE = {"verify", "guidance", "grounded_values", "id_provenance", "duty"}


def deny_causes(pkg: Any, rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """The deny tests the tool schema accepts, by what the tested statement became (the strongest outcome first): a code rule
    (a typed rule that a single call can break), a verify rule, an obligation or a procedure step, a guidance, duty or global
    rule, a definition, a policy question only, or nothing. ``caught`` is a deny or a reminder by the package's rules. A test
    whose statement id is not in the package (the stored ITSM tests: an older split) cannot be placed."""
    outcomes = statement_outcomes(pkg)
    types: Dict[str, set] = {}
    for rule in pkg.rules:
        for sid in rule.statement_ids:
            types.setdefault(sid, set()).add(rule.type)
    cells: Dict[str, Dict[str, int]] = {k: {"tests": 0, "caught": 0} for k in CAUSE_ORDER}
    for row in rows:
        case = row["case"]
        if case["expected"] != "deny" or row.get("schema"):
            continue
        sid = case.get("statement_id")
        kinds, kind_types = set(outcomes.get(sid) or []), types.get(sid, set())
        if sid not in outcomes:
            cause = "statement id not in the package"
        elif kind_types - NOT_CODE:
            cause = "code rule"
        elif "verify" in kind_types:
            cause = "verify"
        elif kinds & {"obligation", "procedure_step"}:
            cause = "obligation or step"
        elif kind_types or "guidance" in kinds or "hard_rule" in kinds or "judgment_rule" in kinds:
            cause = "guidance, duty or global rule"
        elif "definition" in kinds:
            cause = "definition"
        elif "question" in kinds:
            cause = "question only"
        else:
            cause = "no outcome"
        cells[cause]["tests"] += 1
        cells[cause]["caught"] += row["decision"] in ("deny", "remind")
    return {k: v for k, v in cells.items() if v["tests"]}


COMPARE = {  # a policy whose builds are measured side by side on one set of tests and runs
    "itsm/e2891a7b98": ("skill_v1", "builds_v4_v4A", "builds_v5", "gold"),
}


def compare_builds(
    policy: str, builds: Any, tools: str, runs: List[str], roles: List[str]
) -> List[Dict[str, Any]]:
    """The same tests and the same runs through several builds of one policy, all numbers on one denominator."""
    specs = ra.read_specs(tools)
    out = []
    for build in builds:
        t = ra.load_target(f"{policy}/{build}")
        tr = ra.tests_run(t, specs, save=False)
        rows = tr["rows"]
        deny = [r for r in rows if not r.get("schema") and r["case"]["expected"] == "deny"]
        allow = [r for r in rows if not r.get("schema") and r["case"]["expected"] == "allow"]
        replay = ra.replay(t, specs, runs, roles, save=False)["replayed"]
        every_deny = [r for r in rows if r["case"]["expected"] == "deny"]
        out.append(
            {
                "build": build,
                "tests_hash": tr["tests_hash"],
                "deny_accepted": len(deny),
                "allow_accepted": len(allow),
                "deny_all": len(every_deny),
                "rules_caught": sum(r["decision"] in ("deny", "remind") for r in deny),
                "rules_deny": sum(r["decision"] == "deny" for r in deny),
                "rules_remind": sum(r["decision"] == "remind" for r in deny),
                "with_schema": tr["summary"]["caught"],
                "rules_alone_all": sum(r["rules_alone"] in ("deny", "remind") for r in every_deny),
                "false_deny": sum(r["decision"] == "deny" for r in allow),
                "false_remind": sum(r["decision"] == "remind" for r in allow),
                "passed_runs": replay["passed_runs"],
                "passed_runs_denied": replay["passed_runs_with_deny"],
            }
        )
    return out


# -- text ---------------------------------------------------------------------------------------------------------------


def _short(spec: str) -> str:
    bench, policy, build = spec.split("/")
    return f"{bench}/{policy}" + ("" if build == "skill_v1" else f" ({build})")


def _outcomes(c: Dict[str, Any]) -> str:
    if not c["statements"]:
        return "no text in the package"
    return ", ".join(f"{k} {v}" for k, v in c["by_outcome"].items()) or "none"


def _classes(c: Dict[str, Any]) -> str:
    by = c["rules_by_class"]
    return f"{by.get('hard', 0)} / {by.get('judgment', 0)} / {by.get('guidance', 0)}"


def _bt(b: Optional[Dict[str, Any]]) -> str:
    if not b:
        return "not run"
    n = b["counts"]
    return (
        f"{n.get('equivalent', 0)} of {b['judged']} equivalent (broader {n.get('broader', 0)}, "
        f"narrower {n.get('narrower', 0)}, different {n.get('different', 0)})"
    )


def _bare_cell(r: Dict[str, Any]) -> str:
    bare = r["tests"].get("deny_on_no_outcome")
    if bare is None:
        return "-"
    if not r["tests"].get("statement_ids_known"):
        return "ids not in the package"
    return f"{bare['tests']} ({bare['statements']})"


def _tests_cell(r: Dict[str, Any]) -> str:
    n = r["counts"]["tests"]
    if not n:
        return "no tests"
    known = r["tests"].get("statement_ids_known")
    return str(n) if known == n else f"{n} ({known} with a statement id that exists)"


def render(rows: List[Dict[str, Any]], compare: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> str:
    new = [r for r in rows if r["package"].endswith("/skill_v1")]
    gold = [r for r in rows if r["package"].endswith("/gold")]
    out: List[str] = []

    def table(head: List[str], body: List[List[Any]]) -> None:
        out.append("| " + " | ".join(head) + " |")
        out.append("|" + "|".join("---" for _ in head) + "|")
        out.extend("| " + " | ".join(str(c) for c in r) + " |" for r in body)
        out.append("")

    out += ["## 1. What each package holds", ""]
    table(
        [
            "Package",
            "Label",
            "Statements (must, must-not)",
            "Must or must-not statements with no outcome",
            "Deny tests on a statement with no outcome (statements)",
            "Outcomes (statements)",
            "Rules hard / judgment / guidance",
            "Verify",
            "Procedures (steps, must-nots)",
            "Obligations",
            "Policy questions",
            "Tests",
        ],
        [
            [
                _short(r["package"]),
                r["label"][0],
                f"{r['counts']['statements']} ({r['counts']['must_statements']})"
                if r["counts"]["statements"]
                else "none",
                r["counts"]["must_without_outcome"] if r["counts"]["statements"] else "-",
                _bare_cell(r),
                _outcomes(r["counts"]),
                _classes(r["counts"]),
                r["counts"]["verify_rules"],
                f"{r['counts']['procedures']} ({r['counts']['steps']}, {r['counts']['must_nots']})",
                r["counts"]["obligations"],
                r["counts"]["policy_questions"],
                _tests_cell(r),
            ]
            for r in new + gold
        ],
    )
    out += ["## 2. Audit part 1: do the rules say what the text says", ""]
    table(
        [
            "Package",
            "Label",
            "Validator errors / warnings",
            "Values not in the cited text",
            "Rules that never fire",
            "Unknown tool",
            "Cedar vs rule JSON",
            "Back-translation (judge reads the cited statements only)",
        ],
        [
            [
                _short(r["package"]),
                r["label"][0],
                f"{r['static']['validator']['errors']} / {r['static']['validator']['warnings']}",
                r["static"]["ungrounded_values"]
                if r["static"]["grounding"] == "ok"
                else "no text in the package",
                r["static"]["never_fire"],
                r["static"]["unknown_tool"],
                "no role rules"
                if r["cedar"]["status"] == "no role rules"
                else f"{r['cedar']['differences']} differ"
                if r["cedar"]["status"] == "ok"
                else r["cedar"]["status"],
                _bt(r["backtrans"]),
            ]
            for r in new + gold
        ],
    )
    out += ["## 3. Audit part 2: do the rules hold on real data", ""]
    out += [
        "Decision tests are the package's own, written from the text without the rules. A test whose call the tool schema "
        "rejects is counted in the schema columns and left out of the rule columns. Replay: saved arm-A runs of the policy "
        "(CUGA alone) through the package's code and Cedar checks; a deny on a passed run is a conflict with the grader.",
        "",
    ]
    body = []
    for r in new + gold:
        t, p = r["tests"], r["replay"]
        if t["status"] == "ok":
            tests = [
                t["cases"],
                f"{t['caught_by_rules']} of {t['clean_deny_cases']} ({t['caught_deny']} deny)",
                f"{t['false_deny']} of {t['clean_allow_cases']}",
                t["false_remind"],
                f"{t['schema_deny']} deny, {t['schema_allow']} allow",
            ]
        else:
            tests = [t["status"]] + ["-"] * 4
        if p["status"] != "ok":
            replay = p["status"]
        elif not p["passed_runs"]:
            replay = (
                f"{p['runs']} runs, no passed runs, so no deny on a passed run can be counted; on failed runs "
                f"{p['denies_on_failed']} denies and {p['reminds_on_failed']} reminders"
            )
        else:
            replay = (
                f"{p['runs']} runs, {p['passed_runs']} passed; {p['passed_runs_with_deny']} passed runs denied "
                f"({p['denies_on_passed']} denies), {p['passed_runs_with_remind']} reminded ({p['reminds_on_passed']}); "
                f"on failed runs {p['denies_on_failed']} denies and {p['reminds_on_failed']} reminders"
            )
        body.append([_short(r["package"]), r["label"][0], *tests, replay])
    table(
        [
            "Package",
            "Label",
            "Tests",
            "Deny tests caught by rules (schema-accepted)",
            "False denies (allow tests)",
            "False reminders",
            "Rejected by the tool schema",
            "Replay",
        ],
        body,
    )
    out += ["### Why deny tests are not caught: the outcome of the tested statement", ""]
    out += [
        "Deny tests that the tool schema accepts, by what the tested statement became in the package (the strongest outcome "
        "first). Each cell is caught of tests. Obligations and procedures have no test yet (Task 4.1 and 4.3 read them), so a "
        "deny test on an obligation or a step is caught only by a rule that happens to apply to the same tool. A `verify` rule "
        "never denies without a verifier model. The stored ITSM tests carry statement ids of an older split, so they cannot "
        "be placed.",
        "",
    ]
    cause_body = []
    for r in new:
        c = r.get("causes")
        if not c:
            continue
        total = sum(v["tests"] for v in c.values())
        cause_body.append(
            [_short(r["package"]), total]
            + [f"{c[k]['caught']} of {c[k]['tests']}" if k in c else "-" for k in CAUSE_ORDER]
        )
    table(["Package", "Deny tests"] + [k.capitalize() for k in CAUSE_ORDER], cause_body)
    for policy, builds in (compare or {}).items():
        out += [f"### {policy}: the builds on one set of tests and runs", ""]
        out += [
            "All numbers from one run now, on the same tests (same test hash) and the same saved runs. The tests are the tuning "
            "version: the 347 stored blind tests of this policy, and its runs were used to tune the earlier builds, so this is "
            "no held-out number. The count of hard denies differs a lot between the builds: a build that reminds where another "
            "denies gets the same `caught`.",
            "",
        ]
        table(
            [
                "Build",
                f"Rules, of {builds[0]['deny_accepted']}",
                "Deny / remind",
                f"With schema, of {builds[0]['deny_all']}",
                f"Rules alone, of {builds[0]['deny_all']}",
                f"False deny, of {builds[0]['allow_accepted']}",
                f"False remind, of {builds[0]['allow_accepted']}",
                f"Passed runs denied, of {builds[0]['passed_runs']}",
            ],
            [
                [
                    b["build"],
                    b["rules_caught"],
                    f"{b['rules_deny']} / {b['rules_remind']}",
                    b["with_schema"],
                    b["rules_alone_all"],
                    b["false_deny"],
                    b["false_remind"],
                    b["passed_runs_denied"],
                ]
                for b in builds
            ],
        )
    out += ["## 4. Verify rules per package (input for Task 3.5)", ""]
    out += [
        "A `verify` rule has no code check: it needs the verifier model, and with none it never denies. Share = verify rules "
        "of all rules.",
        "",
    ]
    table(
        [
            "Package",
            "Rules",
            "Verify",
            "Share",
            "Rules with a code check (not verify, guidance, duty or global)",
        ],
        [
            [
                _short(r["package"]),
                r["counts"]["rules"],
                r["counts"]["verify_rules"],
                f"{100 * r['counts']['verify_rules'] / max(r['counts']['rules'], 1):.0f}%",
                sum(
                    n
                    for k, n in r["counts"]["rules_by_type"].items()
                    if k not in ("verify", "guidance", "grounded_values", "id_provenance", "duty")
                ),
            ]
            for r in new
        ],
    )
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out", default=str(PACKAGES / "coverage_matrix.json"), help="the measured numbers, as JSON"
    )
    ap.add_argument("--md", default="", help="write the tables here (default: print)")
    a = ap.parse_args()
    inputs = _inputs()
    rows = [measure(spec, *i) for spec, i in inputs.items()]
    compare = {
        policy: compare_builds(policy, builds, *inputs[f"{policy}/skill_v1"])
        for policy, builds in COMPARE.items()
    }
    for builds in compare.values():
        assert len({b["tests_hash"] for b in builds}) == 1, "the builds were not measured on the same tests"
    Path(a.out).write_text(
        json.dumps({"rows": rows, "compare": compare}, indent=1, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    text = render(rows, compare)
    if a.md:
        path = Path(a.md)
        old = path.read_text(encoding="utf-8") if path.is_file() else ""
        if START in old and END in old:  # the notes around the tables are written by hand and stay
            head, rest = old.split(START, 1)
            tail = rest.split(END, 1)[1]
            path.write_text(f"{head}{START}\n{text}\n{END}{tail}", encoding="utf-8")
        else:
            path.write_text(f"{START}\n{text}\n{END}\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
