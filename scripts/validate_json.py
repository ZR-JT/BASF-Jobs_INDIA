"""
validate_json.py — Validate the scraped BASF job JSON files.

Checks:
  - JSON files are valid and parseable
  - Each job has a unique job_id
  - Required fields (name, country, url) are present and non-empty
  - job_field is present or explicitly null/unknown (never guessed)
  - URL looks like a valid BASF job URL
  - No duplicate job_ids across the dataset

Exits with code 0 if all checks pass, 1 if any critical errors are found.
Warnings are logged but do not cause failure.

Usage:
  python scripts/validate_json.py [--input data/basf_jobs_all.json] [--log-dir logs]
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ["job_id", "name", "url"]
WARN_IF_MISSING = ["country", "job_field", "job_type", "flexible_work"]

# Accepts both URL formats BASF uses:
#   legacy:    /job/{city-title}/{8-digit-id}/
#   canonical: /job/{title}/{id}-en_US/   (post-redirect, no city prefix)
VALID_URL_PATTERN = re.compile(
    r"^https://basf\.jobs/(?:.+/)?job/.+/\d+(?:-[a-z_]+)?/?$",
    re.I,
)

# Patterns that always indicate a broken URL regardless of format
INVALID_URL_TOKENS = re.compile(r"\bundefined\b|\bnull\b", re.I)


def validate(input_path: Path, log_dir: Path | None = None) -> bool:
    """
    Validate the jobs file at input_path.
    Returns True if all critical checks pass.
    """
    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        return False

    # Parse JSON
    try:
        with open(input_path, encoding="utf-8") as f:
            jobs = json.load(f)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in %s: %s", input_path, exc)
        return False

    if not isinstance(jobs, list):
        logger.error("Expected a JSON array, got %s", type(jobs).__name__)
        return False

    if len(jobs) == 0:
        logger.warning("File is valid JSON but contains no jobs: %s", input_path)
        return True

    errors: list[str] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()

    for i, job in enumerate(jobs):
        idx = f"[{i}]"

        # Check required fields
        for field in REQUIRED_FIELDS:
            value = job.get(field)
            if not value or (isinstance(value, str) and value.strip() == ""):
                errors.append(f"{idx} Missing or empty required field '{field}': {job.get('url', 'no-url')}")

        # Unique job_id
        job_id = job.get("job_id")
        if job_id:
            if job_id in seen_ids:
                errors.append(f"{idx} Duplicate job_id: {job_id}")
            else:
                seen_ids.add(job_id)

        # URL format — flag truly broken URLs, accept both legacy and canonical formats
        url = job.get("url", "")
        if url:
            if INVALID_URL_TOKENS.search(url):
                errors.append(f"{idx} URL contains invalid token (undefined/null): {url}")
            elif not VALID_URL_PATTERN.match(url):
                errors.append(f"{idx} Suspicious URL format: {url}")

        # Warn on missing optional fields
        for field in WARN_IF_MISSING:
            value = job.get(field)
            if value is None:
                warnings.append(
                    f"{idx} job_id={job_id}: field '{field}' is null — "
                    "could not be extracted from page"
                )

        # Detect fake/empty entries
        name = job.get("name", "")
        if name in ("unknown", "", None) and not job.get("description"):
            errors.append(f"{idx} job_id={job_id}: looks like an empty/fake entry")

    # Report
    if warnings:
        logger.warning("%d warnings found:", len(warnings))
        for w in warnings[:50]:  # cap output
            logger.warning("  %s", w)
        if len(warnings) > 50:
            logger.warning("  ... and %d more warnings", len(warnings) - 50)

    if errors:
        logger.error("%d critical errors found:", len(errors))
        for e in errors[:50]:
            logger.error("  %s", e)
        if len(errors) > 50:
            logger.error("  ... and %d more errors", len(errors) - 50)
    else:
        logger.info(
            "Validation passed: %d jobs, %d unique IDs, %d warnings",
            len(jobs), len(seen_ids), len(warnings),
        )

    # Write validation report
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        report_path = log_dir / "validation_report.txt"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"Validated: {input_path}\n")
            f.write(f"Total jobs: {len(jobs)}\n")
            f.write(f"Unique IDs: {len(seen_ids)}\n")
            f.write(f"Errors: {len(errors)}\n")
            f.write(f"Warnings: {len(warnings)}\n\n")
            if errors:
                f.write("ERRORS:\n" + "\n".join(errors) + "\n\n")
            if warnings:
                f.write("WARNINGS:\n" + "\n".join(warnings) + "\n")
        logger.info("Validation report written to %s", report_path)

    return len(errors) == 0


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(description="Validate BASF job JSON files.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).parent.parent / "data" / "basf_jobs_all.json",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path(__file__).parent.parent / "logs",
    )
    args = parser.parse_args()

    ok = validate(args.input, args.log_dir)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
