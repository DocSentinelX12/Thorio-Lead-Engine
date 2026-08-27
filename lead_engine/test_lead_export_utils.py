from .lead_export_utils import (
    prepare_export,
    prepare_export_lead,
)


def test_prepare_export_lead_contains_standard_fields():
    lead = {
        "source": "linkedin",
        "source_id": "123",
        "url": "https://example.com/job/123",
        "company": "Acme",
        "signal": "remote software engineer",
        "evidence": "Acme is hiring.",
        "route": "Shiftr",
        "lead_score": 90,
        "priority": "Critical",
        "status": "qualified",
        "delivery_status": "approved",
    }

    result = prepare_export_lead(lead)

    assert result["source"] == "linkedin"
    assert result["source_id"] == "123"
    assert result["company"] == "Acme"
    assert result["route"] == "Shiftr"
    assert result["lead_score"] == 90
    assert result["priority"] == "Critical"


def test_prepare_export_lead_normalizes_values():
    lead = {
        "company": " Acme ",
        "contact_email": " JANE@EXAMPLE.COM ",
        "contact_name": " Jane Smith ",
    }

    result = prepare_export_lead(lead)

    assert result["company"] == "Acme"
    assert result["contact_email"] == "jane@example.com"
    assert result["contact_name"] == "Jane Smith"


def test_prepare_export_lead_ignores_unknown_fields():
    lead = {
        "company": "Acme",
        "custom_internal_value": "secret",
    }

    result = prepare_export_lead(lead)

    assert result == {
        "company": "Acme",
    }


def test_prepare_export_lead_does_not_mutate():
    lead = {
        "company": " Acme ",
        "contact_email": " JANE@EXAMPLE.COM ",
    }

    result = prepare_export_lead(lead)

    assert lead["company"] == " Acme "
    assert lead["contact_email"] == " JANE@EXAMPLE.COM "
    assert result is not lead


def test_prepare_export_multiple_leads():
    leads = [
        {
            "company": "A",
            "route": "Shiftr",
        },
        {
            "company": "B",
            "route": "Paxus",
        },
    ]

    result = prepare_export(leads)

    assert result == [
        {
            "company": "A",
            "route": "Shiftr",
        },
        {
            "company": "B",
            "route": "Paxus",
        },
    ]


def test_prepare_export_empty():
    assert prepare_export([]) == []


def test_prepare_export_accepts_generators():
    leads = (
        {"company": name}
        for name in ["A", "B", "C"]
    )

    result = prepare_export(leads)

    assert [
        lead["company"]
        for lead in result
    ] == ["A", "B", "C"]
