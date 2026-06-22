"""
rescrape_nulls.py — Re-fetch India jobs where key fields are missing or the
description looks like a page header instead of actual job content.

Run after a parser fix to clean up stale cached entries:
  python scripts/rescrape_nulls.py [--dry-run] [--output-dir data]
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from parse_job import parse_job
from build_country_files import build_india_json, build_country_files, build_index

logger = logging.getLogger(__name__)

RATE_LIMIT = 1.5

_BAD_DESC_MARKERS = (
    "Job Details | BASF SE",
    "Skip to main content",
    "Find jobs Language",
)


def _is_bad(job: dict) -> bool:
    if job.get("job_type") is None:
        return True
    if job.get("job_field") is None:
        return True
    desc = job.get("description") or ""
    if any(marker in desc for marker in _BAD_DESC_MARKERS):
        return True
    return False


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(description="Re-scrape India jobs with missing fields.")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).parent.parent / "data")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print which jobs would be re-scraped, without fetching")
    args = parser.parse_args()

    all_jobs_path = args.output_dir / "basf_jobs_all.json"
    with open(all_jobs_path, encoding="utf-8-sig") as f:
        jobs: list[dict] = json.load(f)

    by_id = {j["job_id"]: j for j in jobs}

    india_jobs = [j for j in jobs if (j.get("country") or "").lower() == "india"]
    bad = [j for j in india_jobs if _is_bad(j)]

    logger.info("India jobs total: %d", len(india_jobs))
    logger.info("Need re-scrape:   %d", len(bad))

    if args.dry_run:
        for j in bad:
            reasons = []
            if j.get("job_type") is None:
                reasons.append("job_type=null")
            if j.get("job_field") is None:
                reasons.append("job_field=null")
            desc = j.get("description") or ""
            if any(m in desc for m in _BAD_DESC_MARKERS):
                reasons.append("bad-desc")
            logger.info("  [DRY] %s -- %s -- %s", j["job_id"], j.get("name", "?"), ", ".join(reasons))
        return

    session = requests.Session()
    updated = 0
    failed = 0

    for i, job in enumerate(bad, 1):
        job_id = job["job_id"]
        url = job["url"]
        logger.info("[%d/%d] Re-scraping %s: %s", i, len(bad), job_id, url)

        result = parse_job(url, session=session)
        if result:
            by_id[job_id] = result
            updated += 1
            logger.info("  OK -- job_type=%s job_field=%s flexible_work=%s",
                        result.get("job_type"), result.get("job_field"),
                        result.get("flexible_work"))
        else:
            failed += 1
            logger.warning("  FAILED -- keeping existing record")

        time.sleep(RATE_LIMIT)

    logger.info("Done. Updated: %d, Failed: %d", updated, failed)

    if updated:
        jobs_list = sorted(by_id.values(), key=lambda j: j.get("job_id", ""))
        with open(all_jobs_path, "w", encoding="utf-8") as f:
            json.dump(jobs_list, f, ensure_ascii=False, indent=2)
        logger.info("Saved basf_jobs_all.json")

        india_count = build_india_json(jobs_list, args.output_dir)
        build_country_files(jobs_list, args.output_dir)
        build_index(jobs_list, args.output_dir)
        logger.info("Rebuilt output files -- %d India jobs", india_count)


if __name__ == "__main__":
    main()
