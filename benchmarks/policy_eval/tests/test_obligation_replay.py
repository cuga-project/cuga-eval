"""The obligation replay (``obligation_replay.py``, stabilization task 4.3): each metric on small inline fixtures, the rule at its
edges, the model cache and the cost meter, a failed binding on the real ledger with a scripted binder, and the generated
tables (a re-render equals the committed Markdown, so the numbers cannot drift).

The pure parts run here. The ledger is in the gate repo, so the scripted-binder test runs with the gate repo's Python. With
``EVAL_NO_SKIP=1`` a missing input is a failure, not a skip.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

POLICY_EVAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POLICY_EVAL))
sys.path.insert(0, str(POLICY_EVAL.parent))

import obligation_replay as r  # noqa: E402

GATE_PYTHON = os.environ.get("POLICY_GATE_PYTHON") or str(Path.home() / "dev/cuga-agent-gate/.venv/bin/python")
REPORT = POLICY_EVAL / "obligation_replay" / "REPORT.md"
RESULTS = POLICY_EVAL / "obligation_replay" / "results.json"


def missing_input(reason):
    if os.environ.get("EVAL_NO_SKIP"):
        pytest.fail(f"EVAL_NO_SKIP is set: {reason}")
    pytest.skip(reason)


# -- the rule, at its edges ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "false_open, recall, level",
    [
        ((1, 10), (3, 10), 2),  # exactly 10% and exactly 30%: both pass
        ((10, 100), (30, 100), 2),
        ((0, 50), (50, 50), 2),
        ((11, 100), (30, 100), 1),  # 11%: above
        ((2, 19), (3, 10), 1),  # 10.5%
        ((10, 100), (29, 100), 1),  # 29%: below
        ((1, 10), (2, 7), 1),  # 28.6%
        ((1, 10), (3, 9), 2),  # 33.3%
    ],
)
def test_the_rule_at_its_edges(false_open, recall, level):
    assert r.decide(false_open, recall)[0] == level


def test_a_rate_with_no_denominator_does_not_pass():
    assert r.decide((0, 0), (5, 5))[0] == 1
    assert r.decide((0, 20), (0, 0))[0] == 1
    assert "not known" in r.decide((0, 20), (0, 0))[1]


def test_the_reason_names_what_failed():
    assert r.decide((5, 10), (9, 10))[1] == "false-open above 10%"
    assert r.decide((5, 10), (1, 3))[1] == "false-open above 10% and recall is not known: only 3 failed checks that a write could have met"
    assert r.decide((0, 10), (1, 10))[1] == "recall below 30%"
    assert r.decide((5, 10), (1, 10))[1] == "false-open above 10% and recall below 30%"


def test_wilson_interval():
    lo, hi = r.wilson(5, 10)
    assert 0.23 < lo < 0.24 and 0.76 < hi < 0.77
    assert r.wilson(0, 0) == (None, None)
    assert r.wilson(0, 10)[0] == 0.0 and r.wilson(10, 10)[1] == 1.0


# -- the metrics, on rows made by hand -----------------------------------------------------------------------------------


def item(n, status="open", sent=False, values=0, known=0, shown=False, prior=False):
    return {
        "n": n,
        "ob": f"ob{n}",
        "status": status,
        "sent": sent,
        "values": values,
        "known": known,
        "shown": shown,
        "prior_call": prior,
    }


def mapped(maps):
    """``{"0": ["c1"]}`` is the item meeting c1; a dict gives ``meets`` and ``breaks`` as they are."""
    return {n: v if isinstance(v, dict) else {"meets": v, "breaks": []} for n, v in maps.items()}


def row(
    items, checks, maps, run_passed=False, cost=0.01, binding="ok", unbound=0, causes=None, status="ok", task="t0", sets=(), usage=None
):
    return {
        "task": task,
        "sets": list(sets),
        "replay": {
            "status": status,
            "binding": binding,
            "items": items,
            "unbound": unbound,
            "cost_usd": cost,
            "producer": "package",
            "usage": usage or {},
        },
        "checks": [{"id": i, "passed": p, "writable": w} for i, p, w in checks],
        "maps": mapped(maps),
        "causes": causes or {},
        "run_passed": run_passed,
    }


FIXTURE = [
    # run 1 passed: two passed checks; one item is sent for a passed check (a false open)
    row(
        [item(0, sent=True, values=2, known=2, shown=True), item(1, "met", values=1, known=0)],
        [("c1", True, True), ("c2", True, True)],
        {"0": ["c1"]},
        run_passed=True,
        cost=0.02,
    ),
    # run 2 failed: one failed writable check named by a sent item, one failed writable check no item names, one failed
    # check that no write could meet
    row(
        [item(0, sent=True, values=1, known=1), item(1, "unknown"), item(2, "held")],
        [("c1", False, True), ("c2", False, True), ("c3", False, False), ("c4", True, True)],
        {"0": ["c1"]},
        cost=0.03,
        unbound=2,
        causes={"c2": "no item"},
    ),
    # run 3 failed, the binding failed: no item
    row([], [("c1", False, True)], {}, binding="failed", cost=0.005, causes={"c1": "binding failed"}),
    # run 4 passed with no follow-up
    row([item(0, "met")], [("c1", True, True)], {}, run_passed=True, cost=0.0),
]


def test_false_open_is_passed_checks_given_an_item():
    g = r.measure_group(FIXTURE)
    assert (g["false_open"], g["passed_checks"]) == (1, 4)  # c1 of run 1 is named; run 1's c2, run 2's c4 and run 4's c1 are not
    assert g["sent_items_passed_work"] == 1


def test_recall_is_failed_writable_checks_given_an_item_and_names_its_denominator():
    g = r.measure_group(FIXTURE)
    assert g["failed_checks"] == 4
    assert g["failed_writable"] == 3  # run 2 c1, c2 and run 3 c1; c3 is not a write
    assert g["recalled"] == 1
    assert g["failed_all_recalled"] == 1
    assert g["sent_items_failed_work"] == 1


def test_run_level_rates():
    g = r.measure_group(FIXTURE)
    assert g["runs"] == 4 and g["passed_runs"] == 2
    assert g["runs_with_follow_up"] == 2
    assert g["passed_runs_with_follow_up"] == 1
    assert g["follow_ups_naming_failed_work"] == 1  # run 2's follow-up names work of a failed check
    assert g["follow_ups_naming_passed_work"] == 1  # run 1's names work of a passed check


def test_a_failed_binding_is_counted_and_the_checks_it_left_are_not_recalled():
    g = r.measure_group(FIXTURE)
    assert g["failed_bindings"] == 1
    assert g["causes"] == {"binding failed": 1, "no item": 1}


def test_status_counts_value_shares_and_cost():
    g = r.measure_group(FIXTURE)
    assert g["status"] == {"met": 2, "open": 2, "held": 1, "unknown": 1, "wrong": 0, "unbound": 2, "not_applicable": 0}
    assert g["items"] == 6
    assert g["items_with_values"] == 3
    assert g["items_value_known"] == 2  # the item with 1 value and none known is not
    assert g["items_all_values_known"] == 2
    assert g["items_value_shown"] == 1
    assert (g["sent_items"], g["sent_with_values"], g["sent_value_shown"]) == (2, 2, 1)
    assert g["cost_usd"] == pytest.approx(0.055)


def test_the_level_follows_the_rule_on_the_numbers_of_the_group():
    g = r.measure_group(FIXTURE)
    assert g["level"] == 1  # 1 of 4 is 25%, and recall is 1 of 3
    only_good = [row([item(0, sent=True)], [("c1", False, True), ("c2", True, True)], {"0": ["c1"]}) for _ in range(5)]
    assert r.measure_group(only_good)["level"] == 2
    few = r.measure_group(only_good[:4])  # 4 failed checks a write could meet: recall is not known, whatever the hits
    assert few["level"] == 1 and "not known" in few["why"]


def test_an_empty_producer_run_counts_and_adds_no_item():
    g = r.measure_group([row([], [("c1", False, True)], {}, status="empty", causes={"c1": "no item"})])
    assert g["empty_runs"] == 1 and g["items"] == 0 and g["failed_writable"] == 1 and g["recalled"] == 0


def test_an_item_that_would_break_a_passed_check_is_a_false_open_and_never_a_recall_hit():
    rows = [
        row(
            [item(0, sent=True), item(1, sent=True)],
            [("c1", True, True), ("c2", False, True)],
            {"0": {"meets": [], "breaks": ["c1"]}, "1": {"meets": [], "breaks": ["c2"]}},
        )
    ]
    g = r.measure_group(rows)
    assert (g["false_open"], g["passed_checks"]) == (1, 1)  # the item that asks for forbidden work is sent on a passed check
    assert g["recalled"] == 0 and g["failed_writable"] == 1  # asking for forbidden work is no recall
    assert g["sent_items_break_passed_work"] == 1 and g["sent_items_passed_work"] == 1


def test_a_sent_item_with_no_check_is_counted_apart():
    g = r.measure_group([row([item(0, sent=True)], [("c1", True, True)], {"0": []})])
    assert g["sent_items_no_check"] == 1 and g["false_open"] == 0


# -- the hand check ------------------------------------------------------------------------------------------------------


def test_handcheck_stats():
    def d(meets=(), breaks=()):
        return {"meets": list(meets), "breaks": list(breaks)}

    rows = [
        {"judge": d(["a"]), "true": d(["a"])},
        {"judge": d(["a"], ["b"]), "true": d(["a"])},  # a break that the hand check does not make
        {"judge": d(), "true": d(["c"])},
        {"judge": d(["x"]), "true": d([], ["x"])},  # the right check, the wrong kind
    ]
    assert r.handcheck_stats(rows) == {"items": 4, "judge_pairs": 4, "right_pairs": 2, "missed_pairs": 2, "same_set": 1}


# -- the model: cache, meter, budget, failure ----------------------------------------------------------------------------


def scripted(answers):
    calls = []

    def transport(model, system, user, max_tokens):
        calls.append((model, max_tokens))
        text = answers.pop(0) if answers else "{}"
        if isinstance(text, Exception):
            raise text
        return text, 100, 50

    transport.calls = calls
    return transport


def make_model(transport, cap=4.0, tmp=None, retries=2):
    meter = r.Meter(cap=cap, price=lambda m, i, o: (i + o) / 1000)
    return r.CachedModel("m", r.Cache(tmp), meter, transport, 16000, retries=retries, sleep=lambda s: None), meter


def test_a_repeated_call_comes_from_the_cache_and_costs_nothing_new(tmp_path):
    t = scripted(["a", "b"])
    model, meter = make_model(t, tmp=tmp_path / "c.jsonl")
    assert model("s", "u") == "a" and model("s", "u") == "a" and model("s", "other") == "b"
    assert len(t.calls) == 2 and meter.new_calls == 2
    assert model.usage == {"calls": 3, "input_tokens": 300, "output_tokens": 150}  # the cost per run counts cached calls too
    again, meter2 = make_model(scripted([]), tmp=tmp_path / "c.jsonl")  # a new process reads the file
    assert again("s", "u") == "a" and meter2.new_calls == 0


def test_the_call_is_keyed_by_max_tokens():
    assert r.Cache.key("m", 16000, "s", "u") != r.Cache.key("m", None, "s", "u")


def test_a_gateway_failure_retries_then_raises_and_is_counted():
    t = scripted([TimeoutError("hang"), TimeoutError("hang")])
    model, meter = make_model(t, retries=2)
    with pytest.raises(RuntimeError, match="failed after 2 tries"):
        model("s", "u")
    assert meter.failed_calls == 1 and len(t.calls) == 2
    ok, _ = make_model(scripted([TimeoutError("hang"), "fine"]), retries=2)
    assert ok("s", "u") == "fine"


def test_the_cap_stops_new_calls_and_not_cached_ones(tmp_path):
    t = scripted(["a", "b"])
    model, meter = make_model(t, cap=0.1, tmp=tmp_path / "c.jsonl")  # one call costs 0.15
    assert model("s", "u") == "a"
    with pytest.raises(r.BudgetStop):
        model("s", "new")
    assert model("s", "u") == "a"  # cached: no cost


def test_a_model_with_no_transport_cannot_call():
    model, _ = make_model(None)
    with pytest.raises(RuntimeError, match="no transport"):
        model("s", "u")


# -- the sample ----------------------------------------------------------------------------------------------------------


def fake_run(i, bench="itsm"):
    return r.Run(bench, f"run{i}", f"task{i}", None, "m", "p", Path("x"), "req", [], None, [], "", "", [], i % 2 == 0, source=f"s{i}")


def test_the_sample_is_by_hash_of_identity_and_not_by_outcome():
    runs = [fake_run(i) for i in range(40)]
    a, b = r.sample(runs, 10), r.sample(list(reversed(runs)), 10)
    assert [x.uid for x in a] == [x.uid for x in b]  # the order of the input does not matter
    assert len({x.passed for x in a}) == 2  # passes and failures both come in; the hash never reads the outcome
    assert [x.uid for x in r.sample(runs, None)] == [x.uid for x in sorted(runs, key=lambda x: r._hash_order(x.uid + "|" + x.source))]


# -- the real ledger with a scripted binder (gate Python) ---------------------------------------------------------------

LEDGER_SCRIPT = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import obligation_replay as r
from cuga.policy_layer.package import load_package

package = Path(sys.argv[1]) / "packages/itsm/e2891a7b98/skill_v1/package.json"
pkg = load_package(package)
specs = json.loads((Path(sys.argv[2]) / "enterpriseops_gym/tasks/itsm_tools.json").read_text())
REQUEST = "Please move the incident INC-000061 to on hold with the reason Awaiting Caller, and alert the requester."
procedure = next(p.id for p in pkg.procedures)

def run(mode):
    answers = {"bind": None}
    def transport(model, system, user, max_tokens):
        if system.startswith("You read a work request"):
            if mode == "bad":
                return "I cannot answer", 10, 5
            case = {"case": "INC-000061", "keys": ["INC-000061"], "evidence": "move the incident INC-000061 to on hold",
                    "procedure": procedure, "decision": {"branch": "proceed", "evidence": ""}, "answers": {}, "facts": {}, "stated": {}}
            return json.dumps({"cases": [case]}), 1000, 200
        if system.startswith("You list what a user request"):
            item = {"action": "alert the requester", "tool": "send_notification", "args": {}, "targets": [], "values": [],
                    "quote": "on hold with the reason Awaiting Caller, and alert the requester"}
            return json.dumps({"items": [item]}), 300, 100
        return "{}", 1, 1
    meter = r.Meter(cap=1.0)
    models = r.ReplayModels(r.Cache(None), meter, transport, sleep=lambda s: None)
    out = {}
    for producer in ("package", "request"):
        rr = r.Run("itsm", "fix", "t1", None, "m", "e2891a7b98", package, REQUEST, specs, None,
                   [{"tool": "find_incident_by_number", "args": {"number": "INC-000061"}, "result": {"incident_id": "INC_061"}}],
                   "done", "", [r.Check("v0", "x", False)], False)
        out[producer] = r.replay_run(rr, producer, models)
    return out

good, bad = run("good"), run("bad")
print(json.dumps({"good": good, "bad": bad}))
"""


@pytest.fixture(scope="module")
def ledger_runs():
    if not Path(GATE_PYTHON).is_file():
        missing_input(f"the gate repo's Python is missing: {GATE_PYTHON}")
    done = subprocess.run(
        [GATE_PYTHON, "-I", "-c", LEDGER_SCRIPT, str(POLICY_EVAL), str(POLICY_EVAL.parent)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-3000:]
    return json.loads(done.stdout)


def test_with_a_scripted_binder_the_package_producer_sends_open_items_and_counts_cost(ledger_runs):
    rep = ledger_runs["good"]["package"]
    assert rep["status"] == "ok" and rep["binding"] == "ok" and rep["follow_up"] is True
    assert any(i["sent"] for i in rep["items"]) and all(i["status"] == "open" for i in rep["items"] if i["sent"])
    assert rep["usage"]["calls"] == 1 and rep["usage"]["input_tokens"] == 1000
    assert rep["cost_usd"] > 0


def test_the_request_producer_makes_one_call_and_needs_no_case(ledger_runs):
    """What the producer keeps from the model's list is the gate repo's test (quotes, tools); here only the replay's part:
    one call, no binding of cases, a ledger of its own."""
    rep = ledger_runs["good"]["request"]
    assert rep["status"] == "ok" and rep["binding"] == "ok" and rep["errors"] == []
    assert rep["usage"]["calls"] == 1 and rep["unbound"] == 0


def test_a_failed_binding_gives_no_item_and_is_reported_not_raised(ledger_runs):
    rep = ledger_runs["bad"]["package"]
    assert rep["status"] == "ok" and rep["binding"] == "failed"
    assert [i for i in rep["items"] if i["sent"]] == []
    assert rep["follow_up"] is False
    assert rep["errors"] and rep["errors"][0].startswith("binding:")


# -- the generated tables -------------------------------------------------------------------------------------------------


def test_the_report_is_generated_from_results_json():
    """``REPORT.md`` is written by ``obligation_replay.py report`` (the controller runs it and commits the file); until then
    this test fails."""
    if not (REPORT.exists() and RESULTS.exists()):
        missing_input("REPORT.md or results.json is not there: run `obligation_replay.py report` after `measure`")
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert REPORT.read_text(encoding="utf-8") == r.report_text(results)


META = {
    "s-tune": {"status": "tuning", "benchmark": "itsm", "seen": True},
    "s-held": {"status": "heldout", "benchmark": "itsm", "seen": True},
}


def fixture_results(level2=(), previous=True):
    good_rows = [
        row(
            [item(0, sent=True)],
            [("c1", False, True), ("c2", True, True)],
            {"0": ["c1"]},
            task=f"t{i}",
            sets=["s-tune" if i % 2 else "s-held"],
        )
        for i in range(6)
    ]
    bad_rows = FIXTURE
    good, bad = r.measure_group(good_rows), r.measure_group(bad_rows)
    groups = {f"{b}|{p}": (good if (b, p) in level2 else bad) for b in r.BENCHMARKS for p in r.PRODUCERS}
    views = {
        f"{b}|{p}": r.views_of(good_rows if (b, p) in level2 else bad_rows, META) for b in r.BENCHMARKS for p in r.PRODUCERS
    }
    sample = {b: {"runs": 4, "tasks": 2, "models": {"m": 4}, "by_set": {"s-tune": 2}} for b in r.BENCHMARKS}
    diag = {"runs": 4, "obligation_runs": 40, "unbound_obligation_runs": 30, "cases": 8, "no_item_checks": 5, "no_item_with_overlap": 3, "no_item_notification": 2}
    return {
        "groups": groups,
        "views": views,
        "basis": {b: {"tuning": 4} for b in r.BENCHMARKS},
        "runs": {b: 4 for b in r.BENCHMARKS},
        "sample": sample,
        "sets": META,
        "meta": {"gate_commit": "abc123456"},
        "spent_usd": 0.5,
        "limits": {"handbook|code_only": {"unknown": 3, "met": 1}},
        "handcheck": {"items": 4, "distinct_items": 3, "judge_pairs": 4, "right_pairs": 3, "missed_pairs": 1, "same_set": 3},
        "itsm_models": {"aws/gpt-oss-120b": {"runs": 57, "passed": 6}, "azure/DeepSeek-V4-Pro": {"runs": 280, "passed": 145}},
        "truncation": {b: {"calls": 10, "truncated": 2, "runs": 4, "runs_with_truncation": 4} for b in r.BENCHMARKS},
        "package_diagnosis": {b: dict(diag) for b in r.BENCHMARKS},
        "previous": {
            "gate_commit": "61699250e", "false_open": 3, "passed_checks": 95, "recalled": 57, "failed_writable": 134,
            "sent_items": 58, "sent_with_prior_call": 24, "sent_with_prior_call_in_hits": 20, "runs_with_follow_up": 31,
            "level": 2, "views": r.views_of(task_rows("a", 3, True, sets=["s-tune"]) + task_rows("b", 3, True, sets=["s-held"]), META), "examples": [{"item": "update_incident", "check": "No open incidents", "prior": "update_incident({})", "run": "x"}],
        } if previous else None,
    }


def test_the_tables_have_every_column_and_are_deterministic():
    results = fixture_results()
    text = r.render_tables(results)
    assert text == r.render_tables(json.loads(json.dumps(results)))
    assert "| ITSM | tuning 4 | package | 4 | 1 of 4 (25.0%)" in text
    assert "τ² Telecom †" in text and "cannot run these configurations live" in text
    assert "1 of 3 (33.3%)" in text  # recall with its denominator
    assert "1: false-open above 10%" in text
    assert "binding failed" in text and "break a passed check" in text
    assert "sent while a successful call of the item's tool exists" in text and "name no check, on a passed run" in text
    assert "status heldout, label seen" in text and "Task bootstrap" in text


def test_the_report_says_which_producers_pass_and_that_no_result_is_held_out():
    none = r.report_text(fixture_results())
    assert none == r.report_text(json.loads(json.dumps(fixture_results())))
    assert "No producer passes the rule" in none
    one = r.report_text(fixture_results(level2=[("itsm", "request")]))
    assert "Level 2 is allowed by the pooled rule for: ITSM `request`" in one
    assert "none is a held-out result" in one and "`abc123456`" in one
    assert "ITSM `request`: 2" in one and "ITSM `package`: 1" in one
    assert "24 of its 58 sends" in one and "gpt-oss-120b agent only" in one and "6 of 57" in one and "145 of 280" in one
    assert "cannot send on `package` today" in one and "word-overlap estimate" in one


# -- the four counts, the sets, the extras ---------------------------------------------------------------------------------


def task_rows(task, n_runs, hit, sets=()):
    """``n_runs`` runs of one task, each with one passed check and one failed check that a write could meet; ``hit``: the item
    meets the failed check."""
    return [
        row(
            [item(0, sent=True)],
            [("p", True, True), ("f", False, True)],
            {"0": ["f"]} if hit else {"0": []},
            task=task,
            sets=sets,
        )
        for _ in range(n_runs)
    ]


def test_one_count_per_task_weights_a_task_once_whatever_its_runs():
    rows = task_rows("big", 9, hit=True, sets=["s-tune"]) + task_rows("small", 1, hit=False, sets=["s-held"])
    v = r.views_of(rows, META)
    assert v["pooled"]["rec"] == [9, 10] and v["pooled"]["ok"] is True  # 90% of runs name the work
    assert v["per_task"]["rec"] == [1.0, 2.0]  # a task weighs 1: half
    assert v["per_task"]["ok"] is True
    assert v["mean_task"]["rec"] == 0.5 and v["tasks"] == 2


def test_a_pass_is_not_firm_when_the_counts_by_task_disagree():
    rows = task_rows("big", 20, hit=True) + [r2 for t in "abcdefgh" for r2 in task_rows(t, 1, hit=False)]
    v = r.views_of(rows, META)
    assert v["pooled"]["ok"] is True and v["per_task"]["ok"] is False and v["firm"] is False
    assert v["mean_task"]["ok"] is False
    firm = r.views_of(task_rows("a", 3, True) + task_rows("b", 3, True), META)
    assert firm["firm"] is True


def test_sets_are_counted_apart_and_a_run_in_no_set_is_listed():
    rows = task_rows("a", 2, True, sets=["s-tune"]) + task_rows("b", 3, False, sets=["s-held", "s-tune"]) + task_rows("c", 1, True)
    v = r.views_of(rows, META)
    assert v["sets"]["s-tune"]["runs"] == 5 and v["sets"]["s-tune"]["tasks"] == 2
    assert v["sets"]["s-held"]["rec"] == [0, 3] and v["sets"]["s-held"]["status"] == "heldout" and v["sets"]["s-held"]["seen"]
    assert v["sets"]["(in no set)"]["runs"] == 1


def test_the_bootstrap_is_by_task_and_repeatable():
    rows = task_rows("a", 2, True) + task_rows("b", 2, False) + task_rows("c", 2, True)
    a, b = r.views_of(rows, META), r.views_of(list(reversed(rows)), META)
    assert a["boot"] == b["boot"] and a["boot"]["rec"][0] <= 2 / 3 <= a["boot"]["rec"][1]


def test_sent_while_a_call_exists_and_recall_hits_by_such_items_are_counted():
    sent_prior = row(
        [item(0, sent=True, prior=True)], [("f", False, True), ("p", True, True)], {"0": ["f"]}, task="x"
    )
    sent_fresh = row([item(0, sent=True)], [("f", False, True)], {"0": ["f"]}, task="y")
    no_check_passed = row([item(0, sent=True)], [("p", True, True)], {"0": []}, run_passed=True, task="z")
    g = r.measure_group([sent_prior, sent_fresh, no_check_passed])
    assert g["sent_items_prior_call"] == 1
    assert (g["recalled_prior_call"], g["recalled_no_prior_call"]) == (1, 1)
    assert g["sent_items_no_check_on_passed_run"] == 1 and g["sent_items_no_check"] == 1


def test_failed_bindings_say_why():
    cut = {"producer": "package", "usage": {"output_tokens": 16000}}
    bad = {"producer": "package", "usage": {"output_tokens": 300}}
    assert "16000-token output limit" in r.binding_reason(cut)
    assert "not a JSON list" in r.binding_reason(bad)
    g = r.measure_group([row([], [("f", False, True)], {}, binding="failed", usage=cut["usage"]), row([], [("f", False, True)], {}, binding="failed", usage=bad["usage"])])
    assert sum(g["binding_failures"].values()) == 2 and len(g["binding_failures"]) == 2


def test_truncated_results_are_found_by_their_marker():
    run = fake_run(1)
    run.calls = [
        {"tool": "t", "args": {}, "result": "x" * 4000 + "... [59586 chars]"},
        {"tool": "t", "args": {}, "result": {"a": 1}},
    ]
    assert r.truncation_counts([run]) == {"itsm": {"calls": 2, "truncated": 1, "runs": 1, "runs_with_truncation": 1}}


def test_itsm_model_counts_read_runs_by_model(tmp_path):
    for i, (model, passed) in enumerate([("a", True), ("a", False), ("b", True)]):
        folder = tmp_path / f"run{i}"
        folder.mkdir()
        (folder / "A_x.json").write_text(json.dumps({"model": model, "passed": passed, "verifiers": [{"name": "v"}]}))
    (tmp_path / "run9").mkdir()
    (tmp_path / "run9" / "A_y.json").write_text(json.dumps({"model": "a", "passed": True, "verifiers": []}))  # not graded
    assert r.itsm_model_counts(tmp_path) == {"a": {"runs": 2, "passed": 1}, "b": {"runs": 1, "passed": 1}}


def test_distinct_items_ignore_case_and_values():
    rows = [
        {"producer": "package", "item": '- [case Yoon] a__send: "Step 5" [section 11.1] Values: to = "x".'},
        {"producer": "package", "item": '- [case Webb] a__send: "Step 5" [section 11.1] Values: to = "y".'},
        {"producer": "request", "item": '- a__send: "Step 5" [section 11.1]'},
    ]
    assert r.hand_distinct(rows) == 2
