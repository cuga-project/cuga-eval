"""FastMCP server exposing BPO APIs as tools (stdio transport)."""

from typing import List, Optional, Union

import fastmcp
from loguru import logger

# Import API functions
from benchmarks.bpo.api_candidate_source import (
    get_candidate_volume_by_source,
    get_definitions_and_methodology,
    get_funnel_conversion_by_source,
    get_metadata_and_timeframe,
    get_sla_per_source,
    get_source_recommendation_summary,
    get_total_hires_by_source,
)
from benchmarks.bpo.api_skills import (
    get_data_sources_used,
    get_skill_analysis,
    get_skill_impact_fill_rate,
    get_skill_impact_sla,
    get_skill_relevance_justification,
    get_successful_posting_criteria,
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

# Create MCP server
mcp = fastmcp.FastMCP("bpo")


# Candidate Source Tools


@mcp.tool()
def candidate_source_sla_per_source(
    requisition_id: str,
) -> Union[SLAPerSourceResponse, RequisitionNotFoundResponse]:
    """
    Retrieves the SLA percentage for each sourcing channel.

    Args:
        requisition_id: The specific requisition ID to filter SLA data for.

    Returns:
        A dictionary with source names and their SLA percentages.
    """
    logger.info(f"Tool called: candidate_source_sla_per_source(requisition_id={requisition_id})")
    return get_sla_per_source(requisition_id)


@mcp.tool()
def candidate_source_total_hires_by_source(
    requisition_id: str,
) -> Union[TotalHiresBySourceResponse, RequisitionNotFoundResponse]:
    """
    Retrieves the total number of hires per sourcing channel.

    Args:
        requisition_id: The specific requisition ID to filter hiring data for.

    Returns:
        A dictionary with source names and total hires.
    """
    logger.info(f"Tool called: candidate_source_total_hires_by_source(requisition_id={requisition_id})")
    return get_total_hires_by_source(requisition_id)


@mcp.tool()
def candidate_source_candidate_volume_by_source(
    requisition_id: str, sources: Optional[List[str]] = None
) -> Union[CandidateVolumeResponse, RequisitionNotFoundResponse]:
    """
    Retrieves candidate volume per sourcing channel.

    Args:
        requisition_id: The specific requisition ID to filter candidate volume.
        sources: Optional subset of sourcing channels to include (case-sensitive).

    Returns:
        A dictionary with source names and candidate volumes.
    """
    logger.info(f"Tool called: candidate_source_candidate_volume_by_source(requisition_id={requisition_id})")
    return get_candidate_volume_by_source(requisition_id, sources)


@mcp.tool()
def candidate_source_funnel_conversion_by_source(
    requisition_id: str,
) -> Union[FunnelConversionResponse, RequisitionNotFoundResponse]:
    """
    Retrieves conversion rates at each funnel stage for each sourcing channel.

    Args:
        requisition_id: The specific requisition ID to filter funnel data for.

    Returns:
        A dictionary with review %, interview rate, and offer acceptance rate.
    """
    logger.info(f"Tool called: candidate_source_funnel_conversion_by_source(requisition_id={requisition_id})")
    return get_funnel_conversion_by_source(requisition_id)


@mcp.tool()
def candidate_source_metadata_and_timeframe(
    requisition_id: str,
) -> Union[MetadataResponse, RequisitionNotFoundResponse]:
    """
    Retrieves metadata including data timeframe, last update date, and the
    number of requisitions analysed.

    Args:
        requisition_id: The job requisition ID.

    Returns:
        A dictionary containing timeframe and requisition summary.
    """
    logger.info(f"Tool called: candidate_source_metadata_and_timeframe(requisition_id={requisition_id})")
    return get_metadata_and_timeframe(requisition_id)


@mcp.tool()
def candidate_source_definitions_and_methodology(
    requisition_id: str,
) -> Union[DefinitionsResponse, RequisitionNotFoundResponse]:
    """
    Provides definitions of key metrics and outlines the methodology used
    to calculate performance.

    Args:
        requisition_id: The specific requisition ID for context.

    Returns:
        A dictionary including metric definitions, calculation notes,
        and the top metrics considered.
    """
    logger.info(f"Tool called: candidate_source_definitions_and_methodology(requisition_id={requisition_id})")
    return get_definitions_and_methodology(requisition_id)


@mcp.tool()
def candidate_source_source_recommendation_summary(
    requisition_id: str,
) -> Union[SourceRecommendationResponse, RequisitionNotFoundResponse]:
    """
    Returns a high-level summary combining jobs-filled %, review %, offer-accept
    rate, and total hires for each source.

    Args:
        requisition_id: The job requisition ID.

    Returns:
        A dictionary with composite source metrics.
    """
    logger.info(
        f"Tool called: candidate_source_source_recommendation_summary(requisition_id={requisition_id})"
    )
    return get_source_recommendation_summary(requisition_id)


# Skills Tools


@mcp.tool()
def skills_skill_analysis(requisition_id: str) -> Union[SkillAnalysisResponse, RequisitionNotFoundResponse]:
    """
    Provides statistical indicators for each skill associated with the requisition,
    enabling an LLM or analyst to decide whether a skill should be retained,
    removed, or reconsidered.

    Args:
        requisition_id: The job requisition ID.

    Returns:
        Dict with historical counts and SLA correlation per skill.
    """
    logger.info(f"Tool called: skills_skill_analysis(requisition_id={requisition_id})")
    return get_skill_analysis(requisition_id)


@mcp.tool()
def skills_skill_impact_fill_rate(
    requisition_id: str, skill_name: str
) -> Union[SkillImpactFillRateResponse, RequisitionNotFoundResponse]:
    """
    Evaluates how the inclusion of a specific skill affects requisition
    fill-rate metrics and candidate pool size.

    Args:
        requisition_id: The job requisition ID.
        skill_name: The skill to evaluate.

    Returns:
        Impact metrics with and without the skill.
    """
    logger.info(
        f"Tool called: skills_skill_impact_fill_rate(requisition_id={requisition_id}, skill_name={skill_name})"
    )
    return get_skill_impact_fill_rate(requisition_id, skill_name)


@mcp.tool()
def skills_skill_impact_sla(
    requisition_id: str, skill_name: str
) -> Union[SkillImpactSLAResponse, RequisitionNotFoundResponse]:
    """
    Analyzes how a skill affects SLA achievement rate.

    Args:
        requisition_id: The job requisition ID.
        skill_name: The skill being analyzed.

    Returns:
        Success percentages with/without the skill and the delta.
    """
    logger.info(
        f"Tool called: skills_skill_impact_sla(requisition_id={requisition_id}, skill_name={skill_name})"
    )
    return get_skill_impact_sla(requisition_id, skill_name)


@mcp.tool()
def skills_skill_relevance_justification(
    requisition_id: str, skill_name: str
) -> Union[SkillRelevanceResponse, RequisitionNotFoundResponse]:
    """
    Explains whether a skill is relevant and why, based on historical hiring
    success and outcome data.

    Args:
        requisition_id: The job requisition ID.
        skill_name: The skill being justified.

    Returns:
        Relevance determination with justification.
    """
    logger.info(
        f"Tool called: skills_skill_relevance_justification(requisition_id={requisition_id}, skill_name={skill_name})"
    )
    return get_skill_relevance_justification(requisition_id, skill_name)


@mcp.tool()
def skills_successful_posting_criteria() -> SuccessfulPostingResponse:
    """
    Returns the business definition of a successful job posting,
    including thresholds and benchmarks for success.

    Returns:
        Success criteria thresholds.
    """
    logger.info("Tool called: skills_successful_posting_criteria()")
    return get_successful_posting_criteria()


@mcp.tool()
def skills_data_sources_used(requisition_id: str) -> Union[DataSourcesResponse, RequisitionNotFoundResponse]:
    """
    Lists the datasets and ML models used to make hiring recommendations
    for a requisition.

    Args:
        requisition_id: The job requisition ID.

    Returns:
        Data sources and models used.
    """
    logger.info(f"Tool called: skills_data_sources_used(requisition_id={requisition_id})")
    return get_data_sources_used(requisition_id)


if __name__ == "__main__":
    # Run in stdio mode (default for MCP)
    mcp.run()
