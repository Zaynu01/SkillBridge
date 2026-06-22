"""
LinkedIn Search URL Inspector

This script is NOT the final production scraper.

Its goal is to test whether a public LinkedIn search page contains
job IDs or job links that we can extract automatically.

The script:

1. Downloads one LinkedIn search results page
2. Saves the HTML locally for inspection
3. Extracts LinkedIn job IDs from the HTML
4. Converts job IDs into direct job detail URLs
5. Saves discovered URLs to a text file

Expected usage:

docker compose run --rm pipeline python src/scraping/inspect_linkedin_search.py \
  "https://www.linkedin.com/jobs/search/?keywords=data%20analyst&location=Morocco" \
  --output data/sample/linkedin_discovered_urls.txt \
  --max-urls 20
"""

import argparse
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


# Inside Docker, ./data is mounted as /app/data
OUTPUT_HTML_PATH = Path("/app/data/sample/source_inspection/linkedin_search.html")
DEFAULT_OUTPUT_URLS_PATH = Path("/app/data/sample/linkedin_discovered_urls.txt")


def resolve_container_path(path_value: str) -> Path:
    """
    Convert a user-provided path into a container-safe path.

    Example:

    Host-style path:
        data/sample/linkedin_discovered_urls.txt

    Docker container path:
        /app/data/sample/linkedin_discovered_urls.txt

    This lets us run commands using project-relative paths while the script
    still writes to the correct Docker-mounted folder.
    """

    path = Path(path_value)

    if path.is_absolute():
        return path

    if path.parts and path.parts[0] == "data":
        return Path("/app") / path

    return path


def fetch_html(url: str) -> str:
    """
    Download the HTML of a LinkedIn search page.

    This uses a normal HTTP GET request.

    It does not bypass login walls, CAPTCHA, or access restrictions.
    If LinkedIn blocks or changes the response, we report the issue.
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
    Save the search page HTML for manual inspection.

    This is useful if URL discovery fails and we need to inspect the structure.
    """

    OUTPUT_HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML_PATH.write_text(html, encoding="utf-8")

    return OUTPUT_HTML_PATH


def normalize_linkedin_job_url(job_id: str) -> str:
    """
    Convert a LinkedIn job ID into a direct job detail URL.

    Example:
        4430018168

    becomes:
        https://www.linkedin.com/jobs/view/4430018168/
    """

    return f"https://www.linkedin.com/jobs/view/{job_id}/"


def extract_job_ids_from_html(html: str) -> list[str]:
    """
    Extract LinkedIn job IDs from raw HTML.

    LinkedIn job IDs can appear in several forms, for example:

    1. data-entity-urn="urn:li:jobPosting:4430018168"
    2. /jobs/view/data-analyst-engineer-at-company-4430018168
    3. /jobs/view/4430018168
    4. currentJobId=4430018168

    We collect IDs using multiple regex patterns, then deduplicate them
    while preserving order.
    """

    patterns = [
        # Example: urn:li:jobPosting:4430018168
        r"urn:li:jobPosting:(\d+)",

        # Example: /jobs/view/4430018168
        r"/jobs/view/(\d+)",

        # Example: /jobs/view/data-analyst-engineer-at-company-4430018168
        r"/jobs/view/[^\"'?<> ]*?-(\d+)",

        # Example: currentJobId=4430018168
        r"currentJobId=(\d+)",
    ]

    discovered_ids = []

    for pattern in patterns:
        matches = re.findall(pattern, html)

        for match in matches:
            if match not in discovered_ids:
                discovered_ids.append(match)

    return discovered_ids


def extract_job_urls_from_links(html: str) -> list[str]:
    """
    Extract LinkedIn job URLs from anchor tags.

    This is a second discovery strategy in addition to regex.

    It looks for <a href="..."> links containing /jobs/view/.
    Then it extracts the job ID from those links and normalizes it.
    """

    soup = BeautifulSoup(html, "lxml")

    discovered_urls = []

    for link in soup.select("a[href*='/jobs/view/']"):
        href = link.get("href")

        if not href:
            continue

        absolute_url = urljoin("https://www.linkedin.com", href)

        job_id = extract_job_id_from_url(absolute_url)

        if not job_id:
            continue

        direct_url = normalize_linkedin_job_url(job_id)

        if direct_url not in discovered_urls:
            discovered_urls.append(direct_url)

    return discovered_urls


def extract_job_id_from_url(url: str) -> str | None:
    """
    Extract a LinkedIn job ID from a job URL.

    Supported examples:

    https://www.linkedin.com/jobs/view/4430018168/
    https://www.linkedin.com/jobs/view/data-analyst-engineer-at-sharpatoms-4430018168
    https://www.linkedin.com/jobs/search/?currentJobId=4430018168

    Returns:
        job ID as string, or None if no job ID is found.
    """

    # Case 1: currentJobId=4430018168
    current_job_match = re.search(r"[?&]currentJobId=(\d+)", url)
    if current_job_match:
        return current_job_match.group(1)

    # Case 2: /jobs/view/4430018168/
    direct_match = re.search(r"/jobs/view/(\d+)", url)
    if direct_match:
        return direct_match.group(1)

    # Case 3: /jobs/view/some-title-company-4430018168
    slug_match = re.search(r"/jobs/view/[^/?#]*?-(\d+)(?:[/?#]|$)", url)
    if slug_match:
        return slug_match.group(1)

    return None


def discover_direct_job_urls(html: str, max_urls: int | None = None) -> list[str]:
    """
    Discover direct LinkedIn job URLs from a search page HTML.

    We combine two strategies:

    1. Regex over the full HTML
    2. BeautifulSoup anchor extraction

    Then we deduplicate while preserving order.
    """

    discovered_urls = []

    # Strategy 1: Extract job IDs from raw HTML with regex.
    job_ids = extract_job_ids_from_html(html)

    for job_id in job_ids:
        direct_url = normalize_linkedin_job_url(job_id)

        if direct_url not in discovered_urls:
            discovered_urls.append(direct_url)

    # Strategy 2: Extract links from anchor tags.
    linked_urls = extract_job_urls_from_links(html)

    for url in linked_urls:
        if url not in discovered_urls:
            discovered_urls.append(url)

    if max_urls is not None:
        return discovered_urls[:max_urls]

    return discovered_urls


def save_urls(urls: list[str], output_path: Path) -> None:
    """
    Save discovered direct job URLs into a text file.

    One URL per line.

    This output file can be passed directly into collect_linkedin_job_samples.py.
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_text = "\n".join(urls)

    if output_text:
        output_text += "\n"

    output_path.write_text(output_text, encoding="utf-8")


def print_report(search_url: str, urls: list[str], output_path: Path) -> None:
    """
    Print a clear report showing what was discovered.
    """

    print("\n" + "=" * 70)
    print("LinkedIn Search URL Discovery Report")
    print("=" * 70)

    print(f"Search URL: {search_url}")
    print(f"Discovered direct job URLs: {len(urls)}")
    print(f"Output URL file: {output_path}")

    if urls:
        print("\nDiscovered URLs:")

        for index, url in enumerate(urls, start=1):
            print(f"{index}. {url}")
    else:
        print("\nNo job URLs discovered.")
        print("Open the saved HTML file and inspect whether job IDs exist in the page.")

    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect one LinkedIn search page and extract job URLs."
    )

    parser.add_argument(
        "url",
        help="LinkedIn search URL to inspect.",
    )

    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_URLS_PATH),
        help=(
            "Path where discovered direct job URLs will be saved. "
            "Default: /app/data/sample/linkedin_discovered_urls.txt"
        ),
    )

    parser.add_argument(
        "--max-urls",
        type=int,
        default=20,
        help="Maximum number of job URLs to save. Default: 20.",
    )

    args = parser.parse_args()

    output_path = resolve_container_path(args.output)

    print("Starting LinkedIn search URL inspection...")
    print(f"Search URL: {args.url}")
    print(f"Output URL file: {output_path}")
    print(f"Max URLs: {args.max_urls}")

    html = fetch_html(args.url)

    html_path = save_html(html)
    print(f"Saved downloaded search HTML to: {html_path}")

    urls = discover_direct_job_urls(
        html=html,
        max_urls=args.max_urls,
    )

    save_urls(urls, output_path)

    print_report(
        search_url=args.url,
        urls=urls,
        output_path=output_path,
    )


if __name__ == "__main__":
    main()