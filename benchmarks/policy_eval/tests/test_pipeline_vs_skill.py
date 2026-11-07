"""Pipeline against skill (``tools/pipeline_vs_skill.py``): each metric on small made-up packages, with a judge that answers from a
script, and the committed Markdown against a new render of the committed result.

The code is in the gate repo, so the checks run with the gate repo's Python. No model call, no ledger line in the real ledger.
"""

import json
import os
import subprocess
from pathlib import Path

POLICY_EVAL = Path(__file__).resolve().parents[1]
GATE_PYTHON = os.environ.get("POLICY_GATE_PYTHON") or str(
    Path.home() / "dev/cuga-agent-gate/.venv/bin/python"
)

PRELUDE = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[1] + "/tools")
import pipeline_vs_skill as pvs
import rule_audit as ra
import policy_pilot_costs as costs
from cuga.policy_layer.model import CoverageItem, Document, PolicyPackage, Procedure, Rule, Section, Statement, Step
from cuga.policy_layer.package import save_package

tmp = Path(sys.argv[2])
costs.LEDGER = tmp / "ledger.jsonl"
TOOLS = tmp / "tools.json"
TOOLS.write_text(json.dumps([
    {"name": "refund_order", "parameters": {"type": "object", "required": ["order_id"], "properties": {
        "order_id": {"type": "string"}, "reason": {"type": "string"}, "amount": {"type": "number"}}}},
    {"name": "close_order", "parameters": {"type": "object", "properties": {
        "order_id": {"type": "string"}, "status": {"type": "string", "enum": ["shipped", "closed"]}}}},
]))
S = ["Refund reason must be damaged or late.", "Refunds above 100 must not be paid without approval.",
     "Never close an order that has an open refund.", "Orders", "Never email the customer's card number."]
STATEMENTS = [Statement(id=f"shop:1:{i}", text=t, modality="must") for i, t in enumerate(S, 1)]


def rule(rid, kind, number, **slots):
    body = {"id": rid, "type": kind, "source": "§1", "quote": S[number - 1], **slots}
    return Rule(id=rid, type=kind, rule=body, statement_ids=[f"shop:1:{number}"], quote=S[number - 1],
                source={"section": "1"}, cls="hard", level="deny", checker="code")


R_REASON = rule("rule_zq1", "allowed_values", 1, tool="refund_order", arg="reason", values=["damaged", "late"])
R_AMOUNT = rule("rule_zq2", "threshold", 2, tool="refund_order", arg="amount", op="gt", value=100, then="forbid")
CASES = [
    {"tool": "refund_order", "args": {"order_id": "O1", "reason": "fun"}, "expected": "deny", "statement_id": "shop:1:1"},
    {"tool": "refund_order", "args": {"order_id": "O1", "reason": "late"}, "expected": "allow", "statement_id": "shop:1:1"},
    {"tool": "refund_order", "args": {"order_id": "O1", "reason": "late", "amount": 500}, "expected": "deny", "statement_id": "shop:1:2"},
    {"tool": "refund_order", "args": {"order_id": "O1", "reason": "late", "amount": 50}, "expected": "allow", "statement_id": "shop:1:2"},
]
SKILL_PROCS = [
    Procedure(id="refund", name="Refund an order", applies_when="a customer asks for a refund",
              steps=[Step(id="shop:1:1", text="Check the reason"), Step(id="shop:1:2", text="Check the amount")],
              must_not=["Never close an order that has an open refund.", "Never email the customer's card number."]),
    Procedure(id="close", name="Close an order", steps=[Step(id="shop:1:3", text="Close the order")]),
]


def make(build, rules, procedures=(), cov=(), tests=CASES, statements=STATEMENTS):
    doc = Document(id="shop", kind="markdown", sections=[Section(id="1", statements=list(statements))])
    pkg = PolicyPackage(version="v1", policy_hash="shop", documents=[doc], rules=list(rules), procedures=list(procedures),
                        tests=list(tests), coverage=list(cov))
    path = tmp / "packages" / "shopbench" / "shop" / build / "package.json"
    save_package(pkg, path)
    return path
'''


def gate(code, tmp_path):
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", PRELUDE + code, str(POLICY_EVAL), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert done.returncode == 0, done.stdout[-2500:] + done.stderr[-3500:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_catches_and_false_denies_on_the_same_tests_and_the_bar(tmp_path):
    out = gate(
        r"""
skill = pvs.rule_side(str(make("skill_v1", [R_REASON, R_AMOUNT])), str(TOOLS), [], [])
# the pipeline package has the first rule only, and a rule that denies a good call
bad = rule("rule_zq9", "threshold", 2, tool="refund_order", arg="amount", op="gt", value=10, then="forbid")
pipe = pvs.rule_side(str(make("pipeline_x", [R_REASON, bad])), str(TOOLS), [], [])
pipe["must_not_recall"] = {"skill": 2, "A": 2, "B": 2}
b = pvs.bar(skill, pipe)
print(json.dumps({"skill": skill["tests"], "pipe": pipe["tests"], "bar": b, "label": pipe["label"]}))
""",
        tmp_path,
    )
    s, p = out["skill"], out["pipe"]
    assert (s["clean_deny_cases"], s["caught_by_rules"], s["false_deny"]) == (2, 2, 0)
    assert (p["clean_deny_cases"], p["caught_by_rules"], p["false_deny"]) == (
        2,
        2,
        1,
    )  # the same denominator; one good call denied
    assert out["bar"]["catches"]["ok"] and not out["bar"]["false_denies"]["ok"]
    assert out["bar"]["must_not"]["ok"]
    assert out["label"][0] == "unseen, no run"  # a policy that no set names


def test_validate_errors_lost_checks_and_fragments(tmp_path):
    out = gate(
        r"""
skill = make("skill_v1", [R_REASON, R_AMOUNT])
from cuga.policy_layer.package import load_package
sk = load_package(skill)
step_only = Procedure(id="p", name="p", steps=[Step(id="shop:1:2", text="Check the amount", action="")])
pipe_path = make("pipeline_x", [R_REASON], procedures=[step_only],
                 cov=[CoverageItem("shop:1:2", "procedure_step"), CoverageItem("shop:1:4", "guidance")])
pk = load_package(pipe_path)
specs = ra.read_specs(str(TOOLS))
v = pvs.validation_counts(pk, specs)
print(json.dumps({"lost": pvs.lost_checks(sk, pk), "frag": pvs.fragments_typed_must(pk), "v": v}))
""",
        tmp_path,
    )
    assert out["lost"]["step_only"] == [
        "shop:1:2"
    ]  # the skill's threshold rule is a step only in the pipeline package
    assert out["lost"]["skill_hard_statements"] == 2
    assert (
        out["frag"]["fragments"] == 1 and out["frag"]["typed_must"] == 5
    )  # "Orders" is a fragment typed must
    assert out["v"]["errors"] >= 1  # statements typed must with no outcome


def test_must_not_recall_by_text_and_by_judge_and_procedure_recall(tmp_path):
    out = gate(
        r"""
def scripted_model(fn):
    def call(system, user):
        return fn(system, user)
    return call
from cuga.policy_layer.package import load_package
sk = load_package(make("skill_v1", [R_REASON], procedures=SKILL_PROCS))
refs = pvs.skill_must_nots(sk)
graph = {"procedures": [
    {"id": "s1", "name": "Refunds", "applies_when": "refund asked", "steps": ["Check the refund reason", "Check the amount"],
     "must_not": ["Never close an order that has an open refund. (SOP 3)", "Do not send payment card data by e-mail"]},
    {"id": "s2", "name": "Other", "steps": ["Close the order"], "must_not": []}], "escalation": {"must_not": []}}
pipe = load_package(make("pipeline_x", [R_REASON]))
a, b = pvs.pipeline_pools(pipe, graph)
def answer(system, user):
    if "Reference prohibition" in user:
        return json.dumps({"match": 1, "why": "same"}) if "card" in user.split("Candidates")[0] else json.dumps({"match": None, "why": "no"})
    return json.dumps({"match": 1, "steps_held": [1, 2] if "Refund an order" in user else [1], "why": "same flow"})
judge = pvs.Judge(scripted_model(answer), tmp / "judge.json")
rec = pvs.recall_must_nots(refs, a, b, judge)
procs = pvs.recall_procedures_judged(pvs.skill_procedures(sk), pvs.compiled_procedures(graph), judge)
again = pvs.Judge(None, tmp / "judge.json")
rec2 = pvs.recall_must_nots(refs, a, b, again)
print(json.dumps({"rec": [rec["skill"], rec["A"], rec["B"], rec["judged"]], "how": [i["A"]["how"] for i in rec["items"]],
                  "procs": [procs["skill"], procs["recalled"], procs["steps"], procs["steps_held"]],
                  "same": rec2["A"] == rec["A"], "ids": pvs.recall_procedures_by_ids(pvs.skill_procedures(sk), sk)["recalled"]}))
""",
        tmp_path,
    )
    assert out["rec"] == [2, 2, 2, 1]  # one by the text it holds, one by the judge
    assert out["how"] == ["verbatim", "judge"]
    assert out["procs"] == [2, 2, 3, 3]
    assert (
        out["same"] and out["ids"] == 2
    )  # a kept answer is read without a model; the skill against itself by statement ids


def test_bar_and_verdict_rows_from_plain_numbers():

    code = r"""
import json, sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + "/tools")
import pipeline_vs_skill as pvs
def side(caught, deny, fd, recall, label="tuning"):
    return {"tests": {"caught_by_rules": caught, "clean_deny_cases": deny, "false_deny": fd, "clean_allow_cases": 50, "caught_deny": caught, "false_remind": 0, "schema_deny": 0, "schema_allow": 0},
            "must_not_recall": {"skill": 10, "A": recall, "B": recall}, "label": [label, "why"], "validate": {"errors": 0}}
skill = side(50, 100, 1, 10)
cases = {"within 5": side(45, 100, 1, 8), "5.5 below": side(44, 100, 1, 8), "more false denies": side(60, 100, 2, 9), "low recall": side(60, 100, 0, 7)}
res = {k: pvs.bar(skill, v) for k, v in cases.items()}
result = {"docs": {"tau2_retail/retail": {"skill": skill, "pipelines": {"gptoss": cases["within 5"], "dsv4": cases["low recall"]}},
                   "itsm/e2891a7b98": {"skill": skill, "pipelines": {"gptoss": cases["more false denies"]}}}}
rows = pvs.verdicts(result)
print(json.dumps({"ok": {k: pvs.all_met(v) for k, v in res.items()}, "rows": rows}))
"""
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", code, str(POLICY_EVAL)], capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["ok"] == {
        "within 5": True,
        "5.5 below": False,
        "more false denies": False,
        "low recall": False,
    }
    by = {r["bench"]: r for r in out["rows"]}
    assert (
        by["tau2_retail"]["answer"].startswith("yes") and "gpt-oss" in by["tau2_retail"]["answer"]
    )  # one model meets the bar
    assert by["itsm"]["answer"] == "no" and "false denies 2 against 1" in by["itsm"]["reason"]


def test_a_tuned_document_is_labelled_so_in_the_tables_and_the_tables_are_stable():
    code = r"""
import json, sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + "/tools")
import pipeline_vs_skill as pvs
def side(label, caught=5):
    return {"tests": {"caught_by_rules": caught, "clean_deny_cases": 10, "false_deny": 0, "clean_allow_cases": 8, "caught_deny": caught, "false_remind": 0, "schema_deny": 0, "schema_allow": 0},
            "replay": {"status": "ok", "runs": 4, "passed_runs": 2, "passed_runs_with_deny": 0, "passed_runs_with_remind": 1},
            "validate": {"errors": 1, "warnings": 0, "error_codes": {"quote_not_verbatim": 1}}, "procedures": 2, "must_nots": 2, "label": label,
            "must_not_recall": {"skill": 2, "A": 2, "B": 2, "items": []},
            "procedure_recall": {"compiled": {"skill": 2, "recalled": 1, "steps": 4, "steps_held": 3, "items": []}, "builder": {"skill": 2, "recalled": 0, "steps": 4, "steps_held": 0, "items": []}},
            "defects": {"quote_not_verbatim": 1, "lost_checks": {"skill_hard_statements": 3, "step_only": ["policy:4.2:4"], "no_outcome": []}, "fragments": {"typed_must": 6, "fragments": 1, "fragments_without_outcome": 1}},
            "cost": {"build": 0.02, "compile": 0.01, "total": 0.03, "seconds": 9, "calls": 7, "failed_calls": 0}}
skill = side(["tuning", "skill note"], 5)
result = {"docs": {"itsm/e2891a7b98": {"skill": skill, "pipelines": {"gptoss": side(["tuning", "the pipeline was repaired on it in changes 131"])}},
                   "tau2_retail/retail": {"skill": side(["unseen, no run", "x"]), "pipelines": {"gptoss": side(["unseen, no run", "no set names it"])}}}}
a = pvs.render_tables(result)
b = pvs.render_tables(json.loads(json.dumps(result)))
print(json.dumps({"same": a == b, "tuning_row": [l for l in a.splitlines() if "repaired on it" in l], "unseen_row": [l for l in a.splitlines() if "no set names it" in l]}))
"""
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", code, str(POLICY_EVAL)], capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["same"]
    assert out["tuning_row"] and "tuning" in out["tuning_row"][0]
    assert out["unseen_row"] and "unseen, no run" in out["unseen_row"][0]


def test_missing_types_are_wanted_when_both_readings_name_them_and_the_bar_counts_benchmarks():
    code = r"""
import json, sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + "/tools")
import pipeline_vs_skill as pvs
items = [
    {"bench": "handbook", "rule": "a", "statement": "Do not use direct messages."},
    {"bench": "tau2", "rule": "b", "statement": "At most five passengers."},
    {"bench": "itsm", "rule": "c", "statement": "A balance must cover the total."},
    {"bench": "tau2", "rule": "d", "statement": "A balance must cover the total."},
]
def answer(system, user):
    strict = "ONE tool call" in user
    by = {1: ["forbid_tool"], 2: ["array"], 3: ["record_compare"], 4: ["record_compare"] if not strict else []}
    return json.dumps({"answers": [{"n": n, "kinds": k} for n, k in by.items()]})
judge = pvs.Judge(answer, None, "scripted")
td = pvs.type_demand(items, judge)
t = td["by_type"]
print(json.dumps({"rc": [t["record_compare"]["wanted"], t["record_compare"]["either"], t["record_compare"]["benchmarks"], t["record_compare"]["meets_bar"], t["record_compare"]["possible_bar"]],
                  "forbid": [t["forbid_tool"]["wanted"], t["forbid_tool"]["meets_bar"]], "none": td["none_of_them"],
                  "same": [pvs._same("array, record_compare", "record_compare, array"), pvs._same("none", "array")]}))
"""
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", code, str(POLICY_EVAL)], capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["rc"] == [1, 2, 1, False, True]  # item d is named by one reading only: possible, not wanted
    assert out["forbid"] == [1, False] and out["none"] == 0
    assert out["same"] == [True, False]


def test_catches_cannot_fail_when_the_skill_is_under_5_percent_and_must_nots_are_split_by_source():
    code = r"""
import json, sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + "/tools")
import pipeline_vs_skill as pvs
def side(caught, fd, validate=0):
    return {"tests": {"caught_by_rules": caught, "clean_deny_cases": 100, "false_deny": fd, "clean_allow_cases": 50},
            "must_not_recall": {"skill": 4, "A": 4, "B": 4}, "validate": {"errors": validate}}
b = pvs.bar(side(2, 0), side(0, 30))  # an empty package against a skill at 2%: the condition passes, and 60% of the allow tests are denied
c = pvs.bar(side(50, 0), side(40, 0))
recall = {"items": [
    {"ref": "a", "A": {"match": "x1", "where": "compiled s1 must_not"}},
    {"ref": "b", "A": {"match": "x2", "where": "builder 5 exception"}},
    {"ref": "c", "A": {"match": "x2", "where": "builder 5 exception"}},
    {"ref": "d", "A": {"match": None}}]}
pool = [{"text": "x1", "where": "compiled s1 must_not"}, {"text": "y", "where": "compiled escalation must_not"},
        {"text": "x2", "where": "builder 5 exception"}, {"text": "z", "where": "builder 5 precondition"}]
print(json.dumps({"a": [b["catches"]["ok"], b["catches"]["cannot_fail"], b["catches"]["allow_denied"], b["false_denies"]["ok"]],
                  "c": [c["catches"]["ok"], c["catches"]["cannot_fail"]], "src": pvs.must_not_sources(recall, pool)}))
"""
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", code, str(POLICY_EVAL)], capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["a"] == [True, True, 60.0, False]  # cannot fail, yet 60% of the allow tests denied
    assert out["c"] == [False, False]  # 10 points below a skill at 50%
    assert out["src"]["recalled"] == {"compiler": 1, "builder": 2}
    assert out["src"]["pool"] == {"compiler": 2, "builder": 2}
    assert out["src"]["pool_matching_no_skill_text"] == {
        "compiler": 1,
        "builder": 1,
    }  # a text counts once however many skill texts it matched


def test_section_detection_reads_a_bold_line_start_and_star_bullets_and_a_hand_correction_removes_a_kind(
    tmp_path,
):
    code = r"""
import json, sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + "/tools")
import pipeline_vs_skill as pvs
md = "# 1. Bold steps\n**Step 1:** open it\n**Step 2:** close it\n\n# 2. Star bullets\n* If a, do b\n* If c, do d\n\n# 3. Dash bullets\n- If a, do b\n- If c, do d\n"
pvs.originals = lambda doc: [("policy", md)]
d = pvs.section_detection("x/y")
items = [{"bench": "automationbench", "rule": "g1", "statement": "A priority table"}, {"bench": "tau2", "rule": "r1", "statement": "At most five passengers"}]
judge = pvs.Judge(lambda s, u: json.dumps({"answers": [{"n": 1, "kinds": ["array"]}, {"n": 2, "kinds": ["array"]}]}), None, "scripted")
td = pvs.type_demand(items, judge, corrections=[{"rule": "g1", "remove": ["array"], "note": "misread"}])
print(json.dumps({"d": d, "array": [td["by_type"]["array"]["wanted"], td["by_type"]["array"]["benchmarks"], td["by_type"]["array"]["meets_bar"]]}))
"""
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", code, str(POLICY_EVAL)], capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert (out["d"]["as_is"], out["d"]["stars_removed"], out["d"]["bullets_too"]) == (1, 2, 3)
    assert out["array"] == [1, 1, False]  # the misread statement is off: arrays are one benchmark


def test_a_call_that_ends_during_a_flush_is_recorded_in_the_next_one(tmp_path):
    code = r"""
import json, sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + "/tools")
from pathlib import Path
import pipeline_vs_skill as pvs
import policy_pilot_costs as costs
import cuga.policy_layer.llm as llm
costs.LEDGER = Path(sys.argv[2]) / "ledger.jsonl"
class Racy(dict):
    reads = 0
    def __getitem__(self, key):  # another stage ends right after the first reading of `calls`
        value = dict.__getitem__(self, key)
        if key == "calls":
            Racy.reads += 1
            if Racy.reads == 1:
                dict.__setitem__(self, "calls", value + 1)
                dict.__setitem__(self, "input_tokens", dict.__getitem__(self, "input_tokens") + 100)
        return value
def fake(model, **kwargs):
    usage = Racy({"calls": 10, "input_tokens": 1000, "output_tokens": 50})
    def call(system, user):
        return "{}"
    call.usage, call.model_name = usage, model
    return call
llm.openai_json_model = fake
m = pvs.metered("aws/gpt-oss-120b", "race")
m.flush()
m.flush()
lines = [json.loads(l) for l in costs.LEDGER.read_text().splitlines()]
print(json.dumps({"calls": sum(l["policy_calls"] for l in lines), "tokens": sum(l["policy_in"] for l in lines), "usage": [m.usage["calls"], m.usage["input_tokens"]]}))
"""
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", code, str(POLICY_EVAL), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert (
        out["calls"] == out["usage"][0] and out["tokens"] == out["usage"][1]
    )  # nothing lost between two lines


def test_the_committed_markdown_is_the_render_of_the_committed_result(tmp_path):
    md = POLICY_EVAL / "packages" / "PIPELINE_VS_SKILL.md"
    result = POLICY_EVAL / "packages" / "pipeline_vs_skill.json"
    if not md.exists() or not result.exists():
        import pytest

        pytest.skip("the report is not written yet")
    code = r"""
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + "/tools")
import pipeline_vs_skill as pvs
copy = Path(sys.argv[2]) / "copy.md"
copy.write_text(Path(sys.argv[3]).read_text())
pvs.render(copy, Path(sys.argv[4]), Path(sys.argv[5]))
print(copy.read_text() == Path(sys.argv[3]).read_text())
"""
    hand = POLICY_EVAL / "packages" / "pipeline_vs_skill_handcheck.json"
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", code, str(POLICY_EVAL), str(tmp_path), str(md), str(result), str(hand)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().splitlines()[-1] == "True"
