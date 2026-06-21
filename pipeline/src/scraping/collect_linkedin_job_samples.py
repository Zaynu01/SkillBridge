"""
LinkedIn Multi-Job Sample Collector

This script collects multiple LinkedIn job detail pages and saves them
as raw sample records.

It is NOT the final production scraper.

Its goal is to test whether our LinkedIn job detail extractor is stable
across multiple job URLs and to produce a realistic sample dataset for
the bronze ingestion step.

Expected usage:

docker compose run --rm pipeline python src/scraping/collect_linkedin_job_samples.py \
  --input data/sample/linkedin_test_urls.txt \
  --output data/sample/real_raw_sample_jobs.json \
  --delay-seconds 3
"""

import argparse
import json
import time
from pathlib import Path
from typing import Any

# We reuse the tested extraction logic from the single-job inspector.
# This avoids duplicating code and keeps both scripts consistent.
from scraping.inspect_linkedin_job import (
    build_raw_job_record,
    fetch_html,
    get_direct_linkedin_job_url,
)


# Inside the Docker container, the project data folder is mounted at /app/data.
DEFAULT_INPUT_PATH = Path("/app/data/sample/linkedin_test_urls.txt")
DEFAULT_OUTPUT_PATH = Path("/app/data/sample/real_raw_sample_jobs.json")


REQUIRED_RAW_PAYLOAD_FIELDS = [
    "job_id",
    "title",
    "company",
    "location",
    "description_text",
]


def resolve_container_path(path_value: str) -> Path:
    """
    Convert a user-provided path into a container-safe path.

    Why this function exists:

    When running inside Docker, your project data folder is mounted as:

        /app/data

    But from your host machine, you may think of the path as:

        data/sample/linkedin_test_urls.txt

    So this helper accepts both:
    - data/sample/linkedin_test_urls.txt
    - /app/data/sample/linkedin_test_urls.txt

    and converts relative data/ paths to /app/data/.
    """

    path = Path(path_value)

    if path.is_absolute():
        return path

    path_parts = path.parts

    if path_parts and path_parts[0] == "data":
        return Path("/app") / path

    return path


def read_urls(input_path: Path) -> list[str]:
    """
    Read LinkedIn job URLs from a text file.

    Rules:
    - One URL per line
    - Empty lines are ignored
    - Lines starting with # are ignored

    Example file:

        # Data jobs
        https://www.linkedin.com/jobs/view/4430018168/
        https://www.linkedin.com/jobs/view/4402626231/
    """

    if not input_path.exists():
        raise FileNotFoundError(f"Input URL file does not exist: {input_path}")

    urls = []

    for line in input_path.read_text(encoding="utf-8").splitlines():
        cleaned_line = line.strip()

        if not cleaned_line:
            continue

        if cleaned_line.startswith("#"):
            continue

        urls.append(cleaned_line)

    return urls


def get_missing_required_fields(record: dict[str, Any]) -> list[str]:
    """
    Check whether a raw job record contains the fields we consider essential.

    Essential fields:
    - job_id
    - title
    - company
    - location
    - description_text

    These are required because the future silver layer needs them.
    """

    raw_payload = record.get("raw_payload", {})

    missing_fields = []

    for field in REQUIRED_RAW_PAYLOAD_FIELDS:
        if not raw_payload.get(field):
            missing_fields.append(field)

    return missing_fields


def is_successful_record(record: dict[str, Any]) -> bool:
    """
    A record is considered successful if all required fields exist.
    """

    return len(get_missing_required_fields(record)) == 0


def save_records(records: list[dict[str, Any]], output_path: Path) -> None:
    """
    Save all successful raw records into one JSON file.

    This output file will later be used by the bronze loader.
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(
        json.dumps(records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def print_record_summary(index: int, url: str, record: dict[str, Any]) -> None:
    """
    Print a short summary for one extracted job.
    """

    raw_payload = record["raw_payload"]

    print(f"\n[{index}] SUCCESS")
    print(f"URL: {url}")
    print(f"job_id: {raw_payload.get('job_id')}")
    print(f"title: {raw_payload.get('title')}")
    print(f"company: {raw_payload.get('company')}")
    print(f"location: {raw_payload.get('location')}")

    description_text = raw_payload.get("description_text")

    if description_text:
        print(f"description length: {len(description_text)} characters")
    else:
        print("description length: 0")


def print_partial_summary(
    index: int,
    url: str,
    record: dict[str, Any],
    missing_fields: list[str],
) -> None:
    """
    Print a summary when extraction worked partially but required fields are missing.
    """

    raw_payload = record.get("raw_payload", {})

    print(f"\n[{index}] PARTIAL SUCCESS")
    print(f"URL: {url}")
    print(f"Missing required fields: {', '.join(missing_fields)}")
    print(f"job_id: {raw_payload.get('job_id')}")
    print(f"title: {raw_payload.get('title')}")
    print(f"company: {raw_payload.get('company')}")
    print(f"location: {raw_payload.get('location')}")


def print_failure_summary(index: int, url: str, error: Exception) -> None:
    """
    Print a summary when a URL fails completely.
    """

    print(f"\n[{index}] FAILED")
    print(f"URL: {url}")
    print(f"Error: {error}")


def collect_jobs(
    urls: list[str],
    delay_seconds: float,
    keep_partial: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Fetch and extract multiple LinkedIn job detail pages.

    Returns:
    - successful_records: records with all required fields
    - failed_records: information about failed or partial records

    Why we add delay_seconds:
    We do not want to hammer LinkedIn with rapid requests.
    Even during discovery, we should use a small delay.
    """

    successful_records = []
    failed_records = []

    total_urls = len(urls)

    for index, original_url in enumerate(urls, start=1):
        print("\n" + "=" * 70)
        print(f"Processing job {index}/{total_urls}")
        print(f"Original URL: {original_url}")

        try:
            job_url = get_direct_linkedin_job_url(original_url)

            print(f"URL used for request: {job_url}")

            html = fetch_html(job_url)

            record = build_raw_job_record(job_url, html)

            missing_fields = get_missing_required_fields(record)

            if not missing_fields:
                successful_records.append(record)
                print_record_summary(index, job_url, record)

            else:
                print_partial_summary(index, job_url, record, missing_fields)

                failed_records.append(
                    {
                        "url": job_url,
                        "status": "partial_success",
                        "missing_fields": missing_fields,
                        "raw_payload_preview": record.get("raw_payload", {}),
                    }
                )

                if keep_partial:
                    successful_records.append(record)

        except Exception as error:
            print_failure_summary(index, original_url, error)

            failed_records.append(
                {
                    "url": original_url,
                    "status": "failed",
                    "error": str(error),
                }
            )

        if index < total_urls:
            print(f"\nSleeping for {delay_seconds} seconds...")
            time.sleep(delay_seconds)

    return successful_records, failed_records


def print_final_report(
    total_urls: int,
    successful_records: list[dict[str, Any]],
    failed_records: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """
    Print the final stability test report.
    """

    success_count = len(successful_records)
    failed_count = len(failed_records)

    print("\n" + "=" * 70)
    print("LinkedIn Multi-Job Collection Report")
    print("=" * 70)

    print(f"Total URLs tested: {total_urls}")
    print(f"Records saved: {success_count}")
    print(f"Failed or partial records: {failed_count}")
    print(f"Output file: {output_path}")

    if total_urls > 0:
        success_rate = (success_count / total_urls) * 100
        print(f"Saved record rate: {success_rate:.2f}%")

    if failed_records:
        print("\nFailures / partial records:")

        for item in failed_records:
            print("-" * 50)
            print(f"URL: {item.get('url')}")
            print(f"Status: {item.get('status')}")

            if item.get("missing_fields"):
                print(f"Missing fields: {', '.join(item['missing_fields'])}")

            if item.get("error"):
                print(f"Error: {item.get('error')}")

    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect multiple LinkedIn job detail pages as raw sample data."
    )

    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT_PATH),
        help=(
            "Path to text file containing LinkedIn job URLs. "
            "Default: /app/data/sample/linkedin_test_urls.txt"
        ),
    )

    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help=(
            "Path where raw sample JSON will be saved. "
            "Default: /app/data/sample/real_raw_sample_jobs.json"
        ),
    )

    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=3.0,
        help="Delay between requests. Default: 3 seconds.",
    )

    parser.add_argument(
        "--keep-partial",
        action="store_true",
        help=(
            "Save partial records even if required fields are missing. "
            "By default, partial records are not saved."
        ),
    )

    args = parser.parse_args()

    input_path = resolve_container_path(args.input)
    output_path = resolve_container_path(args.output)

    print("Starting LinkedIn multi-job sample collection...")
    print(f"Input URL file: {input_path}")
    print(f"Output JSON file: {output_path}")
    print(f"Delay between requests: {args.delay_seconds} seconds")
    print(f"Keep partial records: {args.keep_partial}")

    urls = read_urls(input_path)

    if not urls:
        raise RuntimeError(f"No URLs found in input file: {input_path}")

    print(f"Loaded {len(urls)} URLs.")

    successful_records, failed_records = collect_jobs(
        urls=urls,
        delay_seconds=args.delay_seconds,
        keep_partial=args.keep_partial,
    )

    save_records(successful_records, output_path)

    print_final_report(
        total_urls=len(urls),
        successful_records=successful_records,
        failed_records=failed_records,
        output_path=output_path,
    )


if __name__ == "__main__":
    main()  