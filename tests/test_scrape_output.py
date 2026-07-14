import json

import scrape_jobs


def _job(job_id: str) -> dict:
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


def test_save_json_writes_wrapper_object_sorted_by_job_id(tmp_path):
    unsorted_jobs = [_job("300"), _job("100"), _job("200")]
    sorted_jobs = sorted(unsorted_jobs, key=lambda j: j["job_id"])

    path = tmp_path / "basf_jobs_all.json"
    scrape_jobs.save_json(path, sorted_jobs)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data.keys()) == {"_about", "_schema", "_generated_at", "_total_jobs", "jobs"}
    assert data["_total_jobs"] == 3
    assert [j["job_id"] for j in data["jobs"]] == ["100", "200", "300"]
    assert data["_schema"]["description"]


def test_save_json_is_deterministic_across_runs(tmp_path):
    jobs = sorted([_job("2"), _job("1")], key=lambda j: j["job_id"])

    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    scrape_jobs.save_json(path_a, jobs)
    scrape_jobs.save_json(path_b, jobs)

    assert path_a.read_text(encoding="utf-8") == path_b.read_text(encoding="utf-8")


def test_load_existing_reads_wrapper_object(tmp_path):
    wrapper = {
        "_about": "test",
        "_schema": {},
        "_generated_at": "2026-01-01",
        "_total_jobs": 1,
        "jobs": [_job("42")],
    }
    path = tmp_path / "in.json"
    path.write_text(json.dumps(wrapper), encoding="utf-8")

    existing = scrape_jobs.load_existing(path)
    assert list(existing.keys()) == ["42"]
    assert existing["42"]["name"] == "Job 42"


def test_load_existing_missing_file_returns_empty(tmp_path):
    assert scrape_jobs.load_existing(tmp_path / "does_not_exist.json") == {}
