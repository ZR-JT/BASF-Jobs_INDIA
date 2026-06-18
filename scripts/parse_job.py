"""
parse_job.py — Fetch and parse a single BASF job detail page.
Returns a structured dict or None on failure.
"""

import re
import logging
import time
from datetime import date
from urllib.parse import urlparse, urlencode, urljoin, parse_qs, urlunparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; BASFJobBot/1.0; "
        "public-data-collection; educational-research)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_TIMEOUT = 30  # seconds

# Text labels as they appear on the page (case-insensitive)
LABEL_MAP = {
    "location": ["location", "standort", "lieu"],
    "country": ["country"],
    "company": ["company", "unternehmen", "société"],
    "job_field": ["job field", "berufsfeld", "domaine"],
    "job_type": ["job type", "stellentyp", "type de contrat", "employment type"],
    "flexible_work": [
        "flexible work options",
        "work flexibility",
        "flexibles arbeiten",
        "flexible",
    ],
    "job_id_page": ["job id", "job-id", "job number"],
}

# Navigation / boilerplate text to strip from description
BOILERPLATE_PATTERNS = re.compile(
    r"(cookie|privacy policy|imprint|impressum|data protection|terms of use"
    r"|all rights reserved|basf\.jobs|copyright|javascript|loading\.\.\."
    r"|skip to|back to|apply now|share this|print|save job)",
    re.I,
)


def _add_locale(url: str, locale: str = "en_US") -> str:
    """Append locale=en_US to a job URL if not already present."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "locale" not in qs:
        connector = "&" if parsed.query else "?"
        return url.rstrip("/") + "/" + connector + f"locale={locale}"
    return url


def extract_job_id_from_url(url: str) -> str | None:
    """Extract the numeric job ID that appears at the end of the URL path."""
    match = re.search(r"/(\d{6,})", url)
    return match.group(1) if match else None


def _find_label_value(soup: BeautifulSoup, labels: list[str]) -> str | None:
    """
    Locate a field value by searching for one of its text labels on the page.
    The SuccessFactors layout pairs labels with values in adjacent elements.
    """
    for label in labels:
        pattern = re.compile(rf"^\s*{re.escape(label)}\s*$", re.I)
        node = soup.find(string=pattern)
        if not node:
            # Partial match fallback
            pattern = re.compile(rf"\b{re.escape(label)}\b", re.I)
            node = soup.find(string=pattern)
        if not node:
            continue

        # Walk up to an element that has a meaningful sibling or child
        for ancestor_steps in range(4):
            elem = node if ancestor_steps == 0 else node.parent
            for _ in range(ancestor_steps):
                if elem and elem.parent:
                    elem = elem.parent

            if elem is None:
                break

            # Try next sibling elements
            sibling = elem.find_next_sibling()
            while sibling:
                text = sibling.get_text(" ", strip=True)
                if text and not re.match(pattern, text):
                    return text
                sibling = sibling.find_next_sibling()

            # Try parent's next sibling
            if elem.parent:
                parent_sib = elem.parent.find_next_sibling()
                if parent_sib:
                    text = parent_sib.get_text(" ", strip=True)
                    if text:
                        return text

    return None


def _extract_location_country(soup: BeautifulSoup, url: str) -> tuple[str, str]:
    """Return (location_string, country_string) parsed from page or URL."""
    raw = _find_label_value(soup, LABEL_MAP["location"])
    country = _find_label_value(soup, LABEL_MAP["country"])

    # Fallback: parse location from URL slug
    if not raw:
        slug_match = re.search(r"/job/([^/]+)/", url)
        if slug_match:
            slug = slug_match.group(1).replace("-", " ").replace("%20", " ")
            parts = slug.split(" ")
            raw = parts[0] if parts else None

    location = raw.strip() if raw else "unknown"

    # Infer country from location string if explicit country field is missing
    if not country and raw:
        # "Hyderabad, IND" → IND
        country_match = re.search(r",\s*([A-Z]{2,3})\s*$", raw)
        if country_match:
            country = country_match.group(1)

    return location, (country.strip() if country else "unknown")


def _extract_description(soup: BeautifulSoup) -> str:
    """Extract and clean the job description text."""
    # Remove script, style, nav, header, footer, cookie banners
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "form"]):
        tag.decompose()

    # Look for common description containers
    desc_elem = None
    for selector in [
        ".jd-desc", ".job-description", "#job-description",
        "[class*='desc']", "[class*='content']", "article",
        ".posting-requirements", ".job-details-description",
    ]:
        desc_elem = soup.select_one(selector)
        if desc_elem:
            break

    if not desc_elem:
        # Fall back to the largest <div> or <section> block
        candidates = []
        for tag in soup.find_all(["div", "section", "main"]):
            text = tag.get_text(" ", strip=True)
            if len(text) > 200:
                candidates.append((len(text), tag))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            desc_elem = candidates[0][1]

    if desc_elem:
        raw_text = desc_elem.get_text(" ", strip=True)
    else:
        raw_text = soup.get_text(" ", strip=True)

    # Clean: split into lines, filter boilerplate
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    cleaned = [l for l in lines if not BOILERPLATE_PATTERNS.search(l) and len(l) > 3]
    return " ".join(cleaned)[:8000]  # cap at 8k chars


def parse_job(url: str, session: requests.Session | None = None) -> dict | None:
    """
    Fetch a BASF job detail page and return a structured dict.
    Returns None if the page cannot be fetched or parsed successfully.
    """
    job_id = extract_job_id_from_url(url)
    if not job_id:
        logger.warning("Cannot extract job_id from URL: %s", url)
        return None

    fetch_url = _add_locale(url)
    sess = session or requests.Session()

    try:
        resp = sess.get(fetch_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Failed to fetch %s: %s", fetch_url, exc)
        return None

    if resp.status_code != 200:
        logger.warning("Non-200 status %d for %s", resp.status_code, fetch_url)
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    # --- Job title ---
    title = None
    for sel in ["h1", ".job-title", ".jd-title", "[class*='title']", "title"]:
        elem = soup.select_one(sel)
        if elem:
            title = elem.get_text(" ", strip=True)
            # Strip site name suffix like " | BASF"
            title = re.sub(r"\s*[|\-–]\s*BASF.*$", "", title, flags=re.I).strip()
            if title:
                break
    if not title:
        title = "unknown"

    # --- Location & Country ---
    location, country = _extract_location_country(soup, url)

    # Normalise country codes to full names
    country = _normalise_country(country)

    # --- Job Field ---
    job_field = _find_label_value(soup, LABEL_MAP["job_field"])

    # --- Job Type ---
    job_type = _find_label_value(soup, LABEL_MAP["job_type"])

    # --- Flexible Work ---
    flexible_work = _find_label_value(soup, LABEL_MAP["flexible_work"])

    # --- Description ---
    description = _extract_description(soup)

    # Guard: if description is essentially empty the page likely failed
    if len(description) < 50:
        logger.warning("Description too short for %s — skipping", url)
        return None

    return {
        "job_id": job_id,
        "name": title,
        "location": location or "unknown",
        "country": country or "unknown",
        "job_type": job_type or None,
        "job_field": job_field or None,
        "flexible_work": flexible_work or None,
        "description": description,
        "url": url,
        "scraped_at": date.today().isoformat(),
    }


# ISO-3166 alpha-3 and common abbreviations → full names
_COUNTRY_CODES: dict[str, str] = {
    "IND": "India", "IN": "India",
    "CHN": "China", "CN": "China",
    "MYS": "Malaysia", "MY": "Malaysia",
    "SGP": "Singapore", "SG": "Singapore",
    "JPN": "Japan", "JP": "Japan",
    "KOR": "South Korea", "KR": "South Korea",
    "THA": "Thailand", "TH": "Thailand",
    "IDN": "Indonesia", "ID": "Indonesia",
    "PHL": "Philippines", "PH": "Philippines",
    "VNM": "Vietnam", "VN": "Vietnam",
    "AUS": "Australia", "AU": "Australia",
    "NZL": "New Zealand", "NZ": "New Zealand",
    "DEU": "Germany", "DE": "Germany",
    "FRA": "France", "FR": "France",
    "GBR": "United Kingdom", "GB": "United Kingdom",
    "USA": "United States", "US": "United States",
    "CAN": "Canada", "CA": "Canada",
    "BRA": "Brazil", "BR": "Brazil",
    "MEX": "Mexico", "MX": "Mexico",
    "CHE": "Switzerland", "CH": "Switzerland",
    "BEL": "Belgium", "BE": "Belgium",
    "NLD": "Netherlands", "NL": "Netherlands",
    "ESP": "Spain", "ES": "Spain",
    "ITA": "Italy", "IT": "Italy",
    "POL": "Poland", "PL": "Poland",
    "HKG": "Hong Kong", "HK": "Hong Kong",
    "TWN": "Taiwan", "TW": "Taiwan",
    "ZAF": "South Africa", "ZA": "South Africa",
    "GER": "Germany",  # BASF sometimes uses this
    "AUT": "Austria", "AT": "Austria",
}


def _normalise_country(raw: str) -> str:
    """Convert country codes or short forms to full country names."""
    if not raw or raw.lower() in ("unknown", ""):
        return "unknown"
    clean = raw.strip().upper()
    if clean in _COUNTRY_CODES:
        return _COUNTRY_CODES[clean]
    # Already a full name
    return raw.strip()
