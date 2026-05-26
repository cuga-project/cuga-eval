"""Keyword matching tests for evaluator metrics.

Tests cover standardized keyword matching semantics:
- OR alternatives with `|` separator
- Unicode/whitespace normalization
- Hyphen normalization
- Markdown punctuation handling
- Regex patterns with `re:` prefix
"""

import pytest

from benchmarks.bpo.metrics import EvaluationMetrics

pytestmark = pytest.mark.sanity


def test_keywords_match_hyphen_normalization():
    """Test that hyphens are normalized to spaces for matching."""
    predicted = "No APIs expose time to fill by source."
    result = EvaluationMetrics.keywords_match(predicted, ["time-to-fill", "source"])
    assert result["match_ratio"] == 1.0
    assert result["missing"] == []


def test_keywords_match_regex():
    """Test regex keyword support with re: prefix."""
    predicted = "Sorry — cannot provide that."
    result = EvaluationMetrics.keywords_match(predicted, ["re:can't|cannot|unable"])
    assert result["match_ratio"] == 1.0
    assert result["missing"] == []


def test_keywords_match_markdown_punctuation():
    """Test that markdown emphasis characters are stripped."""
    predicted = "On average, similar postings attract **73 candidates**."
    result = EvaluationMetrics.keywords_match(predicted, ["73", "candidates"])
    assert result["match_ratio"] == 1.0
    assert result["missing"] == []


# Standardized OR alternatives tests
def test_keywords_match_or_alternatives_first_match():
    """Test OR alternatives where first alternative matches."""
    predicted = "CyberSec Jobs with 67%"
    result = EvaluationMetrics.keywords_match(predicted, ["67%|67 %|67"])
    assert result["match_ratio"] == 1.0
    assert result["missing"] == []


def test_keywords_match_or_alternatives_second_match():
    """Test OR alternatives where second alternative matches."""
    predicted = "CyberSec Jobs with 67 %"
    result = EvaluationMetrics.keywords_match(predicted, ["67%|67 %|67"])
    assert result["match_ratio"] == 1.0
    assert result["missing"] == []


def test_keywords_match_or_alternatives_third_match():
    """Test OR alternatives where third alternative matches."""
    predicted = "The value is 67 percent."
    result = EvaluationMetrics.keywords_match(predicted, ["67%|67 %|67"])
    assert result["match_ratio"] == 1.0
    assert result["missing"] == []


def test_keywords_match_or_alternatives_no_match():
    """Test OR alternatives where none match."""
    predicted = "The value is 68%."
    result = EvaluationMetrics.keywords_match(predicted, ["67%|67 %|67"])
    assert result["match_ratio"] == 0.0
    assert result["missing"] == ["67%|67 %|67"]


def test_keywords_match_multiple_or_keywords():
    """Test multiple keywords with OR alternatives (standardized task 2)."""
    predicted = "Please provide the requisition ID."
    keywords = ["requisition|req", "ID|id|identifier", "missing|share|provide"]
    result = EvaluationMetrics.keywords_match(predicted, keywords)
    assert result["match_ratio"] == 1.0
    assert result["missing"] == []


def test_keywords_match_case_insensitive():
    """Test case-insensitive matching."""
    predicted = "LINKEDIN is the top source."
    result = EvaluationMetrics.keywords_match(predicted, ["LinkedIn"])
    assert result["match_ratio"] == 1.0
    assert result["missing"] == []


def test_keywords_match_unicode_narrow_space():
    """Test unicode narrow no-break space (\\u202f) normalization."""
    # Standard check_keywords replaces \u202f with regular space
    predicted = "The value is 67\u202f%"  # narrow no-break space
    result = EvaluationMetrics.keywords_match(predicted, ["67%|67 %|67"])
    # After normalization, 67\u202f% should become "67 %" matching the second alt
    assert result["match_ratio"] == 1.0
    assert result["missing"] == []


def test_keywords_match_partial_match_in_word():
    """Test that keyword matching works for substrings."""
    predicted = "Historical hiring success data was used."
    result = EvaluationMetrics.keywords_match(predicted, ["Historical hiring success data"])
    assert result["match_ratio"] == 1.0
    assert result["missing"] == []


def test_keywords_match_empty_keywords():
    """Test that empty keyword list returns perfect match."""
    predicted = "Any output text."
    result = EvaluationMetrics.keywords_match(predicted, [])
    assert result["match_ratio"] == 1.0
    assert result["total_keywords"] == 0
