"""
Job analysis enrichment script for SkillBridge.

This script reads cleaned job postings from:

    silver.job_postings

Then writes lightweight analysis results into:

    silver.job_analysis

Current analysis includes:
1. detected_role
   - normalized role category from role_detection.py

2. is_excluded_from_analysis
   - simple data quality safeguard to exclude obvious senior/non-entry-level jobs

This script does NOT calculate:
- student fit score
- personalized job suitability
- detailed seniority level

SkillBridge now focuses on:
    "Based on entry-level job market data, what skills should students learn
    for each data-related role?"
"""

import argparse
import os
import re
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from enrichment.role_detection import detect_role


@dataclass(frozen=True)
class ExclusionResult:
    """
    Result of the lightweight exclusion check.

    is_excluded:
        True if the job should be excluded from entry-level skill demand analysis.

    reason:
        Explanation for the exclusion.
    """

    is_excluded: bool
    reason: str | None


def get_database_connection() -> psycopg.Connection:
    """
    Create a PostgreSQL connection using environment variables.

    Expected environment variables come from .env through docker-compose:

        POSTGRES_USER
        POSTGRES_PASSWORD
        POSTGRES_DB
        POSTGRES_HOST
        POSTGRES_PORT

    Inside Docker Compose, POSTGRES_HOST should usually be:

        postgres
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


def normalize_text(value: str | None) -> str:
    """
    Normalize text for simple keyword matching.

    Example:
        " Senior   Data Analyst " -> "senior data analyst"
    """

    if value is None:
        return ""

    text = str(value).lower().strip()
    text = re.sub(r"\s+", " ", text)

    return text


def contains_keyword(text: str, keyword: str) -> bool:
    """
    Check whether a keyword exists as a standalone word or phrase.

    This is safer than simple substring matching.

    Example:
        keyword = "lead"
        should match "Lead Data Analyst"
        but should not match inside an unrelated longer word.
    """

    if not text or not keyword:
        return False

    pattern = r"\b" + re.escape(keyword.lower()) + r"\b"
    return re.search(pattern, text) is not None


def detect_analysis_exclusion(job_title: str | None) -> ExclusionResult:
    """
    Apply a lightweight exclusion safeguard.

    This is NOT detailed seniority detection.

    It only catches obvious cases where LinkedIn search filters may return
    non-entry-level jobs.

    Examples:
        "Senior Data Analyst"
        -> excluded

        "Lead Data Engineer"
        -> excluded

        "Junior Data Analyst"
        -> not excluded
    """

    title_text = normalize_text(job_title)

    if not title_text:
        return ExclusionResult(
            is_excluded=False,
            reason=None,
        )

    exclusion_keywords = [
        "senior",
        "sr",
        "lead",
        "principal",
        "staff",
        "manager",
        "head",
        "director",
        "architect",
    ]

    for keyword in exclusion_keywords:
        if contains_keyword(title_text, keyword):
            return ExclusionResult(
                is_excluded=True,
                reason=f"senior/exclusion keyword in title: {keyword}",
            )

    return ExclusionResult(
        is_excluded=False,
        reason=None,
    )


def fetch_silver_jobs(
    connection: psycopg.Connection,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch cleaned jobs from silver.job_postings.

    These are the fields needed for analysis:
    - job_id
    - job_title
    - description_text
    - job_function
    - industries

    The script analyzes silver data, not raw JSON files.
    """

    query = """
        SELECT
            job_id,
            job_title,
            description_text,
            job_function,
            industries
        FROM silver.job_postings
        ORDER BY job_id
    """

    params: dict[str, Any] = {}

    if limit is not None:
        query += " LIMIT %(limit)s"
        params["limit"] = limit

    query += ";"

    with connection.cursor() as cursor:
        records = cursor.execute(query, params).fetchall()

    return list(records)


def upsert_job_analysis(
    connection: psycopg.Connection,
    analysis_record: dict[str, Any],
) -> None:
    """
    Insert or update one row in silver.job_analysis.

    Because job_id is the primary key, each job has one analysis row.

    If we improve role detection rules later, rerunning this script will update
    existing analysis rows.
    """

    query = """
        INSERT INTO silver.job_analysis (
            job_id,
            detected_role,
            analysis_method,
            confidence_score,
            role_reason,
            is_excluded_from_analysis,
            exclusion_reason
        )
        VALUES (
            %(job_id)s,
            %(detected_role)s,
            %(analysis_method)s,
            %(confidence_score)s,
            %(role_reason)s,
            %(is_excluded_from_analysis)s,
            %(exclusion_reason)s
        )
        ON CONFLICT (job_id)
        DO UPDATE SET
            detected_role = EXCLUDED.detected_role,
            analysis_method = EXCLUDED.analysis_method,
            confidence_score = EXCLUDED.confidence_score,
            role_reason = EXCLUDED.role_reason,
            is_excluded_from_analysis = EXCLUDED.is_excluded_from_analysis,
            exclusion_reason = EXCLUDED.exclusion_reason,
            updated_at = CURRENT_TIMESTAMP;
    """

    with connection.cursor() as cursor:
        cursor.execute(query, analysis_record)


def analyze_one_job(job: dict[str, Any]) -> dict[str, Any]:
    """
    Analyze one silver job posting.

    Steps:
    1. Detect normalized role
    2. Apply lightweight exclusion safeguard
    3. Return a dictionary ready for database insert/update
    """

    role_result = detect_role(
        job_title=job.get("job_title"),
        description_text=job.get("description_text"),
        job_function=job.get("job_function"),
        industries=job.get("industries"),
    )

    exclusion_result = detect_analysis_exclusion(
        job_title=job.get("job_title"),
    )

    return {
        "job_id": job["job_id"],
        "detected_role": role_result.detected_role,
        "analysis_method": "rule_based",
        "confidence_score": role_result.role_confidence,
        "role_reason": role_result.role_reason,
        "is_excluded_from_analysis": exclusion_result.is_excluded,
        "exclusion_reason": exclusion_result.reason,
    }


def analyze_jobs(
    connection: psycopg.Connection,
    limit: int | None = None,
) -> tuple[int, int, int]:
    """
    Analyze jobs from silver.job_postings and write to silver.job_analysis.

    Returns:
        analyzed_count
        excluded_count
        failed_count
    """

    jobs = fetch_silver_jobs(connection=connection, limit=limit)

    print(f"Fetched {len(jobs)} jobs from silver.job_postings.")

    analyzed_count = 0
    excluded_count = 0
    failed_count = 0

    for index, job in enumerate(jobs, start=1):
        try:
            analysis_record = analyze_one_job(job)

            upsert_job_analysis(
                connection=connection,
                analysis_record=analysis_record,
            )

            connection.commit()

            analyzed_count += 1

            if analysis_record["is_excluded_from_analysis"]:
                excluded_count += 1

            print(
                f"[{index}] ANALYZED "
                f"job_id={analysis_record['job_id']} "
                f"role={analysis_record['detected_role']} "
                f"confidence={analysis_record['confidence_score']} "
                f"excluded={analysis_record['is_excluded_from_analysis']}"
            )

        except Exception as error:
            connection.rollback()
            failed_count += 1

            print(f"[{index}] FAILED job_id={job.get('job_id')}")
            print(f"Error: {error}")

    return analyzed_count, excluded_count, failed_count


def print_report(
    analyzed_count: int,
    excluded_count: int,
    failed_count: int,
) -> None:
    """
    Print final analysis report.
    """

    print("\n" + "=" * 70)
    print("Job Analysis Report")
    print("=" * 70)
    print(f"Analyzed jobs: {analyzed_count}")
    print(f"Excluded from analysis: {excluded_count}")
    print(f"Failed jobs: {failed_count}")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze silver job postings and write to silver.job_analysis."
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit for testing. Example: --limit 10",
    )

    args = parser.parse_args()

    print("Starting job analysis enrichment...")

    connection = get_database_connection()

    try:
        analyzed_count, excluded_count, failed_count = analyze_jobs(
            connection=connection,
            limit=args.limit,
        )

        print_report(
            analyzed_count=analyzed_count,
            excluded_count=excluded_count,
            failed_count=failed_count,
        )

    finally:
        connection.close()


if __name__ == "__main__":
    main()