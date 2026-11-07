import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/dev/cuga-agent-gate/src"))
from dotenv import dotenv_values

os.environ.setdefault(
    "OPENAI_BASE_URL", dotenv_values(os.path.expanduser("~/dev/cuga-eval/.env")).get("OPENAI_BASE_URL") or ""
)
from cuga.policy_layer.llm import openai_json_model
from cuga.policy_layer.procedure_store import ProcedureStore
from cuga.policy_layer.store_gate import StoreGate

B = os.path.expanduser("~/dev/cuga-eval/benchmarks/")
store = ProcedureStore.load(
    B
    + "policy_eval/graphs_handbook/claude_v1/"
    + os.environ.get("GATE_TASK", "hr_crestwood_university_79786c46")
    + ".json"
)
model = openai_json_model(
    sys.argv[2] if len(sys.argv) > 2 else "gcp/gemini-3.8-flash", timeout=180, max_tokens=4000
)
gate = StoreGate(store, model, today=os.environ.get("GATE_TODAY", ""))
r = json.load(
    open(
        B
        + f"handbook/results/{sys.argv[1]}/"
        + os.environ.get("GATE_TASK", "hr_crestwood_university_79786c46")
        + ".json"
    )
)
for c in r["tool_calls"]:
    t, a, res = c["tool"], c.get("args") or {}, c.get("result")
    if t == "policy__get_procedure":
        store.get_procedure(a.get("ids") or [])
    msg = gate.before_tool_call(t, a)
    if msg:
        print("BLOCK", t, json.dumps(a)[:200], "\n   ", msg[:400])
    gate.after_tool_call(t, a, res)
recs = gate.records
print(
    "checked",
    sum(1 for x in recs if x.get("gate") == "checked"),
    "breaks",
    sum(1 for x in recs if x.get("breaks")),
    "grounded",
    sum(1 for x in recs if x.get("grounded")),
    "errors",
    sum(1 for x in recs if x.get("gate") == "error"),
)
for x in recs:
    if x.get("breaks"):
        print(
            "  ",
            x["tool"],
            "|",
            (x.get("rule") or "")[:90],
            "|",
            (x.get("case") or "")[:40],
            "| grounded",
            x.get("grounded"),
            "| repeat",
            x.get("repeat"),
        )
print("usage", dict(getattr(model, "usage", {}) or {}))
