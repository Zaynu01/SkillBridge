-- One job can link to one skill only once --
SELECT
    job_id,
    skill_id,
    COUNT(*) AS row_count
FROM {{ ref('stg_job_skills') }}
GROUP BY
    job_id,
    skill_id
HAVING COUNT(*) > 1