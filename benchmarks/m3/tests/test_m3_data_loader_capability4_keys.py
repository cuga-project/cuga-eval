"""Regression coverage for M3DataLoader's capability_4 key-name fallback.

Different VAKRA exports use different key names for the same shape:
small_train.zip uses top-level "ground_truth" (list) with per-turn
"gold_sequence"; capability_4_multiturn_policy_sampled.zip uses top-level
"output" (list) with per-turn "sequence". load_domain() only recognized the
former before the fix in commit 49e8506 — gold_sequence/answer_per_turn/
tool_response_per_turn came out silently empty for every capability_4 sample.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.m3.m3_data_loader import M3DataLoader

pytestmark = pytest.mark.sanity


def _write_domain(base: Path, capability_dir: str, domain: str, input_data: list, output_data: dict) -> None:
    """``input_data`` is the list of samples; ``output_data`` is a single
    sample's gold dict (matched by uuid), automatically wrapped in the list
    the loader expects for the output file."""
    cap_dir = base / capability_dir
    (cap_dir / "input").mkdir(parents=True, exist_ok=True)
    (cap_dir / "output").mkdir(parents=True, exist_ok=True)
    (cap_dir / "input" / f"{domain}.json").write_text(json.dumps(input_data))
    (cap_dir / "output" / f"{domain}.json").write_text(json.dumps([output_data]))


def test_output_sequence_keys_are_accepted_like_ground_truth_gold_sequence(tmp_path: Path):
    sample = {
        "uuid": "u1",
        "domain": "airline",
        "dialogue": {"turns": [{"turn_id": 0, "query": "how many seats?"}]},
    }
    # capability_4-style: top-level "output", per-turn "sequence".
    gold = {
        "uuid": "u1",
        "output": [
            {
                "turn_id": 0,
                "answer": "42",
                "sequence": {
                    "tool_call": [[{"name": "get_seats", "arguments": {}}]],
                    "tool_response": [[{"seats": 42}]],
                },
            }
        ],
    }
    _write_domain(tmp_path, "capability_4_multiturn", "airline", [sample], gold)

    loader = M3DataLoader(str(tmp_path))
    merged = loader.load_domain(4, "airline")

    assert len(merged) == 1
    out = merged[0]["expected_output"]
    assert out["answer_per_turn"] == ["42"]
    assert out["gold_sequence"] == [[{"name": "get_seats", "arguments": {}}]]
    assert out["tool_response_per_turn"] == [[{"seats": 42}]]


def test_turn_with_no_matching_gold_entry_gets_empty_arrays(tmp_path: Path):
    sample = {
        "uuid": "u1",
        "domain": "airline",
        "dialogue": {
            "turns": [
                {"turn_id": 0, "query": "first"},
                {"turn_id": 1, "query": "second, no gold for this one"},
            ]
        },
    }
    gold = {
        "uuid": "u1",
        "output": [
            {
                "turn_id": 0,
                "answer": "first answer",
                "sequence": {"tool_call": [], "tool_response": []},
            }
            # turn_id 1 deliberately has no matching gold entry.
        ],
    }
    _write_domain(tmp_path, "capability_4_multiturn", "airline", [sample], gold)

    loader = M3DataLoader(str(tmp_path))
    merged = loader.load_domain(4, "airline")

    out = merged[0]["expected_output"]
    assert out["answer_per_turn"] == ["first answer", None]
    assert out["gold_sequence"] == [[], []]
    assert out["tool_response_per_turn"] == [[], []]


def test_ground_truth_gold_sequence_keys_still_work(tmp_path: Path):
    """small_train.zip's key names — unaffected by the output/sequence fallback."""
    sample = {
        "uuid": "u1",
        "domain": "hockey",
        "dialogue": {"turns": [{"turn_id": 0, "query": "who won?"}]},
    }
    gold = {
        "uuid": "u1",
        "ground_truth": [
            {
                "turn_id": 0,
                "answer": "the home team",
                "gold_sequence": {
                    "tool_call": [[{"name": "get_score", "arguments": {}}]],
                    "tool_response": [[{"score": "3-1"}]],
                },
            }
        ],
    }
    _write_domain(tmp_path, "capability_2_dashboard_apis", "hockey", [sample], gold)

    loader = M3DataLoader(str(tmp_path))
    merged = loader.load_domain(2, "hockey")

    out = merged[0]["expected_output"]
    assert out["answer_per_turn"] == ["the home team"]
    assert out["gold_sequence"] == [[{"name": "get_score", "arguments": {}}]]
