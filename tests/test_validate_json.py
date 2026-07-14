import json

import validate_json


def _wrapper(jobs: list[dict]) -> dict:
    return {
        "_about": "test",
        "_schema": {},
        "_generated_at": "2026-01-01",
        "_total_jobs": len(jobs),
        "jobs": jobs,
    }


def _valid_job(job_id: str) -> dict:
    return {
        "job_id": job_id,
        "name": f"Job {job_id}",
        "location": "Somewhere",
        "country": "Germany",
        "job_type": "Permanent",
        "job_field": "Engineering",
        "flexible_work": "Hybrid",
        "description": "A full, unabridged description of the role.",
        "url": f"https://basf.jobs/job/{job_id}/",
        "posted_at": "2026-01-01",
        "scraped_at": "2026-01-01",
    }


def test_validate_passes_for_clean_wrapper(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps(_wrapper([_valid_job("1")])), encoding="utf-8")
    assert validate_json.validate(path, log_dir=tmp_path) is True


def test_validate_rejects_top_level_list(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps([_valid_job("1")]), encoding="utf-8")
    assert validate_json.validate(path, log_dir=tmp_path) is False


def test_validate_flags_empty_description(tmp_path):
    job = _valid_job("1")
    job["description"] = ""
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps(_wrapper([job])), encoding="utf-8")
    assert validate_json.validate(path, log_dir=tmp_path) is False


def test_validate_flags_suspicious_job_field(tmp_path):
    job = _valid_job("1")
    job["job_field"] = "Godrej One - Mumbai, IND"
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps(_wrapper([job])), encoding="utf-8")
    assert validate_json.validate(path, log_dir=tmp_path) is False


def test_validate_allows_null_job_field(tmp_path):
    job = _valid_job("1")
    job["job_field"] = None
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps(_wrapper([job])), encoding="utf-8")
    assert validate_json.validate(path, log_dir=tmp_path) is True


def test_validate_flags_duplicate_job_ids(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text(
        json.dumps(_wrapper([_valid_job("1"), _valid_job("1")])), encoding="utf-8"
    )
    assert validate_json.validate(path, log_dir=tmp_path) is False
