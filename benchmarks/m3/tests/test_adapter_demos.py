"""Demo corpus extraction + prose-pair selection (embedder stubbed where possible)."""

import pytest

from benchmarks.m3.adapter.demos import _format_call, _iter_calls, build_demo_index, select_prose_pairs

pytestmark = pytest.mark.sanity


def _sample(query="How many players?", calls=None, answer="42"):
    return {
        "dialogue": {"turns": [{"turn_id": 0, "query": query}]},
        "additional_instructions": "",
        "expected_output": {
            "gold_sequence": [
                {
                    "tool_call": calls
                    if calls is not None
                    else [{"name": "get_players", "arguments": {"team": "x"}}]
                }
            ],
            "answer_per_turn": [answer],
        },
    }


def test_build_index_extracts_solved_turns():
    index = build_demo_index([_sample(), _sample(query="Other?", answer="7")])
    assert index is not None and len(index.entries) == 2
    assert index.entries[0]["query"] == "How many players?"
    assert index.entries[0]["calls"][0]["name"] == "get_players"
    assert index.entries[0]["answer"] == "42"


def test_build_index_skips_turns_without_calls_and_handles_nested_groups():
    no_calls = _sample(calls=[])
    nested = _sample(
        query="Nested?", calls=[[{"name": "a", "arguments": {}}, {"name": "b", "arguments": {}}]]
    )
    index = build_demo_index([no_calls, nested])
    assert index is not None and len(index.entries) == 1
    assert [c["name"] for c in index.entries[0]["calls"]] == ["a", "b"]


def test_build_index_empty_corpus_is_none():
    assert build_demo_index(None) is None
    assert build_demo_index([]) is None
    assert build_demo_index([_sample(calls=[])]) is None


def test_iter_calls_tolerates_shapes():
    assert list(_iter_calls(None)) == []
    assert list(_iter_calls({"tool_call": [{"name": "x"}]})) == [{"name": "x"}]
    assert list(_iter_calls([{"name": "y", "arguments": {}}]))[0]["name"] == "y"
    assert list(_iter_calls({"tool_call": "garbage"})) == []


def test_format_call_truncates_and_drops_db_path():
    call = {"name": "t", "arguments": {"database_path": "/x", "q": "a" * 100}}
    text = _format_call(call)
    assert "database_path" not in text
    assert "…" in text and len(text) < 120


def test_select_pairs_with_stubbed_embedder():
    pytest.importorskip("numpy")
    import numpy as np

    index = build_demo_index(
        [_sample(), _sample(query="Which team won?", answer="Leafs"), _sample(query="Target?", answer="z")]
    )

    class _StubModel:
        def encode(self, texts, convert_to_numpy=True):
            # deterministic: similarity by shared first word
            return np.array([[1.0, 0.0] if t.startswith("Which") else [0.0, 1.0] for t in texts])

    index._model = _StubModel()
    pairs = select_prose_pairs(index, "Which team lost?", k=1)
    assert len(pairs) == 2  # one demo = user+assistant pair
    assert pairs[0] == {"role": "user", "content": "Which team won?"}
    assert "Chain used:" in pairs[1]["content"]
    assert "Final answer:" in pairs[1]["content"]


def test_self_leak_guard_skips_identical_query():
    pytest.importorskip("numpy")
    import numpy as np

    index = build_demo_index([_sample(query="Same question?")])

    class _StubModel:
        def encode(self, texts, convert_to_numpy=True):
            return np.ones((len(texts), 2))

    index._model = _StubModel()
    assert select_prose_pairs(index, "Same question?", k=2) == []


def test_select_pairs_none_index_or_zero_k():
    assert select_prose_pairs(None, "q", 2) == []
    index = build_demo_index([_sample()])
    assert select_prose_pairs(index, "q", 0) == []
