"""
parse_job.py — Fetch and parse a single BASF job detail page.

Actual BASF/SuccessFactors page structure (verified from inspected HTML):
  Job Title: <value>
  Company: <value>
  Posting Location: Country: <country>  Requisition ID: <id>
  Field: <job_field>   Job Type: <job_type>   Work model: <flexible_work>
  Posting Start Date: <date M/D/YY>
  Job Description Header: ...
  Job Description: <text>
  Apply now  Credits  ...  Copyright © BASF SE
"""

import re
import logging
from datetime import date, datetime
from urllib.parse import urlparse, parse_qs, unquote

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
# Known Indian cities (for country inference when "Country:" label is absent)
# ---------------------------------------------------------------------------
_INDIA_CITIES = frozenset({
    "hyderabad", "mumbai", "navi mumbai", "new mumbai",
    "delhi", "new delhi", "chennai", "pune", "bangalore",
    "bengaluru", "mangalore", "kolkata", "calcutta",
    "mysore", "ahmedabad", "vadodara", "gurgaon",
    "gurugram", "noida", "thane", "nagpur", "lucknow",
    "jaipur", "surat", "kochi", "cochin", "coimbatore",
    "visakhapatnam", "bhubaneswar", "indore",
})

# Phrases in the Company field that indicate India
_INDIA_COMPANY_TOKENS = frozenset({
    "india", "basf india", "basf digital solutions private",
})

# ---------------------------------------------------------------------------
# Country code → full name map
# ---------------------------------------------------------------------------
_COUNTRY_CODES: dict[str, str] = {
    "IND": "India",   "INDIA": "India",
    "CHN": "China",   "CHINA": "China",
    "MYS": "Malaysia","MALAYSIA": "Malaysia",
    "SGP": "Singapore","SINGAPORE": "Singapore",
    "JPN": "Japan",   "JAPAN": "Japan",
    "KOR": "South Korea",
    "THA": "Thailand","THAILAND": "Thailand",
    "IDN": "Indonesia","INDONESIA": "Indonesia",
    "PHL": "Philippines","PHILIPPINES": "Philippines",
    "VNM": "Vietnam", "VIETNAM": "Vietnam",
    "AUS": "Australia","AUSTRALIA": "Australia",
    "NZL": "New Zealand",
    "DEU": "Germany", "GERMANY": "Germany", "GER": "Germany",
    "FRA": "France",  "FRANCE": "France",
    "GBR": "United Kingdom",
    "USA": "United States","US": "United States",
    "CAN": "Canada",  "CANADA": "Canada",
    "BRA": "Brazil",  "BRAZIL": "Brazil",
    "MEX": "Mexico",  "MEXICO": "Mexico",
    "CHE": "Switzerland",
    "BEL": "Belgium", "BELGIUM": "Belgium",
    "NLD": "Netherlands",
    "ESP": "Spain",   "SPAIN": "Spain",
    "ITA": "Italy",   "ITALY": "Italy",
    "POL": "Poland",  "POLAND": "Poland",
    "HKG": "Hong Kong",
    "TWN": "Taiwan",  "TAIWAN": "Taiwan",
    "ZAF": "South Africa",
    "AUT": "Austria", "AUSTRIA": "Austria",
    "BGD": "Bangladesh","BANGLADESH": "Bangladesh",
    "MMR": "Myanmar", "PHL": "Philippines",
}

_KNOWN_FULL = {v.lower() for v in _COUNTRY_CODES.values()}


# ---------------------------------------------------------------------------
# URL helpers
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
    Extract job metadata from the clean page text using the known
    label patterns that BASF SuccessFactors pages use.
    """

    def _capture(prefix: str, stop: str) -> str | None:
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

    # Work model: the value ends before "Posting Start Date:" or end-of-header
    work_model_m = re.search(
        r"Work model:\s*([^\n:]{1,60})(?=\s*(?:Posting Start Date:|Duration|Job Description|$))",
        text, re.I,
    )
    work_model = work_model_m.group(1).strip() if work_model_m else None
    if work_model and ("Posting" in work_model or len(work_model) > 60):
        work_model = None

    # Country — appears as "Country: <value>" (within "Posting Location:")
    country_m = re.search(
        r"Country:\s*([A-Za-z][A-Za-z ()]{1,40}?)(?=\s*(?:Requisition ID:|Field:|$))",
        text, re.I,
    )
    country_raw = country_m.group(1).strip() if country_m else None

    # Location block
    location_m = re.search(
        r"Posting Location:\s*(.+?)(?=\s*(?:Requisition ID:|Field:|Job Description|$))",
        text, re.I,
    )
    location_raw = location_m.group(1).strip() if location_m else None

    # Company — for India inference when country label is missing
    company_m = re.search(
        r"Company:\s*(.+?)(?=\s*(?:Posting Location:|Country:|Field:|Job Description|$))",
        text, re.I,
    )
    company_raw = company_m.group(1).strip() if company_m else None

    # Job title fallback from text block
    title_m = re.search(r"Job Title:\s*(.+?)(?=\s*(?:Company:|$))", text, re.I)
    title_raw = title_m.group(1).strip() if title_m else None

    # Posting date — format "M/D/YY" or "M/D/YYYY"
    date_m = re.search(
        r"Posting Start Date:\s*(\d{1,2})/(\d{1,2})/(\d{2,4})",
        text, re.I,
    )
    posted_at = None
    if date_m:
        month, day, year_raw = date_m.groups()
        year = int(year_raw)
        if year < 100:
            year += 2000
        try:
            posted_at = date(year, int(month), int(day)).isoformat()
        except ValueError:
            pass

    return {
        "title_from_text": title_raw,
        "location_raw": location_raw,
        "country_raw": country_raw,
        "company_raw": company_raw,
        "job_field": job_field or None,
        "job_type": job_type or None,
        "flexible_work": work_model or None,
        "posted_at": posted_at,
    }


# ---------------------------------------------------------------------------
# Country inference (multi-strategy)
# ---------------------------------------------------------------------------

def _city_from_url(url: str) -> str:
    """Extract city hint from the URL slug."""
    m = re.search(r"/job/([^/]+)/", url)
    if not m:
        return ""
    slug = unquote(m.group(1)).replace("-", " ").replace("%20", " ")
    # Try 2-word prefix first, then 1-word
    parts = slug.split()
    if len(parts) >= 2:
        two = " ".join(parts[:2]).lower()
        if two in _INDIA_CITIES:
            return two
    return parts[0].lower() if parts else ""


def _infer_country(
    country_raw: str | None,
    location_raw: str | None,
    company_raw: str | None,
    url: str,
) -> str:
    """
    Determine country using several fallback strategies:
      1. Explicit "Country: <X>" label on page
      2. Country code at end of location string (", IND")
      3. Indian city name in location string
      4. Indian city in URL slug
      5. Company name contains "India"
      6. Region slug fallback
    """
    # Strategy 1: explicit label
    if country_raw:
        clean = country_raw.strip()
        up = clean.upper().replace(" ", "")
        if up in _COUNTRY_CODES:
            return _COUNTRY_CODES[up]
        if clean.upper() in _COUNTRY_CODES:
            return _COUNTRY_CODES[clean.upper()]
        if clean.lower() in _KNOWN_FULL:
            return clean
        # Could be a partial match
        for k, v in _COUNTRY_CODES.items():
            if clean.lower() == v.lower():
                return v

    # Strategy 2: country code in location string (",IND" etc.)
    for src in [location_raw or ""]:
        code_m = re.search(r",\s*([A-Z]{2,3})\s*$", src)
        if code_m:
            code = code_m.group(1).upper()
            if code in _COUNTRY_CODES:
                return _COUNTRY_CODES[code]

    # Strategy 3: Indian city in location string
    loc_lower = (location_raw or "").lower()
    for city in _INDIA_CITIES:
        if city in loc_lower:
            return "India"

    # Strategy 4: Indian city in URL slug
    city_url = _city_from_url(url)
    if city_url and city_url in _INDIA_CITIES:
        return "India"
    # Also check 1-word prefix
    parts = city_url.split()
    if parts and parts[0] in _INDIA_CITIES:
        return "India"

    # Strategy 5: company contains "India"
    co_lower = (company_raw or "").lower()
    if any(tok in co_lower for tok in _INDIA_COMPANY_TOKENS):
        return "India"

    # Strategy 6: region fallback
    if "light_blue_AP" in url:
        return "unknown (Asia-Pacific)"
    if "dark_blue_EMEA" in url:
        return "unknown (EMEA)"
    if "light_green_NA" in url:
        return "unknown (North America)"
    if "red_SA" in url:
        return "unknown (South America)"
    if "dark_green_agri" in url:
        return "unknown (Agriculture)"

    return "unknown"


# ---------------------------------------------------------------------------
# Title extraction
# ---------------------------------------------------------------------------

def _extract_title(soup: BeautifulSoup, text: str) -> str:
    for sel in ["h1", ".job-title", "[class*='title']"]:
        elem = soup.select_one(sel)
        if elem:
            t = elem.get_text(" ", strip=True)
            t = re.sub(r"\s*[|\-–]\s*BASF.*$", "", t, flags=re.I).strip()
            if t and len(t) < 300:
                return t

    title_tag = soup.find("title")
    if title_tag:
        t = title_tag.get_text(" ", strip=True)
        t = re.sub(r"\s*(?:[|\-–]\s*BASF.*|Job Details.*)$", "", t, flags=re.I).strip()
        if t and len(t) < 300:
            return t

    # Fallback from page text
    m = re.search(r"Job Title:\s*(.+?)(?=\s*(?:Company:|$))", text, re.I)
    if m:
        return m.group(1).strip()

    return "unknown"


# ---------------------------------------------------------------------------
# Description extraction
# ---------------------------------------------------------------------------

def _extract_description(text: str) -> str:
    """
    Extract the job description from clean page text.
    The description lives between "Job Description:" and "Apply now".
    """
    # Primary: find "Job Description:" marker
    start_m = re.search(r"Job Description(?:\s+Header)?:\s*", text, re.I)
    if start_m:
        desc = text[start_m.end():]
        # Strip "Job Description Header: ..." prefix if present
        desc = re.sub(
            r"^Job Description Header:.*?Job Description:\s*", "",
            desc, flags=re.I | re.S,
        )
        # Stop at footer markers
        end_m = re.search(r"\s*(?:Apply now|Credits\s+Data|Copyright\s+©)", desc, re.I)
        if end_m:
            desc = desc[: end_m.start()]
        desc = desc.strip()
        if len(desc) > 30:
            return desc[:10000]

    # Fallback: between login area and apply button
    s2 = re.search(r"(?:Employee Login|Profile Login)\s*", text, re.I)
    e2 = re.search(r"Apply now\s*Credits", text, re.I)
    if s2 and e2:
        block = text[s2.end(): e2.start()].strip()
        if len(block) > 30:
            return block[:10000]

    return text[:10000]


# ---------------------------------------------------------------------------
# Main parse function
# ---------------------------------------------------------------------------

def parse_job(url: str, session: requests.Session | None = None) -> dict | None:
    """
    Fetch a BASF job detail page and return a structured dict.
    Returns None on fetch failure or if description is too short.
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

    title = _extract_title(soup, text)
    meta = _extract_fields(text)

    location_raw = meta.get("location_raw") or ""
    # If location block only contains "Country: X", clean it up to just the country
    if location_raw.lower().startswith("country:"):
        location_raw = ""

    country = _infer_country(
        meta.get("country_raw"),
        location_raw or None,
        meta.get("company_raw"),
        url,
    )

    # Location: prefer the compact "City, CODE" form embedded in the location block;
    # fall back to URL-derived city hint
    location = location_raw.strip() if location_raw.strip() else (
        _city_from_url(url).title() or "unknown"
    )

    description = _extract_description(text)
    if len(description) < 30:
        logger.warning("Description too short (%d chars) for %s", len(description), url)
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
        "posted_at": meta.get("posted_at"),
        "scraped_at": date.today().isoformat(),
    }
