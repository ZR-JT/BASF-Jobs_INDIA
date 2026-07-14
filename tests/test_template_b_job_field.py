from bs4 import BeautifulSoup

import parse_job


def _span_div(text: str) -> str:
    return (
        '<div class="fontcolorc63bfd23">'
        f'<span class="rtltextaligneligible">{text}</span>'
        "</div>"
    )


def test_template_b_skips_malformed_location_and_finds_real_job_field():
    """
    Regression test for the documented bug: a location string like
    "Godrej One - Mumbai, IND" doesn't match the strict location regex
    (it has a hyphenated site name prefix), so it used to be guessed as
    job_field. It must now be rejected and the real category recovered
    from a later span instead of leaving job_field wrong or blocked.
    """
    html = "<html><body>" + "".join(
        _span_div(v)
        for v in [
            "Godrej One - Mumbai, IND",  # malformed location (falls through)
            "BASF India Limited",  # company
            "Marketing & Sales",  # real job_field
            "Permanent",  # job_type
            "1234567",  # requisition id
        ]
    ) + "</body></html>"

    soup = BeautifulSoup(html, "lxml")
    meta = parse_job._extract_template_b(soup, job_id="1234567", url="https://basf.jobs/x")

    assert meta["job_field"] == "Marketing & Sales"
    assert meta["job_type"] == "Permanent"
    assert meta["company_raw"] == "BASF India Limited"


def test_template_b_job_field_none_when_only_malformed_candidates():
    html = "<html><body>" + "".join(
        _span_div(v)
        for v in [
            "Mangalore, IND | Mangalore, IND",  # malformed, pipe-separated
            "BASF SE",
            "9876543",
        ]
    ) + "</body></html>"

    soup = BeautifulSoup(html, "lxml")
    meta = parse_job._extract_template_b(soup, job_id="9876543", url="https://basf.jobs/y")

    assert meta["job_field"] is None
