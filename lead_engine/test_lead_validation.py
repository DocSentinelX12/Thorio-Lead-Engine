from .lead_validation import (
    invalid_leads,
    valid_lead,
    validate_lead,
)


def test_valid_lead():
    lead = {
        "company": "Acme",
        "route": "Shiftr",
        "lead_score": 90,
    }

    assert validate_lead(lead) == []
    assert valid_lead(lead) is True


def test_missing_company():
    lead = {
        "route": "Shiftr",
    }

    assert validate_lead(lead) == [
        "missing_company",
    ]
    assert valid_lead(lead) is False


def test_missing_route():
    lead = {
        "company": "Acme",
    }

    assert validate_lead(lead) == [
        "missing_route",
    ]


def test_missing_multiple_fields():
    lead = {}

    assert validate_lead(lead) == [
        "missing_company",
        "missing_route",
    ]


def test_invalid_score_too_high():
    lead = {
        "company": "Acme",
        "route": "Shiftr",
        "lead_score": 101,
    }

    assert validate_lead(lead) == [
        "invalid_lead_score",
    ]


def test_invalid_score_negative():
    lead = {
        "company": "Acme",
        "route": "Shiftr",
        "lead_score": -1,
    }

    assert validate_lead(lead) == [
        "invalid_lead_score",
    ]


def test_invalid_score_text():
    lead = {
        "company": "Acme",
        "route": "Shiftr",
        "lead_score": "bad",
    }

    assert validate_lead(lead) == [
        "invalid_lead_score",
    ]


def test_score_boundaries_are_valid():
    assert valid_lead(
        {
            "company": "A",
            "route": "Shiftr",
            "lead_score": 0,
        }
    )

    assert valid_lead(
        {
            "company": "A",
            "route": "Shiftr",
            "lead_score": 100,
        }
    )


def test_invalid_leads():
    leads = [
        {
            "company": "A",
            "route": "Shiftr",
        },
        {
            "company": "",
            "route": "Paxus",
        },
        {
            "company": "C",
            "route": "Thorio",
            "lead_score": 90,
        },
    ]

    result = invalid_leads(leads)

    assert len(result) == 1
    assert result[0]["company"] == ""


def test_invalid_leads_returns_copies():
    lead = {
        "company": "",
        "route": "Shiftr",
    }

    result = invalid_leads([lead])

    assert result[0] == lead
    assert result[0] is not lead


def test_validation_strips_required_fields():
    lead = {
        "company": "  Acme  ",
        "route": "  Shiftr  ",
    }

    assert valid_lead(lead) is True
