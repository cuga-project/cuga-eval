"""Pure answer functions: canonicalize (ported self-test table), normalize, extract."""

import pytest

from benchmarks.m3.adapter.config import PRESETS
from benchmarks.m3.adapter.final_answer import (
    canonicalize_final_answer,
    extract_values_answer,
    is_giveup,
    looks_like_failure,
    make_final_answer_fn,
    normalize_answer,
    strip_channel_tokens,
)

pytestmark = pytest.mark.sanity

# The observed answer shapes the vendored canonicalizer was validated on.
CANONICALIZE_CASES = [
    ("[[New Hampshire]]", "New Hampshire"),
    ('[["New Hampshire"]]', "New Hampshire"),
    ("[[The Aristocats]]", "The Aristocats"),
    ("[[Stephen J. Anderson]]", "Stephen J. Anderson"),
    ("[[736]]", "736"),
    ("[[0.18197691557631693]]", "0.18197691557631693"),
    ("[[101 Dalmatians], [The Aristocats]]", "101 Dalmatians, The Aristocats"),
    ('[["Charles Judels"],["Christian Rub"]]', "Charles Judels, Christian Rub"),
    ("[[9], [46], [335]]", "9, 46, 335"),
    ("[[?]][[66524]]", "66524"),
    ("Answer: [[66524]]", "66524"),
    ("Moana", "Moana"),
    ("66524", "66524"),
    ("I can not answer", "I can not answer"),
    ("", ""),
]


@pytest.mark.parametrize("text,want", CANONICALIZE_CASES)
def test_canonicalize_table(text, want):
    assert canonicalize_final_answer(text) == want


def test_canonicalize_idempotent():
    for text, _ in CANONICALIZE_CASES:
        once = canonicalize_final_answer(text)
        assert canonicalize_final_answer(once) == once


def test_strip_channel_tokens():
    assert strip_channel_tokens("<|channel|>final<|message|>42") == "final42"
    assert strip_channel_tokens("plain") == "plain"
    assert strip_channel_tokens(None) == ""


def test_normalize_answer():
    assert normalize_answer("**36526.0**") == "36526"
    assert normalize_answer("[1.0, 2.5, 3.0]") == "[1, 2.5, 3]"
    assert normalize_answer("IMPOSSIBLE[1,2,3]") == "[1,2,3]"
    assert normalize_answer("IMPOSSIBLE") == "IMPOSSIBLE"  # kept when it's all there is
    assert normalize_answer("`quoted`") == "quoted"


def test_extract_values_answer():
    assert extract_values_answer('{"count": 0}') == "0"
    assert extract_values_answer('{"avg": 1.23}') == "1.23"
    assert extract_values_answer('[{"lat": 1.0, "lon": 2.5}, {"lat": 3.5, "lon": 4.5}]') == (
        "[[1, 2.5], [3.5, 4.5]]"
    )
    assert extract_values_answer("plain text") == "plain text"
    assert extract_values_answer("[1, 2, 3]") == "[1, 2, 3]"  # list of scalars untouched


def test_giveup_and_failure_detectors():
    assert is_giveup("I can not answer.")
    assert is_giveup("Sorry, I'm unable to find that")
    assert not is_giveup("The answer is 42")
    assert looks_like_failure("IMPOSSIBLE")
    assert looks_like_failure("IMPOSSIBLEIMPOSSIBLE")
    assert looks_like_failure("n/a")
    assert looks_like_failure("0")
    assert not looks_like_failure("42")
    assert not looks_like_failure("")  # empty handled by the gate corrections


def test_make_final_answer_fn_honors_canonicalize_flag():
    on = make_final_answer_fn(PRESETS["cap2"])  # canonicalize=True
    off = make_final_answer_fn(PRESETS["cap4_v3wx"])  # canonicalize=False
    assert on("[[42]]") == "42"
    assert off("[[42]]") == "[[42]]"
    # both always strip harmony tokens
    assert on("<|channel|>[[42]]") == "42"
    assert off("<|channel|>x") == "x"
    # refusal untouched either way
    assert on("I can not answer.") == "I can not answer."


def test_normalize_decodes_unicode_escapes_copied_from_tool_json():
    assert normalize_answer("\\u9b45\\u65cf, MX3") == "\u9b45\u65cf, MX3"
    assert normalize_answer("Jos\\u00e9 Mourinho") == "Jos\u00e9 Mourinho"
    assert normalize_answer("\\ud83d\\ude00 ok") == "\U0001f600 ok"  # surrogate pair
    assert normalize_answer("\\ud83d alone") == "\\ud83d alone"  # lone surrogate left as-is
    assert normalize_answer("C:\\users\\x") == "C:\\users\\x"  # not an escape
    assert normalize_answer("already 魅族") == "already 魅族"


def test_normalize_strips_trailing_source_citation():
    assert normalize_answer("Charles. Source: hockey_get_players_by_position_no_shoot_catch.") == "Charles"
    assert normalize_answer("42. Sources: tool_a, tool_b") == "42"
    # mid-answer "Source" is content, not a citation
    assert normalize_answer("The Source of the Nile") == "The Source of the Nile"
    # citation-only answers are preserved, never emptied
    assert normalize_answer("Source: tool_a.") == "Source: tool_a"


def test_markdown_strip_keeps_underscores_inside_values():
    """An underscore between letters is part of a value, not emphasis: stripping it turned
    "udp_protocol" into "udpprotocol" and the groundedness judge failed the answer for it."""
    assert normalize_answer("udp_protocol, first_name") == "udp_protocol, first_name"
    assert normalize_answer("Ma\u00eetre_d, x__y, 2019_20") == "Ma\u00eetre_d, x__y, 2019_20"
    assert normalize_answer("_italic_ and __bold__ and **x** and `code`") == "italic and bold and x and code"
    assert canonicalize_final_answer('[["udp_protocol"], ["net"]]') == "udp_protocol, net"
    assert canonicalize_final_answer("**udp_protocol**") == "udp_protocol"


def test_canonicalize_drops_escaped_quotes_with_their_backslash():
    """JSON written as text (``\\"KIM KI-DUK, ranked\\"``) lost only its quotes and kept the backslashes."""
    raw = '[[\\"KIM KI-DUK, ranked\\"], [\\"MICHAEL POWELL, ranked\\"]]'
    assert canonicalize_final_answer(raw) == "KIM KI-DUK, ranked, MICHAEL POWELL, ranked"
