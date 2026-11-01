"""vote_runs: per task one run's whole record, chosen by majority / evidence / first."""

import json

import pytest

from benchmarks.m3.parity import vote_runs as V
from benchmarks.m3.parity.recover import TIMEOUT_DRAFT

pytestmark = pytest.mark.sanity


def _rec(uid, answer, calls, error=""):
    return {
        "uuid": uid,
        "domain": "shop",
        "error": error,
        "output": [
            {
                "turn_id": 0,
                "query": "How many stores?",
                "answer": answer,
                "sequence": {
                    "tool_call": [{"name": n, "arguments": {}} for n, _ in calls],
                    "tool_response": [r for _, r in calls],
                },
            }
        ],
    }


def _arm(tmp_path, name, recs):
    arm = tmp_path / name
    (arm / "prediction").mkdir(parents=True)
    (arm / "prediction" / "shop.json").write_text(json.dumps(recs))
    (arm / "meta.json").write_text(json.dumps({"arm": name}))
    return arm


def test_normalize_ignores_format_and_order():
    assert V.normalize('["Toa Baja"]') == V.normalize("toa baja")
    assert V.normalize("5.0") == V.normalize("5")
    assert V.normalize("b, a") == V.normalize("a, b")
    assert V.normalize("") is None


def _three(tmp_path):
    good = [("count", '{"count": 7}')]
    long = [("list", '{"x": 1}'), ("count", '{"count": 7}'), ("count", '{"count": 7}')]
    arms = [
        _arm(tmp_path, "r1", [_rec("t1", "7", long), _rec("t2", "I can not answer.", good)]),
        _arm(tmp_path, "r2", [_rec("t1", "7.0", good), _rec("t2", "8", [("count", '{"count": 8}')])]),
        _arm(
            tmp_path,
            "r3",
            [_rec("t1", "9", [("count", '{"count": 9}')]), _rec("t2", "We need the count", good)],
        ),
    ]
    return arms


def _chosen(out):
    return {
        r["uuid"]: r["output"][-1]["answer"]
        for r in json.loads((out / "prediction" / "shop.json").read_text())
    }


def test_majority_picks_the_majority_answer_with_the_leanest_supported_trace(tmp_path):
    arms = _three(tmp_path)
    s = V.vote(arms, 2, "majority", tmp_path / "vm")
    got = _chosen(tmp_path / "vm")
    assert got["t1"] == "7.0"  # 7 and 7.0 agree; run 2's trace has 1 call vs 3
    assert got["t2"] == "8"  # no majority: the refusal and the plan text are not valid answers on cap2
    assert s["tasks"] == 2
    log = json.loads((tmp_path / "vm" / "vote_log.json").read_text())
    assert log["tasks"][0]["why"] == "majority 2/3"


def test_first_keeps_the_earliest_run_of_the_majority(tmp_path):
    V.vote(_three(tmp_path), 2, "first", tmp_path / "vf")
    got = _chosen(tmp_path / "vf")
    assert got["t1"] == "7" and got["t2"] == "I can not answer."  # no majority -> run 1


def test_evidence_prefers_supported_traces_without_failed_calls(tmp_path):
    arms = [
        _arm(tmp_path, "r1", [_rec("t1", "7", [("count", '{"count": 5}')])]),  # 7 not in its results
        _arm(tmp_path, "r2", [_rec("t1", "7", [("count", "Error: boom"), ("count", '{"count": 7}')])]),
        _arm(tmp_path, "r3", [_rec("t1", "5", [("count", '{"count": 5}')])]),
    ]
    V.vote(arms, 2, "evidence", tmp_path / "ve")
    assert _chosen(tmp_path / "ve")["t1"] == "5"  # the only supported run without a failed call
    V.vote(arms, 2, "majority", tmp_path / "vm")
    assert _chosen(tmp_path / "vm")["t1"] == "7"  # the majority answer, best trace of its group


def test_cap4_refusal_is_a_valid_answer(tmp_path):
    arms = [
        _arm(tmp_path, f"r{i}", [_rec("t1", a, [("query_x", '{"results": []}')])])
        for i, a in enumerate(["I can not answer.", "I can not answer.", "42"])
    ]
    V.vote(arms, 4, "majority", tmp_path / "v4")
    assert _chosen(tmp_path / "v4")["t1"] == "I can not answer."


def test_unknown_rule_and_existing_output_fail(tmp_path):
    arms = _three(tmp_path)
    with pytest.raises(ValueError):
        V.vote(arms, 2, "random", tmp_path / "x")
    (tmp_path / "y").mkdir()
    with pytest.raises(FileExistsError):
        V.vote(arms, 2, "majority", tmp_path / "y")


def _draft_console(arm, *uids):
    """A console log in which every task of ``uids`` answered with its timeout draft."""
    draft = "2099-01-01 00:00:05.000 | WARNING | x - [m3-adapter] " + TIMEOUT_DRAFT
    (arm / "console.log").write_text(
        "".join(
            f"[{i}/{len(uids)}] Processing sample\n{draft}\n2099-01-01 00:00:09.000 | INFO | x - ✅ Completed: {u}\n"
            for i, u in enumerate(uids, 1)
        )
    )


def test_a_timeout_draft_counts_toward_the_majority_but_is_taken_last(tmp_path):
    seven = [("count", '{"count": 7}')]
    arms = [
        _arm(tmp_path, "r1", [_rec("t1", "7", seven), _rec("t2", "5", [("count", '{"count": 5}')])]),
        _arm(tmp_path, "r2", [_rec("t1", "7", seven + seven), _rec("t2", "6", [("count", '{"count": 6}')])]),
    ]
    _draft_console(arms[0], "t1", "t2")  # r1's lean trace for t1 is a draft
    assert V.draft_uuids(arms[0]) == {"t1", "t2"}
    V.vote(arms, 3, "majority", tmp_path / "vm")
    got = _chosen(tmp_path / "vm")
    assert got["t1"] == "7"  # still the 2/2 majority, but with r2's record
    assert got["t2"] == "6"  # no majority: the non-draft valid answer
    log = {e["uuid"]: e for e in json.loads((tmp_path / "vm" / "vote_log.json").read_text())["tasks"]}
    assert log["t1"]["why"] == "majority 2/2" and log["t1"]["chosen_run"] == 1
    assert log["t2"]["timeout_drafts"] == [0]


def test_a_draft_that_a_recovery_pass_replaced_is_not_a_draft(tmp_path):
    arm = _arm(tmp_path / "run_1", "cuga_eval_cap3_fc", [_rec("t1", "7", [])])
    _draft_console(arm, "t1")
    rec = tmp_path / "run_1__recover1" / "cuga_eval_cap3_fc"
    rec.mkdir(parents=True)
    (rec / "console.log").write_text("")
    (arm / "recover_log.jsonl").write_text(
        json.dumps({"recovered_from": str(rec), "replaced": ["t1"]}) + "\n"
    )
    assert V.draft_uuids(arm) == set()
