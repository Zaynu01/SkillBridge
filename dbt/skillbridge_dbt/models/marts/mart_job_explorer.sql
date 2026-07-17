-- One row per job with all extracted skills combined. --

SELECT
    p.job_id,
    p.job_title,
    p.company_name,
    p.location_text,
    p.country,
    p.remote_type,
    p.employment_type,
    p.seniority_level,
    a.detected_role,
    a.confidence_score AS role_confidence_score,
    a.is_excluded_from_analysis,
    a.exclusion_reason,
    p.source_name,
    p.source_url,

    STRING_AGG(DISTINCT s.skill_name, ', ' ORDER BY s.skill_name) AS skill_names,
    STRING_AGG(DISTINCT s.skill_category, ', ' ORDER BY s.skill_category) AS skill_categories,

    CURRENT_TIMESTAMP AS built_at
FROM {{ ref('stg_job_postings') }} p
LEFT JOIN {{ ref('stg_job_analysis') }} a
    ON p.job_id = a.job_id
LEFT JOIN {{ ref('stg_job_skills') }} js
    ON p.job_id = js.job_id
LEFT JOIN {{ ref('stg_skills') }} s
    ON js.skill_id = s.skill_id
GROUP BY
    p.job_id,
    p.job_title,
    p.company_name,
    p.location_text,
    p.country,
    p.remote_type,
    p.employment_type,
    p.seniority_level,
    a.detected_role,
    a.confidence_score,
    a.is_excluded_from_analysis,
    a.exclusion_reason,
    p.source_name,
    p.source_url