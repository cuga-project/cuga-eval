"""Tests for Vakra → Langfuse score push and console logging helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip(
    "evaluator",
    reason="M3 Vakra vendor not installed; run ./setup_m3.sh to enable this test.",
)
pytest.importorskip(
    "benchmark.mcp_client",
    reason="M3 Vakra vendor not installed; run ./setup_m3.sh to enable this test.",
)

from benchmarks.m3.m3_vakra_score import (  # noqa: E402
    _format_judge_scores_compact,
    _last_turn_judge_scores,
    log_vakra_task_scores,
    push_vakra_scores_to_langfuse,
)


def _sample_vakra(*, exactmatch=0.0, answer=1.0, groundedness=0.0):
    return {
        "score": groundedness,
        "details": {
            "per_turn": [
                {
                    "turn_id": 1,
                    "score": groundedness,
                    "metadata": {
                        "exactmatch_score": exactmatch,
                        "answer_score": answer,
                        "groundedness_score": groundedness,
                    },
                }
            ]
        },
    }


def test_last_turn_judge_scores_extracts_all_three():
    scores = _last_turn_judge_scores(_sample_vakra())
    assert scores == {"exactmatch": 0.0, "answer": 1.0, "groundedness": 0.0}
    assert _format_judge_scores_compact(scores) == "exactmatch=0.0 answer=1.0 groundedness=0.0"


def test_last_turn_judge_scores_skips_none():
    vakra = _sample_vakra(exactmatch=1.0, answer=None, groundedness=1.0)
    vakra["details"]["per_turn"][0]["metadata"]["answer_score"] = None
    scores = _last_turn_judge_scores(vakra)
    assert scores == {"exactmatch": 1.0, "groundedness": 1.0}


def test_push_vakra_scores_to_langfuse_creates_five_scores():
    results = [
        {
            "trace_id": "trace-abc",
            "match_rate": 1.0,
            "success": True,
            "vakra": _sample_vakra(exactmatch=0.0, answer=1.0, groundedness=1.0),
        }
    ]
    mock_langfuse = MagicMock()
    with patch("langfuse.get_client", return_value=mock_langfuse):
        pushed = push_vakra_scores_to_langfuse(results)

    assert pushed == 1
    assert mock_langfuse.create_score.call_count == 5
    names = {call.kwargs["name"] for call in mock_langfuse.create_score.call_args_list}
    assert names == {
        "m3_success",
        "m3_dialogue_score",
        "m3_exactmatch_score",
        "m3_answer_score",
        "m3_groundedness_score",
    }
    mock_langfuse.flush.assert_called_once()


def test_push_vakra_scores_skips_results_without_trace_id():
    results = [{"vakra": _sample_vakra()}]
    mock_langfuse = MagicMock()
    with patch("langfuse.get_client", return_value=mock_langfuse):
        assert push_vakra_scores_to_langfuse(results) == 0
    mock_langfuse.create_score.assert_not_called()


def test_log_vakra_task_scores_emits_judge_breakdown(caplog):
    import logging

    caplog.set_level(logging.INFO)
    results = [
        {
            "uuid": "uuid-a",
            "match_rate": 0.0,
            "vakra": _sample_vakra(exactmatch=0.0, answer=1.0, groundedness=0.0),
        }
    ]
    with patch("benchmarks.m3.m3_vakra_score.logger") as mock_logger:
        log_vakra_task_scores(results)
        msg = mock_logger.info.call_args[0][0]
    assert "uuid-a" in msg
    assert "dialogue=0.00" in msg
    assert "exactmatch=0.0 answer=1.0 groundedness=0.0" in msg
