"""
Manual test for SkillBridge content hashing.

This script reads:

    data/sample/real_raw_sample_jobs.json

Then prints:
- source_name
- source_url
- source_job_id
- title
- content_hash

Expected usage:

docker compose run --rm pipeline python src/utils/test_hashing.py
"""

import json
from pathlib import Path

from utils.hashing import (
    compute_record_content_hash,
    extract_source_job_id,
)


INPUT_PATH = Path("/app/data/sample/real_raw_sample_jobs.json")


def main() -> None:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"Input file does not exist: {INPUT_PATH}")

    records = json.loads(INPUT_PATH.read_text(encoding="utf-8"))

    print(f"Loaded {len(records)} records from {INPUT_PATH}")
    print()

    content_hashes = []
    source_job_ids = []

    for index, record in enumerate(records, start=1):
        raw_payload = record.get("raw_payload", {})

        source_job_id = extract_source_job_id(record)
        content_hash = compute_record_content_hash(record)

        source_job_ids.append(source_job_id)
        content_hashes.append(content_hash)

        print(f"[{index}]")
        print(f"source_name: {record.get('source_name')}")
        print(f"source_url: {record.get('source_url')}")
        print(f"source_job_id: {source_job_id}")
        print(f"title: {raw_payload.get('title')}")
        print(f"content_hash: {content_hash}")
        print()

    unique_source_job_ids = set(source_job_ids)
    unique_content_hashes = set(content_hashes)

    print("=" * 70)
    print("Hashing Summary")
    print("=" * 70)
    print(f"Total records: {len(records)}")
    print(f"Unique source_job_ids: {len(unique_source_job_ids)}")
    print(f"Unique content_hashes: {len(unique_content_hashes)}")

    if len(records) == len(unique_source_job_ids):
        print("Source job ID check: No duplicate source_job_ids found.")
    else:
        print("Source job ID check: Duplicate source_job_ids detected.")

    if len(records) == len(unique_content_hashes):
        print("Content hash check: No duplicate raw payload hashes found.")
    else:
        print("Content hash check: Duplicate raw payload hashes detected.")

    print("=" * 70)


if __name__ == "__main__":
    main()