"""
parse_job.py — Fetch and parse a single BASF job detail page.

Actual BASF/SuccessFactors page structure (from inspected HTML):
  Job Title: <value>
  Company: <value>
  Posting Location: Country: <country>  Requisition ID: <id>
  Field: <job_field>  Job Type: <job_type>  Work model: <flexible_work>
  Job Description Header: ...
  Job Description: <main text>
  Apply now  Credits  ...  Copyright © BASF SE

All fields are extracted with targeted regex patterns on the clean page text.
"""

import re
import logging
from datetime import date
from urllib.parse import urlparse, parse_qs

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

REQUEST_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def extract_job_id_from_url(url: str) -> str | None:
    """Return the numeric job ID from the end of a BASF job URL."""
    m = re.search(r"/(\d{6,})/?(?:\?.*)?$", url)
    return m.group(1) if m else None


def _add_locale(url: str, locale: str = "en_US") -> str:
    """Append ?locale=en_US if not already present."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "locale" not in qs:
        sep = "&" if parsed.query else "?"
        return url.rstrip("/") + f"/{sep}locale={locale}"
    return url


def _page_text(html: str) -> str:
    """Convert raw HTML to clean visible text (no scripts/styles)."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return re.sub(r" {2,}", " ", text)


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

def _extract_fields(text: str) -> dict:
    """
    Extract job metadata by matching the known label patterns in the page text.

    Observed label formats on BASF SuccessFactors pages:
      "Job Title: <value>"
      "Company: <value>"
      "Country: <value>"
      "Requisition ID: <value>"
      "Field: <value>"
      "Job Type: <value>"
      "Work model: <value>"

    The labels appear in a compact block before "Job Description Header:".
    We use lookahead for the NEXT known label as the stop boundary.
    """
    def _capture(prefix: str, stop: str) -> str | None:
        """Capture a field value between prefix and stop boundary."""
        m = re.search(
            prefix + rf"(.+?)(?=\s*(?:{stop}|$))",
            text, re.I | re.S,
        )
        if m:
            val = m.group(1).strip()
            if val and len(val) < 300:
                return val
        return None

    job_field = _capture(
        r"Field:\s*",
        r"Job Type:|Work model:|Posting Start Date:|Job Description",
    )
    job_type = _capture(
        r"Job Type:\s*",
        r"Work model:|Posting Start Date:|Job Description",
    )
    # Work model stops before "Posting Start Date:" — use non-greedy single-line
    work_model_m = re.search(
        r"Work model:\s*([^\n:]{1,80})(?=\s*(?:Posting Start Date:|Duration|Job Description|$))",
        text, re.I,
    )
    work_model = work_model_m.group(1).strip() if work_model_m else None
    if work_model and (len(work_model) > 80 or "Posting" in work_model):
        work_model = None

    # Country appears as "Posting Location: Country: <value>" or standalone
    country_m = re.search(
        r"Country:\s*([A-Za-z][A-Za-z ]+?)(?=\s*(?:Requisition ID:|Field:|$))",
        text, re.I
    )
    country_raw = country_m.group(1).strip() if country_m else None

    # Location: "Posting Location: Country: <X> Requisition ID: ..." →
    # BASF doesn't expose a city in the meta block; derive from URL slug later
    location_m = re.search(r"Posting Location:\s*(.+?)(?=Requisition ID:|Field:|$)", text, re.I)
    location_raw = location_m.group(1).strip() if location_m else None

    # Job title from the structured block (fallback for <h1> failures)
    title_m = re.search(r"Job Title:\s*(.+?)(?=Company:|$)", text, re.I)
    title_raw = title_m.group(1).strip() if title_m else None

    return {
        "title_from_text": title_raw,
        "location_raw": location_raw,
        "country_raw": country_raw,
        "job_field": job_field or None,
        "job_type": job_type or None,
        "flexible_work": work_model or None,
    }


# ---------------------------------------------------------------------------
# Description extraction
# ---------------------------------------------------------------------------

def _extract_description(text: str) -> str:
    """
    Extract the job description from clean page text.

    The description sits between "Job Description:" and "Apply now" /
    "Credits" / "Copyright".  If the marker isn't found we fall back to
    the largest prose block.
    """
    # Find start marker
    start_m = re.search(r"Job Description(?:\s+Header)?:\s*", text, re.I)
    if start_m:
        desc = text[start_m.end():]
        # Strip a leading "Job Description Header: " if there are two markers
        desc = re.sub(r"^Job Description Header:.*?Job Description:\s*", "", desc, flags=re.I | re.S)
        # Find end marker
        end_m = re.search(r"\s*(?:Apply now|Credits\s+Data|Copyright\s+©)", desc, re.I)
        if end_m:
            desc = desc[: end_m.start()]
        desc = desc.strip()
        if len(desc) > 50:
            return desc[:10000]

    # Fallback: return everything between navigation and footer markers
    start_m2 = re.search(r"(?:Employee Login|Profile Login)\s*", text, re.I)
    end_m2 = re.search(r"Apply now\s*Credits", text, re.I)
    if start_m2 and end_m2:
        block = text[start_m2.end(): end_m2.start()].strip()
        if len(block) > 50:
            return block[:10000]

    return text[:10000]


# ---------------------------------------------------------------------------
# Title extraction
# ---------------------------------------------------------------------------

def _extract_title(soup: BeautifulSoup, text: str) -> str:
    """Extract the job title from HTML or clean text."""
    # Try HTML selectors
    for sel in ["h1", ".job-title", "[class*='title']"]:
        elem = soup.select_one(sel)
        if elem:
            t = elem.get_text(" ", strip=True)
            t = re.sub(r"\s*[|\-–]\s*BASF.*$", "", t, flags=re.I).strip()
            if t and len(t) < 300:
                return t

    # Try <title> tag
    title_tag = soup.find("title")
    if title_tag:
        t = title_tag.get_text(" ", strip=True)
        t = re.sub(r"\s*(?:[|\-–]\s*BASF.*|Job Details.*)$", "", t, flags=re.I).strip()
        if t and len(t) < 300:
            return t

    # Try "Job Title: ..." in page text
    m = re.search(r"Job Title:\s*(.+?)(?=Company:|$)", text, re.I)
    if m:
        return m.group(1).strip()

    return "unknown"


# ---------------------------------------------------------------------------
# Country normalisation
# ---------------------------------------------------------------------------

_COUNTRY_CODES: dict[str, str] = {
    "IND": "India", "INDIA": "India",
    "CHN": "China", "CHINA": "China",
    "MYS": "Malaysia", "MALAYSIA": "Malaysia",
    "SGP": "Singapore", "SINGAPORE": "Singapore",
    "JPN": "Japan", "JAPAN": "Japan",
    "KOR": "South Korea",
    "THA": "Thailand", "THAILAND": "Thailand",
    "IDN": "Indonesia", "INDONESIA": "Indonesia",
    "PHL": "Philippines", "PHILIPPINES": "Philippines",
    "VNM": "Vietnam", "VIETNAM": "Vietnam",
    "AUS": "Australia", "AUSTRALIA": "Australia",
    "NZL": "New Zealand",
    "DEU": "Germany", "GERMANY": "Germany", "GER": "Germany",
    "FRA": "France", "FRANCE": "France",
    "GBR": "United Kingdom",
    "USA": "United States",
    "CAN": "Canada", "CANADA": "Canada",
    "BRA": "Brazil", "BRAZIL": "Brazil",
    "MEX": "Mexico", "MEXICO": "Mexico",
    "CHE": "Switzerland",
    "BEL": "Belgium", "BELGIUM": "Belgium",
    "NLD": "Netherlands",
    "ESP": "Spain", "SPAIN": "Spain",
    "ITA": "Italy", "ITALY": "Italy",
    "POL": "Poland", "POLAND": "Poland",
    "HKG": "Hong Kong",
    "TWN": "Taiwan", "TAIWAN": "Taiwan",
    "ZAF": "South Africa",
    "AUT": "Austria", "AUSTRIA": "Austria",
}

_KNOWN_FULL = {v.lower() for v in _COUNTRY_CODES.values()}


def _normalise_country(raw: str | None, url: str = "") -> str:
    if not raw:
        # Infer from region slug in URL
        if "light_blue_AP" in url:
            return "unknown (Asia-Pacific)"
        if "dark_blue_EMEA" in url:
            return "unknown (EMEA)"
        if "light_green_NA" in url:
            return "unknown (North America)"
        if "red_SA" in url:
            return "unknown (South America)"
        return "unknown"

    clean = raw.strip()
    up = clean.upper().replace(" ", "")
    if up in _COUNTRY_CODES:
        return _COUNTRY_CODES[up]
    if clean.upper() in _COUNTRY_CODES:
        return _COUNTRY_CODES[clean.upper()]
    if clean.lower() in _KNOWN_FULL:
        # Already a proper name
        return clean.title() if clean.isupper() else clean
    # Try 3-letter code at end: "Navi Mumbai, IND"
    code_m = re.search(r",\s*([A-Z]{2,3})\s*$", clean)
    if code_m and code_m.group(1) in _COUNTRY_CODES:
        return _COUNTRY_CODES[code_m.group(1)]
    return clean


def _location_from_url(url: str) -> str | None:
    """Extract a city hint from the URL slug (first word before first dash)."""
    m = re.search(r"/job/([^/]+)/", url)
    if not m:
        return None
    slug = requests.utils.unquote(m.group(1))
    city = slug.split("-")[0].strip()
    return city if city else None


# ---------------------------------------------------------------------------
# Main parse function
# ---------------------------------------------------------------------------

def parse_job(url: str, session: requests.Session | None = None) -> dict | None:
    """
    Fetch a BASF job detail page and return a structured dict.
    Returns None on fetch failure or if description is too short to be valid.
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

    html = resp.text
    text = _page_text(html)

    soup = BeautifulSoup(html, "lxml")

    # --- Title ---
    title = _extract_title(soup, text)

    # --- Structured fields ---
    meta = _extract_fields(text)

    # --- Location ---
    location_raw = meta.get("location_raw")
    if not location_raw:
        location_raw = _location_from_url(url)
    location = location_raw.strip() if location_raw else "unknown"

    # --- Country ---
    country = _normalise_country(meta.get("country_raw"), url)

    # --- Description ---
    description = _extract_description(text)
    if len(description) < 30:
        logger.warning(
            "Description too short (%d chars) for %s — skipping", len(description), url
        )
        return None

    return {
        "job_id": job_id,
        "name": title,
        "location": location,
        "country": country,
        "job_type": meta.get("job_type"),
        "job_field": meta.get("job_field"),
        "flexible_work": meta.get("flexible_work"),
        "description": description,
        "url": url,
        "scraped_at": date.today().isoformat(),
    }
