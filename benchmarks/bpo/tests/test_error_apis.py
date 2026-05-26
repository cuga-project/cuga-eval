"""Tests for 19 error/negative-test API endpoints.

Each test class targets a specific error behavior documented in the
api_candidate_source_error.py and api_skills_error.py modules.
"""

import json
import random

import pytest
from fastapi.testclient import TestClient

from benchmarks.bpo.api_candidate_source_error import (
    _call_counts as cs_call_counts,
)
from benchmarks.bpo.api_candidate_source_error import (
    _rng as cs_rng,
)
from benchmarks.bpo.api_candidate_source_error import (
    get_batch_metrics,
    get_bulk_source_data,
    get_candidate_pipeline_status,
    get_full_candidate_details,
    get_funnel_status,
    get_inactive_sources,
    get_requisition_details,
    get_sla_extended,
    get_source_directory,
    get_source_metrics_lite,
    get_source_sla_check,
    get_source_sla_score,
    get_volume_report,
    list_all_sources,
)
from benchmarks.bpo.api_skills_error import (
    analyze_skill_match,
    get_model_registry,
    get_skill_deep_analysis,
    get_skill_lookup,
    get_skill_summary,
)
from benchmarks.bpo.main import app

pytestmark = pytest.mark.regression

VALID_REQ = "05958BR"
INVALID_REQ = "INVALID_XYZ"

client = TestClient(app)


# ── Task 27: get_skill_summary — returns plain string ────────────────────────


class TestGetSkillSummary:
    """Task 27: Returns plain comma-separated string instead of structured dict."""

    def test_returns_string_type(self):
        result = get_skill_summary(VALID_REQ)
        assert isinstance(result, str), "Expected plain string, not dict"

    def test_string_contains_comma_separated_skills(self):
        result = get_skill_summary(VALID_REQ)
        skills = [s.strip() for s in result.split(",")]
        assert len(skills) > 1, "Expected multiple comma-separated skills"

    def test_skills_are_sorted_alphabetically(self):
        result = get_skill_summary(VALID_REQ)
        skills = [s.strip() for s in result.split(",")]
        assert skills == sorted(skills)

    def test_invalid_requisition_returns_json_error_string(self):
        result = get_skill_summary(INVALID_REQ)
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["error"] == "requisition_not_found"

    def test_http_route_returns_string(self):
        resp = client.get(f"/skills/skill-summary/{VALID_REQ}")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, str)


# ── Task 28: get_source_sla_score — returns bare int ─────────────────────────


class TestGetSourceSlaScore:
    """Task 28: Returns bare int instead of dict with sla_score key."""

    def test_returns_int_not_dict(self):
        result = get_source_sla_score(VALID_REQ, "Dice")
        assert isinstance(result, int), f"Expected int, got {type(result)}"

    def test_sla_score_in_valid_range(self):
        result = get_source_sla_score(VALID_REQ, "Dice")
        assert 0 <= result <= 100

    def test_different_sources_may_differ(self):
        dice = get_source_sla_score(VALID_REQ, "Dice")
        linkedin = get_source_sla_score(VALID_REQ, "LinkedIn")
        # Both are ints; they may or may not be equal
        assert isinstance(dice, int) and isinstance(linkedin, int)

    def test_invalid_requisition_returns_error_dict(self):
        result = get_source_sla_score(INVALID_REQ)
        assert isinstance(result, dict)
        assert result["error"] == "requisition_not_found"

    def test_http_route_returns_int(self):
        resp = client.get(f"/candidate-source/source-sla-score/{VALID_REQ}?source_name=Dice")
        assert resp.status_code == 200
        assert isinstance(resp.json(), int)


# ── Task 29: get_inactive_sources — returns None instead of empty list ───────


class TestGetInactiveSources:
    """Task 29: Returns None when no inactive sources exist."""

    def test_returns_none_or_list(self):
        result = get_inactive_sources(VALID_REQ)
        assert result is None or isinstance(result, list)

    def test_none_when_all_sources_active(self):
        # With similar requisitions, all sources may be active.
        # The key error behavior is that it returns None instead of [].
        result = get_inactive_sources(VALID_REQ)
        if result is not None:
            assert isinstance(result, list)
            assert all(isinstance(s, str) for s in result)

    def test_return_type_is_not_empty_list_when_none(self):
        """Verify the error: None is returned instead of []."""
        result = get_inactive_sources(VALID_REQ)
        # The function should return None (the bug) rather than []
        # when there are no inactive sources
        if not result:
            assert result is None, "Expected None, not empty list"

    def test_invalid_requisition_returns_error_dict(self):
        result = get_inactive_sources(INVALID_REQ)
        assert isinstance(result, dict)
        assert result["error"] == "requisition_not_found"

    def test_http_route(self):
        resp = client.get(f"/candidate-source/inactive-sources/{VALID_REQ}")
        assert resp.status_code == 200


# ── Task 30: get_candidate_pipeline_status — 20% chance of 404 ──────────────


class TestGetCandidatePipelineStatus:
    """Task 30: 20% chance of 404 using seeded RNG (seed=42)."""

    def test_deterministic_rng_sequence(self):
        """Verify the RNG produces a predictable sequence of successes/failures."""
        # Reset RNG to known state to get predictable results
        rng_copy = random.Random(42)  # noqa: S311 — non-cryptographic, deterministic test sequence
        outcomes = [rng_copy.random() < 0.2 for _ in range(20)]
        # At least one should be True (404) and at least one False (success)
        assert any(outcomes), "Expected at least one 404 in 20 calls"
        assert not all(outcomes), "Expected at least one success in 20 calls"

    def test_404_response_structure(self):
        """When a 404 occurs, verify its structure."""
        # Call enough times that we hit a 404 (reset RNG first)
        cs_rng.seed(42)
        for _ in range(50):
            result = get_candidate_pipeline_status(VALID_REQ)
            if isinstance(result, dict) and result.get("status_code") == 404:
                assert result["error"] is True
                assert "message" in result
                return
        pytest.fail("Did not encounter a 404 in 50 calls")

    def test_success_response_structure(self):
        """When successful, verify response has pipeline data."""
        cs_rng.seed(42)
        for _ in range(50):
            result = get_candidate_pipeline_status(VALID_REQ)
            if isinstance(result, dict) and result.get("status_code") != 404:
                if "error" not in result or result.get("error") != True:  # noqa: E712 — strict identity vs. True
                    assert "pipeline" in result
                    assert "total_candidates" in result
                    assert result["requisition_id"] == VALID_REQ
                    return
        pytest.fail("Did not encounter a success in 50 calls")

    def test_invalid_requisition_returns_error(self):
        cs_rng.seed(0)  # seed that avoids 404 in first call
        # Try multiple times since some calls may hit the 404 branch first
        for _ in range(20):
            result = get_candidate_pipeline_status(INVALID_REQ)
            if isinstance(result, dict) and result.get("error") == "requisition_not_found":
                assert "message" in result
                return
        pytest.fail("Never got requisition_not_found error")


# ── Task 31: get_source_sla_check — HTTP 500 with valid body ────────────────


class TestGetSourceSlaCheck:
    """Task 31: Always returns status_code=500 but body contains valid data."""

    def test_status_code_is_500(self):
        result = get_source_sla_check(VALID_REQ)
        assert result["status_code"] == 500

    def test_error_flag_is_true(self):
        result = get_source_sla_check(VALID_REQ)
        assert result["error"] is True

    def test_body_contains_valid_metrics(self):
        result = get_source_sla_check(VALID_REQ)
        assert "body" in result
        metrics = result["body"]["metrics"]
        assert isinstance(metrics, list)
        assert len(metrics) > 0
        for m in metrics:
            assert "source_name" in m
            assert "sla_percentage" in m
            assert 0 <= m["sla_percentage"] <= 100

    def test_message_is_internal_server_error(self):
        result = get_source_sla_check(VALID_REQ)
        assert result["message"] == "Internal server error"

    def test_invalid_requisition_returns_error(self):
        result = get_source_sla_check(INVALID_REQ)
        assert result["error"] == "requisition_not_found"


# ── Task 32: get_funnel_status — always 503 ─────────────────────────────────


class TestGetFunnelStatus:
    """Task 32: Always returns 503 Service Unavailable."""

    def test_always_returns_503(self):
        result = get_funnel_status(VALID_REQ)
        assert result["status_code"] == 503

    def test_error_flag_is_true(self):
        result = get_funnel_status(VALID_REQ)
        assert result["error"] is True

    def test_has_retry_after(self):
        result = get_funnel_status(VALID_REQ)
        assert "retry_after_seconds" in result
        assert isinstance(result["retry_after_seconds"], int)

    def test_has_expected_recovery(self):
        result = get_funnel_status(VALID_REQ)
        assert "expected_recovery" in result

    def test_returns_503_even_for_invalid_requisition(self):
        """503 is returned before requisition validation."""
        result = get_funnel_status(INVALID_REQ)
        assert result["status_code"] == 503

    def test_http_route_returns_503_body(self):
        resp = client.get(f"/candidate-source/funnel-status/{VALID_REQ}")
        # FastAPI returns 200 because the function returns a dict (not an HTTPException)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status_code"] == 503


# ── Task 33: get_bulk_source_data — 429 after 3rd call ──────────────────────


class TestGetBulkSourceData:
    """Task 33: Returns 429 after the 3rd call via module-level counter."""

    def setup_method(self):
        """Reset the module-level call counter before each test."""
        cs_call_counts.pop("get_bulk_source_data", None)

    def test_first_three_calls_succeed(self):
        for i in range(3):
            result = get_bulk_source_data(VALID_REQ)
            assert "sources" in result, f"Call {i + 1} should succeed"
            assert result["call_number"] == i + 1

    def test_fourth_call_returns_429(self):
        for _ in range(3):
            get_bulk_source_data(VALID_REQ)
        result = get_bulk_source_data(VALID_REQ)
        assert result["status_code"] == 429
        assert result["error"] is True
        assert result["remaining"] == 0

    def test_429_has_retry_after(self):
        for _ in range(3):
            get_bulk_source_data(VALID_REQ)
        result = get_bulk_source_data(VALID_REQ)
        assert "retry_after_seconds" in result
        assert result["limit"] == 3

    def test_success_response_has_sources(self):
        result = get_bulk_source_data(VALID_REQ)
        assert "sources" in result
        assert isinstance(result["sources"], dict)
        for source_name, source_data in result["sources"].items():
            assert "total_candidates" in source_data
            assert "total_hires" in source_data

    def test_invalid_requisition_within_limit(self):
        result = get_bulk_source_data(INVALID_REQ)
        assert result["error"] == "requisition_not_found"


# ── Task 34: get_model_registry — untyped dict ──────────────────────────────


class TestGetModelRegistry:
    """Task 34: Returns untyped dict with no Pydantic schema."""

    def test_returns_dict(self):
        result = get_model_registry(VALID_REQ)
        assert isinstance(result, dict)

    def test_has_models_list(self):
        result = get_model_registry(VALID_REQ)
        assert "models" in result
        assert isinstance(result["models"], list)
        assert len(result["models"]) == 3

    def test_each_model_has_name_and_version(self):
        result = get_model_registry(VALID_REQ)
        for model in result["models"]:
            assert "name" in model
            assert "version" in model
            assert "status" in model

    def test_models_have_heterogeneous_metric_fields(self):
        """Different models have different metric fields (accuracy, r_squared, precision)."""
        result = get_model_registry(VALID_REQ)
        metric_fields = set()
        for model in result["models"]:
            for key in model:
                if key not in ("name", "version", "status", "last_trained"):
                    metric_fields.add(key)
        assert "accuracy" in metric_fields
        assert "r_squared" in metric_fields
        assert "precision" in metric_fields

    def test_has_registry_updated(self):
        result = get_model_registry(VALID_REQ)
        assert "registry_updated" in result

    def test_invalid_requisition_returns_error(self):
        result = get_model_registry(INVALID_REQ)
        assert result["error"] == "requisition_not_found"


# ── Task 35: get_skill_lookup — undocumented params ──────────────────────────


class TestGetSkillLookup:
    """Task 35: Accepts undocumented include_history and format params."""

    def test_basic_lookup(self):
        result = get_skill_lookup(VALID_REQ, skill_name="Python")
        assert result["skill_name"] == "Python"
        assert "occurrence_count" in result
        assert "occurrence_rate" in result

    def test_include_history_param_adds_history(self):
        result = get_skill_lookup(VALID_REQ, skill_name="Python", include_history=True)
        assert "history" in result
        assert "first_seen" in result["history"]
        assert "trend" in result["history"]
        assert "quarterly_counts" in result["history"]

    def test_without_include_history_no_history_key(self):
        result = get_skill_lookup(VALID_REQ, skill_name="Python", include_history=False)
        assert "history" not in result

    def test_format_param_accepted(self):
        """format param is accepted without error even though undocumented."""
        result = get_skill_lookup(VALID_REQ, skill_name="Python", format="csv")
        assert "skill_name" in result  # Still returns dict regardless

    def test_invalid_requisition_returns_error(self):
        result = get_skill_lookup(INVALID_REQ, skill_name="Python")
        assert result["error"] == "requisition_not_found"

    def test_http_route_with_undocumented_params(self):
        resp = client.get(
            f"/skills/skill-lookup/{VALID_REQ}",
            params={"skill_name": "Python", "include_history": True, "format": "xml"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "history" in body


# ── Task 36: get_source_metrics_lite — missing source_name ───────────────────


class TestGetSourceMetricsLite:
    """Task 36: Metrics entries are missing source_name field."""

    def test_metrics_missing_source_name(self):
        result = get_source_metrics_lite(VALID_REQ)
        for m in result["metrics"]:
            assert "source_name" not in m, "source_name should be missing (error behavior)"

    def test_metrics_have_counts(self):
        result = get_source_metrics_lite(VALID_REQ)
        for m in result["metrics"]:
            assert "candidate_count" in m
            assert "hire_count" in m
            assert "sla_met_count" in m

    def test_has_requisition_id(self):
        result = get_source_metrics_lite(VALID_REQ)
        assert result["requisition_id"] == VALID_REQ

    def test_has_note_field(self):
        result = get_source_metrics_lite(VALID_REQ)
        assert "note" in result

    def test_invalid_requisition_returns_error(self):
        result = get_source_metrics_lite(INVALID_REQ)
        assert result["error"] == "requisition_not_found"


# ── Task 37: get_volume_report — candidate_count as string ───────────────────


class TestGetVolumeReport:
    """Task 37: candidate_count returned as string instead of int."""

    def test_candidate_count_is_string(self):
        result = get_volume_report(VALID_REQ)
        for m in result["metrics"]:
            assert isinstance(m["candidate_count"], str), "candidate_count should be string"

    def test_hire_count_is_string(self):
        result = get_volume_report(VALID_REQ)
        for m in result["metrics"]:
            assert isinstance(m["hire_count"], str), "hire_count should be string"

    def test_total_candidates_is_string(self):
        result = get_volume_report(VALID_REQ)
        assert isinstance(result["total_candidates"], str)

    def test_string_values_are_parseable_as_int(self):
        result = get_volume_report(VALID_REQ)
        for m in result["metrics"]:
            int(m["candidate_count"])  # Should not raise
            int(m["hire_count"])

    def test_review_rate_is_formatted_string(self):
        result = get_volume_report(VALID_REQ)
        for m in result["metrics"]:
            assert m["review_rate"].endswith("%")

    def test_invalid_requisition_returns_error(self):
        result = get_volume_report(INVALID_REQ)
        assert result["error"] == "requisition_not_found"


# ── Task 38: get_full_candidate_details — large response ────────────────────


class TestGetFullCandidateDetails:
    """Task 38: Returns up to 1000 candidate records from fixture."""

    def test_returns_candidates_list(self):
        result = get_full_candidate_details(VALID_REQ)
        assert "candidates" in result
        assert isinstance(result["candidates"], list)

    def test_total_records_matches_candidates_length(self):
        result = get_full_candidate_details(VALID_REQ)
        assert result["total_records"] == len(result["candidates"])

    def test_large_payload_or_warning(self):
        """Either returns 1000 records or a warning about missing fixture."""
        result = get_full_candidate_details(VALID_REQ)
        if result["total_records"] == 0:
            assert "warning" in result
        else:
            assert result["total_records"] > 0

    def test_has_requisition_id(self):
        result = get_full_candidate_details(VALID_REQ)
        assert result["requisition_id"] == VALID_REQ

    def test_invalid_requisition_returns_error(self):
        result = get_full_candidate_details(INVALID_REQ)
        assert result["error"] == "requisition_not_found"

    def test_http_route(self):
        resp = client.get(f"/candidate-source/full-candidate-details/{VALID_REQ}")
        assert resp.status_code == 200
        body = resp.json()
        assert "candidates" in body


# ── Task 39: get_source_directory — unicode/emoji in names ───────────────────


class TestGetSourceDirectory:
    """Task 39: Source names contain emoji, CJK, Arabic characters."""

    def test_has_seven_sources(self):
        result = get_source_directory(VALID_REQ)
        assert result["total_sources"] == 7
        assert len(result["sources"]) == 7

    def test_contains_emoji_in_names(self):
        result = get_source_directory(VALID_REQ)
        names = [s["name"] for s in result["sources"]]
        joined = " ".join(names)
        # Check for emoji characters (briefcase, dice, cat)
        assert "\U0001f4bc" in joined or "\U0001f3b2" in joined

    def test_contains_cjk_characters(self):
        result = get_source_directory(VALID_REQ)
        names = [s["name"] for s in result["sources"]]
        joined = " ".join(names)
        assert "\u62db\u8058\u7f51" in joined  # 招聘网

    def test_contains_arabic_characters(self):
        result = get_source_directory(VALID_REQ)
        names = [s["name"] for s in result["sources"]]
        joined = " ".join(names)
        assert "\u0628\u064a\u062a" in joined  # بيت

    def test_sources_have_required_fields(self):
        result = get_source_directory(VALID_REQ)
        for s in result["sources"]:
            assert "name" in s
            assert "region" in s
            assert "status" in s

    def test_http_route_preserves_unicode(self):
        resp = client.get(f"/candidate-source/source-directory/{VALID_REQ}")
        assert resp.status_code == 200
        body = resp.json()
        names = [s["name"] for s in body["sources"]]
        assert any("\U0001f4bc" in n for n in names)

    def test_invalid_requisition_returns_error(self):
        result = get_source_directory(INVALID_REQ)
        assert result["error"] == "requisition_not_found"


# ── Task 40: get_skill_deep_analysis — 15-level nested JSON ─────────────────


class TestGetSkillDeepAnalysis:
    """Task 40: Response nested 15 levels deep."""

    def test_has_results_with_nested_skills(self):
        result = get_skill_deep_analysis(VALID_REQ)
        assert "results" in result
        assert "nested_skills" in result["results"]

    def test_total_depth_is_15(self):
        result = get_skill_deep_analysis(VALID_REQ)
        assert result["results"]["total_depth"] == 15

    def test_nested_structure_reaches_15_levels(self):
        result = get_skill_deep_analysis(VALID_REQ)
        skills = result["results"]["nested_skills"]
        assert len(skills) > 0

        # Traverse the first nested skill down to leaf
        node = skills[0]
        depth = 0
        while "data" in node:
            assert "level" in node
            assert "metadata" in node
            node = node["data"]
            depth += 1

        # At leaf: should have skill and count
        assert "skill" in node
        assert "count" in node
        assert depth == 15

    def test_leaf_has_valid_skill_data(self):
        result = get_skill_deep_analysis(VALID_REQ)
        node = result["results"]["nested_skills"][0]
        while "data" in node:
            node = node["data"]
        assert isinstance(node["skill"], str)
        assert isinstance(node["count"], int)
        assert node["count"] > 0

    def test_invalid_requisition_returns_error(self):
        result = get_skill_deep_analysis(INVALID_REQ)
        assert result["error"] == "requisition_not_found"


# ── Task 41: get_sla_extended — 20 extra undocumented fields ────────────────


class TestGetSlaExtended:
    """Task 41: Response includes 20 undocumented extra fields."""

    def test_has_documented_fields(self):
        result = get_sla_extended(VALID_REQ, "Dice")
        assert result["requisition_id"] == VALID_REQ
        assert result["source_name"] == "Dice"
        assert "sla_percentage" in result
        assert 0 <= result["sla_percentage"] <= 100

    def test_has_undocumented_internal_fields(self):
        result = get_sla_extended(VALID_REQ, "Dice")
        undocumented = [k for k in result if k.startswith("_")]
        assert len(undocumented) >= 20, f"Expected 20+ undocumented fields, got {len(undocumented)}"

    def test_specific_undocumented_fields_exist(self):
        result = get_sla_extended(VALID_REQ, "Dice")
        assert "_internal_id" in result
        assert "_cache_ttl" in result
        assert "_version" in result
        assert "_region" in result
        assert "_feature_flags" in result
        assert "_confidence_interval" in result

    def test_total_field_count_exceeds_documented(self):
        result = get_sla_extended(VALID_REQ, "Dice")
        # 3 documented + 20 undocumented = 23+ total
        assert len(result) >= 23

    def test_invalid_requisition_returns_error(self):
        result = get_sla_extended(INVALID_REQ)
        assert result["error"] == "requisition_not_found"


# ── Task 42: analyze_skill_match — skill_id param name mismatch ─────────────


class TestAnalyzeSkillMatch:
    """Task 42: Parameter named skill_id but semantically it is skill_name."""

    def test_accepts_skill_name_as_skill_id(self):
        result = analyze_skill_match(VALID_REQ, skill_id="Python")
        assert result["skill_id"] == "Python"

    def test_has_match_score(self):
        result = analyze_skill_match(VALID_REQ, skill_id="Python")
        assert "match_score" in result
        assert 0 <= result["match_score"] <= 100

    def test_has_sla_delta(self):
        result = analyze_skill_match(VALID_REQ, skill_id="Python")
        assert "sla_delta" in result
        assert isinstance(result["sla_delta"], (int, float))

    def test_has_recommendation(self):
        result = analyze_skill_match(VALID_REQ, skill_id="Python")
        assert result["recommendation"] in ("good match", "weak match")

    def test_occurrence_rate(self):
        result = analyze_skill_match(VALID_REQ, skill_id="Python")
        assert "occurrence_rate" in result
        assert 0 <= result["occurrence_rate"] <= 100

    def test_http_route_uses_skill_id_in_path(self):
        resp = client.get(f"/skills/analyze-skill-match/{VALID_REQ}/Python")
        assert resp.status_code == 200
        body = resp.json()
        assert body["skill_id"] == "Python"

    def test_invalid_requisition_returns_error(self):
        result = analyze_skill_match(INVALID_REQ, skill_id="Python")
        assert result["error"] == "requisition_not_found"


# ── Task 43: get_requisition_details — non-standard error format ─────────────


class TestGetRequisitionDetails:
    """Task 43: Returns {"err": "not_found"} instead of standard error."""

    def test_valid_requisition_returns_details(self):
        result = get_requisition_details(VALID_REQ)
        assert result["requisition_id"] == VALID_REQ
        assert "department" in result
        assert "total_candidates" in result
        assert "sources_used" in result

    def test_invalid_uses_nonstandard_error_format(self):
        result = get_requisition_details(INVALID_REQ)
        assert "err" in result, "Expected 'err' key (non-standard)"
        assert result["err"] == "not_found"
        assert "req" in result
        assert result["req"] == INVALID_REQ

    def test_invalid_does_not_use_standard_error_key(self):
        result = get_requisition_details(INVALID_REQ)
        assert "error" not in result, "Should NOT use standard 'error' key"

    def test_valid_has_sources_used_list(self):
        result = get_requisition_details(VALID_REQ)
        assert isinstance(result["sources_used"], list)
        assert len(result["sources_used"]) > 0


# ── Task 44: list_all_sources — undocumented pagination ──────────────────────


class TestListAllSources:
    """Task 44: Response includes undocumented next_page token."""

    def test_returns_paginated_results(self):
        result = list_all_sources(VALID_REQ)
        assert "sources" in result
        assert "page_size" in result
        assert result["page_size"] == 3

    def test_has_next_page_token(self):
        result = list_all_sources(VALID_REQ)
        if result.get("has_more"):
            assert "next_page" in result
            assert isinstance(result["next_page"], str)
            assert len(result["next_page"]) > 0

    def test_first_page_has_limited_results(self):
        result = list_all_sources(VALID_REQ)
        assert len(result["sources"]) <= result["page_size"]

    def test_total_count_exceeds_page_size(self):
        result = list_all_sources(VALID_REQ)
        assert result["total_count"] > result["page_size"]

    def test_has_more_flag(self):
        result = list_all_sources(VALID_REQ)
        assert "has_more" in result
        assert isinstance(result["has_more"], bool)

    def test_page_number_is_one(self):
        result = list_all_sources(VALID_REQ)
        assert result["page"] == 1

    def test_sources_have_name_and_index(self):
        result = list_all_sources(VALID_REQ)
        for s in result["sources"]:
            assert "name" in s
            assert "index" in s

    def test_invalid_requisition_returns_error(self):
        result = list_all_sources(INVALID_REQ)
        assert result["error"] == "requisition_not_found"


# ── Task 45: get_batch_metrics — rate limit headers in body ──────────────────


class TestGetBatchMetrics:
    """Task 45: Response body contains X-RateLimit style headers."""

    def test_has_metrics(self):
        result = get_batch_metrics(VALID_REQ)
        assert "metrics" in result
        assert isinstance(result["metrics"], dict)

    def test_metrics_have_candidate_data(self):
        result = get_batch_metrics(VALID_REQ)
        for source, data in result["metrics"].items():
            assert "candidates" in data
            assert "hires" in data
            assert "reviewed" in data

    def test_has_rate_limit_headers_in_body(self):
        result = get_batch_metrics(VALID_REQ)
        assert "X-RateLimit-Limit" in result
        assert "X-RateLimit-Remaining" in result
        assert "X-RateLimit-Reset" in result
        assert "X-RateLimit-Window" in result

    def test_rate_limit_values_are_reasonable(self):
        result = get_batch_metrics(VALID_REQ)
        assert result["X-RateLimit-Limit"] == 100
        assert result["X-RateLimit-Remaining"] <= result["X-RateLimit-Limit"]
        assert isinstance(result["X-RateLimit-Window"], str)

    def test_invalid_requisition_returns_error(self):
        result = get_batch_metrics(INVALID_REQ)
        assert result["error"] == "requisition_not_found"

    def test_http_route_has_rate_limit_in_body(self):
        resp = client.get(f"/candidate-source/batch-metrics/{VALID_REQ}")
        assert resp.status_code == 200
        body = resp.json()
        assert "X-RateLimit-Limit" in body
