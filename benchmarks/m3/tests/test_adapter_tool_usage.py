"""Tool usage examples: solved train questions appended to each tool's description."""

import asyncio
from dataclasses import replace

import pytest
from langchain_core.tools import StructuredTool

from benchmarks.m3.adapter.config import PRESETS
from benchmarks.m3.adapter.demos import ToolUsageIndex, build_tool_usage_index, load_tool_usage_corpus
from benchmarks.m3.adapter.recording import RecordingScopedToolProvider, usage_note

pytestmark = pytest.mark.sanity


def _sample(query, *tools):
    return {
        "dialogue": {"turns": [{"query": query}]},
        "expected_output": {
            "gold_sequence": [{"tool_call": [{"name": t, "arguments": {}} for t in tools]}],
            "answer_per_turn": [[["x"]]],
        },
    }


SAMPLES = [
    _sample("Which store is the least liked?", "get_top_store_by_review_count"),
    _sample("Least liked store in 2019?", "get_top_store_by_review_count", "get_sales"),
    _sample("Total sales of store 7?", "get_sales"),
]


def test_index_maps_tools_to_their_questions_and_never_the_asked_one():
    index = build_tool_usage_index(SAMPLES)
    assert index.questions("get_sales") == ["Least liked store in 2019?", "Total sales of store 7?"]
    assert index.questions("get_sales", exclude_query="Total sales of store 7?") == [
        "Least liked store in 2019?"
    ]
    assert index.questions("get_sales", k=1) == ["Least liked store in 2019?"]


def test_index_resolves_registry_prefixed_names_and_unknown_tools():
    index = build_tool_usage_index(SAMPLES)
    assert index.questions("shop_get_top_store_by_review_count", k=1) == ["Which store is the least liked?"]
    assert index.questions("shop_get_unused") == []
    assert build_tool_usage_index([]) is None


def test_index_truncates_long_questions():
    index = ToolUsageIndex([{"query": "q" * 500, "calls": [{"name": "t"}]}])
    assert len(index.questions("t")[0]) == ToolUsageIndex.MAX_QUESTION_CHARS


def test_usage_note():
    assert usage_note([]) == ""
    assert usage_note(["a?", "b?"]) == '\nSolved questions this tool answered: "a?" | "b?"'


class _Provider:
    def __init__(self, tools):
        self.tools = tools

    async def get_all_tools(self):
        return self.tools


def _tool(name, description):
    return StructuredTool.from_function(func=lambda: "ok", name=name, description=description)


def test_provider_appends_the_note_per_task_and_keeps_wrappers_stable():
    raw = _tool("shop_get_sales", "Get sales.")
    provider = RecordingScopedToolProvider(_Provider([raw]))
    plain = asyncio.run(provider.get_all_tools())[0]
    assert plain.description == "Get sales."

    index = build_tool_usage_index(SAMPLES)
    provider.tool_usage = lambda name: index.questions(name, exclude_query="Total sales of store 7?")
    noted = asyncio.run(provider.get_all_tools())[0]
    assert (
        noted.description == 'Get sales.\nSolved questions this tool answered: "Least liked store in 2019?"'
    )
    assert noted.func.__doc__ == noted.description
    assert asyncio.run(provider.get_all_tools())[0] is noted  # same task: same wrapper

    provider.tool_usage = None
    assert asyncio.run(provider.get_all_tools())[0].description == "Get sales."


def test_corpus_loads_caps_2_to_4_of_the_domain_only_when_on():
    loaded = []

    class _Loader:
        def __init__(self, source):
            pass

        def load_domain(self, task_id, domain):
            loaded.append((task_id, domain))
            return [_sample(f"q{task_id}", "t")]

    cfg = replace(PRESETS["cap2"], demo_data=__file__)  # cap2 keeps it off
    assert load_tool_usage_corpus(cfg, domain="books", loader_factory=_Loader) is None
    on = replace(PRESETS["cap3"], demo_data=__file__)
    corpus = load_tool_usage_corpus(on, domain="books", loader_factory=_Loader)
    assert loaded == [(2, "books"), (3, "books"), (4, "books")]
    assert [s["dialogue"]["turns"][0]["query"] for s in corpus] == ["q2", "q3", "q4"]
