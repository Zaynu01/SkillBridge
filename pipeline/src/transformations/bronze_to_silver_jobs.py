"""
Bronze to Silver job posting transformation for SkillBridge.

This script reads raw job postings from:

    bronze.raw_job_postings

Then transforms them into cleaned structured rows in:

    silver.job_postings

Expected usage:

docker compose run --rm pipeline python src/transformations/bronze_to_silver_jobs.py

Optional:

docker compose run --rm pipeline python src/transformations/bronze_to_silver_jobs.py --limit 20

Main responsibilities:
1. Read raw JSONB payloads from bronze
2. Extract LinkedIn fields from raw_payload
3. Clean text fields
4. Parse basic country and remote_type
5. Upsert into silver.job_postings
6. Keep lineage through raw_job_id and pipeline_run_id
"""

import argparse
import os
import re
from typing import Any

import psycopg
from psycopg.rows import dict_row


def get_database_connection() -> psycopg.Connection:
    """
    Create a PostgreSQL connection using environment variables.

    These should come from docker-compose env_file:

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


def clean_text(value: Any) -> str | None:
    """
    Clean basic text values.

    This function:
    - Converts non-string values to string
    - Strips leading/trailing whitespace
    - Collapses repeated whitespace into one space
    - Converts empty strings to None

    Example:
        "  Data   Analyst\\n " -> "Data Analyst"
    """

    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    text = re.sub(r"\s+", " ", text)

    return text


def clean_description(value: Any) -> str | None:
    """
    Clean job description text.

    We keep this separate from clean_text because descriptions can be longer,
    but for now the logic is similar:
    - Strip surrounding whitespace
    - Normalize repeated whitespace

    Later, if needed, we can improve this function without changing the rest
    of the transformation.
    """

    return clean_text(value)


def parse_country(location_text: str | None) -> str | None:
    """
    Parse a basic country value from location text.

    This function is intentionally rule-based.

    Why:
    LinkedIn locations are often inconsistent.

    Examples:
        "United States" -> "United States"
        "New York, NY" -> "United States"
        "San Francisco, CA" -> "United States"
        "Washington DC-Baltimore Area" -> "United States"
        "Los Angeles Metropolitan Area" -> "United States"
        "Casablanca, Morocco" -> "Morocco"
        "Paris, Île-de-France, France" -> "France"
        "Remote" -> None
    """

    if not location_text:
        return None

    normalized = location_text.strip()

    if not normalized:
        return None

    lower_location = normalized.lower()

    if lower_location in {"remote", "worldwide", "anywhere"}:
        return None

    known_country_names = {
        "united states": "United States",
        "united kingdom": "United Kingdom",
        "morocco": "Morocco",
        "france": "France",
        "spain": "Spain",
        "germany": "Germany",
        "canada": "Canada",
        "india": "India",
        "netherlands": "Netherlands",
        "belgium": "Belgium",
        "italy": "Italy",
        "portugal": "Portugal",
        "ireland": "Ireland",
        "australia": "Australia",
    }

    if lower_location in known_country_names:
        return known_country_names[lower_location]

    us_state_abbreviations = {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "DC",
    }

    # Handles examples like:
    # "New York, NY"
    # "San Francisco, CA"
    # "Fort Worth, TX"
    if "," in normalized:
        parts = [part.strip() for part in normalized.split(",") if part.strip()]
        last_part = parts[-1] if parts else ""

        if last_part.upper() in us_state_abbreviations:
            return "United States"

        # If the last part is an actual country name, use it.
        last_part_lower = last_part.lower()
        if last_part_lower in known_country_names:
            return known_country_names[last_part_lower]

    us_metro_signals = [
        "metropolitan area",
        "metroplex",
        "greater chicago area",
        "greater new york city area",
        "greater boston",
        "greater seattle",
        "greater los angeles",
        "greater houston",
        "greater atlanta",
        "greater phoenix",
        "greater denver",
        "greater miami",
        "greater minneapolis-st. paul",
        "washington dc",
        "washington dc-baltimore",
        "new york city",
        "bay area",
        "san francisco bay area",
        "silicon valley",
        "los angeles metropolitan area",
        "atlanta metropolitan area",
        "dallas-fort worth",
        "dallas fort worth",
        "dallas-fort worth metroplex",
    ]

    if any(signal in lower_location for signal in us_metro_signals):
        return "United States"

    return None


def detect_remote_type(location_text: str | None, description_text: str | None) -> str:
    """
    Detect basic remote type.

    Possible values:
        remote
        hybrid
        onsite
        unknown

    This is not meant to be perfect. It is a first lightweight parser.

    We look at both location_text and description_text because sometimes
    remote/hybrid appears in the description instead of the location.
    """

    combined_text = " ".join(
        part for part in [location_text, description_text] if part
    ).lower()

    if not combined_text:
        return "unknown"

    if "hybrid" in combined_text:
        return "hybrid"

    remote_signals = [
        "remote",
        "work from home",
        "work-from-home",
        "fully remote",
        "remote-first",
    ]

    if any(signal in combined_text for signal in remote_signals):
        return "remote"

    onsite_signals = [
        "on-site",
        "onsite",
        "on site",
    ]

    if any(signal in combined_text for signal in onsite_signals):
        return "onsite"

    return "unknown"


def get_payload_value(raw_payload: dict[str, Any], key: str) -> Any:
    """
    Safely get a field from raw_payload.

    This keeps extraction readable and gives us one place to adjust behavior
    later if raw payload structures become more complex.
    """

    return raw_payload.get(key)


def extract_silver_job_fields(bronze_record: dict[str, Any]) -> dict[str, Any]:
    """
    Convert one bronze record into one silver job record.

    Input record comes from bronze.raw_job_postings and includes:

        raw_job_id
        pipeline_run_id
        source_name
        source_job_id
        source_url
        scraped_at
        raw_payload

    Output matches silver.job_postings columns.
    """

    raw_payload = bronze_record.get("raw_payload")

    if not isinstance(raw_payload, dict):
        raise ValueError(
            f"raw_job_id={bronze_record.get('raw_job_id')} has invalid raw_payload."
        )

    job_title = clean_text(get_payload_value(raw_payload, "title"))
    company_name = clean_text(get_payload_value(raw_payload, "company"))
    location_text = clean_text(get_payload_value(raw_payload, "location"))
    description_text = clean_description(get_payload_value(raw_payload, "description_text"))

    if not job_title:
        raise ValueError(
            f"raw_job_id={bronze_record.get('raw_job_id')} is missing job title."
        )

    if not description_text:
        raise ValueError(
            f"raw_job_id={bronze_record.get('raw_job_id')} is missing description_text."
        )

    country = parse_country(location_text)
    remote_type = detect_remote_type(location_text, description_text)

    silver_record = {
        "raw_job_id": bronze_record["raw_job_id"],
        "pipeline_run_id": bronze_record.get("pipeline_run_id"),
        "source_name": clean_text(bronze_record.get("source_name")),
        "source_job_id": clean_text(bronze_record.get("source_job_id")),
        "source_url": clean_text(bronze_record.get("source_url")),

        "job_title": job_title,
        "company_name": company_name,
        "location_text": location_text,
        "country": country,
        "remote_type": remote_type,

        "employment_type": clean_text(get_payload_value(raw_payload, "employment_type")),
        "seniority_level": clean_text(get_payload_value(raw_payload, "seniority_level")),
        "job_function": clean_text(get_payload_value(raw_payload, "job_function")),
        "industries": clean_text(get_payload_value(raw_payload, "industries")),

        "posted_time_text": clean_text(get_payload_value(raw_payload, "posted_time_text")),
        "applicants_text": clean_text(get_payload_value(raw_payload, "applicants_text")),
        "description_text": description_text,
        "description_html": get_payload_value(raw_payload, "description_html"),

        "scraped_at": bronze_record.get("scraped_at"),
    }

    if not silver_record["source_name"]:
        raise ValueError(
            f"raw_job_id={bronze_record.get('raw_job_id')} is missing source_name."
        )

    if not silver_record["source_job_id"]:
        raise ValueError(
            f"raw_job_id={bronze_record.get('raw_job_id')} is missing source_job_id."
        )

    return silver_record


def fetch_bronze_records(
    connection: psycopg.Connection,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch bronze records that should be transformed into silver.

    For now, we fetch all bronze records.

    Later, we can optimize this to fetch only bronze records that are not
    already in silver, or records changed after a certain time.
    """

    query = """
        SELECT
            raw_job_id,
            pipeline_run_id,
            source_name,
            source_job_id,
            source_url,
            scraped_at,
            raw_payload
        FROM bronze.raw_job_postings
        ORDER BY raw_job_id
    """

    params: dict[str, Any] = {}

    if limit is not None:
        query += " LIMIT %(limit)s"
        params["limit"] = limit

    query += ";"

    with connection.cursor() as cursor:
        records = cursor.execute(query, params).fetchall()

    return list(records)


def upsert_silver_job(
    connection: psycopg.Connection,
    silver_record: dict[str, Any],
) -> int:
    """
    Insert or update one job into silver.job_postings.

    Silver uses upsert instead of insert-only.

    Why?

    If we improve cleaning logic later, rerunning this script should update
    existing silver rows instead of doing nothing.

    Deduplication key:
        UNIQUE (source_name, source_job_id)

    Returns:
        job_id of the inserted or updated silver row.
    """

    query = """
        INSERT INTO silver.job_postings (
            raw_job_id,
            pipeline_run_id,
            source_name,
            source_job_id,
            source_url,
            job_title,
            company_name,
            location_text,
            country,
            remote_type,
            employment_type,
            seniority_level,
            job_function,
            industries,
            posted_time_text,
            applicants_text,
            description_text,
            description_html,
            scraped_at
        )
        VALUES (
            %(raw_job_id)s,
            %(pipeline_run_id)s,
            %(source_name)s,
            %(source_job_id)s,
            %(source_url)s,
            %(job_title)s,
            %(company_name)s,
            %(location_text)s,
            %(country)s,
            %(remote_type)s,
            %(employment_type)s,
            %(seniority_level)s,
            %(job_function)s,
            %(industries)s,
            %(posted_time_text)s,
            %(applicants_text)s,
            %(description_text)s,
            %(description_html)s,
            %(scraped_at)s
        )
        ON CONFLICT (source_name, source_job_id)
        DO UPDATE SET
            raw_job_id = EXCLUDED.raw_job_id,
            pipeline_run_id = EXCLUDED.pipeline_run_id,
            source_url = EXCLUDED.source_url,
            job_title = EXCLUDED.job_title,
            company_name = EXCLUDED.company_name,
            location_text = EXCLUDED.location_text,
            country = EXCLUDED.country,
            remote_type = EXCLUDED.remote_type,
            employment_type = EXCLUDED.employment_type,
            seniority_level = EXCLUDED.seniority_level,
            job_function = EXCLUDED.job_function,
            industries = EXCLUDED.industries,
            posted_time_text = EXCLUDED.posted_time_text,
            applicants_text = EXCLUDED.applicants_text,
            description_text = EXCLUDED.description_text,
            description_html = EXCLUDED.description_html,
            scraped_at = EXCLUDED.scraped_at,
            updated_at = CURRENT_TIMESTAMP
        RETURNING job_id;
    """

    with connection.cursor() as cursor:
        result = cursor.execute(query, silver_record).fetchone()

    return int(result["job_id"])


def transform_bronze_to_silver(
    connection: psycopg.Connection,
    limit: int | None = None,
) -> tuple[int, int]:
    """
    Transform bronze records into silver records.

    Returns:
        successful_count
        failed_count
    """

    bronze_records = fetch_bronze_records(connection, limit=limit)

    print(f"Fetched {len(bronze_records)} bronze records.")

    successful_count = 0
    failed_count = 0

    for index, bronze_record in enumerate(bronze_records, start=1):
        raw_job_id = bronze_record.get("raw_job_id")

        try:
            silver_record = extract_silver_job_fields(bronze_record)

            job_id = upsert_silver_job(
                connection=connection,
                silver_record=silver_record,
            )

            connection.commit()
            successful_count += 1

            print(
                f"[{index}] UPSERTED silver.job_id={job_id} "
                f"from raw_job_id={raw_job_id} - {silver_record['job_title']}"
            )

        except Exception as error:
            connection.rollback()
            failed_count += 1

            print(f"[{index}] FAILED raw_job_id={raw_job_id}")
            print(f"Error: {error}")

    return successful_count, failed_count


def print_report(successful_count: int, failed_count: int) -> None:
    """
    Print final transformation report.
    """

    print("\n" + "=" * 70)
    print("Bronze to Silver Transformation Report")
    print("=" * 70)
    print(f"Successful records: {successful_count}")
    print(f"Failed records: {failed_count}")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transform bronze raw job postings into silver job postings."
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit for testing only. Example: --limit 10",
    )

    args = parser.parse_args()

    print("Starting bronze to silver job transformation...")

    connection = get_database_connection()

    try:
        successful_count, failed_count = transform_bronze_to_silver(
            connection=connection,
            limit=args.limit,
        )

        print_report(
            successful_count=successful_count,
            failed_count=failed_count,
        )

    finally:
        connection.close()


if __name__ == "__main__":
    main()