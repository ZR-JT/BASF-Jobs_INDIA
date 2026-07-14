"""
scrape_jobs.py — Main scraper for BASF public job listings, worldwide.

Strategy:
  1. Parse https://basf.jobs/sitemap.xml to discover all public job URLs.
  2. Optionally filter by region slug (light_blue_AP, dark_blue_EMEA, etc.)
     for local testing — the default scope is the entire sitemap.
  3. Fetch each job detail page with rate limiting and parse structured fields.
  4. Merge with any existing data, remove stale entries.
  5. Write a single self-documenting JSON file: data/basf_jobs_all.json.

Usage:
  python scripts/scrape_jobs.py [--region REGION] [--limit N] [--output-dir data]
"""

import argparse
import json
import logging
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import requests

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent))
from parse_job import parse_job, extract_job_id_from_url

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SITEMAP_URL = "https://basf.jobs/sitemap.xml"
RATE_LIMIT_SECONDS = 1.5   # polite delay between requests
DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent / "data"
DEFAULT_LOG_DIR = Path(__file__).parent.parent / "logs"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; BASFJobBot/1.0; "
        "public-data-collection; educational-research)"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Sitemap namespaces (BASF uses Google's variant)
NS_LIST = [
    {"sm": "http://www.google.com/schemas/sitemap/0.9"},
    {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"},
]

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"scrape_{date.today().isoformat()}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output schema — embedded in the output file so downstream consumers
# (e.g. an MCP server) can read it without needing separate docs.
# ---------------------------------------------------------------------------

SCHEMA = {
    "job_id": "Unique numeric identifier from the BASF job URL",
    "name": "Job title",
    "location": "City / location as shown on the posting",
    "country": "Full country name, or 'unknown' / 'unknown (<region>)' if it could not be determined",
    "job_type": "Employment type (e.g. Permanent, Internship) — null if not shown",
    "job_field": "BASF job category (e.g. Engineering, Research & Development) — null if not found or if the extracted value looked malformed",
    "flexible_work": "Work model (e.g. Hybrid, On-site, Remote) — null if not specified",
    "description": "Full, unabridged English job description text — never truncated",
    "url": "Direct link to the BASF job posting",
    "posted_at": "Date the job was first posted (YYYY-MM-DD) — null if not available",
    "scraped_at": "Date this record was last fetched (YYYY-MM-DD)",
}


# ---------------------------------------------------------------------------
# Sitemap parsing
# ---------------------------------------------------------------------------


def fetch_sitemap(session: requests.Session) -> list[str]:
    """Download and parse the sitemap, returning all job URLs."""
    logger.info("Fetching sitemap: %s", SITEMAP_URL)
    try:
        resp = session.get(SITEMAP_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Failed to fetch sitemap: %s", exc)
        sys.exit(1)

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        logger.error("Failed to parse sitemap XML: %s", exc)
        sys.exit(1)

    urls = []
    # Try each known namespace variant
    for ns in NS_LIST:
        for loc in root.findall(".//sm:loc", ns):
            url = loc.text.strip() if loc.text else ""
            if url and "/job/" in url:
                urls.append(url)
            elif url and url.endswith("sitemap.xml"):
                sub_urls = _fetch_sub_sitemap(session, url)
                urls.extend(sub_urls)
        if urls:
            break

    # Fallback: no namespace
    if not urls:
        for loc in root.findall(".//loc"):
            url = loc.text.strip() if loc.text else ""
            if url and "/job/" in url:
                urls.append(url)
            elif url and url.endswith("sitemap.xml"):
                sub_urls = _fetch_sub_sitemap(session, url)
                urls.extend(sub_urls)

    logger.info("Found %d job URLs in sitemap", len(urls))
    return urls


def _fetch_sub_sitemap(session: requests.Session, url: str) -> list[str]:
    """Fetch a sub-sitemap and return its job URLs."""
    try:
        resp = session.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for ns in NS_LIST:
            urls = [
                loc.text.strip()
                for loc in root.findall(".//sm:loc", ns)
                if loc.text and "/job/" in loc.text
            ]
            if urls:
                return urls
        # Fallback: no namespace
        return [
            loc.text.strip()
            for loc in root.findall(".//loc")
            if loc.text and "/job/" in loc.text
        ]
    except (requests.RequestException, ET.ParseError) as exc:
        logger.warning("Could not fetch sub-sitemap %s: %s", url, exc)
        return []


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

REGION_SLUGS = {
    "AP": "light_blue_AP",
    "EMEA": "dark_blue_EMEA",
    "NA": "light_green_NA",
    "SA": "red_SA",
    "AGRI": "dark_green_agri",
}


def filter_urls(urls: list[str], region: str | None) -> list[str]:
    """Optionally restrict to a specific regional sitemap slug."""
    if not region:
        return urls
    slug = REGION_SLUGS.get(region.upper(), region)
    filtered = [u for u in urls if slug in u]
    logger.info("Filtered to %d URLs for region '%s'", len(filtered), slug)
    return filtered


# ---------------------------------------------------------------------------
# Loading / saving
# ---------------------------------------------------------------------------


def load_existing(path: Path) -> dict[str, dict]:
    """Load existing job data keyed by job_id."""
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        jobs = data.get("jobs", []) if isinstance(data, dict) else data
        if isinstance(jobs, list):
            return {j["job_id"]: j for j in jobs if "job_id" in j}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load existing data from %s: %s", path, exc)
    return {}


def save_json(path: Path, jobs_list: list[dict]) -> None:
    """Write the single self-documenting output file."""
    output = {
        "_about": "BASF job listings worldwide — public data collected from basf.jobs",
        "_schema": SCHEMA,
        "_generated_at": date.today().isoformat(),
        "_total_jobs": len(jobs_list),
        "jobs": jobs_list,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info("Saved: %s (%d jobs)", path, len(jobs_list))


# ---------------------------------------------------------------------------
# Main scraping loop
# ---------------------------------------------------------------------------


def scrape(
    region: str | None,
    limit: int | None,
    output_dir: Path,
    log_dir: Path,
    force_refresh: bool = False,
) -> list[dict]:
    setup_logging(log_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_jobs_path = output_dir / "basf_jobs_all.json"
    error_log_path = log_dir / f"errors_{date.today().isoformat()}.log"

    session = requests.Session()
    session.headers.update(HEADERS)

    # Load existing data to avoid redundant fetches
    existing: dict[str, dict] = {} if force_refresh else load_existing(all_jobs_path)
    logger.info("Loaded %d existing jobs", len(existing))

    # Discover job URLs
    all_urls = fetch_sitemap(session)
    urls = filter_urls(all_urls, region)

    if limit:
        urls = urls[:limit]
        logger.info("Limiting to %d URLs (--limit)", limit)

    # Track which job_ids appear in the current sitemap (for stale removal)
    current_ids = {extract_job_id_from_url(u) for u in urls if extract_job_id_from_url(u)}

    errors: list[str] = []
    scraped_count = 0
    skipped_count = 0

    for i, url in enumerate(urls, 1):
        job_id = extract_job_id_from_url(url)
        if not job_id:
            logger.debug("Skipping malformed URL: %s", url)
            continue

        # Skip if already scraped (unless force_refresh)
        if not force_refresh and job_id in existing:
            skipped_count += 1
            if skipped_count % 100 == 0:
                logger.info("Skipped %d already-cached jobs so far", skipped_count)
            continue

        logger.info("[%d/%d] Scraping job %s: %s", i, len(urls), job_id, url)
        job = parse_job(url, session=session)

        if job:
            existing[job_id] = job
            scraped_count += 1
        else:
            errors.append(url)
            logger.warning("Failed to parse: %s", url)

        # Rate limiting
        time.sleep(RATE_LIMIT_SECONDS)

    logger.info("Done. Scraped: %d, Skipped (cached): %d, Errors: %d",
                scraped_count, skipped_count, len(errors))

    # Remove jobs no longer in sitemap (stale)
    stale = [jid for jid in list(existing) if jid not in current_ids]
    if stale:
        logger.info("Removing %d stale jobs no longer in sitemap", len(stale))
        for jid in stale:
            del existing[jid]

    # Write error log
    if errors:
        error_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(error_log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(errors))
        logger.info("Error URLs written to: %s", error_log_path)

    jobs_list = sorted(existing.values(), key=lambda j: j.get("job_id", ""))
    save_json(all_jobs_path, jobs_list)
    return jobs_list


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape BASF public job listings.")
    parser.add_argument(
        "--region",
        help="Filter by region: AP, EMEA, NA, SA, AGRI (default: all)",
        default=None,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of job URLs to process (for testing)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to write JSON output files",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=DEFAULT_LOG_DIR,
        help="Directory for log files",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Re-scrape all jobs, ignoring cached data",
    )
    args = parser.parse_args()

    scrape(
        region=args.region,
        limit=args.limit,
        output_dir=args.output_dir,
        log_dir=args.log_dir,
        force_refresh=args.force_refresh,
    )


if __name__ == "__main__":
    main()
