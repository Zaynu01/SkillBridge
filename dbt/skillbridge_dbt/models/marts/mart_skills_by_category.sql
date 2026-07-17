-- Shows which skill categories are most common. --

SELECT
    s.skill_category,
    COUNT(DISTINCT s.skill_id) AS distinct_skills_count,
    COUNT(DISTINCT js.job_id) AS jobs_with_category,
    COUNT(*) AS job_skill_links,
    CURRENT_TIMESTAMP AS built_at
FROM {{ ref('stg_skills') }} s
LEFT JOIN {{ ref('stg_job_skills') }} js
    ON s.skill_id = js.skill_id
GROUP BY s.skill_category