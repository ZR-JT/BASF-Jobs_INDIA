# BASF Jobs Data Repository

Automatically collects **publicly available English-language BASF job listings** from [basf.jobs](https://basf.jobs/) and provides them as structured JSON files — ready for AI agents, dashboards, or job-matching applications.

---

## Goal

Enable structured, machine-readable access to BASF's public job postings so that downstream tools (e.g. AI agents or web applications) can filter and search jobs by:

- **Country** and **Location**
- **Job Field** (e.g. Digitalization, Engineering, R&D, Procurement)
- **Job Type** (e.g. Permanent, Internship, Working Student)
- **Flexible Work Options** (e.g. Hybrid, Remote, On-site)
- Free-text **description** search

---

## Data Source

All data is sourced exclusively from **public, freely accessible pages** on [https://basf.jobs/](https://basf.jobs/), a SuccessFactors-powered career portal.

**Discovery strategy:** The scraper reads the public sitemap at `https://basf.jobs/sitemap.xml` to find all job URLs, then fetches each job detail page individually. No private APIs, login sessions, or authenticated endpoints are used.

A polite rate limit (≥1.5 s between requests) is applied to avoid overloading the server.

---

## Output Files

| File | Description |
|------|-------------|
| `data/basf_jobs_all.json` | Complete dataset — all scraped jobs with full descriptions |
| `data/basf_jobs_index.json` | Compact index — key fields only, no description (fast to load) |
| `data/countries/india.json` | Jobs for India |
| `data/countries/china.json` | Jobs for China |
| `data/countries/germany.json` | Jobs for Germany |
| `data/countries/<slug>.json` | One file per country (auto-generated) |

Country files are created automatically for every country found in the data.

---

## JSON Schema

### Full record (`basf_jobs_all.json`)

```json
{
  "job_id":       "1396804333",
  "name":         "GDD/EN - Platform engineer CAE solutions (m/f/d)",
  "location":     "Hyderabad, IND",
  "country":      "India",
  "job_type":     "Permanent",
  "job_field":    "Digitalization",
  "flexible_work": "Hybrid",
  "description":  "We are looking for a platform engineer ...",
  "url":          "https://basf.jobs/light_blue_AP/job/Hyderabad-.../1396804333/",
  "scraped_at":   "2026-06-18"
}
```

### Compact index record (`basf_jobs_index.json`)

```json
{
  "job_id":       "1396804333",
  "name":         "GDD/EN - Platform engineer CAE solutions (m/f/d)",
  "location":     "Hyderabad, IND",
  "country":      "India",
  "job_type":     "Permanent",
  "job_field":    "Digitalization",
  "flexible_work": "Hybrid",
  "url":          "https://basf.jobs/light_blue_AP/job/Hyderabad-.../1396804333/"
}
```

### Field notes

| Field | Notes |
|-------|-------|
| `job_id` | Numeric ID extracted from the URL — unique and stable |
| `job_field` | **Critical field.** Exactly as shown on the BASF job page (e.g. `Digitalization`, `Engineering`, `Research & Development`, `Procurement`, `Supply Chain`, `Marketing`, `Human Resources`). Set to `null` if not found on the page — never guessed. |
| `job_type` | Employment type as shown on page (e.g. `Permanent`, `Internship`, `Working Student`) |
| `flexible_work` | Work model from page (e.g. `Hybrid`, `Remote`, `On-site`) |
| `description` | English job description, cleaned of navigation and cookie text |
| `scraped_at` | ISO date when the record was last fetched |

---

## Local Setup

```bash
# Clone the repo
git clone https://github.com/ZR-JT/BASF-Jobs_India.git
cd BASF-Jobs_India

# Install dependencies
pip install -r requirements.txt

# Run the scraper (all regions, all jobs)
python scripts/scrape_jobs.py

# Run for a specific region only (faster for testing)
python scripts/scrape_jobs.py --region AP

# Limit to 20 jobs for a quick test
python scripts/scrape_jobs.py --region AP --limit 20

# Force re-scrape all jobs (ignore cache)
python scripts/scrape_jobs.py --force-refresh

# Validate output
python scripts/validate_json.py

# Rebuild country files and index from existing data
python scripts/build_country_files.py
```

---

## Project Structure

```
/
├── README.md
├── requirements.txt
├── scripts/
│   ├── scrape_jobs.py          # Main scraper & orchestrator
│   ├── parse_job.py            # Single job page parser
│   ├── build_country_files.py  # Split data by country + build index
│   └── validate_json.py        # JSON validation & quality checks
├── data/
│   ├── basf_jobs_all.json      # Full dataset
│   ├── basf_jobs_index.json    # Compact index
│   └── countries/              # Per-country JSON files
├── logs/                       # Scrape logs and error lists
└── .github/
    └── workflows/
        └── update-jobs.yml     # GitHub Actions automation
```

---

## GitHub Actions

The workflow in `.github/workflows/update-jobs.yml` runs automatically **every day at 03:00 UTC**.

On each run it:
1. Installs Python and dependencies
2. Runs the scraper (only fetches pages not yet cached)
3. Validates the JSON output
4. Rebuilds country files and the index
5. Commits and pushes any changed JSON files with a message like:
   `chore: update job data — 4231 jobs as of 2026-06-18 03:12 UTC`
6. Uploads scrape logs as a GitHub Actions artifact (kept 14 days)

You can also trigger a manual run via **Actions → Update BASF Job Data → Run workflow**, with optional parameters for region, limit, or force-refresh.

---

## Regions

The BASF sitemap organises jobs into regional groups:

| Code | Slug | Coverage |
|------|------|----------|
| `AP` | `light_blue_AP` | Asia-Pacific (India, China, Japan, Singapore, …) |
| `EMEA` | `dark_blue_EMEA` | Europe, Middle East, Africa |
| `NA` | `light_green_NA` | North America |
| `SA` | `red_SA` | South America |
| `AGRI` | `dark_green_agri` | Agriculture division (global) |

Pass `--region AP` to the scraper to restrict to Asia-Pacific only.

---

## Important field: `job_field`

The `job_field` field is **especially important** for filtering and AI-agent use:

- It reflects BASF's own job category system (e.g. `Digitalization`, `Engineering`, `Research & Development`, `Procurement`, `Supply Chain`)
- It is extracted exactly as it appears on the job detail page — never inferred or guessed
- If the field is absent on the page, it is stored as `null`
- AI agents can use this field to match users to relevant functional areas even when job titles vary

---

## Legal & Ethics

- Only **publicly accessible** job data is collected.
- The scraper respects `robots.txt` — no restricted paths are accessed.
- Rate limiting ensures the server is not overloaded.
- No personal data, salary data (unless publicly shown), or application data is collected.
- This project is intended for educational and research purposes.
