"""
parse_job.py — Fetch and parse a single BASF job detail page.

BASF SuccessFactors pages use two different rendering templates:

Template A (older):  colon-separated text labels
  Job Title: <value>
  Company: <value>
  Posting Location: Country: <country>   Requisition ID: <id>
  Field: <job_field>   Job Type: <job_type>   Work model: <work_model>
  Posting Start Date: <M/D/YY>
  Job Description: <text>
  Apply now  Credits  Copyright © BASF SE

Template B (newer):  icon-based labels, values in fontcolorc63bfd23 divs
  [icon] LOCATION  [icon] COMPANY  [icon] JOB FIELD  [icon] JOB TYPE
  [icon] JOB ID   [icon] FLEXIBLE WORK OPTIONS
  Apply now
  <description text>
  Apply now
  A unique total offer: you@BASF ...
  Values stored as 8 fontcolorc63bfd23 spans:
  [location, company, job_field, job_type, req_id, job_area, country, work_model]
"""

import re
import logging
from datetime import date
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
# Known Indian cities for country inference
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

_INDIA_COMPANY_TOKENS = frozenset({
    "india", "basf india", "basf digital solutions private",
})

# ---------------------------------------------------------------------------
# Controlled vocabularies for Template B field identification
# ---------------------------------------------------------------------------
_JOB_TYPES = frozenset({
    "permanent", "internship", "intern", "fixed-term", "fixed term",
    "contract", "temporary", "part-time", "full-time", "apprenticeship",
    "dual study", "working student",
})

_WORK_MODELS = frozenset({
    "hybrid", "remote", "on-site", "onsite", "on site",
    "in office", "in-office", "flexible",
})

# ---------------------------------------------------------------------------
# Country code -> full name map
# ---------------------------------------------------------------------------
_COUNTRY_CODES: dict[str, str] = {
    "IND": "India",    "INDIA": "India",
    "CHN": "China",    "CHINA": "China",
    "MYS": "Malaysia", "MALAYSIA": "Malaysia",
    "SGP": "Singapore","SINGAPORE": "Singapore",
    "JPN": "Japan",    "JAPAN": "Japan",
    "KOR": "South Korea",
    "THA": "Thailand", "THAILAND": "Thailand",
    "IDN": "Indonesia","INDONESIA": "Indonesia",
    "PHL": "Philippines","PHILIPPINES": "Philippines",
    "VNM": "Vietnam",  "VIETNAM": "Vietnam",
    "AUS": "Australia","AUSTRALIA": "Australia",
    "NZL": "New Zealand",
    "DEU": "Germany",  "GERMANY": "Germany",  "GER": "Germany",
    "FRA": "France",   "FRANCE": "France",
    "GBR": "United Kingdom",
    "USA": "United States","US": "United States",
    "CAN": "Canada",   "CANADA": "Canada",
    "BRA": "Brazil",   "BRAZIL": "Brazil",
    "MEX": "Mexico",   "MEXICO": "Mexico",
    "CHE": "Switzerland",
    "BEL": "Belgium",  "BELGIUM": "Belgium",
    "NLD": "Netherlands",
    "ESP": "Spain",    "SPAIN": "Spain",
    "ITA": "Italy",    "ITALY": "Italy",
    "POL": "Poland",   "POLAND": "Poland",
    "HKG": "Hong Kong",
    "TWN": "Taiwan",   "TAIWAN": "Taiwan",
    "ZAF": "South Africa",
    "AUT": "Austria",  "AUSTRIA": "Austria",
    "BGD": "Bangladesh","BANGLADESH": "Bangladesh",
    "MMR": "Myanmar",
}

_KNOWN_FULL = {v.lower() for v in _COUNTRY_CODES.values()}

_JOB_FIELD_BAD_INDICATORS = ("responsibilities", "objectives", "job description")


# ---------------------------------------------------------------------------
# job_field validation — reject values that look like locations or blurbs
# rather than a genuine BASF job category.
# ---------------------------------------------------------------------------

def _validate_job_field(value: str | None) -> str | None:
    """Return the cleaned job_field, or None if it looks malformed."""
    if not value:
        return None
    v = value.strip()
    if not v:
        return None

    if len(v) > 60:
        return None

    if "|" in v:
        return None

    # Trailing country code, e.g. ", IND" or ", US"
    if re.search(r",\s*[A-Z]{2,3}\b", v):
        return None

    # Bare country code or name, e.g. "MYS" or "Malaysia"
    if v.upper() in _COUNTRY_CODES or v.lower() in _KNOWN_FULL:
        return None

    # "Site - City, Region" style location strings
    if " - " in v and re.search(r",\s*[A-Za-z]", v):
        return None

    if ":" in v:
        return None

    vl = v.lower()
    if any(tok in vl for tok in _JOB_FIELD_BAD_INDICATORS):
        return None

    return v


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def extract_job_id_from_url(url: str) -> str | None:
    m = re.search(r"/(\d{6,})/?(?:\?.*)?$", url)
    return m.group(1) if m else None


def _add_locale(url: str, locale: str = "en_US") -> str:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "locale" not in qs:
        sep = "&" if parsed.query else "?"
        return url.rstrip("/") + f"/{sep}locale={locale}"
    return url


def _page_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return re.sub(r" {2,}", " ", text)


# ---------------------------------------------------------------------------
# Template A -- colon-label pages ("Job Title:", "Field:", "Job Type:", ...)
# ---------------------------------------------------------------------------

def _extract_template_a(text: str, job_id: str | None = None, url: str = "") -> dict:
    def _capture(prefix: str, stop: str) -> str | None:
        m = re.search(prefix + rf"(.+?)(?=\s*(?:{stop}|$))", text, re.I | re.S)
        if m:
            val = m.group(1).strip()
            if val and len(val) < 300:
                return val
        return None

    job_field_raw = _capture(
        r"Field:\s*",
        r"Job Type:|Work model:|Posting Start Date:|Job Description",
    )
    job_field = _validate_job_field(job_field_raw)
    if job_field_raw and job_field is None:
        logger.warning(
            "Rejected suspicious job_field %r for job_id=%s url=%s",
            job_field_raw, job_id, url,
        )

    job_type = _capture(
        r"Job Type:\s*",
        r"Work model:|Posting Start Date:|Job Description",
    )

    work_model_m = re.search(
        r"Work model:\s*([^\n:]{1,60})(?=\s*(?:Posting Start Date:|Duration|Job Description|$))",
        text, re.I,
    )
    work_model = work_model_m.group(1).strip() if work_model_m else None
    if work_model and ("Posting" in work_model or len(work_model) > 60):
        work_model = None

    country_m = re.search(
        r"Country:\s*([A-Za-z][A-Za-z ()]{1,40}?)(?=\s*(?:Requisition ID:|Field:|$))",
        text, re.I,
    )
    country_raw = country_m.group(1).strip() if country_m else None

    location_m = re.search(
        r"Posting Location:\s*(.+?)(?=\s*(?:Requisition ID:|Field:|Job Description|$))",
        text, re.I,
    )
    location_raw = location_m.group(1).strip() if location_m else None

    company_m = re.search(
        r"Company:\s*(.+?)(?=\s*(?:Posting Location:|Country:|Field:|Job Description|$))",
        text, re.I,
    )
    company_raw = company_m.group(1).strip() if company_m else None

    date_m = re.search(r"Posting Start Date:\s*(\d{1,2})/(\d{1,2})/(\d{2,4})", text, re.I)
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
        "location_raw": location_raw,
        "country_raw": country_raw,
        "company_raw": company_raw,
        "job_field": job_field or None,
        "job_type": job_type or None,
        "flexible_work": work_model or None,
        "posted_at": posted_at,
    }


# ---------------------------------------------------------------------------
# Template B -- icon-label pages (fontcolorc63bfd23 spans)
# ---------------------------------------------------------------------------

def _extract_template_b(soup: BeautifulSoup, job_id: str | None = None, url: str = "") -> dict:
    """
    Parse fields from the icon-label template.

    Values appear in up to 8 fontcolorc63bfd23 span elements. We identify
    each by content pattern rather than position, making the parser resilient
    to missing or extra entries. job_field is only decided once every other
    field has had a chance to claim its value, then validated so a stray
    location/description string is never stored as a category.
    """
    raw_spans = [
        d.find("span", class_="rtltextaligneligible")
        for d in soup.find_all("div", class_="fontcolorc63bfd23")
    ]
    values = [s.get_text(strip=True) for s in raw_spans if s and s.get_text(strip=True)]

    location_raw = None
    company_raw = None
    job_type = None
    flexible_work = None
    country_raw = None
    remaining: list[str] = []

    for val in values:
        vl = val.lower()

        if re.match(r"^\d+$", val):
            continue  # Requisition ID -- skip

        if re.match(r"^[\w][\w\s]+,\s*[A-Z]{2,3}$", val) and location_raw is None:
            location_raw = val
            continue

        if vl in _JOB_TYPES and job_type is None:
            job_type = val
            continue

        if vl in _WORK_MODELS and flexible_work is None:
            flexible_work = val
            continue

        if (vl in _KNOWN_FULL or val.upper() in _COUNTRY_CODES) and country_raw is None:
            country_raw = val
            continue

        if "basf" in vl and company_raw is None:
            company_raw = val
            continue

        remaining.append(val)

    # Try each unclassified value in order, keeping the first one that
    # validates as a genuine category (a malformed location/blurb that
    # slipped through the checks above should not block a later, valid
    # job_field candidate).
    job_field = None
    rejected_candidates = []
    for val in remaining:
        candidate = _validate_job_field(val)
        if candidate is not None:
            job_field = candidate
            break
        rejected_candidates.append(val)

    if job_field is None and rejected_candidates:
        logger.warning(
            "Rejected suspicious job_field candidate(s) %r for job_id=%s url=%s",
            rejected_candidates, job_id, url,
        )

    return {
        "location_raw": location_raw,
        "country_raw": country_raw,
        "company_raw": company_raw,
        "job_field": job_field,
        "job_type": job_type,
        "flexible_work": flexible_work,
        "posted_at": None,  # Template B does not expose posting date
    }


def _is_template_b(soup: BeautifulSoup) -> bool:
    return bool(soup.find("div", class_="fontcolorc63bfd23"))


# ---------------------------------------------------------------------------
# Description extraction (works for both templates)
# ---------------------------------------------------------------------------

def _extract_description(text: str) -> str:
    # Template A: "Job Description:" marker
    start_m = re.search(r"Job Description(?:\s+Header)?:\s*", text, re.I)
    if start_m:
        desc = text[start_m.end():]
        desc = re.sub(
            r"^Job Description Header:.*?Job Description:\s*", "",
            desc, flags=re.I | re.S,
        )
        end_m = re.search(r"\s*(?:Apply now|Credits\s+Data|Copyright\s+\xc2\xa9)", desc, re.I)
        if end_m:
            desc = desc[: end_m.start()]
        desc = desc.strip()
        if len(desc) > 30:
            return desc

    # Template B: description sits between first and second "Apply now"
    apply_positions = [m.start() for m in re.finditer(r"\bApply now\b", text, re.I)]
    if len(apply_positions) >= 2:
        start = apply_positions[0] + len("Apply now")
        desc = text[start: apply_positions[1]].strip()
        if len(desc) > 30:
            return desc
    elif len(apply_positions) == 1:
        start = apply_positions[0] + len("Apply now")
        tail = text[start:]
        end_m = re.search(r"Credits\s+Data|Copyright", tail, re.I)
        desc = (tail[: end_m.start()] if end_m else tail).strip()
        if len(desc) > 30:
            return desc

    return text


# ---------------------------------------------------------------------------
# Country inference (shared by both templates)
# ---------------------------------------------------------------------------

def _city_from_url(url: str) -> str:
    m = re.search(r"/job/([^/]+)/", url)
    if not m:
        return ""
    slug = unquote(m.group(1)).replace("-", " ").replace("%20", " ")
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
    if country_raw:
        clean = country_raw.strip()
        if clean.upper() in _COUNTRY_CODES:
            return _COUNTRY_CODES[clean.upper()]
        if clean.upper().replace(" ", "") in _COUNTRY_CODES:
            return _COUNTRY_CODES[clean.upper().replace(" ", "")]
        if clean.lower() in _KNOWN_FULL:
            return clean
        for v in _COUNTRY_CODES.values():
            if clean.lower() == v.lower():
                return v

    code_m = re.search(r",\s*([A-Z]{2,3})\s*$", location_raw or "")
    if code_m and code_m.group(1).upper() in _COUNTRY_CODES:
        return _COUNTRY_CODES[code_m.group(1).upper()]

    loc_lower = (location_raw or "").lower()
    for city in _INDIA_CITIES:
        if city in loc_lower:
            return "India"

    city_url = _city_from_url(url)
    if city_url in _INDIA_CITIES:
        return "India"
    parts = city_url.split()
    if parts and parts[0] in _INDIA_CITIES:
        return "India"

    co_lower = (company_raw or "").lower()
    if any(tok in co_lower for tok in _INDIA_COMPANY_TOKENS):
        return "India"

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

    m = re.search(r"Job Title:\s*(.+?)(?=\s*(?:Company:|$))", text, re.I)
    if m:
        return m.group(1).strip()

    return "unknown"


# ---------------------------------------------------------------------------
# Main parse function
# ---------------------------------------------------------------------------

def parse_job(url: str, session: requests.Session | None = None) -> dict | None:
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

    # Use the canonical URL (after any redirects) so callers get a stable link
    canonical_url = resp.url.split("?")[0].rstrip("/") + "/"

    html = resp.text
    soup = BeautifulSoup(html, "lxml")
    text = _page_text(html)

    title = _extract_title(soup, text)

    if _is_template_b(soup):
        meta = _extract_template_b(soup, job_id, url)
    else:
        meta = _extract_template_a(text, job_id, url)

    location_raw = meta.get("location_raw") or ""
    # Remove "Country: X" and "Requisition ID: X" suffixes from the location block
    location_raw = re.sub(r"\s*Country:\s*.+$", "", location_raw, flags=re.I).strip()
    location_raw = re.sub(r"\s*Requisition ID:\s*.+$", "", location_raw, flags=re.I).strip()
    if location_raw.lower().startswith("country:"):
        location_raw = ""

    country = _infer_country(
        meta.get("country_raw"),
        location_raw or None,
        meta.get("company_raw"),
        url,
    )

    # Build location: strip trailing country code (e.g. "Hyderabad, IND" -> "Hyderabad")
    loc = location_raw.strip()
    if "," in loc:
        loc = loc.split(",")[0].strip()

    # If still empty, try URL slug — but only accept known city names
    if not loc:
        url_city = _city_from_url(url)
        if url_city in _INDIA_CITIES:
            loc = url_city.title()

    location = loc or "unknown"

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
        "url": canonical_url,
        "posted_at": meta.get("posted_at"),
        "scraped_at": date.today().isoformat(),
    }
