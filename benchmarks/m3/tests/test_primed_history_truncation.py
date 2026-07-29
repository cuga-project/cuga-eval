"""Tests for M3_PRIMED_HISTORY_MAX_CHARS (eval_m3._truncate_primed_answer).

Multi-turn dialogue priming replays each prior turn's ground-truth answer
verbatim. A few cap4 answers are megabytes wide and get the whole request
rejected before the model runs. These tests pin the flag's default-off
behaviour, the truncation itself, and the explicit marker.
"""

import importlib

import pytest

eval_m3 = importlib.import_module("benchmarks.m3.eval_m3")


@pytest.fixture(autouse=True)
def _clear_flag(monkeypatch):
    monkeypatch.delenv("M3_PRIMED_HISTORY_MAX_CHARS", raising=False)


def test_default_is_off():
    """Absent the env var the feature must not engage at all - the current
    300-task run depends on this staying inert."""
    assert eval_m3._primed_history_max_chars() == 0
    huge = "x" * 10_000_000
    assert eval_m3._truncate_primed_answer(huge) == huge


def test_explicit_zero_is_off(monkeypatch):
    monkeypatch.setenv("M3_PRIMED_HISTORY_MAX_CHARS", "0")
    huge = "x" * 5_000
    assert eval_m3._truncate_primed_answer(huge) == huge


@pytest.mark.parametrize("bad", ["", "off", "1.5", "none"])
def test_non_integer_is_off_not_a_crash(monkeypatch, bad):
    """A typo'd flag must degrade to off, never take down a 300-task run."""
    monkeypatch.setenv("M3_PRIMED_HISTORY_MAX_CHARS", bad)
    assert eval_m3._primed_history_max_chars() == 0


def test_negative_is_clamped_to_off(monkeypatch):
    monkeypatch.setenv("M3_PRIMED_HISTORY_MAX_CHARS", "-100")
    assert eval_m3._primed_history_max_chars() == 0


def test_under_limit_is_untouched(monkeypatch):
    monkeypatch.setenv("M3_PRIMED_HISTORY_MAX_CHARS", "1000")
    text = "y" * 999
    assert eval_m3._truncate_primed_answer(text) == text


def test_exactly_at_limit_is_untouched(monkeypatch):
    monkeypatch.setenv("M3_PRIMED_HISTORY_MAX_CHARS", "1000")
    text = "y" * 1000
    assert eval_m3._truncate_primed_answer(text) == text


def test_over_limit_keeps_head_and_marks_the_cut(monkeypatch):
    monkeypatch.setenv("M3_PRIMED_HISTORY_MAX_CHARS", "100")
    text = "A" * 60 + "B" * 500
    out = eval_m3._truncate_primed_answer(text)

    # Head is preserved verbatim: a follow-up's referent ("it", "that paper")
    # lives in the first records far more often than the last.
    assert out.startswith("A" * 60 + "B" * 40)
    # The dropped tail is gone.
    assert "B" * 100 not in out
    # And the marker states the real numbers, not a vague ellipsis.
    assert "truncated: 460 of 560 characters" in out
    assert "partial extract, not the complete result" in out


def test_marker_forbids_the_completeness_claim(monkeypatch):
    """The groundedness rider bans calling a list complete/exhaustive. A
    silently-cut list would invite exactly that claim, so the marker has to say
    the extract is partial."""
    monkeypatch.setenv("M3_PRIMED_HISTORY_MAX_CHARS", "10")
    out = eval_m3._truncate_primed_answer("z" * 100)
    assert "not the complete result" in out


def test_realistic_cap4_payload_lands_under_the_gateway_ceiling(monkeypatch):
    """The measured ceiling sits between 1.05 MB (passes) and 1.81 MB (fails).
    A 100 KB cap must bring the worst real task (9.68 MB, authors
    840942187214-e8928dfedee1) well under it."""
    monkeypatch.setenv("M3_PRIMED_HISTORY_MAX_CHARS", "100000")
    worst = "q" * 9_683_549
    out = eval_m3._truncate_primed_answer(worst)
    assert len(out) < 105_000
    assert len(out) < 1_050_000  # below even the largest task that passes today


def test_read_fresh_each_call(monkeypatch):
    """Matches judge.py's convention: an in-process env change (A/B toggle,
    pytest fixture) must take effect immediately, not be cached at import."""
    text = "w" * 500
    monkeypatch.setenv("M3_PRIMED_HISTORY_MAX_CHARS", "0")
    assert eval_m3._truncate_primed_answer(text) == text
    monkeypatch.setenv("M3_PRIMED_HISTORY_MAX_CHARS", "100")
    assert eval_m3._truncate_primed_answer(text) != text
