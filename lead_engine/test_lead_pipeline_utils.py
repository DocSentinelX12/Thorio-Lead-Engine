from .lead_pipeline_utils import (
    prepare_lead,
    valid_prepared_leads,
)


def make_lead():
    return {
        "source": " linkedin ",
        "source_id": " 123 ",
        "url": " https://example.com/job/123 ",
        "company": " Acme ",
        "signal": " remote software engineer ",
        "evidence": " Acme is hiring a remote software engineer. ",
        "contact_email": " JANE@EXAMPLE.COM ",
        "lead_score": 85,
    }


def test_prepare_lead_normalizes_and_prioritizes():
    result = prepare_lead(make_lead())

    assert result["source"] == "linkedin"
    assert result["source_id"] == "123"
    assert result["company"] == "Acme"
    assert result["contact_email"] == "jane@example.com"
    assert result["priority"] == "High"


def test_prepare_lead_does_not_mutate_original():
    lead = make_lead()

    result = prepare_lead(lead)

    assert lead["company"] == " Acme "
    assert lead["contact_email"] == " JANE@EXAMPLE.COM "
    assert "priority" not in lead
    assert result is not lead


def test_valid_prepared_leads_filters_invalid_records():
    valid = make_lead()

    invalid = make_lead()
    invalid["company"] = ""

    result = valid_prepared_leads(
        [valid, invalid]
    )

    assert len(result) == 1
    assert result[0]["company"] == "Acme"


def test_valid_prepared_leads_assigns_priority():
    lead = make_lead()
    lead["lead_score"] = 95

    result = valid_prepared_leads([lead])

    assert result[0]["priority"] == "Critical"


def test_valid_prepared_leads_allows_missing_route():
    lead = make_lead()

    result = valid_prepared_leads([lead])

    assert len(result) == 1
    assert result[0]["company"] == "Acme"


def test_valid_prepared_leads_empty():
    assert valid_prepared_leads([]) == []


def test_valid_prepared_leads_accepts_generators():
    leads = (
        make_lead()
        for _ in range(3)
    )

    result = valid_prepared_leads(leads)

    assert len(result) == 3
