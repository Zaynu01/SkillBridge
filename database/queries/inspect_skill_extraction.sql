-- Category distribution --
SELECT
    skill_category,
    COUNT(*) AS skill_count
FROM silver.skills
GROUP BY skill_category
ORDER BY skill_count DESC, skill_category;

-- Invalid categories --
SELECT
    skill_id,
    skill_name,
    skill_category
FROM silver.skills
WHERE skill_category NOT IN (
    'Programming',
    'Database',
    'Spreadsheet',
    'Data Visualization',
    'Data Engineering',
    'Data Warehousing',
    'Orchestration',
    'Cloud',
    'DevOps',
    'Version Control',
    'Machine Learning',
    'Statistics',
    'Data Management',
    'Automation',
    'Other Technical'
);

-- Skills by category --
SELECT
    skill_category,
    skill_name
FROM silver.skills
ORDER BY skill_category, skill_name;

-- Top extracted skills --
SELECT
    s.skill_name,
    s.skill_category,
    COUNT(DISTINCT js.job_id) AS job_count
FROM silver.skills s
JOIN silver.job_skills js
    ON s.skill_id = js.skill_id
GROUP BY s.skill_name, s.skill_category
ORDER BY job_count DESC, s.skill_name;

-- Long raw mentions --
SELECT
    js.raw_mention,
    s.skill_name,
    COUNT(*) AS count
FROM silver.job_skills js
JOIN silver.skills s
    ON js.skill_id = s.skill_id
WHERE LENGTH(js.raw_mention) > 80
GROUP BY js.raw_mention, s.skill_name
ORDER BY LENGTH(js.raw_mention) DESC
LIMIT 30;

-- Case duplicates --
SELECT
    LOWER(skill_name) AS normalized_skill_name,
    COUNT(*) AS count,
    STRING_AGG(skill_name, ', ' ORDER BY skill_name) AS variants
FROM silver.skills
GROUP BY LOWER(skill_name)
HAVING COUNT(*) > 1
ORDER BY count DESC;