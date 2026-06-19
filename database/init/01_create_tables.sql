-- ============================================================
-- SkillBridge Initial Database Schema
-- ============================================================
-- This schema stores job postings, extracted skills,
-- job-skill relationships, and analysis metadata.
-- ============================================================


-- ------------------------------------------------------------
-- 1. Job postings table
-- ------------------------------------------------------------
-- Stores the main information about each job posting.
-- One row = one job posting.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS job_postings (
    job_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    title TEXT NOT NULL,
    company TEXT,
    location TEXT,
    description TEXT NOT NULL,

    posting_date DATE,

    source TEXT NOT NULL,
    source_url TEXT NOT NULL UNIQUE,

    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- ------------------------------------------------------------
-- 2. Skills table
-- ------------------------------------------------------------
-- Stores the standardized skills.
-- One row = one normalized skill.
--
-- Examples:
-- Python
-- SQL
-- PostgreSQL
-- Power BI
-- Docker
-- Airflow
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS skills (
    skill_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    skill_name TEXT NOT NULL UNIQUE,
    skill_category TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- ------------------------------------------------------------
-- 3. Job skills table
-- ------------------------------------------------------------
-- Connects job postings with skills.
--
-- This is a many-to-many table:
-- - One job can require many skills.
-- - One skill can appear in many jobs.
--
-- Example:
-- Job 1 requires Python
-- Job 1 requires SQL
-- Job 2 requires SQL
-- Job 2 requires Docker
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS job_skills (
    job_id BIGINT NOT NULL,
    skill_id BIGINT NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (job_id, skill_id),

    CONSTRAINT fk_job_skills_job
        FOREIGN KEY (job_id)
        REFERENCES job_postings(job_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_job_skills_skill
        FOREIGN KEY (skill_id)
        REFERENCES skills(skill_id)
        ON DELETE CASCADE
);


-- ------------------------------------------------------------
-- 4. Job analysis table
-- ------------------------------------------------------------
-- Stores enriched analysis about each job posting.
--
-- This includes:
-- - detected role
-- - seniority level
-- - whether it is junior friendly
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS job_analysis (
    job_id BIGINT PRIMARY KEY,

    role TEXT,
    seniority_level TEXT NOT NULL DEFAULT 'Unknown',
    junior_friendly BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_job_analysis_job
        FOREIGN KEY (job_id)
        REFERENCES job_postings(job_id)
        ON DELETE CASCADE,

    CONSTRAINT chk_seniority_level
        CHECK (
            seniority_level IN (
                'Internship',
                'Junior',
                'Intermediate',
                'Senior',
                'Unknown'
            )
        )
);


-- ------------------------------------------------------------
-- 5. Useful indexes
-- ------------------------------------------------------------
-- Indexes make searches and joins faster.
-- These will help later when dbt and Streamlit query the database.
-- ------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_job_postings_title
    ON job_postings(title);

CREATE INDEX IF NOT EXISTS idx_job_postings_company
    ON job_postings(company);

CREATE INDEX IF NOT EXISTS idx_job_postings_location
    ON job_postings(location);

CREATE INDEX IF NOT EXISTS idx_job_postings_source
    ON job_postings(source);

CREATE INDEX IF NOT EXISTS idx_skills_skill_name
    ON skills(skill_name);

CREATE INDEX IF NOT EXISTS idx_job_analysis_role
    ON job_analysis(role);

CREATE INDEX IF NOT EXISTS idx_job_analysis_seniority
    ON job_analysis(seniority_level);