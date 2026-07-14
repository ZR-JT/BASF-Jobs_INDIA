# BASF Jobs Data Repository

Automatically collects **all publicly available BASF job listings worldwide**
from [basf.jobs](https://basf.jobs/) and provides them as a single,
structured JSON file — ready for AI agents, dashboards, or job-matching
applications.

---

## Goal

Enable structured, machine-readable access to BASF's public job postings
worldwide so that downstream tools (e.g. AI agents or web applications) can
filter and search jobs by:

- **Country** and **Location**
- **Job Field** (e.g. Digitalization, Engineering, R&D, Procurement) —
  validated so it never holds a misparsed location or blurb string
- **Job Type** (e.g. Permanent, Internship, Working Student)
- **Flexible Work Options** (e.g. Hybrid, Remote, On-site)
- Free-text **description** search — the full, unabridged job description,
  never truncated

---

## Data Source

All data is sourced exclusively from **public, freely accessible pages** on
[https://basf.jobs/](https://basf.jobs/), a SuccessFactors-powered career
portal.

**Discovery strategy:** The scraper reads the public sitemap at
`https://basf.jobs/sitemap.xml` to find all job URLs across every BASF
region (Asia-Pacific, EMEA, North America, South America, Agriculture), then
fetches each job detail page individually. No private APIs, login sessions,
or authenticated endpoints are used.

A polite rate limit (1.5 s between requests) is applied to avoid overloading
the server.

---

## Output File

The scraper writes **exactly one file**: `data/basf_jobs_all.json`.

It is a self-documenting wrapper object — the schema is embedded at the top
so a consumer (e.g. an MCP server) can read it without needing separate
docs:

```json
{
  "_about": "BASF job listings worldwide — public data collected from basf.jobs",
  "_schema": {
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
    "scraped_at": "Date this record was last fetched (YYYY-MM-DD)"
  },
  "_generated_at": "2026-07-14",
  "_total_jobs": 4231,
  "jobs": [
    {
      "job_id": "1396804333",
      "name": "GDD/EN - Platform engineer CAE solutions (m/f/d)",
      "location": "Hyderabad",
      "country": "India",
      "job_type": "Permanent",
      "job_field": "Digitalization",
      "flexible_work": "Hybrid",
      "description": "We are looking for a platform engineer ... (full text, unabridged)",
      "url": "https://basf.jobs/light_blue_AP/job/Hyderabad-.../1396804333/",
      "posted_at": "2026-06-01",
      "scraped_at": "2026-07-14"
    }
  ]
}
```

`jobs` is sorted by `job_id` ascending and serialized with `indent=2` and
`ensure_ascii=False`, so re-running the scraper against unchanged source data
produces byte-identical output (diff-friendly for the daily commit).

---

## Field notes

| Field | Notes |
|-------|-------|
| `job_id` | Numeric ID extracted from the URL — unique and stable |
| `job_field` | BASF's own job category (e.g. `Digitalization`, `Engineering`, `Research & Development`, `Procurement`, `Supply Chain`, `Marketing & Sales`). Extracted exactly as shown on the page and validated — a value that looks like a location, a pipe-separated list, or a description blurb is rejected and stored as `null` instead of being silently wrong. |
| `job_type` | Employment type as shown on page (e.g. `Permanent`, `Internship`, `Working Student`) |
| `flexible_work` | Work model from page (e.g. `Hybrid`, `Remote`, `On-site`) |
| `description` | Full English job description, cleaned of navigation/cookie text — **never truncated** |
| `posted_at` | Date the job was first posted, if shown on the page |
| `scraped_at` | ISO date when the record was last fetched |

No location or job-level normalization is applied here (e.g. mapping city
spellings or seniority levels) — that stays downstream in the consuming
application (e.g. an MCP server), so this repo can stay a thin, faithful
mirror of what BASF publishes.

---

## Local Setup

```bash
# Clone the repo
git clone https://github.com/ZR-JT/BASF-Jobs_India.git
cd BASF-Jobs_India

# Install dependencies
pip install -r requirements.txt

# Run the scraper (worldwide, all jobs — this is the default scope)
python scripts/scrape_jobs.py

# Quick local test: limit to 20 jobs
python scripts/scrape_jobs.py --limit 20

# Restrict to one region only (for faster testing)
python scripts/scrape_jobs.py --region AP --limit 20

# Force re-scrape all jobs (ignore cache)
python scripts/scrape_jobs.py --force-refresh

# Validate output
python scripts/validate_json.py

# Run the test suite
pytest
```

---

## Project Structure

```
/
├── README.md
├── requirements.txt
├── scripts/
│   ├── scrape_jobs.py   # Main scraper & orchestrator — writes the single output file
│   ├── parse_job.py     # Single job page parser (full description, validated job_field)
│   └── validate_json.py # JSON validation & quality checks
├── tests/                # pytest test suite (offline, fixture-based)
├── data/
│   └── basf_jobs_all.json  # The one output file — all jobs worldwide
├── logs/                 # Scrape logs and error lists
└── .github/
    └── workflows/
        └── update-jobs.yml  # Daily GitHub Actions automation
```

---

## GitHub Actions

The workflow in `.github/workflows/update-jobs.yml` runs automatically
**every day at 03:00 UTC**.

On each run it:
1. Installs Python and dependencies
2. Runs the scraper (only fetches pages not yet cached; scope is worldwide
   by default)
3. Validates the JSON output
4. Commits and pushes `data/basf_jobs_all.json` if it changed, with a message
   like: `chore: update job data — 4231 jobs worldwide as of 2026-07-14 03:12 UTC`
5. Uploads scrape logs as a GitHub Actions artifact (kept 14 days)

You can also trigger a manual run via **Actions → Update BASF Job Data → Run
workflow**, with optional parameters for region, limit, or force-refresh —
these are testing aids only; the default (no inputs) always scrapes
worldwide. The job has `timeout-minutes: 360` to allow for a full worldwide
scrape.

---

## Regions (testing only)

The BASF sitemap organises jobs into regional groups. `--region` is a
**local testing convenience** — it is never applied by default, so the
scheduled Action always covers every region below:

| Code | Slug | Coverage |
|------|------|----------|
| `AP` | `light_blue_AP` | Asia-Pacific (India, China, Japan, Singapore, …) |
| `EMEA` | `dark_blue_EMEA` | Europe, Middle East, Africa |
| `NA` | `light_green_NA` | North America |
| `SA` | `red_SA` | South America |
| `AGRI` | `dark_green_agri` | Agriculture division (global) |

---

## Legal & Ethics

- Only **publicly accessible** job data is collected.
- The scraper respects `robots.txt` — no restricted paths are accessed.
- A polite rate limit (1.5 s between requests) ensures the server is not
  overloaded.
- No personal data, salary data (unless publicly shown), or application data
  is collected.
- This project is intended for educational and research purposes.
