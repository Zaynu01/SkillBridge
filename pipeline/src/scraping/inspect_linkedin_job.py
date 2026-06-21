"""
LinkedIn Job Detail Inspector

This script is NOT the final LinkedIn scraper.

Its goal is to test one LinkedIn job detail URL and answer:

1. Can Python requests download the job detail HTML?
2. Does the downloaded HTML contain a known phrase from the job description?
3. Can we extract useful fields from the LinkedIn job detail page?
4. Can we save one raw job sample in the format expected by the bronze layer?

Expected usage:

docker compose run --rm pipeline python src/scraping/inspect_linkedin_job.py \
  "https://www.linkedin.com/jobs/view/4430018168/" \
  --phrase "We are building a massive pool"
"""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup, Comment


# Inside the Docker container, ./data is mounted as /app/data
OUTPUT_DIR = Path("/app/data/sample/source_inspection")
RAW_SAMPLE_PATH = Path("/app/data/sample/real_raw_sample_jobs.json")


# ============================================================
# URL Helpers
# ============================================================

def get_direct_linkedin_job_url(url: str) -> str:
    """
    Convert a LinkedIn search URL with currentJobId into a direct job detail URL.

    Example:
    https://www.linkedin.com/jobs/search/?currentJobId=4430018168&...
    becomes:
    https://www.linkedin.com/jobs/view/4430018168/

    If the URL is already a direct /jobs/view/ URL, it is returned unchanged.
    """

    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)

    current_job_ids = query_params.get("currentJobId")

    if current_job_ids:
        job_id = current_job_ids[0]
        direct_url = f"https://www.linkedin.com/jobs/view/{job_id}/"

        print("Detected LinkedIn search URL with currentJobId.")
        print(f"Converted to direct job URL: {direct_url}")

        return direct_url

    return url


# ============================================================
# HTTP Fetching
# ============================================================

def fetch_html(url: str) -> str:
    """
    Download the HTML for one LinkedIn job detail page.

    This uses a normal HTTP GET request.
    It does not bypass login, CAPTCHA, or access restrictions.

    If LinkedIn blocks the request, we report that clearly.
    """

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=30,
    )

    print(f"HTTP status code: {response.status_code}")
    print(f"Final URL: {response.url}")
    print(f"Downloaded HTML size: {len(response.text)} characters")

    if response.status_code != 200:
        raise RuntimeError(
            f"Request failed with status code {response.status_code}. "
            "LinkedIn may be blocking the request or requiring login."
        )

    return response.text


def save_html(html: str) -> Path:
    """
    Save the downloaded HTML locally so we can inspect it manually later.

    This is useful when extraction fails and we need to inspect the page structure.
    """

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_path = OUTPUT_DIR / "linkedin_job_detail.html"
    output_path.write_text(html, encoding="utf-8")

    return output_path


# ============================================================
# Text and HTML Helpers
# ============================================================

def clean_text(text: Optional[str]) -> Optional[str]:
    """
    Normalize whitespace in extracted text.

    Example:
    "  Data   Analyst \\n Engineer  "
    becomes:
    "Data Analyst Engineer"
    """

    if not text:
        return None

    cleaned = re.sub(r"\s+", " ", text).strip()

    return cleaned if cleaned else None


def select_text(soup: BeautifulSoup, selector: str) -> Optional[str]:
    """
    Extract cleaned text from the first element matching a CSS selector.
    """

    element = soup.select_one(selector)

    if not element:
        return None

    return clean_text(element.get_text(" ", strip=True))


def select_attr(soup: BeautifulSoup, selector: str, attr: str) -> Optional[str]:
    """
    Extract an attribute value from the first element matching a CSS selector.

    Example:
    selector = "link[rel='canonical']"
    attr = "href"
    """

    element = soup.select_one(selector)

    if not element:
        return None

    value = element.get(attr)

    return clean_text(value)


def extract_comment_value_by_id(soup: BeautifulSoup, element_id: str) -> Optional[str]:
    """
    LinkedIn stores some values inside HTML comments.

    Example:

    <code id="decoratedJobPostingId" style="display: none">
      <!--"4430018168"-->
    </code>

    Normal get_text() may return empty, so we inspect comments.
    """

    element = soup.select_one(f"#{element_id}")

    if not element:
        return None

    for child in element.children:
        if isinstance(child, Comment):
            return child.strip().strip('"')

    return clean_text(element.get_text(" ", strip=True))


def contains_phrase(html: str, phrase: Optional[str]) -> bool:
    """
    Check whether a known phrase from the job description exists
    in the downloaded HTML.

    This is the key test:
    - True means requests downloaded useful job content.
    - False means LinkedIn may have returned different HTML.
    """

    if not phrase:
        return False

    return phrase.lower() in html.lower()


# ============================================================
# LinkedIn Extraction Logic
# ============================================================

def extract_description(soup: BeautifulSoup) -> tuple[Optional[str], Optional[str]]:
    """
    Extract both HTML and text versions of the job description.

    In the uploaded LinkedIn HTML, the actual job description is inside:

    div.show-more-less-html__markup

    We keep both:
    - description_html: useful if later we want section structure
    - description_text: useful for cleaning and skill extraction
    """

    container = soup.select_one("div.show-more-less-html__markup")

    if not container:
        return None, None

    description_html = str(container)
    description_text = clean_text(container.get_text(" ", strip=True))

    return description_html, description_text


def extract_criteria(soup: BeautifulSoup) -> dict:
    """
    Extract LinkedIn job criteria.

    Example criteria:
    - Seniority level
    - Employment type
    - Job function
    - Industries

    The output keys are normalized.

    Example:
    "Seniority level" becomes "seniority_level"
    """

    criteria = {}

    for item in soup.select("li.description__job-criteria-item"):
        key_element = item.select_one("h3.description__job-criteria-subheader")
        value_element = item.select_one("span.description__job-criteria-text")

        if not key_element or not value_element:
            continue

        key = clean_text(key_element.get_text(" ", strip=True))
        value = clean_text(value_element.get_text(" ", strip=True))

        if not key or not value:
            continue

        normalized_key = (
            key.lower()
            .replace(" ", "_")
            .replace("-", "_")
        )

        criteria[normalized_key] = value

    return criteria


def extract_linkedin_job_payload(html: str) -> dict:
    """
    Extract one LinkedIn job detail page into a raw payload.

    This payload is still considered raw/bronze-level because:
    - it keeps LinkedIn-specific fields
    - it keeps raw text like "2 days ago"
    - it keeps raw criteria labels
    - it keeps metadata like title_id and company_id

    Later, the silver mapper will convert this into clean standard tables.
    """

    soup = BeautifulSoup(html, "lxml")

    description_html, description_text = extract_description(soup)

    payload = {
        # LinkedIn job identifier.
        "job_id": extract_comment_value_by_id(
            soup,
            "decoratedJobPostingId",
        ),

        # Main job title.
        "title": select_text(
            soup,
            "h1.top-card-layout__title.topcard__title",
        ),

        # Company name.
        "company": select_text(
            soup,
            "a.topcard__org-name-link",
        ),

        # Job location.
        "location": select_text(
            soup,
            "span.topcard__flavor--bullet",
        ),

        # Raw posting age text.
        # Example: "2 days ago"
        "posted_time_text": select_text(
            soup,
            "span.posted-time-ago__text",
        ),

        # Raw applicant count text.
        # Example: "Over 200 applicants"
        "applicants_text": select_text(
            soup,
            "figcaption.num-applicants__caption",
        ),

        # Full description.
        "description_html": description_html,
        "description_text": description_text,

        # LinkedIn criteria section.
        "criteria": extract_criteria(soup),

        # Useful URLs and metadata.
        "canonical_url": select_attr(
            soup,
            "link[rel='canonical']",
            "href",
        ),

        "linkedin_url": select_attr(
            soup,
            "meta[property='lnkd:url']",
            "content",
        ),

        "og_title": select_attr(
            soup,
            "meta[property='og:title']",
            "content",
        ),

        "og_description": select_attr(
            soup,
            "meta[property='og:description']",
            "content",
        ),

        "title_id": select_attr(
            soup,
            "meta[name='titleId']",
            "content",
        ),

        "company_id": select_attr(
            soup,
            "meta[name='companyId']",
            "content",
        ),

        # Useful for debugging extraction quality.
        "html_size": len(html),
    }

    return payload


# ============================================================
# Raw Sample Output
# ============================================================

def build_raw_job_record(url: str, html: str) -> dict:
    """
    Build one bronze-compatible raw record.

    The wrapper matches the future bronze loader input:

    {
      "source_name": "...",
      "source_url": "...",
      "scraped_at": "...",
      "raw_payload": {...}
    }
    """

    raw_payload = extract_linkedin_job_payload(html)

    return {
        "source_name": "linkedin",
        "source_url": raw_payload.get("linkedin_url") or url,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "raw_payload": raw_payload,
    }


def save_raw_sample(record: dict) -> Path:
    """
    Save the extracted raw sample as JSON.

    For now, we overwrite the file with one record.

    Later, when we collect 10-30 jobs, we will change this behavior
    so the script can save multiple records.
    """

    RAW_SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)

    RAW_SAMPLE_PATH.write_text(
        json.dumps([record], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return RAW_SAMPLE_PATH


# ============================================================
# Console Summary
# ============================================================

def print_summary(record: dict, phrase_found: bool, phrase: Optional[str]) -> None:
    """
    Print a clear summary of what the inspector found.
    """

    raw_payload = record["raw_payload"]

    print("\n========== LinkedIn Inspection Summary ==========")

    print(f"Source URL: {record['source_url']}")
    print(f"Scraped at: {record['scraped_at']}")

    if phrase:
        print(f"Known phrase searched: {phrase}")
        print(f"Phrase found in downloaded HTML: {phrase_found}")
    else:
        print("Known phrase searched: None")

    print("\nExtracted raw payload preview:")
    print(f"- job_id: {raw_payload.get('job_id')}")
    print(f"- title: {raw_payload.get('title')}")
    print(f"- company: {raw_payload.get('company')}")
    print(f"- location: {raw_payload.get('location')}")
    print(f"- posted_time_text: {raw_payload.get('posted_time_text')}")
    print(f"- applicants_text: {raw_payload.get('applicants_text')}")

    criteria = raw_payload.get("criteria") or {}

    print("\nExtracted criteria:")
    if criteria:
        for key, value in criteria.items():
            print(f"- {key}: {value}")
    else:
        print("- No criteria found")

    description = raw_payload.get("description_text")

    print("\nDescription:")
    if description:
        print(f"- description length: {len(description)} characters")
        print(f"- description preview: {description[:300]}...")
    else:
        print("- description: NOT FOUND")

    print("================================================\n")


def print_warnings(record: dict, phrase: Optional[str], phrase_found: bool) -> None:
    """
    Print warnings when important fields are missing.
    """

    raw_payload = record["raw_payload"]

    if phrase and not phrase_found:
        print(
            "WARNING: The known phrase was not found in the downloaded HTML. "
            "This may mean LinkedIn returned different HTML to Python than to your browser."
        )

    required_fields = [
        "job_id",
        "title",
        "company",
        "location",
        "description_text",
    ]

    missing_fields = [
        field for field in required_fields
        if not raw_payload.get(field)
    ]

    if missing_fields:
        print(
            "WARNING: Some important fields were not extracted: "
            + ", ".join(missing_fields)
        )

    if not raw_payload.get("description_text"):
        print(
            "WARNING: Description extraction failed. "
            "Open the saved HTML file and inspect the structure manually."
        )


# ============================================================
# Main Entrypoint
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect one LinkedIn job detail page."
    )

    parser.add_argument(
        "url",
        help="LinkedIn job detail URL or LinkedIn search URL with currentJobId.",
    )

    parser.add_argument(
        "--phrase",
        help="Known phrase from the job description to search inside the downloaded HTML.",
        default=None,
    )

    args = parser.parse_args()

    print("Starting LinkedIn job detail inspection...")
    print(f"Original URL: {args.url}")

    job_url = get_direct_linkedin_job_url(args.url)

    print(f"URL used for request: {job_url}")

    html = fetch_html(job_url)

    html_path = save_html(html)
    print(f"Saved downloaded HTML to: {html_path}")

    phrase_found = contains_phrase(html, args.phrase)

    record = build_raw_job_record(job_url, html)

    raw_sample_path = save_raw_sample(record)
    print(f"Saved raw sample JSON to: {raw_sample_path}")

    print_summary(record, phrase_found, args.phrase)
    print_warnings(record, args.phrase, phrase_found)


if __name__ == "__main__":
    main()