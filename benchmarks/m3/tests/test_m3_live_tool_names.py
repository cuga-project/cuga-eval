"""Live MCP tool-name matching: the case cuga's registry drops (``..._shootCatch`` -> ``..._shootcatch``)."""

import os

import pytest

# m3_vakra_score imports this repo's Vakra evaluator: its judges are built at import time and need a
# key (none is called here), and it needs the vendor checkout (`./setup_m3.sh`; absent in CI).
os.environ.setdefault("JUDGE_API_KEY", "test-key-not-used")  # noqa: S105
try:
    from benchmarks.m3.m3_vakra_score import _match_live_name
except ImportError as exc:  # no vendor checkout
    pytest.skip(f"M3 Vakra vendor not installed ({exc}); run ./setup_m3.sh", allow_module_level=True)

pytestmark = pytest.mark.sanity

LIVE = ["get_goalies_born_in_year_with_null_shootCatch", "get_players", "get_Dup", "get_DUP"]


def test_registry_lowercased_names_resolve_to_the_live_spelling():
    assert _match_live_name("hockey_get_goalies_born_in_year_with_null_shootcatch", LIVE) == LIVE[0]
    assert _match_live_name("get_goalies_born_in_year_with_null_shootcatch", LIVE) == LIVE[0]


def test_same_case_matches_win_and_case_ambiguous_names_stay_unmapped():
    assert _match_live_name("hockey_get_players", LIVE) == "get_players"
    assert _match_live_name("get_players", LIVE) == "get_players"
    assert _match_live_name("get_dup", LIVE) is None
    assert _match_live_name("hockey_get_unknown", LIVE) is None
