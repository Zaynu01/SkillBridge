"""
AI-assisted skill extraction for SkillBridge.

This script reads cleaned job postings from:

    silver.job_postings

It sends each job title and description to OpenAI, asks for structured
technical skill extraction, validates the response, then stores the
results in:

    silver.skills
    silver.skill_aliases
    silver.job_skills

This script does NOT scrape jobs.
This script does NOT clean raw HTML.
This script works only after:
    1. bronze.raw_job_postings is loaded
    2. silver.job_postings is populated
    3. silver.job_analysis is populated

Main idea:
    AI extracts and normalizes skills.
    Python validates and protects the database.
    PostgreSQL stores canonical skills and job-skill links.
"""

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import psycopg
from openai import OpenAI
from psycopg.rows import dict_row


# ============================================================
# Configuration
# ============================================================

DEFAULT_MODEL = "gpt-4.1-mini"

# Limit description length to control token usage and cost.
# Most skills appear in the first part / requirements part of a job description.
MAX_DESCRIPTION_CHARACTERS = 6000

# Small pause between API calls to avoid sending requests too aggressively.
DEFAULT_DELAY_SECONDS = 0.5


# Categories we allow in silver.skills.
# The AI can return slightly different words, so we normalize categories later.
ALLOWED_SKILL_CATEGORIES = {
    "Programming",
    "Database",
    "Spreadsheet",
    "Data Visualization",
    "Data Engineering",
    "Data Warehousing",
    "Orchestration",
    "Cloud",
    "DevOps",
    "Version Control",
    "Machine Learning",
    "Statistics",
    "Data Management",
    "Automation",
    "Other Technical",
}   


# Common AI naming corrections.
# This is not a huge manual taxonomy.
# It only enforces canonical names for common cases.
CANONICAL_SKILL_OVERRIDES = {
    "Apache Spark": "Spark",
    "PySpark": "Spark",
    "Apache Airflow": "Airflow",
    "Apache Kafka": "Kafka",
    "Microsoft Power BI": "Power BI",
    "PowerBI": "Power BI",
    "Postgres": "PostgreSQL",
    "Postgre SQL": "PostgreSQL",
    "Google Cloud Platform": "GCP",
    "Amazon Web Services": "AWS",
    "Microsoft Azure": "Azure",
    "Data Build Tool": "dbt",
    "DBT": "dbt",
    "AI": "Artificial Intelligence",
    "A.I.": "Artificial Intelligence",
    "Database": "Databases",
}


# Normalize category names returned by AI.
# This prevents many category variants from entering the database.
CATEGORY_OVERRIDES = {
    # Programming
    "Programming Language": "Programming",
    "Scripting Language": "Programming",

    # Database
    "Query Language": "Database",
    "Database Technology": "Database",
    "Relational Database": "Database",
    "Relational Databases": "Database",

    # Data Visualization
    "Business Intelligence": "Data Visualization",
    "BI": "Data Visualization",
    "BI Tool": "Data Visualization",
    "BI Tools": "Data Visualization",
    "Visualization": "Data Visualization",
    "Dashboarding": "Data Visualization",
    "Dashboard": "Data Visualization",
    "Dashboards": "Data Visualization",
    "Reporting": "Data Visualization",
    "Reporting Tool": "Data Visualization",
    "Reporting Tools": "Data Visualization",

    # Data Engineering
    "Big Data Processing": "Data Engineering",
    "Data Pipeline": "Data Engineering",
    "Data Pipelines": "Data Engineering",
    "ETL": "Data Engineering",
    "ELT": "Data Engineering",
    "Data Modeling": "Data Engineering",
    "Dimensional Modeling": "Data Engineering",

    # Data Warehousing
    "Data Warehouse": "Data Warehousing",
    "Data Warehouses": "Data Warehousing",
    "Cloud Data Warehouse": "Data Warehousing",
    "Cloud Data Warehousing": "Data Warehousing",

    # Orchestration
    "Workflow Orchestration": "Orchestration",
    "Pipeline Orchestration": "Orchestration",

    # Cloud
    "Cloud Platform": "Cloud",
    "Cloud Computing": "Cloud",
    "Cloud Services": "Cloud",

    # DevOps
    "Containerization": "DevOps",
    "Containerisation": "DevOps",

    # Version Control
    "Version Control System": "Version Control",

    # Machine Learning
    "ML": "Machine Learning",
    "AI": "Machine Learning",
    "Artificial Intelligence": "Machine Learning",
    "Machine Learning Framework": "Machine Learning",
    "Data Mining": "Machine Learning",
    "Predictive Modeling": "Machine Learning",

    # Statistics
    "Statistical Modeling": "Statistics",
    "Statistical Analysis": "Statistics",
    "A/B Testing": "Statistics",
    "Hypothesis Testing": "Statistics",

    # Data Management
    "Data Governance": "Data Management",
    "Data Quality": "Data Management",
    "Data Lineage": "Data Management",
    "Metadata Management": "Data Management",

    # Automation
    "Workflow Automation": "Automation",
    "Process Automation": "Automation",
}

SKILL_CATEGORY_OVERRIDES = {
    "SQL": "Database",
    "Databases": "Database",
    "Microsoft Access": "Database",
    "Oracle": "Database",

    "Artificial Intelligence": "Machine Learning",

    "Power BI": "Data Visualization",
    "Tableau": "Data Visualization",
    "Looker": "Data Visualization",
    "Google Analytics": "Data Visualization",

    "Python": "Programming",
    "R": "Programming",
    "NumPy": "Programming",

    "Excel": "Spreadsheet",
}


# Skills/phrases that should not become canonical technical skills.
# This protects the dashboard from vague or soft-skill pollution.
REJECTED_SKILL_NAMES = {
    "communication",
    "teamwork",
    "leadership",
    "problem solving",
    "problem-solving",
    "collaboration",
    "stakeholder management",
    "attention to detail",
    "fast-paced environment",
    "data",
    "tools",
    "technology",
    "technologies",
    "software",
    "business",
    "analytics",
    "reporting",
    "PowerPoint",
}


# ============================================================
# Data classes
# ============================================================

@dataclass(frozen=True)
class ExtractedSkill:
    """
    One validated skill extracted from a job posting.

    skill_name:
        Canonical normalized skill name.
        Example: PostgreSQL

    skill_category:
        Normalized category.
        Example: Database

    raw_mention:
        Exact or approximate text mentioned in the job description.
        Example: Postgres

    confidence_score:
        AI confidence between 0 and 1.
    """

    skill_name: str
    skill_category: str
    raw_mention: str | None
    confidence_score: float | None


# ============================================================
# Database and OpenAI clients
# ============================================================

def get_database_connection() -> psycopg.Connection:
    """
    Create a PostgreSQL connection using Docker/.env environment variables.

    Required environment variables:
        POSTGRES_USER
        POSTGRES_PASSWORD
        POSTGRES_DB

    Optional:
        POSTGRES_HOST defaults to postgres
        POSTGRES_PORT defaults to 5432
    """

    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    database = os.getenv("POSTGRES_DB")
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")

    missing_values = []

    if not user:
        missing_values.append("POSTGRES_USER")

    if not password:
        missing_values.append("POSTGRES_PASSWORD")

    if not database:
        missing_values.append("POSTGRES_DB")

    if missing_values:
        raise RuntimeError(
            "Missing required database environment variables: "
            + ", ".join(missing_values)
        )

    connection_string = (
        f"host={host} "
        f"port={port} "
        f"dbname={database} "
        f"user={user} "
        f"password={password}"
    )

    return psycopg.connect(connection_string, row_factory=dict_row)


def get_openai_client() -> OpenAI:
    """
    Create an OpenAI client using OPENAI_API_KEY.

    The API key must be stored in .env and passed by docker-compose.
    Never hardcode the key in source code.
    """

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing. Add it to your .env file."
        )

    return OpenAI(api_key=api_key)


# ============================================================
# Text normalization helpers
# ============================================================

def normalize_whitespace(value: str | None) -> str:
    """
    Normalize whitespace.

    Example:
        "  Power   BI\\n" -> "Power BI"
    """

    if value is None:
        return ""

    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_lookup_key(value: str | None) -> str:
    """
    Normalize a string for lookup/comparison.

    Example:
        " PowerBI " -> "powerbi"
        "Apache Airflow" -> "apache airflow"
    """

    return normalize_whitespace(value).lower()


def normalize_skill_name(skill_name: str) -> str:
    """
    Normalize a skill name returned by AI.

    This function applies small canonical overrides.

    Example:
        Apache Spark -> Spark
        PowerBI -> Power BI
        Postgres -> PostgreSQL
    """

    cleaned = normalize_whitespace(skill_name)

    if not cleaned:
        return ""

    # Case-insensitive override lookup.
    override_map = {
        normalize_lookup_key(key): value
        for key, value in CANONICAL_SKILL_OVERRIDES.items()
    }

    lookup_key = normalize_lookup_key(cleaned)

    return override_map.get(lookup_key, cleaned)


def normalize_skill_category(
    skill_name: str,
    category: str | None,
) -> str:
    """
    Normalize and validate a skill category.

    Priority:
    1. If this is an obvious known skill, use its fixed category.
    2. Otherwise normalize the AI category using CATEGORY_OVERRIDES.
    3. If still invalid, use Other Technical.
    """

    if skill_name in SKILL_CATEGORY_OVERRIDES:
        return SKILL_CATEGORY_OVERRIDES[skill_name]

    cleaned = normalize_whitespace(category)

    if not cleaned:
        return "Other Technical"

    override_map = {
        normalize_lookup_key(key): value
        for key, value in CATEGORY_OVERRIDES.items()
    }

    lookup_key = normalize_lookup_key(cleaned)
    normalized = override_map.get(lookup_key, cleaned)

    if normalized not in ALLOWED_SKILL_CATEGORIES:
        return "Other Technical"

    return normalized


def clean_json_output(output_text: str) -> str:
    """
    Clean AI output before JSON parsing.

    Sometimes the model returns JSON wrapped in Markdown:

        ```json
        {...}
        ```

    json.loads() cannot parse backticks, so we remove them.
    """

    cleaned = output_text.strip()

    if cleaned.startswith("```json"):
        cleaned = cleaned.removeprefix("```json").strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```").strip()

    if cleaned.endswith("```"):
        cleaned = cleaned.removesuffix("```").strip()

    return cleaned


def truncate_description(description_text: str | None) -> str:
    """
    Limit description length to control token usage.

    We keep the beginning of the description because most job posts list
    requirements/tools in the early or middle sections.
    """

    cleaned = normalize_whitespace(description_text)

    if len(cleaned) <= MAX_DESCRIPTION_CHARACTERS:
        return cleaned

    return cleaned[:MAX_DESCRIPTION_CHARACTERS]


# ============================================================
# Validation
# ============================================================

def is_rejected_skill_name(skill_name: str) -> bool:
    """
    Decide whether a skill should be rejected.

    This avoids inserting vague or soft skills into silver.skills.
    """

    lookup_key = normalize_lookup_key(skill_name)

    if lookup_key in REJECTED_SKILL_NAMES:
        return True

    # Avoid very long phrases becoming skills.
    if len(skill_name) > 80:
        return True

    # Avoid extremely short garbage, but allow R.
    if len(skill_name) < 2 and skill_name != "R":
        return True

    return False


def parse_confidence_score(value: Any) -> float | None:
    """
    Convert confidence score to float and validate it.

    Returns None if invalid.
    """

    if value is None:
        return None

    try:
        score = float(value)
    except (TypeError, ValueError):
        return None

    if score < 0 or score > 1:
        return None

    return score


def validate_and_normalize_skill_item(item: dict[str, Any]) -> ExtractedSkill | None:
    """
    Validate one skill item returned by AI.

    If the item is invalid, return None so it is skipped.
    """

    raw_skill_name = item.get("skill_name")

    if not raw_skill_name:
        return None

    skill_name = normalize_skill_name(str(raw_skill_name))

    if not skill_name:
        return None

    if is_rejected_skill_name(skill_name):
        return None

    skill_category = normalize_skill_category(
                        skill_name=skill_name,
                        category=item.get("skill_category"),
                    )

    raw_mention = normalize_whitespace(item.get("raw_mention"))

    if not raw_mention:
        raw_mention = skill_name

    confidence_score = parse_confidence_score(item.get("confidence_score"))

    return ExtractedSkill(
        skill_name=skill_name,
        skill_category=skill_category,
        raw_mention=raw_mention,
        confidence_score=confidence_score,
    )


def deduplicate_skills(skills: list[ExtractedSkill]) -> list[ExtractedSkill]:
    """
    Remove duplicate skills from one job.

    If the same canonical skill appears multiple times, keep the one with
    the highest confidence score.
    """

    best_by_skill_name: dict[str, ExtractedSkill] = {}

    for skill in skills:
        key = normalize_lookup_key(skill.skill_name)

        existing = best_by_skill_name.get(key)

        if existing is None:
            best_by_skill_name[key] = skill
            continue

        existing_score = existing.confidence_score or 0
        new_score = skill.confidence_score or 0

        if new_score > existing_score:
            best_by_skill_name[key] = skill

    return list(best_by_skill_name.values())


# ============================================================
# OpenAI extraction
# ============================================================

def build_skill_extraction_prompt(
    job_title: str,
    description_text: str,
) -> str:
    """
    Build the prompt sent to OpenAI.

    The prompt asks for valid JSON only and gives strict extraction rules.
    """

    return f"""
You are extracting technical skills from job postings for a data job market analytics project.

Return valid JSON only. Do not wrap the JSON in Markdown.

Use this exact structure:
{{
  "skills": [
    {{
      "skill_name": "Canonical skill name",
      "skill_category": "Category",
      "raw_mention": "Exact text from the job posting",
      "confidence_score": 0.95
    }}
  ]
}}

Rules:
- Extract only technical, data, analytics, software, cloud, database, BI, machine learning, or data engineering skills.
- Do not extract soft skills such as communication, teamwork, leadership, ownership, stakeholder management, or problem solving.
- Normalize skill names to common canonical names.
- Prefer "Spark" over "Apache Spark".
- Prefer "Airflow" over "Apache Airflow".
- Prefer "Kafka" over "Apache Kafka".
- Prefer "Power BI" over "PowerBI" or "Microsoft Power BI".
- Prefer "PostgreSQL" over "Postgres".
- Prefer "dbt" over "Data Build Tool".
- confidence_score must be a number between 0 and 1.
- If no technical skills are found, return: {{"skills": []}}

Use only one of these skill_category values:
- Programming
- Database
- Spreadsheet
- Data Visualization
- Data Engineering
- Data Warehousing
- Orchestration
- Cloud
- DevOps
- Version Control
- Machine Learning
- Statistics
- Data Management
- Automation
- Other Technical

Do not invent new categories.

Classify dashboarding, BI, reporting, and visualization tools such as Power BI, Tableau, Looker, Qlik, Sigma, and Looker Studio as Data Visualization.

Classify data modeling, dimensional modeling, ETL, ELT, and data pipelines as Data Engineering.

Classify Snowflake, BigQuery, Redshift, Delta Lake, and data warehouse concepts as Data Warehousing.

Classify Data Quality, Data Governance, Data Lineage, and Metadata Management as Data Management.

Classify Data Mining and Predictive Modeling as Machine Learning.

Classify Statistical Modeling, A/B Testing, and Hypothesis Testing as Statistics.

Important raw_mention rule:
- raw_mention must be the shortest exact phrase from the job posting.
- raw_mention must refer to only one skill.
- Do not use a full sentence.
- Do not use a phrase containing multiple skills.
- If a phrase contains multiple skills, split them into separate skills.

Examples:
If the job says: "cloud data platforms (Snowflake or AWS preferred)"
Return:
- skill_name: "Snowflake", raw_mention: "Snowflake"
- skill_name: "AWS", raw_mention: "AWS"

Do not return:
- skill_name: "Snowflake", raw_mention: "cloud data platforms (Snowflake or AWS preferred)"
- skill_name: "AWS", raw_mention: "cloud data platforms (Snowflake or AWS preferred)"

If the job says: "Tableau, Power BI, or Looker"
Return:
- skill_name: "Tableau", raw_mention: "Tableau"
- skill_name: "Power BI", raw_mention: "Power BI"
- skill_name: "Looker", raw_mention: "Looker"

Normalize these names consistently:
- AI -> Artificial Intelligence
- A.I. -> Artificial Intelligence
- Database -> Databases
- Databases -> Databases

Classify:
- SQL as Database
- Databases as Database
- Artificial Intelligence as Machine Learning 

Job title:
{job_title}

Job description:
{description_text}
""".strip()


def extract_skills_with_openai(
    client: OpenAI,
    job_title: str,
    description_text: str,
    model: str,
) -> list[ExtractedSkill]:
    """
    Call OpenAI and return validated extracted skills.
    """

    prompt = build_skill_extraction_prompt(
        job_title=job_title,
        description_text=description_text,
    )

    response = client.responses.create(
        model=model,
        input=prompt,
    )

    output_text = response.output_text
    cleaned_output = clean_json_output(output_text)

    try:
        parsed = json.loads(cleaned_output)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "OpenAI response could not be parsed as JSON. "
            f"Raw response: {output_text}"
        ) from error

    raw_skills = parsed.get("skills")

    if raw_skills is None:
        return []

    if not isinstance(raw_skills, list):
        raise RuntimeError("OpenAI JSON field 'skills' must be a list.")

    validated_skills = []

    for item in raw_skills:
        if not isinstance(item, dict):
            continue

        skill = validate_and_normalize_skill_item(item)

        if skill is not None:
            validated_skills.append(skill)

    return deduplicate_skills(validated_skills)


# ============================================================
# Database operations
# ============================================================

def fetch_jobs_for_skill_extraction(
    connection: psycopg.Connection,
    limit: int | None = None,
    only_missing: bool = True,
) -> list[dict[str, Any]]:
    """
    Fetch jobs from silver.job_postings for skill extraction.

    only_missing=True means:
        Skip jobs that already have at least one skill in silver.job_skills.

    This is useful to avoid repeated API calls during normal runs.

    If you improve the prompt and want to re-extract everything, run with:
        --force
    """

    query = """
        SELECT
            p.job_id,
            p.job_title,
            p.description_text
        FROM silver.job_postings p
        LEFT JOIN silver.job_analysis a
            ON p.job_id = a.job_id
        WHERE
            p.description_text IS NOT NULL
            AND COALESCE(a.is_excluded_from_analysis, FALSE) = FALSE
    """

    params: dict[str, Any] = {}

    if only_missing:
        query += """
            AND NOT EXISTS (
                SELECT 1
                FROM silver.job_skills js
                WHERE js.job_id = p.job_id
            )
        """

    query += """
        ORDER BY p.job_id
    """

    if limit is not None:
        query += " LIMIT %(limit)s"
        params["limit"] = limit

    query += ";"

    with connection.cursor() as cursor:
        records = cursor.execute(query, params).fetchall()

    return list(records)


def upsert_skill(
    connection: psycopg.Connection,
    skill: ExtractedSkill,
) -> int:
    """
    Insert a canonical skill if it does not exist.

    Category rule:
    - New skill: use the validated AI category.
    - Existing skill: keep the existing database category.
    - Existing skill with NULL category: fill it.

    This prevents category flip-flopping.
    """

    query = """
        INSERT INTO silver.skills (
            skill_name,
            skill_category
        )
        VALUES (
            %(skill_name)s,
            %(skill_category)s
        )
        ON CONFLICT (skill_name)
        DO UPDATE SET
            skill_category = COALESCE(
                NULLIF(silver.skills.skill_category, ''),
                EXCLUDED.skill_category
            ),
            updated_at = CURRENT_TIMESTAMP
        RETURNING skill_id;
    """

    with connection.cursor() as cursor:
        result = cursor.execute(
            query,
            {
                "skill_name": skill.skill_name,
                "skill_category": skill.skill_category,
            },
        ).fetchone()

    return int(result["skill_id"])


def is_safe_alias(raw_mention: str | None, skill_name: str) -> bool:
    """
    Decide whether a raw mention is safe to store as an alias.

    We want aliases like:
        postgres -> PostgreSQL
        powerbi -> Power BI
        apache airflow -> Airflow

    We do not want aliases like:
        cloud data platforms (snowflake or aws preferred) -> Snowflake

    because that broad phrase contains multiple possible skills.
    """

    cleaned = normalize_whitespace(raw_mention)

    if not cleaned:
        return False

    normalized_alias = normalize_lookup_key(cleaned)
    normalized_skill = normalize_lookup_key(skill_name)

    if not normalized_alias:
        return False

    # The canonical skill name itself is always a safe alias.
    if normalized_alias == normalized_skill:
        return True

    # Very long aliases are usually phrases, not clean skill mentions.
    if len(cleaned) > 60:
        return False

    # Too many words usually means a description phrase, not a skill mention.
    if len(cleaned.split()) > 6:
        return False

    lowered = cleaned.lower()

    # These markers often mean the phrase contains multiple skills or context.
    broad_phrase_markers = [
        " or ",
        " and ",
        ",",
        ";",
        "(",
        ")",
        " such as ",
        " including ",
        " preferred",
        " experience with ",
    ]

    if any(marker in lowered for marker in broad_phrase_markers):
        return False

    return True


def upsert_skill_alias(
    connection: psycopg.Connection,
    skill_id: int,
    raw_mention: str | None,
    skill_name: str,
) -> None:
    """
    Insert the raw mention as an alias for the canonical skill.

    Example:
        raw_mention = "Postgres"
        skill_name = "PostgreSQL"

    Stored alias:
        postgres -> PostgreSQL

    If raw_mention is empty, do nothing.
    Insert a raw mention as an alias only if it is safe.
    """

    if not is_safe_alias(raw_mention, skill_name):
        return

    alias_name = normalize_lookup_key(raw_mention)

    if not alias_name:
        return

    query = """
        INSERT INTO silver.skill_aliases (
            skill_id,
            alias_name
        )
        VALUES (
            %(skill_id)s,
            %(alias_name)s
        )
        ON CONFLICT (alias_name)
        DO NOTHING;
    """

    with connection.cursor() as cursor:
        cursor.execute(
            query,
            {
                "skill_id": skill_id,
                "alias_name": alias_name,
            },
        )

def upsert_job_skill(
    connection: psycopg.Connection,
    job_id: int,
    skill_id: int,
    skill: ExtractedSkill,
) -> None:
    """
    Insert or update the job-skill relationship.

    Primary key is:
        (job_id, skill_id)

    This keeps the script rerunnable.
    """

    query = """
        INSERT INTO silver.job_skills (
            job_id,
            skill_id,
            extraction_method,
            raw_mention,
            confidence_score
        )
        VALUES (
            %(job_id)s,
            %(skill_id)s,
            'ai',
            %(raw_mention)s,
            %(confidence_score)s
        )
        ON CONFLICT (job_id, skill_id)
        DO UPDATE SET
            extraction_method = EXCLUDED.extraction_method,
            raw_mention = EXCLUDED.raw_mention,
            confidence_score = EXCLUDED.confidence_score;
    """

    with connection.cursor() as cursor:
        cursor.execute(
            query,
            {
                "job_id": job_id,
                "skill_id": skill_id,
                "raw_mention": skill.raw_mention,
                "confidence_score": skill.confidence_score,
            },
        )


def save_skills_for_job(
    connection: psycopg.Connection,
    job_id: int,
    skills: list[ExtractedSkill],
) -> int:
    """
    Save all extracted skills for one job.

    Returns:
        number of job-skill links inserted/updated
    """

    saved_count = 0

    for skill in skills:
        skill_id = upsert_skill(
            connection=connection,
            skill=skill,
        )

        upsert_skill_alias(
            connection=connection,
            skill_id=skill_id,
            raw_mention=skill.raw_mention,
            skill_name=skill.skill_name,
        )

        # Also store canonical skill name as its own alias.
        # This helps future lookup/matching.
        upsert_skill_alias(
            connection=connection,
            skill_id=skill_id,
            raw_mention=skill.skill_name,
            skill_name=skill.skill_name,
        )

        upsert_job_skill(
            connection=connection,
            job_id=job_id,
            skill_id=skill_id,
            skill=skill,
        )

        saved_count += 1

    return saved_count


# ============================================================
# Pipeline logic
# ============================================================

def extract_skills_for_jobs(
    connection: psycopg.Connection,
    client: OpenAI,
    model: str,
    limit: int | None,
    only_missing: bool,
    delay_seconds: float,
) -> tuple[int, int, int]:
    """
    Extract skills for jobs and save results.

    Returns:
        jobs_processed
        job_skill_links_saved
        failed_jobs
    """

    jobs = fetch_jobs_for_skill_extraction(
        connection=connection,
        limit=limit,
        only_missing=only_missing,
    )

    print(f"Fetched {len(jobs)} jobs for AI skill extraction.")

    jobs_processed = 0
    job_skill_links_saved = 0
    failed_jobs = 0

    for index, job in enumerate(jobs, start=1):
        job_id = int(job["job_id"])
        job_title = normalize_whitespace(job.get("job_title"))
        description_text = truncate_description(job.get("description_text"))

        print("\n" + "=" * 70)
        print(f"[{index}/{len(jobs)}] job_id={job_id}")
        print(f"Title: {job_title}")

        try:
            skills = extract_skills_with_openai(
                client=client,
                job_title=job_title,
                description_text=description_text,
                model=model,
            )

            saved_count = save_skills_for_job(
                connection=connection,
                job_id=job_id,
                skills=skills,
            )

            connection.commit()

            jobs_processed += 1
            job_skill_links_saved += saved_count

            if skills:
                print(f"Extracted skills ({len(skills)}):")
                for skill in skills:
                    print(
                        f"- {skill.skill_name} "
                        f"[{skill.skill_category}] "
                        f"raw='{skill.raw_mention}' "
                        f"confidence={skill.confidence_score}"
                    )
            else:
                print("No technical skills extracted.")

            print(f"Saved job-skill links: {saved_count}")

        except Exception as error:
            connection.rollback()
            failed_jobs += 1

            print(f"FAILED job_id={job_id}")
            print(f"Error: {error}")

        if index < len(jobs):
            time.sleep(delay_seconds)

    return jobs_processed, job_skill_links_saved, failed_jobs


def print_report(
    jobs_processed: int,
    job_skill_links_saved: int,
    failed_jobs: int,
) -> None:
    """
    Print final extraction report.
    """

    print("\n" + "=" * 70)
    print("AI Skill Extraction Report")
    print("=" * 70)
    print(f"Jobs processed: {jobs_processed}")
    print(f"Job-skill links saved: {job_skill_links_saved}")
    print(f"Failed jobs: {failed_jobs}")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract technical skills from silver job postings using OpenAI."
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional number of jobs to process. Useful for testing.",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Reprocess jobs even if they already have skills. "
            "Without this flag, only jobs missing skills are processed."
        ),
    )

    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help="Delay between OpenAI API calls. Default: 0.5 seconds.",
    )

    args = parser.parse_args()

    model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL)

    print("Starting AI skill extraction...")
    print(f"OpenAI model: {model}")
    print(f"Limit: {args.limit}")
    print(f"Force reprocess: {args.force}")
    print(f"Delay seconds: {args.delay_seconds}")

    connection = get_database_connection()
    client = get_openai_client()

    try:
        jobs_processed, job_skill_links_saved, failed_jobs = extract_skills_for_jobs(
            connection=connection,
            client=client,
            model=model,
            limit=args.limit,
            only_missing=not args.force,
            delay_seconds=args.delay_seconds,
        )

        print_report(
            jobs_processed=jobs_processed,
            job_skill_links_saved=job_skill_links_saved,
            failed_jobs=failed_jobs,
        )

    finally:
        connection.close()


if __name__ == "__main__":
    main()