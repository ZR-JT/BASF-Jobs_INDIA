"""
build_country_files.py — Split job data by country and build the index file.

Can be run standalone or imported from scrape_jobs.py.

Usage:
  python scripts/build_country_files.py [--input data/basf_jobs_all.json]
                                         [--output-dir data]
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Fields included in the compact index file
INDEX_FIELDS = [
    "job_id", "name", "location", "country",
    "job_type", "job_field", "flexible_work", "url",
]

# Maps lowercase country name → filename slug
def _country_to_slug(country: str) -> str:
    slug = country.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug or "unknown"


def build_country_files(jobs: list[dict], output_dir: Path) -> None:
    """Group jobs by country and write one JSON file per country."""
    countries: dict[str, list[dict]] = {}
    for job in jobs:
        country = job.get("country") or "unknown"
        countries.setdefault(country, []).append(job)

    countries_dir = output_dir / "countries"
    countries_dir.mkdir(parents=True, exist_ok=True)

    # Remove stale country files before rewriting
    for old_file in countries_dir.glob("*.json"):
        old_file.unlink()

    for country, country_jobs in sorted(countries.items()):
        slug = _country_to_slug(country)
        path = countries_dir / f"{slug}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(country_jobs, f, ensure_ascii=False, indent=2)
        logger.info("Country file: %s (%d jobs)", path.name, len(country_jobs))

    logger.info("Wrote %d country files to %s", len(countries), countries_dir)


def build_index(jobs: list[dict], output_dir: Path) -> None:
    """Write a compact index file with only the key searchable fields."""
    index = [
        {k: job.get(k) for k in INDEX_FIELDS}
        for job in jobs
    ]
    path = output_dir / "basf_jobs_index.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    logger.info("Index file: %s (%d jobs)", path, len(index))


def load_jobs(input_path: Path) -> list[dict]:
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        logger.error("Expected a JSON array in %s", input_path)
        sys.exit(1)
    return data


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(description="Build country and index JSON files.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).parent.parent / "data" / "basf_jobs_all.json",
        help="Path to basf_jobs_all.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent.parent / "data",
        help="Directory to write output files",
    )
    args = parser.parse_args()

    jobs = load_jobs(args.input)
    logger.info("Loaded %d jobs from %s", len(jobs), args.input)
    build_country_files(jobs, args.output_dir)
    build_index(jobs, args.output_dir)


if __name__ == "__main__":
    main()
