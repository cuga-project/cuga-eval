"""FastAPI HTTP server exposing BPO APIs with OpenAPI documentation."""

from typing import List, Optional, Union

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from benchmarks.bpo.api_candidate_source import (
    get_candidate_volume_by_source,
    get_definitions_and_methodology,
    get_funnel_conversion_by_source,
    get_metadata_and_timeframe,
    get_sla_per_source,
    get_source_recommendation_summary,
    get_total_hires_by_source,
)
from benchmarks.bpo.api_candidate_source_error import (
    get_batch_metrics as get_batch_metrics_error,
)
from benchmarks.bpo.api_candidate_source_error import (
    get_bulk_source_data as get_bulk_source_data_error,
)
from benchmarks.bpo.api_candidate_source_error import (
    get_candidate_pipeline_status as get_candidate_pipeline_status_error,
)
from benchmarks.bpo.api_candidate_source_error import (
    get_full_candidate_details as get_full_candidate_details_error,
)
from benchmarks.bpo.api_candidate_source_error import (
    get_funnel_status as get_funnel_status_error,
)
from benchmarks.bpo.api_candidate_source_error import (
    get_inactive_sources as get_inactive_sources_error,
)
from benchmarks.bpo.api_candidate_source_error import (
    get_requisition_details as get_requisition_details_error,
)
from benchmarks.bpo.api_candidate_source_error import (
    get_sla_extended as get_sla_extended_error,
)
from benchmarks.bpo.api_candidate_source_error import (
    get_source_directory as get_source_directory_error,
)
from benchmarks.bpo.api_candidate_source_error import (
    get_source_metrics_lite as get_source_metrics_lite_error,
)
from benchmarks.bpo.api_candidate_source_error import (
    get_source_sla_check as get_source_sla_check_error,
)
from benchmarks.bpo.api_candidate_source_error import (
    get_source_sla_score as get_source_sla_score_error,
)
from benchmarks.bpo.api_candidate_source_error import (
    get_volume_report as get_volume_report_error,
)
from benchmarks.bpo.api_candidate_source_error import (
    list_all_sources as list_all_sources_error,
)
from benchmarks.bpo.api_skills import (
    get_data_sources_used,
    get_skill_analysis,
    get_skill_impact_fill_rate,
    get_skill_impact_sla,
    get_skill_relevance_justification,
    get_successful_posting_criteria,
)
from benchmarks.bpo.api_skills_error import (
    analyze_skill_match as analyze_skill_match_error,
)
from benchmarks.bpo.api_skills_error import (
    get_model_registry as get_model_registry_error,
)
from benchmarks.bpo.api_skills_error import (
    get_skill_deep_analysis as get_skill_deep_analysis_error,
)
from benchmarks.bpo.api_skills_error import (
    get_skill_lookup as get_skill_lookup_error,
)
from benchmarks.bpo.api_skills_error import (
    get_skill_summary as get_skill_summary_error,
)
from benchmarks.bpo.models import (
    CandidateVolumeResponse,
    DataSourcesResponse,
    DefinitionsResponse,
    FunnelConversionResponse,
    MetadataResponse,
    RequisitionNotFoundResponse,
    SkillAnalysisResponse,
    SkillImpactFillRateResponse,
    SkillImpactSLAResponse,
    SkillRelevanceResponse,
    SLAPerSourceResponse,
    SourceRecommendationResponse,
    SuccessfulPostingResponse,
    TotalHiresBySourceResponse,
)

app = FastAPI(
    title="BPO Recruiting Analytics API",
    description="API for BPO recruiting analytics benchmark with 32 tool endpoints (13 original + 19 error/negative-test endpoints)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Candidate Source Endpoints


@app.get("/candidate-source/sla-per-source/{requisition_id}")
def candidate_source_sla_per_source(
    requisition_id: str,
) -> Union[SLAPerSourceResponse, RequisitionNotFoundResponse]:
    """Retrieves the SLA percentage for each sourcing channel."""
    return get_sla_per_source(requisition_id)


@app.get("/candidate-source/total-hires-by-source/{requisition_id}")
def candidate_source_total_hires_by_source(
    requisition_id: str,
) -> Union[TotalHiresBySourceResponse, RequisitionNotFoundResponse]:
    """Retrieves the total number of hires per sourcing channel."""
    return get_total_hires_by_source(requisition_id)


@app.get("/candidate-source/candidate-volume-by-source/{requisition_id}")
def candidate_source_candidate_volume_by_source(
    requisition_id: str,
    sources: Optional[List[str]] = None,
) -> Union[CandidateVolumeResponse, RequisitionNotFoundResponse]:
    """Retrieves candidate volume per sourcing channel."""
    return get_candidate_volume_by_source(requisition_id, sources)


@app.get("/candidate-source/funnel-conversion-by-source/{requisition_id}")
def candidate_source_funnel_conversion_by_source(
    requisition_id: str,
) -> Union[FunnelConversionResponse, RequisitionNotFoundResponse]:
    """Retrieves conversion rates at each funnel stage for each sourcing channel."""
    return get_funnel_conversion_by_source(requisition_id)


@app.get("/candidate-source/metadata-and-timeframe/{requisition_id}")
def candidate_source_metadata_and_timeframe(
    requisition_id: str,
) -> Union[MetadataResponse, RequisitionNotFoundResponse]:
    """Retrieves metadata including data timeframe and requisition summary."""
    return get_metadata_and_timeframe(requisition_id)


@app.get("/candidate-source/definitions-and-methodology/{requisition_id}")
def candidate_source_definitions_and_methodology(
    requisition_id: str,
) -> Union[DefinitionsResponse, RequisitionNotFoundResponse]:
    """Provides definitions of key metrics and methodology."""
    return get_definitions_and_methodology(requisition_id)


@app.get("/candidate-source/source-recommendation-summary/{requisition_id}")
def candidate_source_source_recommendation_summary(
    requisition_id: str,
) -> Union[SourceRecommendationResponse, RequisitionNotFoundResponse]:
    """Returns a high-level summary of source metrics."""
    return get_source_recommendation_summary(requisition_id)


# Skills Endpoints


@app.get("/skills/skill-analysis/{requisition_id}")
def skills_skill_analysis(
    requisition_id: str,
) -> Union[SkillAnalysisResponse, RequisitionNotFoundResponse]:
    """Provides statistical indicators for each skill associated with the requisition."""
    return get_skill_analysis(requisition_id)


@app.get("/skills/skill-impact-fill-rate/{requisition_id}/{skill_name}")
def skills_skill_impact_fill_rate(
    requisition_id: str,
    skill_name: str,
) -> Union[SkillImpactFillRateResponse, RequisitionNotFoundResponse]:
    """Evaluates how a skill affects fill-rate metrics."""
    return get_skill_impact_fill_rate(requisition_id, skill_name)


@app.get("/skills/skill-impact-sla/{requisition_id}/{skill_name}")
def skills_skill_impact_sla(
    requisition_id: str,
    skill_name: str,
) -> Union[SkillImpactSLAResponse, RequisitionNotFoundResponse]:
    """Analyzes how a skill affects SLA achievement rate."""
    return get_skill_impact_sla(requisition_id, skill_name)


@app.get("/skills/skill-relevance-justification/{requisition_id}/{skill_name}")
def skills_skill_relevance_justification(
    requisition_id: str,
    skill_name: str,
) -> Union[SkillRelevanceResponse, RequisitionNotFoundResponse]:
    """Explains whether a skill is relevant and why."""
    return get_skill_relevance_justification(requisition_id, skill_name)


@app.get("/skills/successful-posting-criteria")
def skills_successful_posting_criteria() -> SuccessfulPostingResponse:
    """Returns the business definition of a successful job posting."""
    return get_successful_posting_criteria()


@app.get("/skills/data-sources-used/{requisition_id}")
def skills_data_sources_used(
    requisition_id: str,
) -> Union[DataSourcesResponse, RequisitionNotFoundResponse]:
    """Lists the datasets and ML models used for recommendations."""
    return get_data_sources_used(requisition_id)


# Error/Negative Test Endpoints


@app.get("/candidate-source/source-sla-score/{requisition_id}", response_model=None)
def candidate_source_source_sla_score(
    requisition_id: str,
    source_name: str = "Dice",
):
    """Get the SLA score for a specific sourcing channel (error variant)."""
    return get_source_sla_score_error(requisition_id, source_name)


@app.get("/candidate-source/inactive-sources/{requisition_id}", response_model=None)
def candidate_source_inactive_sources(
    requisition_id: str,
):
    """Show any inactive sourcing channels with no candidates (error variant)."""
    return get_inactive_sources_error(requisition_id)


@app.get("/candidate-source/candidate-pipeline-status/{requisition_id}", response_model=None)
def candidate_source_candidate_pipeline_status(
    requisition_id: str,
):
    """Get candidate pipeline status for a requisition (error variant)."""
    return get_candidate_pipeline_status_error(requisition_id)


@app.get("/candidate-source/source-sla-check/{requisition_id}", response_model=None)
def candidate_source_source_sla_check(
    requisition_id: str,
):
    """Run a quick SLA status check across all sourcing channels (error variant)."""
    return get_source_sla_check_error(requisition_id)


@app.get("/candidate-source/funnel-status/{requisition_id}", response_model=None)
def candidate_source_funnel_status(
    requisition_id: str,
):
    """Get the current funnel status for a requisition (error variant)."""
    return get_funnel_status_error(requisition_id)


@app.get("/candidate-source/bulk-source-data/{requisition_id}", response_model=None)
def candidate_source_bulk_source_data(
    requisition_id: str,
):
    """Pull bulk source data for all requisitions (error variant)."""
    return get_bulk_source_data_error(requisition_id)


@app.get("/candidate-source/source-metrics-lite/{requisition_id}", response_model=None)
def candidate_source_source_metrics_lite(
    requisition_id: str,
):
    """Get a lightweight summary of source metrics (error variant)."""
    return get_source_metrics_lite_error(requisition_id)


@app.get("/candidate-source/volume-report/{requisition_id}", response_model=None)
def candidate_source_volume_report(
    requisition_id: str,
):
    """Generate a volume report for a requisition (error variant)."""
    return get_volume_report_error(requisition_id)


@app.get("/candidate-source/full-candidate-details/{requisition_id}", response_model=None)
def candidate_source_full_candidate_details(
    requisition_id: str,
):
    """Get full candidate details for a requisition (error variant)."""
    return get_full_candidate_details_error(requisition_id)


@app.get("/candidate-source/source-directory/{requisition_id}", response_model=None)
def candidate_source_source_directory(
    requisition_id: str,
):
    """Show the source directory for a requisition (error variant)."""
    return get_source_directory_error(requisition_id)


@app.get("/candidate-source/sla-extended/{requisition_id}", response_model=None)
def candidate_source_sla_extended(
    requisition_id: str,
    source_name: str = "Dice",
):
    """Get extended SLA data for a specific sourcing channel (error variant)."""
    return get_sla_extended_error(requisition_id, source_name)


@app.get("/candidate-source/requisition-details/{requisition_id}", response_model=None)
def candidate_source_requisition_details(
    requisition_id: str,
):
    """Get detailed information for a specific requisition (error variant)."""
    return get_requisition_details_error(requisition_id)


@app.get("/candidate-source/list-all-sources/{requisition_id}", response_model=None)
def candidate_source_list_all_sources(
    requisition_id: str,
):
    """List all available sourcing channels (error variant)."""
    return list_all_sources_error(requisition_id)


@app.get("/candidate-source/batch-metrics/{requisition_id}", response_model=None)
def candidate_source_batch_metrics(
    requisition_id: str,
):
    """Fetch batch metrics for all sourcing channels (error variant)."""
    return get_batch_metrics_error(requisition_id)


@app.get("/skills/skill-summary/{requisition_id}", response_model=None)
def skills_skill_summary(
    requisition_id: str,
):
    """Get a quick text summary of skills needed for a requisition (error variant)."""
    return get_skill_summary_error(requisition_id)


@app.get("/skills/model-registry/{requisition_id}", response_model=None)
def skills_model_registry(
    requisition_id: str,
):
    """Check which ML models are registered for a given requisition (error variant)."""
    return get_model_registry_error(requisition_id)


@app.get("/skills/skill-lookup/{requisition_id}", response_model=None)
def skills_skill_lookup(
    requisition_id: str,
    skill_name: Optional[str] = None,
    include_history: bool = False,
    format: str = "json",
):
    """Look up a specific skill and its metrics for a requisition (error variant)."""
    return get_skill_lookup_error(requisition_id, skill_name, include_history, format)


@app.get("/skills/skill-deep-analysis/{requisition_id}", response_model=None)
def skills_skill_deep_analysis(
    requisition_id: str,
):
    """Get a deep analysis breakdown of skills (error variant)."""
    return get_skill_deep_analysis_error(requisition_id)


@app.get("/skills/analyze-skill-match/{requisition_id}/{skill_id}", response_model=None)
def skills_analyze_skill_match(
    requisition_id: str,
    skill_id: str,
):
    """Check if a skill is a good match for a requisition (error variant)."""
    return analyze_skill_match_error(requisition_id, skill_id)
