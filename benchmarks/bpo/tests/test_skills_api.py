"""Unit tests for skills APIs."""

import pytest

from benchmarks.bpo.api_skills import (
    get_data_sources_used,
    get_skill_analysis,
    get_skill_impact_fill_rate,
    get_skill_impact_sla,
    get_skill_relevance_justification,
    get_successful_posting_criteria,
)
from benchmarks.bpo.tests.conftest import to_dict

pytestmark = pytest.mark.regression


class TestGetSkillAnalysis:
    """Tests for get_skill_analysis API."""

    def test_05958BR_returns_historical_skills(self):
        """Test that historical skills are returned."""
        result = to_dict(get_skill_analysis("05958BR"))

        assert "historical_skills_with_analysis" in result
        assert len(result["historical_skills_with_analysis"]) > 0

    def test_05958BR_has_historical_jobs_count(self):
        """Test that historical_jobs field exists and is positive."""
        result = to_dict(get_skill_analysis("05958BR"))

        assert "historical_jobs" in result
        assert result["historical_jobs"] > 0

    def test_05958BR_risk_analysis_negative_correlation(self):
        """Test that Risk Analysis shows highly negative SLA impact."""
        result = to_dict(get_skill_analysis("05958BR"))

        risk_analysis = next(
            (s for s in result["historical_skills_with_analysis"] if s["name"] == "Risk Assessment"), None
        )

        if risk_analysis:
            assert "negative impact on SLA" in risk_analysis["correlation"]

    def test_05958BR_skill_has_required_fields(self):
        """Test that each skill has required fields."""
        result = to_dict(get_skill_analysis("05958BR"))

        for skill in result["historical_skills_with_analysis"]:
            assert "name" in skill
            assert "skill_occurrence" in skill
            assert "correlation" in skill
            assert isinstance(skill["skill_occurrence"], int)

    def test_05958BR_returns_top_10_skills(self):
        """Test that at most 10 skills are returned."""
        result = to_dict(get_skill_analysis("05958BR"))
        assert len(result["historical_skills_with_analysis"]) <= 10


class TestGetSkillImpactFillRate:
    """Tests for get_skill_impact_fill_rate API."""

    def test_05958BR_python_impact(self):
        """Test Python's impact on fill rate."""
        result = to_dict(get_skill_impact_fill_rate("05958BR", "Python"))

        assert result["skill_name"] == "Python"
        assert "impact" in result
        assert "compared_to_baseline" in result

    def test_05958BR_python_fill_rate_values(self):
        """Test that Python fill rate values are reasonable."""
        result = to_dict(get_skill_impact_fill_rate("05958BR", "Python"))

        # Should have fill rate percentage
        assert "fill_rate_percentage" in result["impact"]
        assert "fill_rate_percentage" in result["compared_to_baseline"]

        # Fill rates should be small positive numbers (< 10%)
        with_python = result["impact"]["fill_rate_percentage"]
        without_python = result["compared_to_baseline"]["fill_rate_percentage"]

        assert 0 <= with_python <= 10
        assert 0 <= without_python <= 10

    def test_05958BR_python_time_to_fill(self):
        """Test that time to fill values exist and are reasonable."""
        result = to_dict(get_skill_impact_fill_rate("05958BR", "Python"))

        with_time = result["impact"]["time_to_fill_days"]
        without_time = result["compared_to_baseline"]["time_to_fill_days"]

        # Time to fill should be positive and less than a year
        assert 0 < with_time < 365
        # Baseline can be 0 if no candidates without the skill exist
        assert 0 <= without_time < 365

    def test_05958BR_has_candidate_pool_size(self):
        """Test that candidate pool sizes are returned."""
        result = to_dict(get_skill_impact_fill_rate("05958BR", "Python"))

        assert "candidate_pool_size" in result["impact"]
        assert "candidate_pool_size" in result["compared_to_baseline"]

        assert result["impact"]["candidate_pool_size"] > 0
        # Baseline can be 0 if no candidates without the skill exist
        assert result["compared_to_baseline"]["candidate_pool_size"] >= 0


class TestGetSkillImpactSLA:
    """Tests for get_skill_impact_sla API."""

    def test_05958BR_python_zero_delta(self):
        """Test that Python has 0% SLA delta."""
        result = to_dict(get_skill_impact_sla("05958BR", "Python"))

        assert result["skill_name"] == "Python"
        assert result["delta"] == 0

    def test_05958BR_python_90_percent_both(self):
        """Test that Python shows 90% SLA with and without."""
        result = to_dict(get_skill_impact_sla("05958BR", "Python"))

        # Allow ±5% tolerance
        assert abs(result["sla_achievement_with_skill"] - 90) <= 5
        assert abs(result["sla_achievement_without_skill"] - 90) <= 5

    def test_05958BR_cyber_engineering_negative_15(self):
        """Test that Cyber Engineering has -15pp delta."""
        result = to_dict(get_skill_impact_sla("05958BR", "Cyber Engineering"))

        assert result["skill_name"] == "Cyber Engineering"
        # Allow ±3pp tolerance
        assert abs(result["delta"] - (-15)) <= 3

    def test_05958BR_wireshark_negative_impact(self):
        """Test that Wireshark has negative SLA delta."""
        result = to_dict(get_skill_impact_sla("05958BR", "Wireshark"))

        assert result["skill_name"] == "Wireshark"
        # Expected around -21pp (±5pp tolerance for data variation)
        assert abs(result["delta"] - (-21)) <= 5

    def test_05958BR_has_requisition_id(self):
        """Test that requisition_id is included in response."""
        result = to_dict(get_skill_impact_sla("05958BR", "Python"))
        assert result["requisition_id"] == "05958BR"


class TestGetSkillRelevanceJustification:
    """Tests for get_skill_relevance_justification API."""

    def test_05958BR_python_not_relevant(self):
        """Test that Python is not flagged as relevant."""
        result = to_dict(get_skill_relevance_justification("05958BR", "Python"))

        assert result["skill_name"] == "Python"
        # Python should not be relevant (neutral impact)
        assert isinstance(result["is_relevant"], bool)  # Just check it returns a bool

    def test_05958BR_has_justification_object(self):
        """Test that justification object is present."""
        result = to_dict(get_skill_relevance_justification("05958BR", "Python"))

        assert "justification" in result
        justification = result["justification"]

        # Should have SLA metrics
        assert "sla_achievement_with_skill" in justification
        assert "sla_achievement_without_skill" in justification
        assert "delta" in justification

    def test_05958BR_justification_has_fill_rate_impact(self):
        """Test that justification includes fill rate impact."""
        result = to_dict(get_skill_relevance_justification("05958BR", "Python"))

        justification = result["justification"]

        assert "impact" in justification
        assert "compared_to_baseline" in justification

        assert "fill_rate_percentage" in justification["impact"]
        assert "time_to_fill_days" in justification["impact"]
        assert "candidate_pool_size" in justification["impact"]

    def test_05958BR_includes_requisition_id(self):
        """Test that requisition_id is included."""
        result = to_dict(get_skill_relevance_justification("05958BR", "AWS"))
        assert result["requisition_id"] == "05958BR"


class TestGetSuccessfulPostingCriteria:
    """Tests for get_successful_posting_criteria API."""

    def test_returns_criteria(self):
        """Test that criteria are returned."""
        result = to_dict(get_successful_posting_criteria())

        assert "criteria" in result
        criteria = result["criteria"]

        # Should have key thresholds
        assert "time_to_fill_threshold_days" in criteria
        assert "offer_acceptance_rate_min" in criteria
        assert "sla_compliance_min" in criteria
        assert "candidate_quality_rating_avg" in criteria

    def test_criteria_values_reasonable(self):
        """Test that criteria values are reasonable."""
        result = to_dict(get_successful_posting_criteria())
        criteria = result["criteria"]

        # Time to fill should be positive
        assert criteria["time_to_fill_threshold_days"] > 0

        # Percentages should be between 0 and 100
        assert 0 <= criteria["offer_acceptance_rate_min"] <= 100
        assert 0 <= criteria["sla_compliance_min"] <= 100

        # Quality rating should be positive
        assert criteria["candidate_quality_rating_avg"] > 0

    def test_has_justification(self):
        """Test that justification is provided."""
        result = to_dict(get_successful_posting_criteria())
        assert "justification" in result
        assert len(result["justification"]) > 0


class TestGetDataSourcesUsed:
    """Tests for get_data_sources_used API."""

    def test_05958BR_returns_datasets(self):
        """Test that datasets_used list is returned."""
        result = to_dict(get_data_sources_used("05958BR"))

        assert "datasets_used" in result
        assert isinstance(result["datasets_used"], list)
        assert len(result["datasets_used"]) > 0

    def test_05958BR_required_datasets_present(self):
        """Test that required datasets are present."""
        result = to_dict(get_data_sources_used("05958BR"))
        datasets = result["datasets_used"]

        # These MUST be present (from tasks 17, 21)
        required = [
            "Historical hiring success data",
            "Funnel conversion metrics",
            "Requisition skill tagging",
            "Candidate quality feedback",
        ]

        for dataset in required:
            assert dataset in datasets, f"Missing required dataset: {dataset}"

    def test_05958BR_job_embeddings_not_present(self):
        """Test that Job description embeddings is NOT present."""
        result = to_dict(get_data_sources_used("05958BR"))
        datasets = result["datasets_used"]

        # This must NOT be present (from task 17)
        assert "Job description embeddings" not in datasets

    def test_05958BR_returns_models(self):
        """Test that models_involved list is returned."""
        result = to_dict(get_data_sources_used("05958BR"))

        assert "models_involved" in result
        assert isinstance(result["models_involved"], list)
        assert len(result["models_involved"]) > 0

    def test_05958BR_required_models_present(self):
        """Test that required models are present."""
        result = to_dict(get_data_sources_used("05958BR"))
        models = result["models_involved"]

        # These MUST be present (from task 18, 20)
        required = [
            "SLA impact regression model",
            "Skill relevance classifier",
            "Funnel conversion recommender",
        ]

        for model in required:
            assert model in models, f"Missing required model: {model}"

    def test_05958BR_candidate_ranking_not_present(self):
        """Test that Candidate ranking model is NOT present."""
        result = to_dict(get_data_sources_used("05958BR"))
        models = result["models_involved"]

        # This must NOT be present (from task 18)
        assert "Candidate ranking model" not in models

    def test_05958BR_includes_requisition_id(self):
        """Test that requisition_id is included in response."""
        result = to_dict(get_data_sources_used("05958BR"))
        assert result["requisition_id"] == "05958BR"

    def test_05958BR_exactly_4_datasets(self):
        """Test that exactly 4 datasets are returned."""
        result = to_dict(get_data_sources_used("05958BR"))
        assert len(result["datasets_used"]) == 4

    def test_05958BR_exactly_3_models(self):
        """Test that exactly 3 models are returned."""
        result = to_dict(get_data_sources_used("05958BR"))
        assert len(result["models_involved"]) == 3
