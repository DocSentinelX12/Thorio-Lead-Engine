from .lead_summary import (
    summarize_lead,
    summarize_leads,
)


def test_summarize_lead():
    lead = {
        "company": "Acme",
        "contact_name": "Jane Smith",
        "route": "Shiftr",
        "signal": "remote software engineer",
    }

    assert summarize_lead(lead) == (
        "Acme | contact: Jane Smith | "
        "route: Shiftr | signal: remote software engineer"
    )


def test_summarize_lead_uses_person_fallback():
    lead = {
        "company": "Acme",
        "person": "John Smith",
        "route": "Paxus",
    }

    assert summarize_lead(lead) == (
        "Acme | contact: John Smith | route: Paxus"
    )


def test_summarize_lead_missing_optional_fields():
    lead = {
        "company": "Acme",
    }

    assert summarize_lead(lead) == "Acme"


def test_summarize_empty_lead():
    assert summarize_lead({}) == ""


def test_summarize_leads():
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

    assert summarize_leads(leads) == [
        "A | route: Shiftr",
        "B | route: Paxus",
    ]


def test_summarize_leads_accepts_generator():
    leads = (
        {
            "company": f"Company {i}",
        }
        for i in range(3)
    )

    assert summarize_leads(leads) == [
        "Company 0",
        "Company 1",
        "Company 2",
    ]


def test_summarize_strips_values():
    lead = {
        "company": "  Acme  ",
        "contact_name": " Jane Smith ",
        "route": " Shiftr ",
        "signal": " remote engineer ",
    }

    assert summarize_lead(lead) == (
        "Acme | contact: Jane Smith | "
        "route: Shiftr | signal: remote engineer"
    )
