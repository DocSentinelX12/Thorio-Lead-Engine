from .lead_contact import (
    contact_email,
    filter_contactable_leads,
    has_contact_email,
)


def test_contact_email_normalizes():
    lead = {
        "contact_email": "  JANE@EXAMPLE.COM  ",
    }

    assert contact_email(lead) == "jane@example.com"


def test_contact_email_missing():
    assert contact_email({}) == ""


def test_contact_email_none():
    assert contact_email(
        {"contact_email": None}
    ) == ""


def test_has_contact_email():
    assert has_contact_email(
        {"contact_email": "jane@example.com"}
    )


def test_has_contact_email_rejects_missing():
    assert not has_contact_email({})


def test_has_contact_email_rejects_invalid():
    assert not has_contact_email(
        {"contact_email": "not-an-email"}
    )


def test_filter_contactable_leads():
    leads = [
        {
            "company": "Good",
            "contact_email": "good@example.com",
        },
        {
            "company": "Bad",
            "contact_email": "",
        },
        {
            "company": "Also Good",
            "contact_email": "other@example.org",
        },
    ]

    result = filter_contactable_leads(leads)

    assert [
        lead["company"]
        for lead in result
    ] == [
        "Good",
        "Also Good",
    ]


def test_filter_contactable_leads_returns_copies():
    lead = {
        "company": "Acme",
        "contact_email": "jane@example.com",
    }

    result = filter_contactable_leads([lead])

    assert result[0] == lead
    assert result[0] is not lead


def test_filter_contactable_leads_accepts_generator():
    leads = (
        {
            "company": f"Company {i}",
            "contact_email": f"user{i}@example.com",
        }
        for i in range(3)
    )

    result = filter_contactable_leads(leads)

    assert len(result) == 3
