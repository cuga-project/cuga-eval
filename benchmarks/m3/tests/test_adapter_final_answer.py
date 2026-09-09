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


def test_normalize_strips_trailing_source_citation():
    assert normalize_answer("Charles. Source: hockey_get_players_by_position_no_shoot_catch.") == "Charles"
    assert normalize_answer("42. Sources: tool_a, tool_b") == "42"
    # mid-answer "Source" is content, not a citation
    assert normalize_answer("The Source of the Nile") == "The Source of the Nile"
    # citation-only answers are preserved, never emptied (underscores go via the
    # ported markdown-emphasis strip, as in the original normalizer)
    assert normalize_answer("Source: tool_a.") == "Source: toola"
