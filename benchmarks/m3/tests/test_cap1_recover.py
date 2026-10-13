"""cap1 recovery pass: which items rerun, in what batches, and how answers merge back."""

from types import SimpleNamespace

import pytest

from benchmarks.m3 import cap1_recover
from benchmarks.m3.eval_m3_task_1_enterprise_style import parse_item_ids

pytestmark = pytest.mark.sanity


def _results():
    return [
        {"uuid": "a", "domain": "beer", "response": "42"},
        {"uuid": "b", "domain": "beer", "response": ""},
        {"uuid": "c", "domain": "beer", "response": "  "},
        {"uuid": "d", "domain": "wine", "response": None},
    ]


def test_empties_grouped_by_domain_and_batched_by_four():
    assert cap1_recover.empties_by_domain(_results()) == {"beer": ["b", "c"], "wine": ["d"]}
    assert cap1_recover.batches(list("abcdefghij"), 4) == [list("abcd"), list("efgh"), list("ij")]


def test_merge_fills_only_empty_answers_with_non_empty_recoveries():
    results = _results()
    recovered = [
        {"uuid": "b", "domain": "beer", "response": "7"},
        {"uuid": "c", "domain": "beer", "response": ""},  # still empty: stays a candidate
        {"uuid": "a", "domain": "beer", "response": "99"},  # never overwrite a real answer
    ]
    assert cap1_recover.merge_recovered(results, recovered) == 1
    assert [r["response"] for r in results] == ["42", "7", "  ", None]
    assert results[1]["recovered"] is True


def test_two_passes_with_the_campaign_timeouts(monkeypatch, tmp_path):
    calls = []

    def fake_batch(domain, ids, out_dir, args):
        calls.append((domain, tuple(ids), args.agent_timeout, args.llm_timeout, args.switch_timeout))
        # pass 1 recovers only "b"; pass 2 recovers the rest
        return [{"uuid": u, "domain": domain, "response": "x"} for u in ids if u == "b" or len(calls) > 2]

    monkeypatch.setattr(cap1_recover, "run_batch", fake_batch)
    args = SimpleNamespace(
        passes=2,
        batch=4,
        restart_container=False,
        output=tmp_path,
        agent_timeout=400,
        llm_timeout=300,
        switch_timeout=200,
    )
    results = cap1_recover.recover(_results(), args)
    assert calls[0] == ("beer", ("b", "c"), 400, 300, 200)
    assert [c[:2] for c in calls] == [
        ("beer", ("b", "c")),
        ("wine", ("d",)),
        ("beer", ("c",)),
        ("wine", ("d",)),
    ]
    assert not cap1_recover.empties_by_domain(results)


def test_item_ids_flag_accepts_a_list_or_a_file(tmp_path):
    assert parse_item_ids(None) is None
    assert parse_item_ids("a, b") == {"a", "b"}
    f = tmp_path / "ids.json"
    f.write_text('["x", "y"]')
    assert parse_item_ids(f"@{f}") == {"x", "y"}
    g = tmp_path / "ids.txt"
    g.write_text("p\nq\n")
    assert parse_item_ids(f"@{g}") == {"p", "q"}
