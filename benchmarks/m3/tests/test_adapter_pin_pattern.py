"""Bind-time pinning of cap1's generic data tools (shortlist_pin_pattern) when a catalog exceeds the cap."""

import asyncio
import re
from types import SimpleNamespace

import pytest

from benchmarks.m3.adapter import shortlist as sl
from benchmarks.m3.adapter.config import CAP1_DATA_TOOLS_PATTERN, PRESETS, resolve_adapter_config

pytestmark = pytest.mark.sanity

GENERIC = [  # every generic name the cap1 train ground-truth chains use
    "initialize_active_data",
    "filter_data",
    "select_data_equal_to",
    "retrieve_data",
    "aggregate_data",
    "truncate",
    "compute_data_count",
    "sort_data",
    "sort_data_descending",
    "select_unique_values",
    "Calculator",
    "select_data_greater_than",
    "select_data_like",
    "sort_data_ascending",
    "select_data_less_than",
    "compute_data_mean",
    "transform_data",
    "transform_data_to_datetime_part",
    "compute_data_sum",
    "compute_data_max",
    "get_data",
]
SPECIFIC = [
    "get_PlayerInfo_PlayerNames",
    "get_Country_Country_Names",
    "get_data_car_names",
    "get_Paper_Titles",
]


def test_pattern_matches_the_generic_family_and_no_domain_tool():
    rx = re.compile(CAP1_DATA_TOOLS_PATTERN)
    assert all(rx.fullmatch(n) for n in GENERIC)
    assert not any(rx.fullmatch(n) for n in SPECIFIC)


def test_pinned_strategy_keeps_pattern_tools_ahead_of_the_ranked_rest(monkeypatch):
    from cuga.backend.cuga_graph.nodes.cuga_lite.shortlister.base import (
        ShortlistCandidate,
        ShortlistRequest,
        ShortlistResult,
    )

    names = ["get_A", "get_B", "filter_data", "get_C", "retrieve_data", "select_data_equal_to"]

    class _Inner:  # ranks the domain tools first, the generic ones last
        async def shortlist(self, request):
            order = ["get_A", "get_B", "get_C", "filter_data", "retrieve_data", "select_data_equal_to"]
            return ShortlistResult(
                candidates=[ShortlistCandidate(name=n, score=1.0 - i / 10) for i, n in enumerate(order)]
            )

    strat = sl.MiniLMPinnedStrategy()
    monkeypatch.setattr(strat, "_ensure_inner", lambda: _Inner())
    monkeypatch.setattr(sl.MiniLMPinnedStrategy, "pin_retrievers", False)
    monkeypatch.setattr(sl.MiniLMPinnedStrategy, "pin_pattern", CAP1_DATA_TOOLS_PATTERN)
    tools = [SimpleNamespace(name=n, description="", args_schema=None) for n in names]
    req = ShortlistRequest(query="q?", tools=tools, apps=[], top_k=4, llm=None)
    got = [c.name for c in asyncio.run(strat.shortlist(req)).candidates]
    assert got == ["filter_data", "retrieve_data", "select_data_equal_to", "get_A"]  # 3 pinned + best ranked


def test_the_knob_selects_the_pinned_strategy_and_no_preset_pins_yet(monkeypatch):
    assert all(PRESETS[p].shortlist_pin_pattern == "" for p in ("cap1", "cap2", "cap3", "cap4", "off"))
    cfg = resolve_adapter_config("cap1", env={"M3_ADAPTER_SHORTLIST_PIN_PATTERN": CAP1_DATA_TOOLS_PATTERN})
    assert cfg.shortlist_pin_pattern == CAP1_DATA_TOOLS_PATTERN
    monkeypatch.setattr(sl, "prewarm_embedding_backend", lambda cfg: True)
    built = sl.build_shortlister(cfg)
    assert built.strategy == sl.PINNED_STRATEGY_PATH and built.top_k == 128
    assert sl.MiniLMPinnedStrategy.pin_pattern == CAP1_DATA_TOOLS_PATTERN
    assert sl.MiniLMPinnedStrategy.pin_retrievers is False
    assert sl.build_shortlister(PRESETS["cap1"]).strategy == "embedding"  # the preset as shipped: unchanged


def test_force_distinct_false_rewrites_only_cap1_data_tools():
    from benchmarks.m3.adapter.recording import without_distinct

    assert without_distinct("retrieve_data", {"key_name": "x", "distinct": True}) == {
        "key_name": "x",
        "distinct": False,
    }
    assert without_distinct("compute_data_count", {"distinct": "true"}) == {"distinct": False}
    assert without_distinct("aggregate_data", {"distinct": False}) is None  # already False: untouched
    assert without_distinct("retrieve_data", {"key_name": "x"}) is None  # no distinct argument
    assert without_distinct("get_PlayerInfo_PlayerNames", {"distinct": True}) is None  # not a data tool
    assert PRESETS["cap1"].force_distinct_false is False  # opt-in until the A/B
