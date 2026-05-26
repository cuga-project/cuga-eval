"""Data constraint validation tests.

These tests validate critical data requirements to catch regressions early.
Run with: uv run pytest benchmarks/bpo/tests/test_constraints.py -v
"""

import pytest

from benchmarks.bpo import api_candidate_source as candidate_source
from benchmarks.bpo.data_loader import get_data_loader
from benchmarks.bpo.tests.conftest import to_dict

pytestmark = pytest.mark.regression


class TestTask4Constraints:
    """Validate Task 4 requirements: candidate volumes and acceptance rates."""

    def test_candidate_volume_percentages(self):
        """Validate candidate volume percentages with round() rounding."""
        result = to_dict(candidate_source.get_candidate_volume_by_source("05958BR"))

        # Extract percentages from metrics
        volumes = {m['source_name']: m['candidate_volume'] for m in result['metrics']}

        # Task 4 requires: LinkedIn 519 (18%), Dice 516 (18%), GitHub 468 (16%)
        assert volumes["LinkedIn"] == 519, f"LinkedIn should be 519, got {volumes['LinkedIn']}"
        assert volumes["Dice"] == 516, f"Dice should be 516, got {volumes['Dice']}"
        assert volumes["GitHub"] == 468, f"GitHub should be 468, got {volumes['GitHub']}"

    def test_offer_acceptance_rates(self):
        """Validate offer acceptance rates with round() rounding."""
        result = to_dict(candidate_source.get_source_recommendation_summary("05958BR"))

        # Extract acceptance rates
        acceptance = {m['source_name']: m['offer_acceptance_rate'] for m in result['metrics']}

        # Task 4 requires: LinkedIn 70%, Dice 79%, GitHub 77%
        assert acceptance['LinkedIn'] == 70, (
            f"LinkedIn acceptance should be 70%, got {acceptance['LinkedIn']}%"
        )
        assert acceptance['Dice'] == 79, f"Dice acceptance should be 79%, got {acceptance['Dice']}%"
        assert acceptance['GitHub'] == 77, f"GitHub acceptance should be 77%, got {acceptance['GitHub']}%"

    def test_total_hires(self):
        """Validate total hires per source."""
        result = to_dict(candidate_source.get_total_hires_by_source("05958BR"))

        hires = {m['source_name']: m['total_hires'] for m in result['metrics']}

        # Task 4 requires: LinkedIn 7, Dice 11, GitHub 10
        assert hires['LinkedIn'] == 7, f"LinkedIn should have 7 hires, got {hires['LinkedIn']}"
        assert hires['Dice'] == 11, f"Dice should have 11 hires, got {hires['Dice']}"
        assert hires['GitHub'] == 10, f"GitHub should have 10 hires, got {hires['GitHub']}"


class TestTask5Constraints:
    """Validate Task 5 requirements: Dice funnel conversion rates."""

    def test_dice_funnel_percentages(self):
        """Validate Dice funnel conversion at each stage."""
        result = to_dict(candidate_source.get_funnel_conversion_by_source("05958BR"))

        # Find Dice metrics
        dice_metrics = next(m for m in result['metrics'] if m['source_name'] == 'Dice')

        # Task 5 requires: 11% review, 6.8% interview, 2.7% offer
        assert dice_metrics['first_round_review_percentage'] == 11.0, (
            f"Dice review should be 11.0%, got {dice_metrics['first_round_review_percentage']}%"
        )
        assert dice_metrics['interview_rate'] == 6.8, (
            f"Dice interview should be 6.8%, got {dice_metrics['interview_rate']}%"
        )
        assert dice_metrics['offer_acceptance_rate'] == 2.7, (
            f"Dice offer should be 2.7%, got {dice_metrics['offer_acceptance_rate']}%"
        )

    def test_dice_total_hires(self):
        """Validate Dice resulted in 11 hires (27.5% of all hires)."""
        result = to_dict(candidate_source.get_total_hires_by_source("05958BR"))

        # Total should be 40 hires
        assert result['total_hires'] == 40, f"Total hires should be 40, got {result['total_hires']}"

        # Find Dice
        dice = next(m for m in result['metrics'] if m['source_name'] == 'Dice')
        assert dice['total_hires'] == 11, f"Dice should have 11 hires, got {dice['total_hires']}"

        # Verify percentage (use approx for floating point comparison)
        dice_pct = dice['total_hires'] / result['total_hires'] * 100
        assert dice_pct == pytest.approx(27.5), f"Dice should be 27.5% of hires, got {dice_pct:.1f}%"


class TestTask2Constraints:
    """Validate Task 2 requirements: SLA percentages."""

    def test_sla_percentages(self):
        """Validate SLA percentages for all sources."""
        result = to_dict(candidate_source.get_sla_per_source("05958BR"))

        sla = {m['source_name']: m['sla_percentage'] for m in result['metrics']}

        # Task 2 requires CyberSec Jobs to be lowest at 67%
        assert sla['CyberSec Jobs'] == 67, f"CyberSec Jobs SLA should be 67%, got {sla['CyberSec Jobs']}"

        # Validate other sources (updated to match actual data)
        assert sla['Indeed'] == 86, f"Indeed SLA should be 86%, got {sla['Indeed']}"
        assert sla['GitHub'] == 90, f"GitHub SLA should be 90%, got {sla['GitHub']}"
        assert sla['Dice'] == 95, f"Dice SLA should be 95%, got {sla['Dice']}"
        assert sla['LinkedIn'] == 95, f"LinkedIn SLA should be 95%, got {sla['LinkedIn']}"
        assert sla['Internal'] == 95, f"Internal SLA should be 95%, got {sla['Internal']}"
        assert sla['Referral'] == 95, f"Referral SLA should be 95%, got {sla['Referral']}"


class TestTask3Constraints:
    """Validate Task 3 requirements: total hires and percentages."""

    def test_total_hires_with_percentages(self):
        """Validate total hires per source match expected percentages."""
        result = to_dict(candidate_source.get_total_hires_by_source("05958BR"))

        total = result['total_hires']
        assert total == 40, f"Total hires should be 40, got {total}"

        hires = {m['source_name']: m['total_hires'] for m in result['metrics']}

        # Task 3 expected percentages
        expected = {
            'Dice': (11, 27.5),
            'GitHub': (10, 25.0),
            'LinkedIn': (7, 17.5),
            'Internal': (5, 12.5),
            'Referral': (4, 10.0),
            'CyberSec Jobs': (3, 7.5),
        }

        for source, (exp_hires, exp_pct) in expected.items():
            assert hires[source] == exp_hires, f"{source} should have {exp_hires} hires, got {hires[source]}"
            actual_pct = hires[source] / total * 100
            assert actual_pct == pytest.approx(exp_pct), f"{source} should be {exp_pct}%, got {actual_pct}%"


class TestDataIntegrity:
    """Validate overall data integrity."""

    def test_source_volumes_match_total(self):
        """Validate source volumes sum to total candidate volume."""
        result = to_dict(candidate_source.get_candidate_volume_by_source("05958BR"))

        total = result['total_candidate_volume']

        # Sum up individual source volumes (now integers)
        source_sum = sum(metric['candidate_volume'] for metric in result['metrics'])

        assert source_sum == total, f"Source volumes ({source_sum}) don't sum to total ({total})"

    def test_requisition_similarity_grouping(self):
        """Validate requisition similarity uses data-driven matching."""
        loader = get_data_loader()

        # Test 05958BR group
        group1 = loader.get_similar_requisitions("05958BR")
        assert len(group1) == 2913, f"05958BR group should have 2913 candidates, got {len(group1)}"
        assert group1['requisition_id'].nunique() == 40, (
            f"05958BR group should have 40 requisitions, got {group1['requisition_id'].nunique()}"
        )

        # Verify all have same template_id
        template_ids = group1['requisition_template_id'].unique()
        assert len(template_ids) == 1, f"Should have 1 template_id, got {len(template_ids)}"

        # Test 05959BR group
        group2 = loader.get_similar_requisitions("05959BR")
        assert len(group2) == 2913, f"05959BR group should have 2913 candidates, got {len(group2)}"
        assert group2['requisition_id'].nunique() == 40, (
            f"05959BR group should have 40 requisitions, got {group2['requisition_id'].nunique()}"
        )

        # Verify groups are distinct
        assert template_ids[0] != group2['requisition_template_id'].iloc[0], (
            "Template IDs should be different between groups"
        )

    def test_hired_candidates_have_full_funnel(self):
        """Validate all hired candidates have full funnel (reviewed, interviewed, offered, accepted)."""
        loader = get_data_loader()
        data = loader.get_similar_requisitions("05958BR")

        hired = data[data['hired'] == True]  # noqa: E712 — pandas boolean filter, == is the idiom

        # All hired candidates must have gone through full funnel
        assert hired['reviewed'].all(), "All hired candidates must be reviewed"
        assert hired['interviewed'].all(), "All hired candidates must be interviewed"
        assert hired['offer_extended'].all(), "All hired candidates must have offer extended"
        assert hired['offer_accepted'].all(), "All hired candidates must have accepted offer"

    def test_similarity_fallback_department_seniority(self):
        """Validate fallback similarity uses department + seniority_level."""
        loader = get_data_loader()
        original_data = loader.data

        # Find a dept/seniority combo with at least two requisitions.
        group_counts = original_data.groupby(["department", "seniority_level"])["requisition_id"].nunique()
        eligible = group_counts[group_counts >= 2]
        assert not eligible.empty, "Need at least two requisitions sharing dept+seniority"

        ref_department, ref_seniority = eligible.index[0]
        req_ids = (
            original_data[
                (original_data["department"] == ref_department)
                & (original_data["seniority_level"] == ref_seniority)
            ]["requisition_id"]
            .unique()
            .tolist()
        )
        ref_req = req_ids[0]
        other_req = req_ids[1]

        # Create a modified dataset where the reference requisition has no template_id.
        modified = original_data.copy()
        modified.loc[modified["requisition_id"] == ref_req, "requisition_template_id"] = None

        try:
            loader._data = modified
            similar = loader.get_similar_requisitions(ref_req)
            similar_ids = set(similar["requisition_id"].unique())
            assert other_req in similar_ids, (
                "Fallback matching should include requisitions with same dept+seniority"
            )
        finally:
            loader._data = original_data


if __name__ == "__main__":
    # Allow running directly for quick validation
    pytest.main([__file__, "-v"])
