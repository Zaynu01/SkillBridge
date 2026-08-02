-- Test one row per role and skill --
SELECT
    detected_role,
    skill_id,
    COUNT(*) AS row_count
FROM {{ ref('mart_top_skills_by_role') }}
GROUP BY
    detected_role,
    skill_id
HAVING COUNT(*) > 1