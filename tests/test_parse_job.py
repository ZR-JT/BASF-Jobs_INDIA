import parse_job


# ---------------------------------------------------------------------------
# _validate_job_field
# ---------------------------------------------------------------------------


def test_validate_job_field_rejects_location_with_country_code():
    assert parse_job._validate_job_field("Godrej One - Mumbai, IND") is None


def test_validate_job_field_rejects_pipe_separated_locations():
    assert parse_job._validate_job_field("Mangalore, IND | Mangalore, IND") is None


def test_validate_job_field_rejects_long_blurb_text():
    long_text = (
        "We are looking for a passionate professional to join our growing "
        "team and help shape the future of the organisation together with us."
    )
    assert len(long_text) > 60
    assert parse_job._validate_job_field(long_text) is None


def test_validate_job_field_rejects_colon_and_indicator_words():
    assert parse_job._validate_job_field("Job Description: engineering") is None
    assert parse_job._validate_job_field("Key Responsibilities and tasks") is None
    assert parse_job._validate_job_field("Objectives of the role") is None


def test_validate_job_field_accepts_real_categories():
    assert parse_job._validate_job_field("Marketing & Sales") == "Marketing & Sales"
    assert (
        parse_job._validate_job_field("Research & Development")
        == "Research & Development"
    )
    assert parse_job._validate_job_field("Engineering") == "Engineering"


def test_validate_job_field_handles_none_and_blank():
    assert parse_job._validate_job_field(None) is None
    assert parse_job._validate_job_field("") is None
    assert parse_job._validate_job_field("   ") is None


# ---------------------------------------------------------------------------
# _extract_description — must never truncate
# ---------------------------------------------------------------------------

_LONG_PARAGRAPH = (
    "We are looking for an experienced and highly motivated professional to "
    "join our team. In this role you will collaborate with cross-functional "
    "teams across the globe, drive innovative projects, and contribute to "
    "BASF's mission of creating chemistry for a sustainable future. You will "
    "be responsible for a wide range of tasks including planning, execution, "
    "and continuous improvement of key processes."
)


def test_extract_description_template_a_returns_full_text():
    text = (
        f"Job Description: {_LONG_PARAGRAPH} "
        "Apply now Credits Data Copyright \xc2\xa9 BASF SE"
    )
    desc = parse_job._extract_description(text)
    assert desc == _LONG_PARAGRAPH
    assert len(desc) > 100


def test_extract_description_template_b_returns_full_text():
    text = (
        f"Header nav stuff Apply now {_LONG_PARAGRAPH} "
        "Apply now A unique total offer: you@BASF"
    )
    desc = parse_job._extract_description(text)
    assert desc == _LONG_PARAGRAPH
    assert len(desc) > 100


def test_extract_description_too_short_is_not_truncated_either():
    # Even a description just above/below the validity threshold should
    # never be sliced to a fixed length.
    text = "Job Description: " + "x" * 40 + " Apply now Credits Data"
    desc = parse_job._extract_description(text)
    assert desc == "x" * 40
