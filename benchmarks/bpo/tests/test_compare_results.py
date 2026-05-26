"""Tests for compare_results.py metrics computation and report generation.

Covers:
- Cumulative-to-per-task delta conversion for tokens/LLM calls
- Per-task detail computation with metadata
- pass@N and pass^N metrics
- Summary footer (no majority metric)
- Backward compatibility when metadata is missing
- Format helpers (format_tokens_k, format_duration, format_llm_calls)
"""

import pytest

from benchmarks.bpo.compare_results import (
    compute_metrics,
    format_duration,
    format_llm_calls,
    format_tokens_k,
    generate_per_task_details,
)

pytestmark = pytest.mark.sanity


def _make_result(task_scores, cumulative_tokens=None, cumulative_llm=None, durations=None):
    """Build a mock evaluation result dict.

    Args:
        task_scores: list of 0/1 per task.
        cumulative_tokens: list of cumulative token counts (same length as task_scores).
        cumulative_llm: list of cumulative LLM call counts.
        durations: list of per-task durations.
    """
    detailed = []
    for i, score in enumerate(task_scores):
        meta = {}
        if cumulative_tokens is not None:
            meta["total_tokens"] = cumulative_tokens[i]
            meta["total_cache_input_tokens"] = 0
        if cumulative_llm is not None:
            meta["total_llm_calls"] = cumulative_llm[i]
        if durations is not None:
            meta["duration"] = durations[i]
        detailed.append(
            {
                "task_id": i + 1,
                "task_final_score": score,
                "metadata": meta if meta else {},
            }
        )
    passes = sum(task_scores)
    return {
        "total_tasks": len(task_scores),
        "final_score_passes": passes,
        "final_score_accuracy": passes / len(task_scores) if task_scores else 0,
        "detailed_results": detailed,
    }


class TestCumulativeDeltaConversion:
    """Verify cumulative metadata is converted to per-task deltas."""

    def test_tokens_are_per_task_not_cumulative(self):
        result = _make_result(
            [1, 1, 0],
            cumulative_tokens=[1000, 3500, 5000],
            cumulative_llm=[3, 8, 12],
        )
        metrics = compute_metrics([result])
        details = metrics["per_task_details"]

        assert details[0]["mean_tokens"] == 1000  # 1000 - 0
        assert details[1]["mean_tokens"] == 2500  # 3500 - 1000
        assert details[2]["mean_tokens"] == 1500  # 5000 - 3500

    def test_llm_calls_are_per_task_deltas(self):
        result = _make_result(
            [1, 1, 0],
            cumulative_llm=[3, 8, 12],
        )
        metrics = compute_metrics([result])
        details = metrics["per_task_details"]

        assert details[0]["mean_llm_calls"] == 3  # 3 - 0
        assert details[1]["mean_llm_calls"] == 5  # 8 - 3
        assert details[2]["mean_llm_calls"] == 4  # 12 - 8

    def test_duration_is_not_delta(self):
        """Duration is already per-task, should not be subtracted."""
        result = _make_result(
            [1, 0],
            durations=[2.5, 3.1],
        )
        metrics = compute_metrics([result])
        details = metrics["per_task_details"]

        assert details[0]["mean_duration"] == 2.5
        assert details[1]["mean_duration"] == 3.1

    def test_deltas_averaged_across_runs(self):
        """With 2 runs, per-task values should be averaged."""
        run1 = _make_result([1, 0], cumulative_tokens=[1000, 3000])
        run2 = _make_result([1, 1], cumulative_tokens=[2000, 5000])
        metrics = compute_metrics([run1, run2])
        details = metrics["per_task_details"]

        # Task 1: run1=1000, run2=2000 -> mean=1500
        assert details[0]["mean_tokens"] == 1500
        # Task 2: run1=2000 (3000-1000), run2=3000 (5000-2000) -> mean=2500
        assert details[1]["mean_tokens"] == 2500

    def test_summary_tokens_uses_last_cumulative(self):
        """Summary mean_tokens should be the run total (last cumulative value)."""
        run1 = _make_result([1, 1], cumulative_tokens=[1000, 5000])
        run2 = _make_result([1, 0], cumulative_tokens=[2000, 7000])
        metrics = compute_metrics([run1, run2])

        # mean_tokens = (5000 + 7000) / 2 = 6000
        assert metrics["mean_tokens"] == 6000


class TestPassMetrics:
    """Verify pass@N, pass^N, and no majority metric."""

    def test_pass_at_n(self):
        """pass@N: fraction of tasks where at least one run passed."""
        run1 = _make_result([1, 0, 0])
        run2 = _make_result([0, 1, 0])
        metrics = compute_metrics([run1, run2])

        # Tasks 1 and 2 each have at least one pass -> 2/3
        assert metrics["pass_at_n"] == pytest.approx(2 / 3)

    def test_pass_pow_n(self):
        """pass^N: fraction of tasks where all runs passed."""
        run1 = _make_result([1, 1, 0])
        run2 = _make_result([1, 0, 0])
        metrics = compute_metrics([run1, run2])

        # Only task 1 passes both -> 1/3
        assert metrics["pass_pow_n"] == pytest.approx(1 / 3)

    def test_no_majority_metric(self):
        """majority_pass_n should not exist in metrics."""
        run1 = _make_result([1, 0])
        metrics = compute_metrics([run1])
        assert "majority_pass_n" not in metrics


class TestBackwardCompatibility:
    """Verify graceful handling when metadata is missing."""

    def test_missing_metadata_returns_none(self):
        result = _make_result([1, 0])
        # No cumulative_tokens or durations passed -> metadata is empty
        metrics = compute_metrics([result])
        details = metrics["per_task_details"]

        assert details[0]["mean_tokens"] is None
        assert details[0]["mean_duration"] is None
        assert details[0]["mean_llm_calls"] is None

    def test_empty_results(self):
        metrics = compute_metrics([])
        assert metrics["mean_accuracy"] == 0
        assert metrics["per_task_details"] == []
        assert metrics["mean_tokens"] == 0


class TestPerTaskDetailsOutput:
    """Test the per-task details report generation."""

    def test_summary_footer_has_average_not_majority(self):
        run1 = _make_result([1, 0, 1])
        metrics = compute_metrics([run1])
        model_data = {("test-model", "agent"): {"policies": metrics}}
        output = generate_per_task_details(model_data, compare_policies=False)

        assert "Average" in output
        assert "majority" not in output.lower()

    def test_dashes_for_missing_metadata(self):
        run1 = _make_result([1, 0])
        metrics = compute_metrics([run1])
        model_data = {("test-model", "agent"): {"policies": metrics}}
        output = generate_per_task_details(model_data, compare_policies=False)

        assert "--" in output


class TestFormatHelpers:
    """Test format_tokens_k, format_duration, format_llm_calls."""

    def test_format_tokens_k_thousands(self):
        assert format_tokens_k(1500) == "1.5K"
        assert format_tokens_k(26100) == "26.1K"
        assert format_tokens_k(450000) == "450K"

    def test_format_tokens_k_small(self):
        assert format_tokens_k(500) == "0.5K"

    def test_format_tokens_k_none(self):
        assert format_tokens_k(None) == "--"

    def test_format_duration(self):
        assert format_duration(3.6) == "3.6s"
        assert format_duration(0.5) == "0.5s"

    def test_format_duration_none(self):
        assert format_duration(None) == "--"

    def test_format_llm_calls(self):
        assert format_llm_calls(8) == "8"
        assert format_llm_calls(12.5) == "12"

    def test_format_llm_calls_none(self):
        assert format_llm_calls(None) == "--"
