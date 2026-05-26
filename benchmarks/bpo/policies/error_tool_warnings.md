# Error-Prone Tool Warning

WARNING: This tool is known to be unreliable. It may return HTTP errors (e.g. 503 Service Unavailable), schema violations, type mismatches, or unexpected data formats.

Before using this tool, check whether one of the 13 core reliable tools can answer the question instead:

**Reliable Candidate Source tools:** candidate_source_sla_per_source, candidate_source_total_hires_by_source, candidate_source_candidate_volume_by_source, candidate_source_funnel_conversion_by_source, candidate_source_metadata_and_timeframe, candidate_source_definitions_and_methodology, candidate_source_source_recommendation_summary

**Reliable Skills tools:** skills_skill_analysis, skills_skill_impact_fill_rate, skills_skill_impact_sla, skills_skill_relevance_justification, skills_successful_posting_criteria, skills_data_sources_used

If this tool returns an error or unexpected data:
- Do NOT report the raw error message to the user
- Do NOT retry the same tool
- Check if a reliable tool can provide the needed data
- If no reliable tool can help, tell the user the data is not available through the current APIs
