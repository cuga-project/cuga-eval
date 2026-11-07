"""The audit of a package (``rule_audit.py``): each method on a small package of a made-up shop, with models that answer from a
script, and the known numbers of one real policy from saved files.

The code is in the gate repo, so the checks run with the gate repo's Python. No model call, no ledger line in the real ledger.
"""

import ast
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

POLICY_EVAL = Path(__file__).resolve().parents[1]
BENCHMARKS = POLICY_EVAL.parent
GATE_PYTHON = os.environ.get("POLICY_GATE_PYTHON") or str(
    Path.home() / "dev/cuga-agent-gate/.venv/bin/python"
)
ITSM_TOOLS = BENCHMARKS / "enterpriseops_gym" / "tasks" / "itsm_tools.json"
ITSM_RUNS = BENCHMARKS / "enterpriseops_gym" / "results"

# The made-up policy: refunds, closing orders, one rule that only reminds, one statement with no rule.
PRELUDE = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import rule_audit as ra
import policy_pilot_costs as costs
from cuga.policy_layer.model import CoverageItem, Document, PolicyPackage, Rule, Section, Statement
from cuga.policy_layer.package import save_package

tmp = Path(sys.argv[2])
ra.OUT = tmp / "results"
costs.LEDGER = tmp / "ledger.jsonl"
TOOLS = tmp / "tools.json"
TOOLS.write_text(json.dumps([
    {"name": "refund_order", "parameters": {"type": "object", "required": ["order_id"], "properties": {
        "order_id": {"type": "string"}, "reason": {"type": "string"}, "amount": {"type": "number"}}}},
    {"name": "close_order", "parameters": {"type": "object", "properties": {
        "order_id": {"type": "string"}, "status": {"type": "string", "enum": ["shipped", "closed"]}}}},
    {"name": "archive_order", "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}}},
]))
S = ["Refund reason must be damaged or late.", "Only managers may close orders.", "Orders must be gift wrapped.",
     "Refunds above 100 must be approved by the owner.", "Interns must not archive orders."]
STATEMENTS = [Statement(id=f"shop:1:{i}", text=t, modality="must") for i, t in enumerate(S, 1)]


def rule(rid, kind, level, number, **slots):
    body = {"id": rid, "type": kind, "source": "§1", "quote": S[number - 1], **slots}
    return Rule(id=rid, type=kind, rule=body, statement_ids=[f"shop:1:{number}"], quote=S[number - 1],
                source={"section": "1"}, cls="judgment" if kind == "verify" else "hard", level=level, checker="code")


RULES = [
    rule("rule_zq1", "allowed_values", "deny", 1, tool="refund_order", arg="reason", values=["damaged", "late"]),
    rule("rule_zq2", "role_permission", "deny", 2, tools=["close_order"], roles=["clerk"], effect="forbid"),
    rule("rule_zq3", "verify", "remind", 4, statement=S[3], tools=["refund_order"]),
    rule("rule_zq4", "role_permission", "remind", 5, tools=["archive_order"], roles=["intern"], effect="forbid"),
]
CASES = [
    {"tool": "refund_order", "args": {"order_id": "O1", "reason": "fun"}, "role": "clerk", "expected": "deny", "statement_id": "shop:1:1"},
    {"tool": "refund_order", "args": {"order_id": "O1", "reason": "late"}, "role": "clerk", "expected": "allow", "statement_id": "shop:1:1"},
    {"tool": "close_order", "args": {"order_id": "O1", "status": "closed"}, "role": "clerk", "expected": "deny", "statement_id": "shop:1:2"},
    {"tool": "close_order", "args": {"order_id": "O1", "status": "closed"}, "role": "manager", "expected": "allow", "statement_id": "shop:1:2"},
    {"tool": "close_order", "args": {"order_id": "O1", "status": "archived"}, "role": "manager", "expected": "deny", "statement_id": "shop:1:2"},
    {"tool": "archive_order", "args": {"order_id": "O1"}, "role": "clerk", "expected": "deny", "statement_id": "shop:1:3"},
    {"tool": "refund_order", "args": {"order_id": "O1", "reason": "late", "amount": 500}, "role": "clerk", "expected": "deny", "statement_id": "shop:1:4"},
    {"tool": "archive_order", "args": {"order_id": "O1"}, "role": "intern", "expected": "allow", "statement_id": "shop:1:5"},
]


def make(bench, policy, build, rules=RULES, tests=(), statements=STATEMENTS, coverage=True):
    doc = Document(id="shop", kind="markdown", sections=[Section(id="1", statements=list(statements))]) if statements else None
    pkg = PolicyPackage(version="v1", policy_hash=policy, documents=[doc] if doc else [], rules=list(rules), tests=list(tests),
                        coverage=[CoverageItem(f"shop:1:{i}", "hard_rule") for i in (1, 2, 4, 5)] if coverage else [])
    path = tmp / "packages" / bench / policy / build / "package.json"
    save_package(pkg, path)
    return path


def scripted(answer, usage_name="scripted"):
    """A model that answers from a function of (system, user), with the usage record the ledger reads."""
    seen = []

    def call(system, user):
        seen.append((system, user))
        call.usage["calls"] += 1
        call.usage["input_tokens"] += 10
        call.usage["output_tokens"] += 5
        return answer(system, user)

    call.usage, call.model_name, call.seen = {"calls": 0, "input_tokens": 0, "output_tokens": 0}, usage_name, seen
    return call
'''


def gate(code, tmp_path, *args):
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", PRELUDE + code, str(POLICY_EVAL), str(tmp_path), *args],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert done.returncode == 0, done.stdout[-2500:] + done.stderr[-3500:]
    return json.loads(done.stdout.strip().splitlines()[-1])


# -- each method on the small package ---------------------------------------------------------------------------------------


def test_static_counts_coverage_values_and_findings(tmp_path):
    out = gate(
        r"""
path = make("shopbench", "shop", "builds")
r = ra.static(ra.load_target(str(path)), ra.read_specs(str(TOOLS)))
print(json.dumps({k: r[k] for k in ("rules", "cedar_rules", "ungrounded_values", "never_fire", "unknown_tool", "coverage", "validator")}))
""",
        tmp_path,
    )
    assert (
        out["rules"],
        out["cedar_rules"],
        out["ungrounded_values"],
        out["never_fire"],
        out["unknown_tool"],
    ) == (4, 2, 0, 0, 0)
    assert out["coverage"]["statements"] == 5
    assert out["coverage"]["without_outcome"] == 1  # "Orders must be gift wrapped." has no outcome
    assert out["validator"]["mode"] == "strict" and out["validator"]["errors"] >= 1


def test_a_threshold_rule_whose_then_is_a_word_does_not_break_the_audit(tmp_path):
    out = gate(
        r"""
rule = {"type": "threshold", "tool": "refund_order", "arg": "amount", "op": "gt", "value": 100, "then": "forbid"}
print(json.dumps(ra._literals(rule)))
""",
        tmp_path,
    )
    assert out == []


def test_a_string_that_the_tool_pattern_rejects_is_a_schema_reject_and_not_a_rule_result(tmp_path):
    out = gate(
        r"""
specs = [{"name": "jira_get", "parameters": {"properties": {"issue_key": {"type": "string", "pattern": "^[A-Z]+-\\d+$"}}}}]
specs = [{**s, "inputSchema": ra.schema_of(s)} for s in specs]
print(json.dumps([ra._schema_reject({"tool": "jira_get", "args": {"issue_key": a}}, specs) for a in ("OPS-12", "OPS-FIN-2", 12)]))
""",
        tmp_path,
    )
    assert out[0] is None and out[2] is None  # a match, and a value that is not a string
    assert "OPS-FIN-2" in out[1] and "does not match the tool pattern" in out[1]


def test_tests_run_counts_every_layer_and_says_what_only_the_schema_stops(tmp_path):
    out = gate(
        r"""
path = make("shopbench", "shop", "builds", tests=CASES)
t = ra.load_target(str(path))
specs = ra.read_specs(str(TOOLS))
code = ra.tests_run(t, specs, save=False)
ra._model = lambda name: scripted(lambda s, u: json.dumps({"violations": [{"statement": 1, "reason": "needs approval", "fix": "ask"}]}
                                                          if '"amount": 500' in u else {"violations": []}))
with_verifier = ra.tests_run(t, specs, verifier_model="scripted", save=False)
print(json.dumps({"code": code["summary"], "verifier": with_verifier["summary"], "row": code["rows"][4]}))
""",
        tmp_path,
    )
    s, v = out["code"], out["verifier"]
    assert (s["deny_cases"], s["allow_cases"]) == (5, 3)
    assert (
        s["caught_by_schema"] == 1 and s["caught_only_by_schema"] == 1
    )  # archived is not in the tool's enum; no rule says so
    assert s["caught_deny"] == 2 and s["caught_deny_or_remind"] == 2 and s["caught"] == 3
    assert (s["false_deny"], s["false_remind"]) == (0, 1)  # an intern archiving an order gets a reminder
    assert (
        s["layers"]["code"]["caught"] == 1
        and s["layers"]["cedar"]["caught"] == 1
        and s["layers"]["verifier"]["caught"] == 0
    )
    assert s["layers"]["cedar"]["false_remind"] == 1
    assert (
        out["row"]["decision"] == "schema" and out["row"]["rules_alone"] == "allow"
    )  # the rules also ran on this call
    # the verifier layer catches the refund of 500 and nothing else changes
    assert (
        v["layers"]["verifier"]["caught"] == 1
        and v["caught"] == 4
        and v["false_deny"] == 0
        and v["verifier_errors"] == 0
    )


def test_a_verifier_that_fails_is_counted_not_hidden(tmp_path):
    out = gate(
        r"""
path = make("shopbench", "shop", "builds", tests=CASES)
def broken(system, user):
    raise RuntimeError("gateway hang")
ra._model = lambda name: scripted(broken)
r = ra.tests_run(ra.load_target(str(path)), ra.read_specs(str(TOOLS)), verifier_model="scripted", save=False)
print(json.dumps(r["summary"]))
""",
        tmp_path,
    )
    assert out["verifier_errors"] > 0 and out["layers"]["verifier"]["caught"] == 0


def test_a_package_with_no_tests_says_so(tmp_path):
    out = gate(
        r"""
path = make("shopbench", "shop", "builds")
r = ra.tests_run(ra.load_target(str(path)), ra.read_specs(str(TOOLS)), save=True)
print(json.dumps([r["status"], r["reason"], sorted(p.name for p in ra.OUT.glob("*"))]))
""",
        tmp_path,
    )
    assert out == ["no tests", "the package has no `tests`", []]  # nothing scored, no file written


def test_a_result_file_name_has_the_package_and_build_and_no_run_overwrites_another(tmp_path):
    out = gate(
        r"""
a = make("shopbench", "shop", "builds_a", tests=CASES)
b = make("shopbench", "shop", "builds_b", tests=CASES)
specs = ra.read_specs(str(TOOLS))
ta, tb = ra.load_target(str(a)), ra.load_target(str(b))
first = ra.tests_run(ta, specs)["file"]
text = (ra.OUT / first).read_text()
other_build = ra.tests_run(tb, specs)["file"]
again = ra.tests_run(ta, specs)["file"]
print(json.dumps([first, other_build, again, (ra.OUT / first).read_text() == text, sorted(p.name for p in ra.OUT.glob("*"))]))
""",
        tmp_path,
    )
    first, other_build, again, unchanged, files = out
    assert first == "tests_run__shopbench_shop__builds_a.json"
    assert other_build == "tests_run__shopbench_shop__builds_b.json"
    assert again == "tests_run__shopbench_shop__builds_a__2.json"
    assert unchanged and len(files) == 3


def test_cedar_validates_and_checks_every_role_and_tool_against_the_rule_json(tmp_path):
    out = gate(
        r"""
path = make("shopbench", "shop", "builds", tests=CASES)
r = ra.cedar(ra.load_target(str(path)), ra.read_specs(str(TOOLS)), save=False)
none = ra.cedar(ra.load_target(str(make("othermark", "plain", "builds", rules=RULES[:1], statements=[], coverage=False))),
                ra.read_specs(str(TOOLS)), save=False)
print(json.dumps([r, none["status"]]))
""",
        tmp_path,
    )
    r, none = out
    assert (
        r["roles"] == ["clerk", "intern", "manager"] and r["tools"] == 3 and r["requests"] == 9
    )  # roles of the rules and of the tests
    assert r["validator"]["passed"] and r["differences"] == 0
    assert none == "no role rules"


def test_replay_reads_old_and_new_runs_of_this_policy_only_and_says_why_it_leaves_one_out(tmp_path):
    out = gate(
        r"""
path = make("shopbench", "shop", "builds", tests=CASES)
sibling = make("shopbench", "shop", "builds_b", rules=RULES[:1])
other_policy = make("shopbench", "other", "builds")  # same package version "v1" as the policy above, another policy
t = ra.load_target(str(path))
runs = tmp / "runs"
runs.mkdir()
TOOLNAMES = ["refund_order", "close_order", "archive_order"]
def call(tool, **args):
    return {"tool": tool, "args": args, "result": {}}
def old(name, passed, calls, **extra):
    (runs / name).write_text(json.dumps({"tool_calls": calls, "tools": TOOLNAMES, **extra, **({"passed": passed} if passed is not None else {})}))
# an IT-service-style file: names its policy; one that breaks a deny rule and meets a reminder (an intern archives); one that breaks Cedar
old("A_pass.json", True, [call("refund_order", order_id="O1", reason="fun"), call("archive_order", order_id="O1")], task_id="A_pass.json", policy_version="shop")
old("A_fail.json", False, [call("close_order", order_id="O1", status="closed")], task_id="A_fail.json", policy_version="shop")
old("A_other.json", True, [], task_id="A_other.json", policy_version="other")
old("A_nopolicy.json", True, [call("archive_order", order_id="O1")], task_id="some task")  # names no policy and its task is no policy folder
# an AutomationBench/HANDBOOK-style file: no policy_version, the task is the policy folder, `pass` for passed
old("A_task.json", None, [call("refund_order", order_id="O1", reason="fun")], task="shop", **{"pass": True})
(runs / "B_pass.json").write_text(json.dumps({"task_id": "A_pass.json", "principal_role": "intern"}))
(runs / "B_fail.json").write_text(json.dumps({"task_id": "A_fail.json", "principal_role": "clerk"}))
# a tau2-style shard: runs of one domain with a chat log
(runs / "shard.json").write_text(json.dumps({"results": [
    {"task_id": "7", "domain": "shop", "reward": 0.0, "messages": [
        {"role": "assistant", "tool_calls": [{"id": "x", "name": "refund_order", "arguments": {"order_id": "O1", "reason": "fun"}}]},
        {"role": "tool", "content": "{}"}]},
    {"task_id": "8", "domain": "elsewhere", "reward": 1.0, "messages": []}]}))
# new result files of the harness
run = tmp / "harness" / "run_t1"
(run / "trajectories").mkdir(parents=True)
def new(task, version_id, passed, calls, lines, policy=None):
    (run / f"{task}.json").write_text(json.dumps({"schema": "policy_eval.result.v1", "task": task, "policy": policy, "package_version": version_id,
        "score": {"primary": 1.0 if passed else 0.0, "pass": passed}, "trajectory": str(run / "trajectories" / f"{task}.json")}))
    (run / "trajectories" / f"{task}.json").write_text(json.dumps({"tool_calls": calls}))
    (run / "work" / task).mkdir(parents=True, exist_ok=True)
    (run / "work" / task / "audit.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
line = lambda **kw: {"component": "rules", "hook": "before_tool_call", "tool": "refund_order", "rule_id": "rule_zq1", "class": "hard", "source": "§1", "verdict": "deny", **kw}
new("T_live", t.version_id, True, [], [line(package_version=t.version_id), line(package_version=t.version_id, verdict="remind", rule_id="rule_zq4")], policy="shop")
# saved before `policy` was written: its package is exactly one package of this policy folder (another build): replayed, not live
sib = ra.load_target(str(sibling)).version_id
new("T_sibling", sib, False, [call("refund_order", order_id="O1", reason="fun")], [line(package_version=sib)])
# the same package version part "v1", but the file hash is a package of another policy: cannot be told
new("T_foreign", ra.load_target(str(other_policy)).version_id, False, [call("refund_order", order_id="O1", reason="fun")], [])
new("T_named_other", t.version_id, False, [], [], policy="other")
(run / "T_ungraded.json").write_text(json.dumps({"schema": "policy_eval.result.v1", "task": "T_ungraded", "score": None}))
(run / "T_noaudit.json").write_text("not json")
specs = ra.read_specs(str(TOOLS))
r = ra.replay(t, specs, [str(runs / "*.json"), str(run / "*.json"), str(run / "work" / "*" / "audit.jsonl")], [str(runs / "B_*.json")], save=False)
nothing = ra.replay(t, specs, [], save=False)
nomatch = ra.replay(t, specs, [str(runs / "A_other.json")], save=False)
print(json.dumps([r, nothing, nomatch]))
""",
        tmp_path,
    )
    r, nothing, nomatch = out
    rep, live = r["replayed"], r["live"]
    # replayed: A_pass, A_fail, A_task, the tau2 run "7", T_sibling. Not the other 4 files
    assert (rep["runs"], rep["passed_runs"]) == (5, 2)
    assert (rep["denies_on_passed"], rep["passed_runs_with_deny"]) == (
        2,
        2,
    )  # A_pass and A_task break the allowed values
    assert (rep["reminds_on_passed"], rep["passed_runs_with_remind"]) == (
        1,
        1,
    )  # the intern, from the roles file
    assert (rep["denies_on_failed"], rep["failed_runs_with_deny"]) == (
        3,
        3,
    )  # A_fail (Cedar), tau2 run 7, T_sibling
    # roles: two from the roles file, the rest on the default; the count is in the result
    assert r["role_sources"] == {"roles file": 2, "default admin": 3} and r["errors"] == 0
    # live: the one run that names this very package version; its own audit lines
    assert (live["runs"], live["passed_runs"], live["denies_on_passed"], live["reminds_on_passed"]) == (
        1,
        1,
        1,
        1,
    )
    skipped = r["skipped"]
    assert (
        skipped["other policy (other)"] == 2 and skipped["other policy (elsewhere)"] == 1
    )  # A_other, T_named_other, tau2 run "8"
    assert (
        skipped["cannot tell policy: the file names no policy and its task is not this policy's folder"] == 1
    )  # A_nopolicy
    assert skipped["cannot tell policy: package version is not a package of this policy"] == 1  # T_foreign
    assert (
        skipped["not graded"] == 1
        and skipped["not a JSON object"] == 1
        and skipped["no tool_calls in it"] == 2
    )  # the two role files
    assert skipped["same run twice"] == 4  # the audit.jsonl of each of the 4 harness runs that have one
    assert "no policy or package named" not in skipped
    assert {(c["rule"], c["from"]) for c in r["conflicts_with_graders"]} == {
        ("rule_zq1", "replayed"),
        ("rule_zq1", "live"),
    }
    assert (
        nothing["status"] == "no runs"
        and nomatch["status"] == "no runs"
        and "other policy (other)" in nomatch["reason"]
    )


def test_tests_gen_stores_tests_in_the_package_and_shows_the_model_no_rule(tmp_path):
    out = gate(
        r"""
path = make("shopbench", "shop", "builds", rules=RULES)
t = ra.load_target(str(path))
before = json.loads(path.read_text())
model = scripted(lambda s, u: json.dumps({"cases": [{"tool": "refund_order", "args": {"order_id": "O1", "reason": "fun"}, "role": "clerk", "expected": "deny", "why": "w"}]}))
ra._model = lambda name: model
ra.tests_gen(t, ra.read_specs(str(TOOLS)), "scripted")
after = json.loads(path.read_text())
refused = None
try:
    ra.tests_gen(ra.load_target(str(path)), ra.read_specs(str(TOOLS)), "scripted")
except SystemExit as exc:
    refused = str(exc)
ra.tests_gen(ra.load_target(str(path)), ra.read_specs(str(TOOLS)), "scripted", replace=True)
no_text = None
try:
    ra.tests_gen(ra.load_target(str(make("othermark", "plain", "builds", statements=[], coverage=False))), ra.read_specs(str(TOOLS)), "scripted")
except SystemExit as exc:
    no_text = str(exc)
prompts = " ".join(u for _, u in model.seen)
print(json.dumps({"n": len(after["tests"]), "case": after["tests"][0], "same_rest": {k: v for k, v in after.items() if k != "tests"} == {k: v for k, v in before.items() if k != "tests"},
                  "refused": refused, "rules_seen": [r.id for r in RULES if r.id in prompts],
                  "incident": "incident" in prompts.lower(), "tests_after_replace": len(json.loads(path.read_text())["tests"]), "no_text": no_text,
                  "ledger": [json.loads(x)["kind"] for x in (tmp / "ledger.jsonl").read_text().splitlines()]}))
""",
        tmp_path,
    )
    assert out["n"] == 5  # one case for each of the 5 statements
    assert out["case"]["by"] == "scripted" and out["case"]["statement_id"].startswith("shop:1:")
    assert out["same_rest"] and out["tests_after_replace"] == 5
    assert "already has 5 tests" in out["refused"] and "has no policy text" in out["no_text"]
    assert out["rules_seen"] == []  # no rule id appears in any prompt
    assert not out["incident"]  # the generic prompt names no benchmark's record
    assert out["ledger"] == ["rule_audit_tests_gen"] * 2


def test_tests_gen_sends_the_whole_text_and_writes_nothing_when_a_statement_fails(tmp_path):
    out = gate(
        r"""
long_text = [Statement(id=f"shop:1:{i}", text=f"Rule number {i}: orders of kind {i} need a note on the order.", modality="must") for i in range(1, 501)]
path = make("shopbench", "shop", "builds", rules=[], statements=long_text, coverage=False)
specs = ra.read_specs(str(TOOLS))
good = {"cases": [{"tool": "refund_order", "args": {"order_id": "O1"}, "expected": "allow", "why": "w"}]}
def failing(system, user):
    if '"Rule number 7:' in user.split("Statement to test")[1]:
        raise RuntimeError("gateway hang")
    return json.dumps(good)
seen = []
model = scripted(lambda s, u: (seen.append(u), failing(s, u))[1])
ra._model = lambda name: model
result = {}
def attempt(label, **kw):
    try:
        ra.tests_gen(ra.load_target(str(path)), specs, "scripted", **kw)
        result[label] = "ok"
    except SystemExit as exc:
        result[label] = str(exc)
    result[label + "_tests"] = len(json.loads(path.read_text())["tests"])
before = path.read_text()
attempt("plain")
attempt("partial", keep_partial=True)
kept = json.loads(path.read_text())["tests"]
ra._model = lambda name: scripted(lambda s, u: (_ for _ in ()).throw(RuntimeError("down")))
path.write_text(before)
attempt("all_fail", keep_partial=True)
print(json.dumps({"result": result, "first_prompt_has_last_statement": "Rule number 500:" in seen[0], "prompt_chars": len(seen[0]),
                  "failed_entries": [c for c in kept if c.get("error")], "cases": len([c for c in kept if c.get("tool")]),
                  "valid": len(ra.valid_tests(kept)), "unchanged_after_plain": result["plain_tests"] == 0}))
""",
        tmp_path,
    )
    result = out["result"]
    assert out["prompt_chars"] > 14000 and out["first_prompt_has_last_statement"]  # nothing is cut
    assert "1 of 500 statements failed" in result["plain"] and result["plain_tests"] == 0  # nothing written
    assert (
        "stored 499 cases and 1 failed" in result["partial"] and result["partial_tests"] == 500
    )  # asked for, and still a failure
    assert (
        out["failed_entries"][0]["statement_id"] == "shop:1:7" and out["cases"] == 499 and out["valid"] == 499
    )
    assert (
        "500 of 500 statements failed" in result["all_fail"] and result["all_fail_tests"] == 0
    )  # never an empty list over good tests


def test_backtrans_takes_the_text_from_a_package_of_the_same_policy_and_never_from_the_rule_itself(tmp_path):
    out = gate(
        r"""
make("shopbench", "shop", "builds")  # holds the text
gold = make("shopbench", "shop", "gold", statements=[], coverage=False)  # rules only, naming the statements of the other package
alone = make("othermark", "plain", "builds", statements=[], coverage=False)  # no text anywhere
writer = scripted(lambda s, u: json.dumps({"text": "restated"}))
judge = scripted(lambda s, u: json.dumps({"verdict": "equivalent", "why": "w"}))
ra._model = lambda name: writer if name == "w" else judge
sibling = ra.backtrans(ra.load_target(str(gold)), "w", "j", save=False)
none = ra.backtrans(ra.load_target(str(alone)), "w", "j", save=False)
st = ra.static(ra.load_target(str(gold)), ra.read_specs(str(TOOLS)))
st_none = ra.static(ra.load_target(str(alone)), ra.read_specs(str(TOOLS)))
print(json.dumps([{k: sibling[k] for k in ("judged", "not_judged", "text_from", "source_kinds")}, none, [st["grounding"], st["text_from"], st["coverage"]["statements"]], st_none["grounding"]]))
""",
        tmp_path,
    )
    sibling, none, static_gold, static_none = out
    assert sibling == {"judged": 4, "not_judged": 0, "text_from": "builds", "source_kinds": {"statements": 4}}
    assert none["status"] == "no text" and "quote is not a source" in none["reason"]  # no number
    assert static_gold == ["ok", "builds", 0]  # grounding uses the sibling's text, coverage does not
    assert static_none == "no text"


def test_confirm_refuses_a_result_of_another_package(tmp_path):
    out = gate(
        r"""
a = make("shopbench", "shop", "builds", tests=CASES)
b = make("shopbench", "shop", "builds_b", rules=RULES[:2], tests=CASES)
specs = ra.read_specs(str(TOOLS))
ra._model = lambda name: scripted(lambda s, u: json.dumps({"violations": []}))
saved = ra.tests_run(ra.load_target(str(a)), specs, verifier_model="scripted")["file"]
try:
    ra.confirm(ra.load_target(str(b)), str(ra.OUT / saved), "judge")
    refused = None
except SystemExit as exc:
    refused = str(exc)
print(json.dumps(refused))
""",
        tmp_path,
    )
    assert "another package" in out and "build" in out


def test_a_cedar_validator_that_fails_is_a_failed_exit_code_and_an_empty_tool_list_is_refused(tmp_path):
    out = gate(
        r"""
ghost = Rule(id="rule_zq9", type="role_permission", rule={"id": "rule_zq9", "type": "role_permission", "tools": ["ghost_tool"], "roles": ["clerk"], "effect": "forbid", "source": "§1", "quote": S[1]},
             statement_ids=["shop:1:2"], quote=S[1], cls="hard", level="deny", checker="cedar")
path = make("shopbench", "shop", "builds", rules=[ghost], tests=CASES)
code = ra.main(["cedar", "--package", str(path), "--tools", str(TOOLS)])
(tmp / "empty.json").write_text("[]")
try:
    ra.read_specs(str(tmp / "empty.json"))
    empty = None
except SystemExit as exc:
    empty = str(exc)
print(json.dumps([code, ra.main(["cedar", "--package", str(make("shopbench", "shop", "ok", tests=CASES)), "--tools", str(TOOLS)]), empty]))
""",
        tmp_path,
    )
    assert out[0] == 1 and out[1] == 0 and "no tool specs" in out[2]


def test_backtrans_restates_each_rule_and_a_judge_compares_it_with_the_source(tmp_path):
    out = gate(
        r"""
path = make("shopbench", "shop", "builds")
writer = scripted(lambda s, u: json.dumps({"text": "restated"}))
judge = scripted(lambda s, u: json.dumps({"verdict": "narrower" if "owner" in u else "equivalent", "why": "w"}))
ra._model = lambda name: writer if name == "w" else judge
r = ra.backtrans(ra.load_target(str(path)), "w", "j", save=True)
print(json.dumps([r["counts"], r["rules"], r["file"], [json.loads(x)["name"] for x in (tmp / "ledger.jsonl").read_text().splitlines()]]))
""",
        tmp_path,
    )
    assert out[0] == {"equivalent": 3, "narrower": 1} and out[1] == 4
    assert out[2] == "backtrans__shopbench_shop__builds__j.json"
    assert out[3] == ["shopbench_shop:builds:w", "shopbench_shop:builds:j"]


def test_report_has_both_parts_for_every_package_and_says_why_a_part_has_no_data(tmp_path):
    out = gate(
        r"""
a = make("shopbench", "shop", "builds", tests=CASES)
make("shopbench", "shop", "gold", tests=CASES)
other = make("othermark", "plain", "builds", rules=RULES[:1], statements=[], coverage=False)
runs = tmp / "runs"
runs.mkdir()
(runs / "A_pass.json").write_text(json.dumps({"task_id": "x", "policy_version": "shop", "passed": True,
    "tool_calls": [{"tool": "refund_order", "args": {"order_id": "O1", "reason": "fun"}, "result": {}}]}))
specs = ra.read_specs(str(TOOLS))
# a saved verifier result is read, not run
ra._model = lambda name: scripted(lambda s, u: json.dumps({"violations": []}))
ra.tests_run(ra.load_target(str(a)), specs, verifier_model="scripted")
ra.tests_run(ra.load_target(str(a)), specs, verifier_model="scripted")
texts = {}
for name, p in (("tuning", a), ("gold", a.parent.parent / "gold"), ("held", other)):
    ra.write_report(ra.load_target(str(p)), specs, str(tmp / "out" / name), run_globs=[] if name == "held" else [str(runs / "A_*.json")])
    texts[name] = (tmp / "out" / name / "AUDIT.md").read_text()
bare = ra.write_report(ra.load_target(str(a)), None)  # no tool specs: the package folder gets the file
texts["bare"] = bare.read_text()
# the same folder, one rule fewer: the verifier results saved above are of another package version
make("shopbench", "shop", "builds", rules=RULES[:3], tests=CASES)
ra.write_report(ra.load_target(str(a)), specs, str(tmp / "out" / "changed"))
texts["changed"] = (tmp / "out" / "changed" / "AUDIT.md").read_text()
# a change in the tests only keeps the package version (the tests are not in it), but not the test set
make("shopbench", "shop", "builds", rules=RULES[:3], tests=CASES[:5])
ra.write_report(ra.load_target(str(a)), specs, str(tmp / "out" / "tests"), note="earlier runs: 148")
texts["tests"] = (tmp / "out" / "tests" / "AUDIT.md").read_text()
print(json.dumps([texts, str(bare.parent) == str(a.parent)]))
""",
        tmp_path,
    )
    texts, in_package_folder = out
    assert in_package_folder
    for name, text in texts.items():
        assert "## Part 1: fidelity to the text" in text and "## Part 2: fidelity to use" in text, name
    tuning = texts["tuning"]
    # a policy that no set and no change names is unseen, never held-out
    assert "**unseen, no run**" in tuning and "**gold, unseen, no run**" in texts["gold"]
    assert "**unseen, no run**" in texts["held"]
    assert "held-out**" not in tuning
    assert (
        "False denies" in tuning
        and "False reminders" in tuning
        and "Passed runs with a reminder (false reminders)" in tuning
    )
    assert (
        "Verifier spread over 2 runs" in tuning
        and "Conflicts with graders" in tuning
        and "rule_zq1" in tuning
    )
    assert "Back-translation | no data" in tuning
    held = texts["held"]  # no tests, no runs, no policy text, no role rules
    assert "No data: the package has no `tests`." in held and "No data: no --runs given." in held
    assert "Coverage | no data" in held and "Cedar validator and batch check | no data" in held
    assert "No data: no --tools given" in texts["bare"]
    assert (
        "Verifier spread" not in texts["changed"]
        and "tests_run__shopbench_shop__builds__verifier.json" in texts["changed"]
    )
    assert "Left out, a saved result of another package version or another test set" in texts["changed"]
    assert "Left out, a saved result" in texts["tests"] and "Note: earlier runs: 148" in texts["tests"]
    assert "Rows that differ from the first run" in tuning and "lower bound" in tuning


def test_confirm_drops_a_verifier_flag_that_the_judge_rejects_and_keeps_code_findings(tmp_path):
    out = gate(
        r"""
path = make("shopbench", "shop", "builds", tests=CASES)
t = ra.load_target(str(path))
specs = ra.read_specs(str(TOOLS))
ra._model = lambda name: scripted(lambda s, u: json.dumps({"violations": [{"statement": 1, "reason": "needs approval", "fix": "ask"}]}
                                                          if '"amount": 500' in u else {"violations": []}))
saved = ra.tests_run(t, specs, verifier_model="scripted")["file"]
judge = scripted(lambda s, u: json.dumps({"correct": False, "why": "not shown"}))
ra._model = lambda name: judge
print(json.dumps([ra.confirm(t, str(ra.OUT / saved), "judge"), len(judge.seen)]))
""",
        tmp_path,
    )
    summ, judged = out
    assert judged == 1  # only the one verifier flag is put to the judge
    assert (summ["caught_before"], summ["caught_after"]) == (4, 3)  # the refund of 500 is no longer caught
    assert (summ["false_flags_before"], summ["false_flags_after"]) == (1, 1)  # the Cedar reminder stays


def test_the_command_line_runs_a_method_on_a_package_given_by_path(tmp_path):
    out = gate(
        r"""
path = make("shopbench", "shop", "builds", tests=CASES)
ra.main(["tests-run", "--package", str(path.parent), "--tools", str(TOOLS)])
ra.main(["static", "--package", str(path), "--tools", str(TOOLS)])
print(json.dumps(sorted(p.name for p in ra.OUT.glob("*"))))
""",
        tmp_path,
    )
    assert out == ["static__shopbench_shop__builds.json", "tests_run__shopbench_shop__builds.json"]


# -- the module itself ---------------------------------------------------------------------------------------------------------


def test_no_benchmark_name_or_policy_version_in_the_code_and_tool_guard_is_gone():
    source = (POLICY_EVAL / "rule_audit.py").read_text()
    docstring_lines = ast.parse(source).body[0].end_lineno  # the help text may name a benchmark in an example
    code = "\n".join(source.splitlines()[docstring_lines:])
    assert not re.search(
        r"itsm|enterpriseops|automationbench|handbook|tau2|τ²|e2891a7b98|incident", code, re.I
    )
    assert not re.search(
        r"itsm|enterpriseops|automationbench|handbook|tau2|τ²|e2891a7b98|incident",
        (POLICY_EVAL / "audit_report.py").read_text(),
        re.I,
    )
    assert "tg_run" not in source and "tg-run" not in source and "toolguard" not in code.lower()
    assert (POLICY_EVAL / "toolguard_step1.py").is_file()  # the record stays


# -- the known numbers of one real policy, from saved inputs ---------------------------------------------------------------------


def missing_input(reason):
    """Saved folders are not in git, so on another machine these tests would pass by skipping. With ``EVAL_NO_SKIP=1`` a
    missing input is a failure."""
    if os.environ.get("EVAL_NO_SKIP"):
        pytest.fail(f"EVAL_NO_SKIP is set: {reason}")
    pytest.skip(reason)


REAL = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import rule_audit as ra
specs = ra.read_specs(sys.argv[3])
builds = ["builds_v2", "gold", "builds_v4", "builds_v4_remind", "builds_v4_v4A"]
code = {}
for b in builds:
    s = ra.tests_run(ra.load_target("itsm/e2891a7b98/" + b), specs, save=False)["summary"]
    code[b] = [s["caught"], s["deny_cases"], s["false_deny"], s["allow_cases"]]
replay = {}
if sys.argv[4] != "no-runs":
    for b in builds:
        r = ra.replay(ra.load_target("itsm/e2891a7b98/" + b), specs, [sys.argv[4] + "/*/A_*.json"], [sys.argv[4] + "/*/B_*.json"], save=False)["replayed"]
        replay[b] = [r["passed_runs_with_deny"], r["passed_runs"], r["runs"]]
cedar = ra.cedar(ra.load_target("itsm/e2891a7b98/gold"), specs, save=False)
print(json.dumps([code, replay, [cedar["requests"], cedar["differences"], cedar["validator"]["passed"]]]))
"""


def run_real(runs):
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", REAL, str(POLICY_EVAL), "", str(ITSM_TOOLS), runs],
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert done.returncode == 0, done.stdout[-2500:] + done.stderr[-3500:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_the_code_only_numbers_of_the_research_table_come_out_of_the_packages():
    """87 / 97 / 99 / 99 / 104 of 182 caught, with 1 / 1 / 7 / 1 / 1 false denies of 165 (research note, section 3), and the
    372 requests of the Cedar check. The tests are the ones in the package."""
    if not ITSM_TOOLS.is_file():
        missing_input(f"the tool specs are missing: {ITSM_TOOLS}")
    code, _, cedar = run_real("no-runs")
    assert code == {
        "builds_v2": [87, 182, 1, 165],
        "gold": [97, 182, 1, 165],
        "builds_v4": [99, 182, 7, 165],
        "builds_v4_remind": [99, 182, 1, 165],
        "builds_v4_v4A": [104, 182, 1, 165],
    }
    assert cedar == [372, 0, True]


def test_the_replay_numbers_of_the_research_table_come_out_of_the_saved_arm_a_runs():
    """Passed runs with a deny, of 93 passed of 182: 2 / 9 / 20 / 2 / 2."""
    if not list(ITSM_RUNS.glob("*/A_*.json")):
        missing_input(f"the saved arm-A runs are missing: {ITSM_RUNS}")
    _, replay, _ = run_real(str(ITSM_RUNS))
    assert replay == {
        "builds_v2": [2, 93, 182],
        "gold": [9, 93, 182],
        "builds_v4": [20, 93, 182],
        "builds_v4_remind": [2, 93, 182],
        "builds_v4_v4A": [2, 93, 182],
    }


# -- what kind of numbers (the registry), and the identity of a package ----------------------------------------------------------


def test_the_kind_of_numbers_comes_from_the_registry_and_is_never_held_out_by_default():
    """Real policies, from ``sets/registry.json``. 33 of 34 labels were once a false `held-out`."""
    import sys

    sys.path.insert(0, str(POLICY_EVAL))
    import audit_report

    def kind(bench, policy, build="builds_v5"):
        return audit_report.basis_of(bench, policy, build)

    assert kind("handbook", "hr_crestwood_university_79786c46", "v4")[0] == "tuning"  # set handbook-public3
    assert kind("tau2_telecom", "telecom", "builds")[0] == "tuning"  # tau2-telecom-dev20
    assert kind("itsm", "2e555b5177")[0] == "tuning"  # itsm-pilot
    assert kind("itsm", "c47f8ceef3")[0] == "tuning"
    d5, why = kind("itsm", "d5ab75ff0f")  # no tuning set; change 131 fixed the pipeline on it
    assert d5 == "tuning" and "131" in why
    assert kind("itsm", "80cd3ebb50")[0] == "unseen, no run"  # no set and no change names it
    assert kind("automationbench", "finance.prepaid_amortization", "gold")[0] == "gold, tuning"  # in ab-tune
    gold, why = kind("itsm", "e2891a7b98", "gold")
    assert gold == "gold, tuning" and "reference build" in why and "changes 105" in why  # both facts
    assert kind("shopbench", "nothing")[0] == "unseen, no run"
    assert audit_report.basis_of("itsm", "80cd3ebb50", "builds_v5", "tuning") == (
        "tuning",
        "set with --basis",
    )


def test_a_set_that_a_model_has_run_is_never_held_out(tmp_path):
    import sys

    sys.path.insert(0, str(POLICY_EVAL))
    import audit_report

    def write(sets):
        registry = tmp_path / "registry.json"
        registry.write_text(
            json.dumps(
                {
                    "sets": sets,
                    "policies": {"b/p": {"tuning_sets": [], "heldout_sets": ["x"], "tuned_by_changes": []}},
                }
            )
        )
        return registry

    kind = lambda registry, policy="p": audit_report.basis_of("b", policy, "builds", registry=registry)[0]  # noqa: E731
    assert kind(write([{"id": "x", "seen_n": {"m1": 0}}])) == "held-out"  # a held-out set that no model ran
    assert kind(write([{"id": "x", "seen_n": {"m1": 0, "m2": 3}}])) == "seen, not tuned"  # one model ran it
    assert kind(write([])) == "seen, not tuned"  # the registry does not know the set: not claimed as held-out
    assert kind(write([{"id": "x", "seen_n": {"m1": 2}}]), "q") == "unseen, no run"  # no policy entry
    assert kind(tmp_path / "missing.json") == "unseen, no run"
    assert (
        "m2"
        in audit_report.basis_of("b", "p", "builds", registry=write([{"id": "x", "seen_n": {"m2": 3}}]))[1]
    )


def test_no_package_is_held_out_and_the_labels_of_the_rulings_are_exact():
    import sys

    sys.path.insert(0, str(POLICY_EVAL))
    import audit_report

    registry = json.loads((POLICY_EVAL / "sets" / "registry.json").read_text())
    folders = sorted(f"{p.parent.name}/{p.name}" for p in (POLICY_EVAL / "packages").glob("*/*/"))
    kinds = {f: audit_report.basis_of(*f.split("/"), "skill_v1")[0] for f in folders}
    assert "held-out" not in kinds.values()
    assert kinds["tau2_airline/airline"] == "seen, not tuned"
    assert kinds["tau2_retail/retail"] == "unseen, no run" and kinds["itsm/80cd3ebb50"] == "unseen, no run"
    assert (
        kinds["tau2_telecom/telecom"] == "tuning"
        and kinds["handbook/hr_crestwood_university_79786c46"] == "tuning"
    )
    assert {
        kinds[f"itsm/{h}"]
        for h in "e2891a7b98 2e555b5177 7bb25d850c 933219af01 a5e328395b c47f8ceef3 cb2d4ee021 d5ab75ff0f".split()
    } == {"tuning"}
    assert (
        audit_report.basis_of("automationbench", "finance.prepaid_amortization", "gold")[0] == "gold, tuning"
    )
    sets = {s["id"]: s for s in registry["sets"]}
    assert sets["tau2-airline-test"]["label"] == "seen" and sets["tau2-airline-test"]["status"] == "heldout"
    for s in sets.values():  # the label of a held-out set is never held-out while a model has run it
        ran = any(n > 0 for n in s["seen_n"].values())
        assert s["label"] == (s["status"] if s["status"] != "heldout" else "seen" if ran else "held-out")
    note = registry["policies"]["tau2_airline/airline"]["note"]
    assert "labels.md" in note and "design decision 1" in note and "Task 5.3" in note


def test_the_policies_section_of_the_registry_is_what_the_sets_say():
    registry = json.loads((POLICY_EVAL / "sets" / "registry.json").read_text())
    policies = registry["policies"]
    folders = {f"{p.parent.name}/{p.name}" for p in (POLICY_EVAL / "packages").glob("*/*/")}
    assert set(policies) <= folders and folders - set(policies) == {
        "itsm/80cd3ebb50"
    }  # only policies with a package
    assert (
        policies["itsm/d5ab75ff0f"]["tuned_by_changes"] == [131]
        and not policies["itsm/d5ab75ff0f"]["tuning_sets"]
    )
    assert "ab-tune" in policies["automationbench/finance.prepaid_amortization"]["tuning_sets"]


def test_the_identity_of_a_package_leaves_the_decision_tests_out_and_the_harness_uses_the_same_function(
    tmp_path,
):
    import sys

    sys.path.insert(0, str(BENCHMARKS))
    from policy_eval.harness import run as hr
    from policy_eval.harness.result import package_identity

    base = json.dumps({"version": "v1", "rules": [], "tests": []}, indent=1, ensure_ascii=False) + "\n"
    plain, tested = tmp_path / "plain.json", tmp_path / "tested.json"
    plain.write_text(base)
    tested.write_text(base.replace('"tests": []', '"tests": [{"tool": "x", "expected": "deny"}]'))
    assert package_identity(plain, "v1") == package_identity(tested, "v1")
    other = tmp_path / "other.json"
    other.write_text(base.replace('"rules": []', '"rules": [1]'))
    assert package_identity(other, "v1") != package_identity(plain, "v1")  # a rule does count
    pkg = type("P", (), {"version": "v1"})()
    assert hr.package_version(tested, pkg) == package_identity(tested, "v1")  # one helper, two callers
    saved = POLICY_EVAL / "packages/itsm/e2891a7b98/builds/package.json"
    if (
        saved.is_file()
    ):  # the hash the smoke run (smk24_itsm_rules_t1) names for this package, before it had tests
        assert package_identity(saved, "3f8382b04c91277c") == "3f8382b04c91277c+108af1c22be7"
