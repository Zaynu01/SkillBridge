"""
Hashing utilities for SkillBridge.

This module creates stable hashes for raw job payloads.

Current project decision:

- Deduplication is handled by:
    source_name + source_job_id

- content_hash is used to fingerprint the raw payload content.

This means:
- The same LinkedIn job with different URL formats is still treated as the same job.
- scraped_at does not affect the hash.
- source_url does not affect the hash.
- Only the actual extracted raw content affects the content_hash.
"""

import hashlib
import json
from typing import Any


def stable_json_dumps(data: Any) -> str:
    """
    Convert Python data into a stable JSON string.

    Why this matters:

    These two dictionaries are logically the same:

        {"title": "Data Analyst", "company": "SharpAtoms"}

        {"company": "SharpAtoms", "title": "Data Analyst"}

    But as raw strings, their key order is different.

    By using sort_keys=True, both dictionaries are converted into the
    same stable JSON string before hashing.
    """

    return json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def sha256_text(text: str) -> str:
    """
    Generate a SHA-256 hash from text.

    SHA-256 returns a 64-character hexadecimal string.
    """

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_raw_payload_hash(raw_payload: dict[str, Any]) -> str:
    """
    Compute a stable content hash from raw_payload only.

    This is the main function we will use in the bronze loader.

    Example input:

        {
          "job_id": "4430018168",
          "title": "Data Analyst/Engineer",
          "company": "SharpAtoms",
          "description_text": "..."
        }

    Important:
    - source_url is not included
    - scraped_at is not included
    - source_name is not included

    Reason:
    content_hash should represent the content itself, not where or when
    it was collected.
    """

    stable_text = stable_json_dumps(raw_payload)
    return sha256_text(stable_text)


def compute_record_content_hash(record: dict[str, Any]) -> str:
    """
    Compute content_hash from a full raw job record.

    Expected record shape:

        {
          "source_name": "linkedin",
          "source_url": "...",
          "scraped_at": "...",
          "raw_payload": {...}
        }

    Only record["raw_payload"] is hashed.
    """

    raw_payload = record.get("raw_payload")

    if not isinstance(raw_payload, dict):
        raise ValueError("Record must contain raw_payload as a dictionary.")

    return compute_raw_payload_hash(raw_payload)


def extract_source_job_id(record: dict[str, Any]) -> str | None:
    """
    Extract the source-specific job ID from a raw job record.

    For LinkedIn, this comes from:

        record["raw_payload"]["job_id"]

    Example:

        source_job_id = "4430018168"

    This will be used by the bronze loader for deduplication.
    """

    raw_payload = record.get("raw_payload")

    if not isinstance(raw_payload, dict):
        return None

    job_id = raw_payload.get("job_id")

    if job_id is None:
        return None

    return str(job_id)