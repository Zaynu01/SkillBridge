-- ============================================================
-- SkillBridge Database Schema
-- Metadata / Bronze / Silver / Gold Architecture
-- ============================================================
--
-- This database design follows a layered data engineering approach:
--
-- metadata = technical pipeline tracking
-- bronze   = raw ingested data exactly as collected
-- silver   = cleaned, standardized, and enriched data
-- gold     = analytics-ready marts created later by dbt
--
-- Important:
-- - Gold tables are NOT created manually here.
-- - dbt will create gold mart tables later.
-- - This file only prepares the database schemas and core tables.
--
-- ============================================================



-- ============================================================
-- 1. Create Database Schemas
-- ============================================================
--
-- A schema in PostgreSQL is like a namespace or folder inside
-- the database. It helps separate tables by responsibility.
--
-- metadata:
--   Stores technical pipeline information.
--
-- bronze:
--   Stores raw scraped records exactly as collected.
--
-- silver:
--   Stores cleaned and enriched business data.
--
-- gold:
--   Reserved for analytics marts created by dbt later.
--
-- ============================================================

CREATE SCHEMA IF NOT EXISTS metadata;
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;



-- ============================================================
-- 2. Metadata Layer
-- ============================================================
--
-- The metadata layer stores technical information about the
-- pipeline itself.
--
-- This is not raw job data.
-- This is information about pipeline executions.
--
-- Example:
-- - When did the pipeline start?
-- - When did it finish?
-- - Did it succeed or fail?
-- - How many records were processed?
-- - Did any error happen?
--
-- ============================================================



-- ------------------------------------------------------------
-- metadata.pipeline_runs
-- ------------------------------------------------------------
--
-- One row = one execution of the pipeline.
--
-- Example:
--
-- pipeline_run_id: 1
-- run_name: "sample_raw_ingestion"
-- source_name: "sample_linkedin"
-- status: "success"
-- started_at: 2026-06-20 10:00:00+01
-- finished_at: 2026-06-20 10:01:00+01
-- raw_records_count: 3
-- inserted_raw_count: 3
-- cleaned_records_count: 3
-- enriched_records_count: 3
-- failed_records_count: 0
--
-- Why this table exists:
--
-- In real data engineering projects, it is important to know
-- what happened during each pipeline run.
--
-- Without this table, you would not know:
-- - which run loaded which data
-- - whether a run failed
-- - how many records were inserted
-- - what error happened
--
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS metadata.pipeline_runs (
    -- Auto-generated unique identifier for each pipeline run.
    pipeline_run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Optional readable name for the run.
    -- Example: "daily_linkedin_scrape", "sample_raw_ingestion"
    run_name TEXT,

    -- Name of the source processed in this run.
    -- Example: "linkedin", "indeed", "sample_linkedin"
    source_name TEXT,

    -- Current status of the pipeline run.
    -- Default is "running" because a run starts before it finishes.
    status TEXT NOT NULL DEFAULT 'running',

    -- Timestamp when the run started.
    -- TIMESTAMPTZ is used because pipeline events are time-sensitive
    -- and timezone-aware timestamps are safer than plain TIMESTAMP.
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Timestamp when the run finished.
    -- This is NULL while the run is still running.
    finished_at TIMESTAMPTZ,

    -- Number of raw records found by the scraper or raw input.
    raw_records_count INT DEFAULT 0,

    -- Number of raw records successfully inserted into bronze.
    inserted_raw_count INT DEFAULT 0,

    -- Number of records successfully cleaned into silver job postings.
    cleaned_records_count INT DEFAULT 0,

    -- Number of records successfully enriched with skills, role, seniority, etc.
    enriched_records_count INT DEFAULT 0,

    -- Number of records that failed during processing.
    failed_records_count INT DEFAULT 0,

    -- Error details if the pipeline failed.
    -- Keep this as TEXT because error messages can be long.
    error_message TEXT,

    -- Restrict status values to a known controlled list.
    -- This prevents invalid values like "done", "ok", "broken", etc.
    CONSTRAINT chk_pipeline_run_status
        CHECK (
            status IN (
                'running',
                'success',
                'failed',
                'partial_success'
            )
        )
);



-- ============================================================
-- 3. Bronze Layer
-- ============================================================
--
-- Bronze stores raw data exactly as collected.
--
-- Bronze should NOT try to fully understand the job posting.
-- It should not force all websites into the same structure.
--
-- Different websites may return different fields.
--
-- Example source A:
--
-- {
--   "title": "Junior Data Engineer",
--   "company": "ExampleTech",
--   "description": "<p>Python and SQL required</p>"
-- }
--
-- Example source B:
--
-- {
--   "jobName": "BI Analyst Intern",
--   "organization": "DataCorp",
--   "details": "Power BI, SQL, Excel required"
-- }
--
-- Because these structures are different, bronze stores the
-- full raw object inside raw_payload JSONB.
--
-- The interpretation happens later in the silver layer.
--
-- ============================================================



-- ------------------------------------------------------------
-- bronze.raw_job_postings
-- ------------------------------------------------------------
--
-- One row = one raw job posting record.
--
-- This table stores:
-- - which pipeline run produced the raw record
-- - which source it came from
-- - optional source URL
-- - when it was scraped
-- - when it was inserted into the database
-- - the full raw JSON object
-- - a content hash for deduplication
--
-- Why raw_payload JSONB?
--
-- JSONB allows us to store source-specific messy data without
-- forcing it into a fixed structure too early.
--
-- Why content_hash?
--
-- It helps avoid duplicates. If the same raw payload appears
-- again, it should produce the same hash.
--
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS bronze.raw_job_postings (
    raw_job_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    pipeline_run_id BIGINT NOT NULL,

    source_name TEXT NOT NULL,

    -- Source-specific job identifier.
    -- For LinkedIn, this is raw_payload.job_id, for example: 4430018168.
    -- This is more stable than source_url and is used for deduplication.
    source_job_id TEXT,

    source_url TEXT,

    scraped_at TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    raw_payload JSONB NOT NULL,

    -- Hash of the raw payload content.
    -- Useful for debugging and future change detection,
    -- but not the main deduplication key for now.
    content_hash TEXT NOT NULL,

    CONSTRAINT fk_raw_job_postings_pipeline_run
        FOREIGN KEY (pipeline_run_id)
        REFERENCES metadata.pipeline_runs(pipeline_run_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_raw_job_source_job
        UNIQUE (source_name, source_job_id)
);



-- ============================================================
-- 4. Silver Layer
-- ============================================================
--
-- Silver stores cleaned, standardized, and enriched job data.
--
-- This is where raw source-specific fields become a consistent
-- structure that the rest of the project can use.
--
-- Bronze:
--   raw_payload["jobName"]
--   raw_payload["organization"]
--   raw_payload["details"]
--
-- Silver:
--   title
--   company
--   description
--
-- The silver layer is produced by Python cleaning and enrichment
-- logic, not by dbt.
--
-- ============================================================



-- ------------------------------------------------------------
-- silver.job_postings
-- ------------------------------------------------------------
--
-- One row = one cleaned job posting.
--
-- This table stores the standardized job fields:
-- - title
-- - company
-- - location
-- - description
-- - posting_date
-- - source information
--
-- It also links back to bronze.raw_job_postings using raw_job_id.
--
-- This gives traceability:
--
-- silver.job_postings.job_id
--        ↓
-- silver.job_postings.raw_job_id
--        ↓
-- bronze.raw_job_postings.raw_payload
--        ↓
-- metadata.pipeline_runs
--
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS silver.job_postings (
    job_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Link back to the raw bronze record.
    raw_job_id BIGINT NOT NULL,

    -- Link back to the pipeline run that loaded the bronze record.
    pipeline_run_id BIGINT,

    -- Source identity fields.
    source_name TEXT NOT NULL,
    source_job_id TEXT NOT NULL,
    source_url TEXT,

    -- Cleaned job fields.
    job_title TEXT NOT NULL,
    company_name TEXT,
    location_text TEXT,
    country TEXT,
    remote_type TEXT,

    -- Source-provided job metadata.
    employment_type TEXT,
    seniority_level TEXT,
    job_function TEXT,
    industries TEXT,

    -- Text fields used later for role detection, student-fit detection,
    -- and skill extraction.
    posted_time_text TEXT,
    applicants_text TEXT,
    description_text TEXT NOT NULL,
    description_html TEXT,

    -- Timestamps.
    scraped_at TIMESTAMPTZ,
    cleaned_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_silver_job_raw_job
        FOREIGN KEY (raw_job_id)
        REFERENCES bronze.raw_job_postings(raw_job_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_silver_job_pipeline_run
        FOREIGN KEY (pipeline_run_id)
        REFERENCES metadata.pipeline_runs(pipeline_run_id)
        ON DELETE SET NULL,

    CONSTRAINT uq_silver_job_source_job
        UNIQUE (source_name, source_job_id)
);



-- ------------------------------------------------------------
-- silver.skills
-- ------------------------------------------------------------
--
-- One row = one canonical skill.
--
-- Canonical means the official standardized name we want to use.
--
-- Good examples:
-- - Python
-- - SQL
-- - PostgreSQL
-- - Power BI
-- - Docker
-- - Airflow
--
-- Bad examples for this table:
-- - powerbi
-- - PowerBI
-- - postgres
-- - Apache Airflow
--
-- Those alternative names belong in silver.skill_aliases.
--
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS silver.skills (
    -- Auto-generated unique identifier for each skill.
    skill_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Canonical skill name.
    -- Example: "PostgreSQL", not "postgres".
    skill_name TEXT NOT NULL UNIQUE,

    -- Optional category for grouping skills.
    -- Example: "Programming", "Database", "BI Tool", "DevOps"
    skill_category TEXT,

    -- Row creation timestamp.
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Row update timestamp.
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);



-- ------------------------------------------------------------
-- silver.skill_aliases
-- ------------------------------------------------------------
--
-- One row = one alternative name for a canonical skill.
--
-- Example:
--
-- alias_name       canonical skill
-- --------------------------------
-- Postgres         PostgreSQL
-- PostgreSQL       PostgreSQL
-- PowerBI          Power BI
-- Apache Airflow   Airflow
--
-- This table helps the NLP-lite skill extraction logic normalize
-- different spellings into one official skill name.
--
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS silver.skill_aliases (
    -- Auto-generated unique identifier for each alias.
    skill_alias_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- The canonical skill this alias points to.
    skill_id BIGINT NOT NULL,

    -- Alternative skill name.
    -- Example: "postgres", "PowerBI", "Apache Spark"
    alias_name TEXT NOT NULL,

    -- Row creation timestamp.
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Link alias to canonical skill.
    -- If the canonical skill is deleted, its aliases are deleted too.
    CONSTRAINT fk_skill_aliases_skill
        FOREIGN KEY (skill_id)
        REFERENCES silver.skills(skill_id)
        ON DELETE CASCADE,

    -- Prevent the same alias from pointing to multiple skills.
    CONSTRAINT uq_skill_alias_name
        UNIQUE (alias_name)
);



-- ------------------------------------------------------------
-- silver.job_skills
-- ------------------------------------------------------------
--
-- Many-to-many relationship between jobs and skills.
--
-- One job can require many skills.
-- One skill can appear in many jobs.
--
-- Example:
--
-- Junior Data Engineer -> Python
-- Junior Data Engineer -> SQL
-- Junior Data Engineer -> Docker
-- BI Analyst Intern    -> SQL
-- BI Analyst Intern    -> Power BI
--
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS silver.job_skills (
    -- Cleaned job identifier.
    job_id BIGINT NOT NULL,

    -- Canonical skill identifier.
    skill_id BIGINT NOT NULL,

    -- Where the skill was detected from.
    -- Example: "description", "title", "requirements_section"
    detected_from TEXT DEFAULT 'description',

    -- Optional confidence score.
    -- For regex/dictionary matching, this can be NULL or 1.0.
    -- If later you use fuzzy matching or embeddings, this becomes useful.
    confidence_score NUMERIC(5, 4),

    -- Row creation timestamp.
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Composite primary key.
    -- This prevents the same skill being attached to the same job twice.
    PRIMARY KEY (job_id, skill_id),

    -- Link to cleaned job.
    -- If a job is deleted, its job-skill links are deleted.
    CONSTRAINT fk_job_skills_job
        FOREIGN KEY (job_id)
        REFERENCES silver.job_postings(job_id)
        ON DELETE CASCADE,

    -- Link to canonical skill.
    -- If a skill is deleted, its job-skill links are deleted.
    CONSTRAINT fk_job_skills_skill
        FOREIGN KEY (skill_id)
        REFERENCES silver.skills(skill_id)
        ON DELETE CASCADE,

    -- Confidence score must be between 0 and 1 when provided.
    CONSTRAINT chk_skill_confidence_score
        CHECK (
            confidence_score IS NULL
            OR (
                confidence_score >= 0
                AND confidence_score <= 1
            )
        )
);



-- ------------------------------------------------------------
-- silver.job_analysis
-- ------------------------------------------------------------
--
-- One row = analysis/enrichment result for one job.
--
-- This table stores derived information:
-- - detected role
-- - seniority level
-- - junior friendliness
-- - detected language
-- - analysis notes
--
-- It is separated from silver.job_postings because this information
-- is not raw job data; it is generated by our enrichment logic.
--
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS silver.job_analysis (
    -- Same ID as silver.job_postings.job_id.
    -- This means one job has at most one analysis row.
    job_id BIGINT PRIMARY KEY,

    -- Detected role.
    -- Example: "Data Engineer", "BI Analyst", "Data Scientist"
    role TEXT,

    -- Detected seniority level.
    -- Default is "Unknown" because we should not guess when the
    -- title/description does not provide enough evidence.
    seniority_level TEXT NOT NULL DEFAULT 'Unknown',

    -- Whether the job appears suitable for a junior/student profile.
    junior_friendly BOOLEAN DEFAULT FALSE,

    -- Optional detected language.
    -- Example: "en", "fr", "unknown"
    detected_language TEXT,

    -- Optional notes from the analysis logic.
    -- Example: "No seniority keyword found"
    analysis_notes TEXT,

    -- Timestamp when analysis was created.
    analyzed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Timestamp when analysis was last updated.
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Link analysis to cleaned job.
    -- If the job is deleted, its analysis is deleted too.
    CONSTRAINT fk_job_analysis_job
        FOREIGN KEY (job_id)
        REFERENCES silver.job_postings(job_id)
        ON DELETE CASCADE,

    -- Restrict seniority values to the allowed categories.
    -- This matches the project rule-based seniority design.
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



-- ============================================================
-- 5. Indexes
-- ============================================================
--
-- Indexes improve query speed.
--
-- They are useful for:
-- - filtering pipeline runs by status/date
-- - finding raw jobs by source
-- - joining bronze to silver
-- - finding skills quickly
-- - future dbt transformations
-- - future Streamlit dashboard queries
--
-- ============================================================



-- ------------------------------------------------------------
-- Metadata indexes
-- ------------------------------------------------------------

-- Speeds up queries like:
-- SELECT * FROM metadata.pipeline_runs WHERE status = 'failed';
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status
    ON metadata.pipeline_runs(status);

-- Speeds up queries ordered or filtered by pipeline start time.
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started_at
    ON metadata.pipeline_runs(started_at);



-- ------------------------------------------------------------
-- Bronze indexes
-- ------------------------------------------------------------

-- Speeds up joins from bronze raw jobs to metadata pipeline runs.
CREATE INDEX IF NOT EXISTS idx_raw_job_postings_pipeline_run_id
    ON bronze.raw_job_postings(pipeline_run_id);

-- Speeds up filtering raw records by source.
CREATE INDEX IF NOT EXISTS idx_raw_job_postings_source_name
    ON bronze.raw_job_postings(source_name);

-- Speeds up lookup by original job URL when available.
CREATE INDEX IF NOT EXISTS idx_raw_job_postings_source_url
    ON bronze.raw_job_postings(source_url);

-- Speeds up duplicate checking and debugging by content hash.
CREATE INDEX IF NOT EXISTS idx_raw_job_postings_content_hash
    ON bronze.raw_job_postings(content_hash);

-- Speeds up filtering raw records by ingestion time.
CREATE INDEX IF NOT EXISTS idx_raw_job_postings_ingested_at
    ON bronze.raw_job_postings(ingested_at);



-- ------------------------------------------------------------
-- Silver indexes
-- ------------------------------------------------------------

-- Speeds up tracing a silver job back to its bronze raw record.
CREATE INDEX IF NOT EXISTS idx_silver_job_postings_raw_job_id
    ON silver.job_postings(raw_job_id);

-- Speeds up searches/filtering by title.
CREATE INDEX IF NOT EXISTS idx_silver_job_postings_title
    ON silver.job_postings(title);

-- Speeds up searches/filtering by company.
CREATE INDEX IF NOT EXISTS idx_silver_job_postings_company
    ON silver.job_postings(company);

-- Speeds up searches/filtering by location.
CREATE INDEX IF NOT EXISTS idx_silver_job_postings_location
    ON silver.job_postings(location);

-- Speeds up filtering cleaned jobs by source.
CREATE INDEX IF NOT EXISTS idx_silver_job_postings_source_name
    ON silver.job_postings(source_name);

-- Speeds up skill lookup by canonical skill name.
CREATE INDEX IF NOT EXISTS idx_silver_skills_skill_name
    ON silver.skills(skill_name);

-- Speeds up alias lookup during skill normalization.
CREATE INDEX IF NOT EXISTS idx_silver_skill_aliases_alias_name
    ON silver.skill_aliases(alias_name);

-- Speeds up dbt/dashboard queries by role.
CREATE INDEX IF NOT EXISTS idx_silver_job_analysis_role
    ON silver.job_analysis(role);

-- Speeds up dbt/dashboard queries by seniority level.
CREATE INDEX IF NOT EXISTS idx_silver_job_analysis_seniority
    ON silver.job_analysis(seniority_level);