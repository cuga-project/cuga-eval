"""Tests for scope-conditional retriever pinning in ToolShortlister.

The ported shortlister pinned every retriever tool to the FRONT of the
shortlist unconditionally, ahead of tools far more relevant to the query. That
is defensible only under a retriever-only policy, where retrievers are the sole
legal choice and must survive the top-k cut.

Measured cost of the unconditional version, from cap4_300_allguards: of 41
wrong-tool multi-turn failures, 22 called a retriever as their FIRST action -
most on tasks carrying no policy at all. Replaying the shortlister offline
showed the correct structured tool sat in the shortlist at median rank 4 while
the least specific tool in the catalog occupied position 1.
"""

import importlib

import pytest

eval_m3 = importlib.import_module("benchmarks.m3.eval_m3")


class _Tool:
    def __init__(self, name):
        self.name = name
        self.description = name.replace("_", " ")


def _catalog(n=60):
    return (
        [_Tool("dom_query_dom")]
        + [_Tool(f"dom_get_thing_{i}") for i in range(n)]
        + [_Tool("dom_get_count_mountains_in_country")]
    )


QUERY = "how many mountains are in this country"


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    monkeypatch.delenv("M3_SHORTLIST_PIN_RETRIEVERS", raising=False)


def _shortlist(scope, top_k=5, tools=None):
    tools = tools or _catalog()
    sl = eval_m3.ToolShortlister(top_k=top_k)
    sl.encode_tools(tools)
    sl.set_scope_hint(scope)
    return [t.name for t in sl.shortlist(QUERY, tools)]


def test_unscoped_puts_the_relevant_tool_first():
    """The whole point: with no retriever policy in force, relevance decides."""
    names = _shortlist("all")
    assert names[0] == "dom_get_count_mountains_in_country"


def test_unscoped_does_not_force_the_retriever_into_the_shortlist():
    names = _shortlist("all")
    assert "dom_query_dom" not in names[:1]


def test_retriever_only_still_pins():
    """Under retriever_only the retriever is the only legal tool, so it must
    survive the cut and lead."""
    names = _shortlist("retriever_only")
    assert names[0] == "dom_query_dom"


def test_no_retriever_scope_does_not_pin():
    """'no_retriever' forbids them outright - pinning would be actively wrong."""
    names = _shortlist("no_retriever")
    assert names[0] == "dom_get_count_mountains_in_country"


def test_env_override_restores_the_old_behaviour(monkeypatch):
    """Kept so the previous configuration remains reproducible for A/B."""
    monkeypatch.setenv("M3_SHORTLIST_PIN_RETRIEVERS", "always")
    assert _shortlist("all")[0] == "dom_query_dom"


def test_small_catalog_is_returned_untouched():
    """At or below top_k the shortlister is a no-op, in every mode."""
    tools = _catalog(n=2)
    for scope in ("all", "retriever_only"):
        assert len(_shortlist(scope, top_k=40, tools=tools)) == len(tools)


def test_respects_top_k():
    for scope in ("all", "retriever_only"):
        assert len(_shortlist(scope, top_k=5)) == 5


def test_ordering_is_by_descending_relevance():
    """Not just the first slot - the whole list should be ranked, so the model
    reads better candidates earlier."""
    tools = [
        _Tool("dom_get_count_mountains_in_country"),
        _Tool("dom_get_weather_forecast"),
        _Tool("dom_get_mountain_height_by_name"),
    ] + [_Tool(f"dom_get_thing_{i}") for i in range(50)]
    names = _shortlist("all", top_k=3, tools=tools)
    assert "mountain" in names[0]
