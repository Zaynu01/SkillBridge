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
) -> Path:
    """
    Save every response separately for debugging.

    Example:

        linkedin_start_0.html
        linkedin_start_25.html
        linkedin_start_50.html
    """

    INSPECTION_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        INSPECTION_DIRECTORY
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Discover LinkedIn job URLs across "
            "multiple result offsets."
        )
    )

    parser.add_argument(
        "url",
        help="Original LinkedIn job search URL.",
    )

    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_URLS_PATH),
        help=(
            "Output text file containing one direct "
            "job URL per line."
        ),
    )

    parser.add_argument(
        "--max-urls",
        type=int,
        default=200,
        help=(
            "Maximum number of unique job URLs to save. "
            "This is a ceiling, not a guaranteed result count."
        ),
    )

    parser.add_argument(
        "--offset-step",
        type=int,
        default=10,
        help=(
            "Amount added to the start offset between requests. "
            "This does not control how many cards are returned."
        ),
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help=(
            "Maximum number of result-fragment requests."
        ),
    )

    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=3.0,
        help=(
            "Delay between requests."
        ),
    )

    parser.add_argument(
        "--max-consecutive-no-new",
        type=int,
        default=2,
        help=(
            "Stop after this many consecutive offsets "
            "return no new unique job URLs."
        ),
    )

    args = parser.parse_args()

    output_path = resolve_container_path(
        args.output
    )

    print("Starting LinkedIn URL discovery...")
    print(f"Original search URL: {args.url}")
    print(f"Output file: {output_path}")
    print(f"Maximum URLs: {args.max_urls}")
    print(f"Offset step: {args.offset_step}")
    print(f"Maximum pages: {args.max_pages}")
    print(f"Delay: {args.delay_seconds} seconds")

    urls = discover_job_urls_across_offsets(
        search_url=args.url,
        max_urls=args.max_urls,
        offset_step=args.offset_step,
        max_pages=args.max_pages,
        delay_seconds=args.delay_seconds,
        max_consecutive_no_new=(
            args.max_consecutive_no_new
        ),
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