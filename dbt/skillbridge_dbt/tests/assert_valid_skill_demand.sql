-- A skill cannot appear in more jobs than the total number of jobs for that role. --
SELECT
    detected_role,
    skill_id,
    skill_name,
    jobs_with_skill,
    total_jobs_for_role,
    demand_percentage
FROM {{ ref('mart_top_skills_by_role') }}
WHERE demand_percentage < 0
   OR demand_percentage > 100
   OR jobs_with_skill < 0
   OR total_jobs_for_role <= 0
   OR jobs_with_skill > total_jobs_for_role