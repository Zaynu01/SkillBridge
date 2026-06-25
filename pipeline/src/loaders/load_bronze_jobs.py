"""
Bronze raw job loader for SkillBridge.

This script loads raw scraped job records from a JSON file into:

    bronze.raw_job_postings

It also creates and updates a pipeline run in:

    metadata.pipeline_runs

Expected usage:

docker compose run --rm pipeline python src/loaders/load_bronze_jobs.py \
  --input data/sample/real_raw_sample_jobs.json \
  --run-name linkedin_bronze_load

Main responsibilities:
1. Read raw job records from JSON
2. Create metadata.pipeline_runs row
3. Extract source_job_id from raw_payload.job_id
4. Compute content_hash from raw_payload
5. Insert records into bronze.raw_job_postings
6. Skip duplicates using UNIQUE (source_name, source_job_id)
7. Update pipeline run counts and status
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from utils.hashing import (
    compute_record_content_hash,
    extract_source_job_id,
)


DEFAULT_INPUT_PATH = Path("/app/data/sample/real_raw_sample_jobs.json")


def resolve_container_path(path_value: str) -> Path:
    """
    Convert a user-provided path into a Docker-container-safe path.

    From the host machine, you usually think in paths like:

        data/sample/real_raw_sample_jobs.json

    But inside the Docker container, ./data is mounted as:

        /app/data

    So this function converts:

        data/sample/real_raw_sample_jobs.json

    into:

        /app/data/sample/real_raw_sample_jobs.json
    """

    path = Path(path_value)

    if path.is_absolute():
        return path

    if path.parts and path.parts[0] == "data":
        return Path("/app") / path

    return path


def get_database_connection() -> psycopg.Connection:
    """
    Create a PostgreSQL connection using environment variables.

    These variables should come from your .env file through docker-compose:

        POSTGRES_USER
        POSTGRES_PASSWORD
        POSTGRES_DB
        POSTGRES_HOST
        POSTGRES_PORT

    In Docker, POSTGRES_HOST should usually be:

        postgres

    because that is the service name in docker-compose.yml.
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


def read_raw_records(input_path: Path) -> list[dict[str, Any]]:
    """
    Read raw job records from a JSON file.

    The expected file is:

        data/sample/real_raw_sample_jobs.json

    Expected shape:

        [
          {
            "source_name": "linkedin",
            "source_url": "...",
            "scraped_at": "...",
            "raw_payload": {...}
          }
        ]
    """

    if not input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")

    records = json.loads(input_path.read_text(encoding="utf-8"))

    if not isinstance(records, list):
        raise ValueError("Input JSON must contain a list of raw job records.")

    return records


def create_pipeline_run(
    connection: psycopg.Connection,
    run_name: str,
    source_name: str,
    raw_records_count: int,
) -> int:
    """
    Create a new row in metadata.pipeline_runs.

    At the beginning, status is set to 'running'.

    Later, after loading finishes, we update this same row to:
    - success
    - partial_success
    - failed
    """

    query = """
        INSERT INTO metadata.pipeline_runs (
            run_name,
            source_name,
            status,
            raw_records_count
        )
        VALUES (
            %(run_name)s,
            %(source_name)s,
            'running',
            %(raw_records_count)s
        )
        RETURNING pipeline_run_id;
    """

    with connection.cursor() as cursor:
        result = cursor.execute(
            query,
            {
                "run_name": run_name,
                "source_name": source_name,
                "raw_records_count": raw_records_count,
            },
        ).fetchone()

    connection.commit()

    return int(result["pipeline_run_id"])


def update_pipeline_run(
    connection: psycopg.Connection,
    pipeline_run_id: int,
    status: str,
    inserted_raw_count: int,
    failed_records_count: int,
    error_message: str | None = None,
) -> None:
    """
    Update the metadata.pipeline_runs row after loading finishes.

    This gives us traceability.

    Example:
        pipeline_run_id = 3
        status = success
        raw_records_count = 35
        inserted_raw_count = 35
        failed_records_count = 0
    """

    query = """
        UPDATE metadata.pipeline_runs
        SET
            status = %(status)s,
            finished_at = CURRENT_TIMESTAMP,
            inserted_raw_count = %(inserted_raw_count)s,
            failed_records_count = %(failed_records_count)s,
            error_message = %(error_message)s
        WHERE pipeline_run_id = %(pipeline_run_id)s;
    """

    with connection.cursor() as cursor:
        cursor.execute(
            query,
            {
                "pipeline_run_id": pipeline_run_id,
                "status": status,
                "inserted_raw_count": inserted_raw_count,
                "failed_records_count": failed_records_count,
                "error_message": error_message,
            },
        )

    connection.commit()


def get_source_name_from_records(records: list[dict[str, Any]]) -> str:
    """
    Determine the source_name for this loading run.

    For now, our file should contain only LinkedIn records.

    If the file contains multiple source_names, we fail intentionally.
    That keeps the pipeline simple and prevents confusing pipeline run metadata.
    """

    source_names = {
        record.get("source_name")
        for record in records
        if record.get("source_name")
    }

    if not source_names:
        raise ValueError("No source_name found in input records.")

    if len(source_names) > 1:
        raise ValueError(
            "Input file contains multiple source names. "
            f"Found: {sorted(source_names)}"
        )

    return source_names.pop()


def validate_record(record: dict[str, Any], index: int) -> None:
    """
    Validate that one raw job record has the fields required for bronze loading.

    Required:
    - source_name
    - raw_payload
    - raw_payload.job_id

    source_url and scraped_at are useful, but source_url may vary and scraped_at
    may be missing in some future source, so they are not the identity rule.
    """

    if not record.get("source_name"):
        raise ValueError(f"Record {index} is missing source_name.")

    raw_payload = record.get("raw_payload")

    if not isinstance(raw_payload, dict):
        raise ValueError(f"Record {index} is missing raw_payload dictionary.")

    source_job_id = extract_source_job_id(record)

    if not source_job_id:
        raise ValueError(
            f"Record {index} is missing raw_payload.job_id, "
            "so source_job_id cannot be created."
        )


def insert_raw_job_record(
    connection: psycopg.Connection,
    pipeline_run_id: int,
    record: dict[str, Any],
) -> bool:
    """
    Insert one raw job record into bronze.raw_job_postings.

    Returns:
        True if a new row was inserted
        False if the row was skipped because it already exists

    Duplicate rule:
        UNIQUE (source_name, source_job_id)

    SQL behavior:
        ON CONFLICT (source_name, source_job_id) DO NOTHING

    This means if the same LinkedIn job appears again with a different URL,
    it is skipped because source_job_id is the same.
    """

    source_name = record["source_name"]
    source_job_id = extract_source_job_id(record)
    source_url = record.get("source_url")
    scraped_at = record.get("scraped_at")
    raw_payload = record["raw_payload"]
    content_hash = compute_record_content_hash(record)

    query = """
        INSERT INTO bronze.raw_job_postings (
            pipeline_run_id,
            source_name,
            source_job_id,
            source_url,
            scraped_at,
            raw_payload,
            content_hash
        )
        VALUES (
            %(pipeline_run_id)s,
            %(source_name)s,
            %(source_job_id)s,
            %(source_url)s,
            %(scraped_at)s,
            %(raw_payload)s,
            %(content_hash)s
        )
        ON CONFLICT (source_name, source_job_id) DO NOTHING
        RETURNING raw_job_id;
    """

    with connection.cursor() as cursor:
        result = cursor.execute(
            query,
            {
                "pipeline_run_id": pipeline_run_id,
                "source_name": source_name,
                "source_job_id": source_job_id,
                "source_url": source_url,
                "scraped_at": scraped_at,
                "raw_payload": Jsonb(raw_payload),
                "content_hash": content_hash,
            },
        ).fetchone()

    return result is not None


def load_records_to_bronze(
    connection: psycopg.Connection,
    pipeline_run_id: int,
    records: list[dict[str, Any]],
) -> tuple[int, int, int]:
    """
    Load all raw records into bronze.

    Returns:
        inserted_count
        skipped_duplicate_count
        failed_count

    Each record is handled independently so that one bad record does not
    destroy the whole load.
    """

    inserted_count = 0
    skipped_duplicate_count = 0
    failed_count = 0

    for index, record in enumerate(records, start=1):
        try:
            validate_record(record, index)

            inserted = insert_raw_job_record(
                connection=connection,
                pipeline_run_id=pipeline_run_id,
                record=record,
            )

            if inserted:
                inserted_count += 1

                raw_payload = record.get("raw_payload", {})
                print(
                    f"[{index}] INSERTED "
                    f"{record.get('source_name')}:{raw_payload.get('job_id')} "
                    f"- {raw_payload.get('title')}"
                )
            else:
                skipped_duplicate_count += 1

                raw_payload = record.get("raw_payload", {})
                print(
                    f"[{index}] SKIPPED DUPLICATE "
                    f"{record.get('source_name')}:{raw_payload.get('job_id')} "
                    f"- {raw_payload.get('title')}"
                )

            connection.commit()

        except Exception as error:
            failed_count += 1
            connection.rollback()

            print(f"[{index}] FAILED")
            print(f"Error: {error}")

    return inserted_count, skipped_duplicate_count, failed_count


def determine_final_status(
    inserted_count: int,
    skipped_duplicate_count: int,
    failed_count: int,
    total_records: int,
) -> str:
    """
    Decide the final pipeline status.

    success:
        no failed records

    partial_success:
        at least one record failed, but some records inserted or skipped safely

    failed:
        every record failed
    """

    if failed_count == 0:
        return "success"

    successful_or_known_records = inserted_count + skipped_duplicate_count

    if successful_or_known_records > 0:
        return "partial_success"

    if total_records > 0 and failed_count == total_records:
        return "failed"

    return "partial_success"


def print_final_report(
    input_path: Path,
    pipeline_run_id: int,
    total_records: int,
    inserted_count: int,
    skipped_duplicate_count: int,
    failed_count: int,
    status: str,
) -> None:
    """
    Print a final loading report.
    """

    print("\n" + "=" * 70)
    print("Bronze Loading Report")
    print("=" * 70)
    print(f"Input file: {input_path}")
    print(f"Pipeline run ID: {pipeline_run_id}")
    print(f"Total records read: {total_records}")
    print(f"Inserted records: {inserted_count}")
    print(f"Skipped duplicates: {skipped_duplicate_count}")
    print(f"Failed records: {failed_count}")
    print(f"Final status: {status}")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load raw scraped job records into bronze.raw_job_postings."
    )

    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT_PATH),
        help=(
            "Path to raw jobs JSON file. "
            "Default: /app/data/sample/real_raw_sample_jobs.json"
        ),
    )

    parser.add_argument(
        "--run-name",
        default="manual_bronze_load",
        help="Name to store in metadata.pipeline_runs.",
    )

    args = parser.parse_args()

    input_path = resolve_container_path(args.input)

    print("Starting bronze raw job load...")
    print(f"Input file: {input_path}")
    print(f"Run name: {args.run_name}")

    records = read_raw_records(input_path)
    total_records = len(records)

    if total_records == 0:
        raise RuntimeError("Input file contains zero records.")

    source_name = get_source_name_from_records(records)

    print(f"Records found: {total_records}")
    print(f"Source name: {source_name}")

    connection = get_database_connection()

    pipeline_run_id = None

    try:
        pipeline_run_id = create_pipeline_run(
            connection=connection,
            run_name=args.run_name,
            source_name=source_name,
            raw_records_count=total_records,
        )

        print(f"Created pipeline run: {pipeline_run_id}")

        inserted_count, skipped_duplicate_count, failed_count = load_records_to_bronze(
            connection=connection,
            pipeline_run_id=pipeline_run_id,
            records=records,
        )

        final_status = determine_final_status(
            inserted_count=inserted_count,
            skipped_duplicate_count=skipped_duplicate_count,
            failed_count=failed_count,
            total_records=total_records,
        )

        update_pipeline_run(
            connection=connection,
            pipeline_run_id=pipeline_run_id,
            status=final_status,
            inserted_raw_count=inserted_count,
            failed_records_count=failed_count,
            error_message=None,
        )

        print_final_report(
            input_path=input_path,
            pipeline_run_id=pipeline_run_id,
            total_records=total_records,
            inserted_count=inserted_count,
            skipped_duplicate_count=skipped_duplicate_count,
            failed_count=failed_count,
            status=final_status,
        )

    except Exception as error:
        connection.rollback()

        if pipeline_run_id is not None:
            update_pipeline_run(
                connection=connection,
                pipeline_run_id=pipeline_run_id,
                status="failed",
                inserted_raw_count=0,
                failed_records_count=total_records,
                error_message=str(error),
            )

        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()