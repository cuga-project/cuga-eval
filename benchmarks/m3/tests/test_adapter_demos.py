"""Demo corpus extraction + prose-pair selection (embedder stubbed where possible)."""

from pathlib import Path

import pytest
from loguru import logger

from benchmarks.m3.adapter.config import ENV_PREFIX, AdapterConfig, resolve_adapter_config
from benchmarks.m3.adapter.demos import (
    DEFAULT_DEMO_DATA,
    _format_call,
    _iter_calls,
    build_demo_index,
    load_demo_corpus,
    resolve_demo_source,
    select_prose_pairs,
)

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


# ------------------------------ corpus source -------------------------------


def test_resolve_demo_source_defaults_to_bundled_train_zip():
    assert resolve_demo_source(None) == DEFAULT_DEMO_DATA
    assert DEFAULT_DEMO_DATA.name == "small_train.zip" and DEFAULT_DEMO_DATA.parent.name == "data"
    assert resolve_demo_source("/x/train.zip") == Path("/x/train.zip")


def test_demo_data_env_override_and_cli_precedence():
    assert resolve_adapter_config("cap2", env={}).demo_data is None
    cfg = resolve_adapter_config("cap2", env={f"{ENV_PREFIX}DEMO_DATA": "/env.zip"})
    assert cfg.demo_data == "/env.zip"
    cfg = resolve_adapter_config("cap2", env={f"{ENV_PREFIX}DEMO_DATA": "/env.zip"}, demo_data="/cli.zip")
    assert cfg.demo_data == "/cli.zip"


class _Loader:
    def __init__(self, samples=None, fail=False):
        self.samples = [_sample()] if samples is None else samples
        self.fail = fail
        self.calls = []

    def load_domain(self, task_id, domain):
        self.calls.append((task_id, domain))
        if self.fail:
            raise FileNotFoundError("no such domain")
        return self.samples


def test_load_demo_corpus_off_or_missing_source_is_none(tmp_path):
    assert load_demo_corpus(AdapterConfig(enabled=True, demos=False), task_id=2, domain="hockey") is None
    cfg = AdapterConfig(enabled=True, demos=True, demo_data=str(tmp_path / "missing.zip"))
    assert load_demo_corpus(cfg, task_id=2, domain="hockey", loader_factory=lambda p: _Loader()) is None


def test_load_demo_corpus_reads_explicit_source_for_the_runs_task_and_domain(tmp_path):
    src = tmp_path / "train.zip"
    src.write_bytes(b"")
    loader = _Loader()
    seen = {}

    def factory(path):
        seen["path"] = path
        return loader

    cfg = AdapterConfig(enabled=True, demos=True, demo_data=str(src))
    out = load_demo_corpus(
        cfg, task_id=2, domain="hockey", eval_source=tmp_path / "test.zip", loader_factory=factory
    )
    assert out == loader.samples
    assert seen["path"] == src and loader.calls == [(2, "hockey")]


def test_load_demo_corpus_degrades_on_loader_failure_or_empty_split(tmp_path):
    src = tmp_path / "train.zip"
    src.write_bytes(b"")
    cfg = AdapterConfig(enabled=True, demos=True, demo_data=str(src))
    assert (
        load_demo_corpus(cfg, task_id=1, domain="movie", loader_factory=lambda p: _Loader(fail=True)) is None
    )
    assert (
        load_demo_corpus(cfg, task_id=1, domain="movie", loader_factory=lambda p: _Loader(samples=[])) is None
    )


def test_load_demo_corpus_same_source_as_eval_warns_but_loads(tmp_path):
    src = tmp_path / "small_train.zip"
    src.write_bytes(b"")
    cfg = AdapterConfig(enabled=True, demos=True, demo_data=str(src))
    messages = []
    handle = logger.add(lambda m: messages.append(str(m)), level="WARNING")
    try:
        out = load_demo_corpus(
            cfg, task_id=2, domain="hockey", eval_source=str(src), loader_factory=lambda p: _Loader()
        )
    finally:
        logger.remove(handle)
    assert out  # train-split runs are legitimate; the run is warned, not refused
    assert any("evaluated data" in m for m in messages)
