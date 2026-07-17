SELECT
    job_id,
    detected_role,
    analysis_method,
    confidence_score,
    role_reason,
    is_excluded_from_analysis,
    exclusion_reason,
    analyzed_at
FROM silver.job_analysis