"""Cache token extraction from Langfuse trace payloads (usageDetails)."""

from benchmarks.helpers.sdk_eval_helpers import (
    _find_generation_observations,
    _sum_generation_cache_tokens_from_trace,
)


def test_sum_cache_reads_usage_details():
    trace = {
        "observations": [
            {
                "type": "GENERATION",
                "id": "a",
                "usage": {"total": 100},
                "usageDetails": {"input_cache_read": 11776},
            },
            {
                "type": "GENERATION",
                "id": "b",
                "usage": {"total": 200, "input_cache_read": 500},
                "usageDetails": {"input_cache_read": 11776},
            },
            {"type": "SPAN", "id": "c"},
        ]
    }
    assert _sum_generation_cache_tokens_from_trace(trace) == 11776 + 11776
    assert len(_find_generation_observations(trace)) == 2
