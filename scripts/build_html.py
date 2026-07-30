"""
build_html.py — Generates a static HTML overview of all BASF job listings,
grouped by country and city, each job title linking directly to its posting.

Usage:
  python scripts/build_html.py [--input data/basf_jobs_all.json] [--output docs/index.html]
"""

import argparse
import html
import json
from collections import defaultdict
from pathlib import Path

DEFAULT_INPUT = Path(__file__).parent.parent / "data" / "basf_jobs_all.json"
DEFAULT_OUTPUT = Path(__file__).parent.parent / "docs" / "index.html"


def load_jobs(path: Path) -> tuple[list[dict], str, int]:
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    jobs = data.get("jobs", [])
    return jobs, data.get("_generated_at", ""), data.get("_total_jobs", len(jobs))


def group_jobs(jobs: list[dict]) -> dict[str, dict[str, list[dict]]]:
    grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for job in jobs:
        country = job.get("country") or "unknown"
        location = job.get("location") or "unknown"
        grouped[country][location].append(job)
    return grouped


def _sort_key(name: str) -> tuple[int, str]:
    """Alphabetical, but 'unknown' / 'unknown (...)' values sort last."""
    return (1, name.lower()) if name.lower().startswith("unknown") else (0, name.lower())


def render_html(grouped: dict, generated_at: str, total_jobs: int) -> str:
    countries = sorted(grouped, key=_sort_key)
    country_blocks = []

    for country in countries:
        cities = sorted(grouped[country], key=_sort_key)
        country_job_count = sum(len(grouped[country][city]) for city in cities)

        city_blocks = []
        for city in cities:
            jobs = sorted(grouped[country][city], key=lambda j: j.get("name", ""))
            items = "\n".join(
                f'          <li><a href="{html.escape(job.get("url", ""))}" target="_blank" '
                f'rel="noopener">{html.escape(job.get("name", "Untitled"))}</a></li>'
                for job in jobs
            )
            city_blocks.append(
                f'      <details class="city">\n'
                f'        <summary>{html.escape(city)} '
                f'<span class="count">({len(jobs)})</span></summary>\n'
                f'        <ul>\n{items}\n        </ul>\n'
                f'      </details>'
            )

        country_blocks.append(
            f'    <details class="country">\n'
            f'      <summary>{html.escape(country)} '
            f'<span class="count">({country_job_count})</span></summary>\n'
            + "\n".join(city_blocks) + "\n"
            f'    </details>'
        )

    body = "\n".join(country_blocks)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BASF Job Listings — by Country &amp; City</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    max-width: 900px;
    margin: 2rem auto;
    padding: 0 1rem;
    line-height: 1.5;
  }}
  h1 {{ font-size: 1.4rem; margin-bottom: 0.2rem; }}
  .meta {{ color: #666; font-size: 0.9rem; margin-bottom: 1.5rem; }}
  details.country {{
    border: 1px solid #ccc;
    border-radius: 6px;
    margin-bottom: 0.5rem;
    padding: 0.4rem 0.8rem;
  }}
  details.country > summary {{ font-size: 1.1rem; font-weight: 600; cursor: pointer; }}
  details.city {{ margin: 0.4rem 0 0.4rem 1rem; }}
  details.city > summary {{ font-weight: 500; cursor: pointer; }}
  .count {{ color: #888; font-weight: normal; font-size: 0.9em; }}
  ul {{ margin: 0.3rem 0 0.6rem 0; }}
  li {{ margin: 0.15rem 0; }}
  a {{ text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<h1>BASF Job Listings — by Country &amp; City</h1>
<p class="meta">{total_jobs} open positions worldwide &middot; data generated {html.escape(generated_at)} &middot; source: <a href="https://basf.jobs/" target="_blank" rel="noopener">basf.jobs</a></p>
{body}
</body>
</html>
"""


def build(input_path: Path, output_path: Path) -> None:
    jobs, generated_at, total_jobs = load_jobs(input_path)
    grouped = group_jobs(jobs)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_html(grouped, generated_at, total_jobs), encoding="utf-8")
    print(f"Wrote {output_path} ({total_jobs} jobs, {len(grouped)} countries)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a static HTML overview of jobs, grouped by country and city."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Source JSON file")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output HTML file")
    args = parser.parse_args()
    build(args.input, args.output)


if __name__ == "__main__":
    main()
