SELECT
    LOWER(TRIM(skill_name)) AS normalized_skill_name,
    COUNT(*) AS row_count,
    STRING_AGG(skill_name, ', ' ORDER BY skill_name) AS variants
FROM {{ ref('stg_skills') }}
GROUP BY LOWER(TRIM(skill_name))
HAVING COUNT(*) > 1