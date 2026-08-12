"""
Paginated LinkedIn Job URL Discovery

This script extracts public LinkedIn job URLs from multiple result offsets.

It does not:
- log in to LinkedIn;
- bypass CAPTCHA;
- bypass access restrictions;
- guarantee that LinkedIn exposes every available search result.

Example:

docker compose run --rm pipeline python \
src/scraping/inspect_linkedin_search.py \
"https://www.linkedin.com/jobs/search/?keywords=machine%20learning&location=United%20States" \
--output data/sample/linkedin_batch_02_urls.txt \
--max-urls 200 \
--offset-step 25 \
--max-pages 20 \
--delay-seconds 3
"""

from __future__ import annotations

import argparse
import hashlib
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit
import json

import requests
from bs4 import BeautifulSoup


# Result-fragment path used by LinkedIn's public jobs page.
SEARCH_FRAGMENT_ENDPOINT = (
    "https://www.linkedin.com/jobs-guest/"
    "jobs/api/seeMoreJobPostings/search"
)

DEFAULT_OUTPUT_URLS_PATH = Path(
    "/app/data/sample/linkedin_discovered_urls.txt"
)

INSPECTION_DIRECTORY = Path(
    "/app/data/sample/source_inspection/linkedin_pages"
)

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
}

LINKEDIN_SEARCH_URL = "https://www.linkedin.com/jobs/search/"


def resolve_container_path(path_value: str) -> Path:
    """
    Convert a project-relative data path into its Docker path.

    Example:

        data/sample/jobs.txt

    becomes:

        /app/data/sample/jobs.txt
    """

    path = Path(path_value)

    if path.is_absolute():
        return path

    if path.parts and path.parts[0] == "data":
        return Path("/app") / path

    return path

def load_batch_config(config_path: Path) -> dict:
    """
    Load and validate the LinkedIn batch-search configuration.
    """

    if not config_path.exists():
        raise FileNotFoundError(
            f"Batch config does not exist: {config_path}"
        )

    config = json.loads(
        config_path.read_text(encoding="utf-8")
    )

    required_fields = {
        "location",
        "max_urls_per_search",
        "offset_step",
        "max_pages",
        "delay_seconds",
        "output_dir",
        "searches",
    }

    missing_fields = required_fields - config.keys()

    if missing_fields:
        raise ValueError(
            "Batch config is missing required fields: "
            + ", ".join(sorted(missing_fields))
        )

    if not isinstance(config["searches"], list):
        raise ValueError(
            "'searches' must be a list."
        )

    if not config["searches"]:
        raise ValueError(
            "'searches' cannot be empty."
        )

    return config

def build_linkedin_search_url(
    keywords: str,
    location: str,
) -> str:
    """
    Build a LinkedIn search-page URL from keywords and location.
    """

    query_string = urlencode(
        {
            "keywords": keywords,
            "location": location,
        }
    )

    return f"{LINKEDIN_SEARCH_URL}?{query_string}"


def normalize_linkedin_job_url(job_id: str) -> str:
    """Build one stable direct LinkedIn job URL."""

    return f"https://www.linkedin.com/jobs/view/{job_id}/"


def extract_job_id_from_url(url: str) -> str | None:
    """
    Extract the numeric LinkedIn job ID from a direct or slug URL.

    Supported examples:

        /jobs/view/4430018168/
        /jobs/view/data-analyst-company-4430018168
    """

    direct_match = re.search(
        r"/jobs/view/(\d+)",
        url,
    )

    if direct_match:
        return direct_match.group(1)

    slug_match = re.search(
        r"/jobs/view/[^/?#]*?-(\d+)(?:[/?#]|$)",
        url,
    )

    if slug_match:
        return slug_match.group(1)

    return None


def build_fragment_url(
    original_search_url: str,
    start_offset: int,
) -> str:
    """
    Build a result-fragment request while preserving the search filters.

    Example input:

        https://www.linkedin.com/jobs/search/
        ?keywords=machine%20learning
        &location=United%20States
        &f_E=2

    Example fragment request:

        https://www.linkedin.com/jobs-guest/jobs/api/
        seeMoreJobPostings/search
        ?keywords=machine+learning
        &location=United+States
        &f_E=2
        &start=25
    """

    parsed_url = urlsplit(original_search_url)

    original_parameters = parse_qsl(
        parsed_url.query,
        keep_blank_values=True,
    )

    # These parameters belong to page navigation or tracking and should not
    # be copied into each fragment request.
    ignored_parameters = {
        "start",
        "currentJobId",
        "position",
        "pageNum",
        "trk",
    }

    fragment_parameters = [
        (name, value)
        for name, value in original_parameters
        if name not in ignored_parameters
    ]

    fragment_parameters.append(
        ("start", str(start_offset))
    )

    encoded_parameters = urlencode(
        fragment_parameters,
        doseq=True,
    )

    return (
        f"{SEARCH_FRAGMENT_ENDPOINT}"
        f"?{encoded_parameters}"
    )


def fetch_html(
    session: requests.Session,
    url: str,
) -> str:
    """
    Download one result fragment.

    The function raises an error for non-successful HTTP responses.
    """

    response = session.get(
        url,
        headers=REQUEST_HEADERS,
        timeout=30,
    )

    print(f"HTTP status: {response.status_code}")
    print(f"Final URL: {response.url}")
    print(f"HTML size: {len(response.text)} characters")

    if response.status_code != 200:
        raise RuntimeError(
            f"Request failed with HTTP status "
            f"{response.status_code}."
        )

    response_text_lower = response.text.lower()

    restriction_markers = (
        "captcha",
        "authwall",
        "sign in to linkedin",
        "join linkedin",
    )

    if any(
        marker in response_text_lower
        for marker in restriction_markers
    ):
        raise RuntimeError(
            "LinkedIn returned a login or access-restriction page."
        )

    return response.text


def save_fragment_html(
    html: str,
    start_offset: int,
    search_name: str,
) -> Path:
    """
    Save one result fragment inside a directory
    dedicated to the current search.
    """

    search_directory = (
        INSPECTION_DIRECTORY / search_name
    )

    search_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        search_directory
        / f"linkedin_start_{start_offset}.html"
    )

    output_path.write_text(
        html,
        encoding="utf-8",
    )

    return output_path


def extract_job_urls_from_cards(
    html: str,
) -> list[str]:
    """
    Extract direct URLs only from job-card anchor elements.

    We intentionally do not scan the full HTML using broad regex patterns.
    The earlier approach could collect IDs from preloaded scripts and other
    unrelated sections of the complete search page.
    """

    soup = BeautifulSoup(
        html,
        "lxml",
    )

    discovered_urls: list[str] = []
    discovered_ids: set[str] = set()

    # Preferred selector for LinkedIn public job cards.
    links = soup.select(
        "a.base-card__full-link"
    )

    # Fallback in case the specific CSS class changes while the job links
    # still contain /jobs/view/.
    if not links:
        links = soup.select(
            "a[href*='/jobs/view/']"
        )

    for link in links:
        href = link.get("href")

        if not href:
            continue

        absolute_url = urljoin(
            "https://www.linkedin.com",
            href,
        )

        job_id = extract_job_id_from_url(
            absolute_url,
        )

        if not job_id:
            continue

        if job_id in discovered_ids:
            continue

        discovered_ids.add(job_id)

        discovered_urls.append(
            normalize_linkedin_job_url(job_id)
        )

    return discovered_urls


def discover_job_urls_across_offsets(
    search_url: str,
    max_urls: int,
    offset_step: int,
    max_pages: int,
    delay_seconds: float,
    max_consecutive_no_new: int = 2,
    search_name: str = "single_search",
) -> list[str]:
    """
    Request several result offsets and collect unique job URLs.

    Stops when:

    1. max_urls unique URLs have been collected;
    2. max_pages requests have been made;
    3. multiple consecutive offsets return no new jobs;
    4. a request fails or returns an access-restriction page.
    """

    if max_urls <= 0:
        raise ValueError(
            "--max-urls must be greater than zero."
        )

    if offset_step <= 0:
        raise ValueError(
            "--offset-step must be greater than zero."
        )

    if max_pages <= 0:
        raise ValueError(
            "--max-pages must be greater than zero."
        )

    if delay_seconds < 0:
        raise ValueError(
            "--delay-seconds cannot be negative."
        )

    if max_consecutive_no_new <= 0:
        raise ValueError(
            "--max-consecutive-no-new must be greater than zero."
        )

    discovered_urls: list[str] = []
    discovered_url_set: set[str] = set()

    consecutive_no_new_responses = 0

    with requests.Session() as session:
        for page_index in range(max_pages):
            if len(discovered_urls) >= max_urls:
                break

            start_offset = page_index * offset_step

            fragment_url = build_fragment_url(
                original_search_url=search_url,
                start_offset=start_offset,
            )

            print()
            print("=" * 72)
            print(
                f"Request {page_index + 1}/{max_pages}"
            )
            print(f"Start offset: {start_offset}")
            print(f"Request URL: {fragment_url}")
            print("=" * 72)

            try:
                html = fetch_html(
                    session=session,
                    url=fragment_url,
                )
            except (
                requests.RequestException,
                RuntimeError,
            ) as error:
                print(
                    "Stopping because the request failed:"
                )
                print(error)
                break

            saved_path = save_fragment_html(
                html=html,
                start_offset=start_offset,
                search_name=search_name,
            )

            print(
                f"Saved response HTML: {saved_path}"
            )

            html_fingerprint = hashlib.sha256(
                html.encode("utf-8")
            ).hexdigest()[:12]

            page_urls = extract_job_urls_from_cards(
                html
            )

            page_url_set = set(page_urls)

            already_known_urls = (
                page_url_set
                & discovered_url_set
            )

            new_page_urls = [
                url
                for url in page_urls
                if url not in discovered_url_set
            ]

            print(
                f"Response fingerprint: "
                f"{html_fingerprint}"
            )
            print(
                f"Unique card URLs in response: "
                f"{len(page_url_set)}"
            )
            print(
                f"Previously discovered URLs: "
                f"{len(already_known_urls)}"
            )
            print(
                f"New unique URLs: "
                f"{len(new_page_urls)}"
            )

            for url in new_page_urls:
                discovered_url_set.add(url)
                discovered_urls.append(url)

                if len(discovered_urls) >= max_urls:
                    break

            print(
                f"Total unique URLs: "
                f"{len(discovered_urls)}/{max_urls}"
            )

            if new_page_urls:
                consecutive_no_new_responses = 0
            else:
                consecutive_no_new_responses += 1

                print(
                    "No new URLs for this offset "
                    f"({consecutive_no_new_responses}/"
                    f"{max_consecutive_no_new})."
                )

            if (
                consecutive_no_new_responses
                >= max_consecutive_no_new
            ):
                print(
                    "Stopping because multiple consecutive "
                    "offsets returned no new job URLs."
                )
                break

            if len(discovered_urls) >= max_urls:
                break

            if page_index < max_pages - 1:
                print(
                    f"Waiting {delay_seconds} seconds..."
                )

                time.sleep(delay_seconds)

    return discovered_urls[:max_urls]


def run_batch_discovery(config_path: Path) -> None:
    config = load_batch_config(config_path)

    location = config["location"]
    default_max_urls = config["max_urls_per_search"]
    offset_step = config["offset_step"]
    max_pages = config["max_pages"]
    delay_seconds = config["delay_seconds"]

    max_consecutive_no_new = config.get(
        "max_consecutive_no_new",
        2,
    )

    output_directory = resolve_container_path(
        config["output_dir"]
    )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    searches = config["searches"]

    # Used for the final report
    batch_results = {}


    # Remember every role-specific URL file
    role_url_files = []

    print()
    print("=" * 72)
    print("Starting LinkedIn batch URL discovery")
    print("=" * 72)

    # Run every configured search
    for index, search in enumerate(
        searches,
        start=1,
    ):
        search_name = search["name"]
        keywords = search["keywords"]

        max_urls = search.get(
            "max_urls",
            default_max_urls,
        )

        search_url = build_linkedin_search_url(
            keywords=keywords,
            location=location,
        )

        output_path = (
            output_directory
            / f"{search_name}_urls.txt"
        )

        print()
        print("#" * 72)
        print(
            f"SEARCH {index}/{len(searches)}: "
            f"{search_name}"
        )
        print("#" * 72)

        urls = discover_job_urls_across_offsets(
            search_url=search_url,
            max_urls=max_urls,
            offset_step=offset_step,
            max_pages=max_pages,
            delay_seconds=delay_seconds,
            max_consecutive_no_new=(
                max_consecutive_no_new
            ),
            search_name=search_name,
        )

        # Save this particular role
        save_urls(
            urls=urls,
            output_path=output_path,
        )

        # Remember the file for final combination
        role_url_files.append(output_path)

        batch_results[search_name] = len(urls)

        print(
            f"Completed {search_name}: "
            f"{len(urls)} unique URLs"
        )

    # Combine the role-specific files
    combined_output_path = (
        output_directory
        / "all_job_urls.txt"
    )

    combined_urls = combine_job_urls(
        files=role_url_files,
        output_path=combined_output_path,
    )

    # Batch report
    print()
    print("=" * 72)
    print("Batch discovery summary")
    print("=" * 72)

    total_search_references = 0

    for search_name, url_count in batch_results.items():
        print(
            f"{search_name:<30} {url_count:>5}"
        )

        total_search_references += url_count

    print("-" * 72)

    print(
        f"{'Search references':<30} "
        f"{total_search_references:>5}"
    )

    print(
        f"{'Final unique jobs':<30} "
        f"{len(combined_urls):>5}"
    )

    print(
        f"{'Duplicates removed':<30} "
        f"{total_search_references - len(combined_urls):>5}"
    )

    print(
        f"Combined file: {combined_output_path}"
    )

    print("=" * 72)

def save_urls(
    urls: list[str],
    output_path: Path,
) -> None:
    """Save one direct job URL per line."""

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_text = "\n".join(urls)

    if output_text:
        output_text += "\n"

    output_path.write_text(
        output_text,
        encoding="utf-8",
    )


def print_report(
    search_url: str,
    urls: list[str],
    output_path: Path,
) -> None:
    """Print the final URL-discovery summary."""

    print()
    print("=" * 72)
    print("LinkedIn URL Discovery Report")
    print("=" * 72)
    print(f"Search URL: {search_url}")
    print(
        f"Unique job URLs discovered: {len(urls)}"
    )
    print(f"Output file: {output_path}")

    if len(urls) == 0:
        print(
            "No public job-card URLs were discovered."
        )

    print("=" * 72)

def combine_job_urls(files, output_path):
    job_urls = set()

    for file_path in files:
        with open(file_path, "r", encoding="utf-8") as file:
            for line in file:
                url = line.strip()

                if url:
                    job_urls.add(url)

    with open(output_path, "w", encoding="utf-8") as file:
        for url in job_urls:
            file.write(url + "\n")

    return job_urls


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Discover LinkedIn job URLs."
        )
    )

    parser.add_argument(
        "url",
        nargs="?",
        help=(
            "LinkedIn search URL for "
            "single-search mode."
        ),
    )

    parser.add_argument(
        "--batch-config",
        help=(
            "JSON configuration file for "
            "batch-search mode."
        ),
    )

    # Keep your existing arguments:
    parser.add_argument(
        "--output",
        default=str(
            DEFAULT_OUTPUT_URLS_PATH
        ),
    )

    parser.add_argument(
        "--max-urls",
        type=int,
        default=200,
    )

    parser.add_argument(
        "--offset-step",
        type=int,
        default=10,
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=30,
    )

    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=3.0,
    )

    parser.add_argument(
        "--max-consecutive-no-new",
        type=int,
        default=2,
    )

    args = parser.parse_args()

    # ============================================
    # Batch mode
    # ============================================

    if args.batch_config:
        config_path = Path(
            args.batch_config
        )

        if not config_path.is_absolute():
            config_path = (
                Path("/app") / config_path
            )

        run_batch_discovery(
            config_path=config_path
        )

        return

    # ============================================
    # Single-search mode
    # ============================================

    if not args.url:
        parser.error(
            "Provide either a search URL "
            "or --batch-config."
        )

    output_path = resolve_container_path(
        args.output
    )

    urls = discover_job_urls_across_offsets(
        search_url=args.url,
        max_urls=args.max_urls,
        offset_step=args.offset_step,
        max_pages=args.max_pages,
        delay_seconds=args.delay_seconds,
        max_consecutive_no_new=(
            args.max_consecutive_no_new
        ),
        search_name="single_search",
    )

    save_urls(
        urls=urls,
        output_path=output_path,
    )

    print_report(
        search_url=args.url,
        urls=urls,
        output_path=output_path,
    )

if __name__ == "__main__":
    main()