-- For each role, what skills are most demanded? --

WITH eligible_jobs AS (
    SELECT
        p.job_id,
        a.detected_role
    FROM {{ ref('stg_job_postings') }} p
    JOIN {{ ref('stg_job_analysis') }} a
        ON p.job_id = a.job_id
    WHERE a.is_excluded_from_analysis = false
      AND a.detected_role NOT IN ('unknown', 'other')
),

role_totals AS (
    SELECT
        detected_role,
        COUNT(DISTINCT job_id) AS total_jobs_for_role
    FROM eligible_jobs
    GROUP BY detected_role
),

skill_counts AS (
    SELECT
        ej.detected_role,
        js.skill_id,
        COUNT(DISTINCT ej.job_id) AS jobs_with_skill
    FROM eligible_jobs ej
    JOIN {{ ref('stg_job_skills') }} js
        ON ej.job_id = js.job_id
    GROUP BY
        ej.detected_role,
        js.skill_id
),

final AS (
    SELECT
        sc.detected_role,
        s.skill_id,
        s.skill_name,
        s.skill_category,
        sc.jobs_with_skill,
        rt.total_jobs_for_role,
        ROUND(
            sc.jobs_with_skill * 100.0 / NULLIF(rt.total_jobs_for_role, 0),
            2
        ) AS demand_percentage
    FROM skill_counts sc
    JOIN role_totals rt
        ON sc.detected_role = rt.detected_role
    JOIN {{ ref('stg_skills') }} s
        ON sc.skill_id = s.skill_id
)

SELECT
    detected_role,
    skill_id,
    skill_name,
    skill_category,
    jobs_with_skill,
    total_jobs_for_role,
    demand_percentage,

    RANK() OVER (
        PARTITION BY detected_role
        ORDER BY jobs_with_skill DESC, skill_name
    ) AS skill_rank,

    CURRENT_TIMESTAMP AS built_at
FROM final