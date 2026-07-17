WITH jobs AS (
    SELECT
        p.job_id,
        p.company_name,
        p.source_name,
        a.detected_role,
        a.is_excluded_from_analysis
    FROM {{ ref('stg_job_postings') }} p
    LEFT JOIN {{ ref('stg_job_analysis') }} a
        ON p.job_id = a.job_id
),

skills AS (
    SELECT DISTINCT skill_id
    FROM {{ ref('stg_skills') }}
),

job_skills AS (
    SELECT DISTINCT job_id, skill_id
    FROM {{ ref('stg_job_skills') }}
)

SELECT
    COUNT(DISTINCT job_id) AS total_jobs,
    COUNT(DISTINCT company_name) AS total_companies,
    COUNT(DISTINCT source_name) AS total_sources,
    COUNT(DISTINCT detected_role) AS total_detected_roles,

    COUNT(DISTINCT CASE
        WHEN is_excluded_from_analysis = false THEN job_id
    END) AS analyzable_jobs,

    COUNT(DISTINCT CASE
        WHEN is_excluded_from_analysis = true THEN job_id
    END) AS excluded_jobs,

    (SELECT COUNT(*) FROM skills) AS total_skills,
    (SELECT COUNT(*) FROM job_skills) AS total_job_skill_links,

    CURRENT_TIMESTAMP AS built_at
FROM jobs