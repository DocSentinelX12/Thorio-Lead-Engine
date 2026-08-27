from .lead_queue import (
    build_lead_queue,
    queue_size,
)


def make_lead(source_id, company="Acme", score=80):
    return {
        "source": "linkedin",
        "source_id": source_id,
        "company": company,
        "contact_email": " TEST@EXAMPLE.COM ",
        "lead_score": score,
    }


def test_build_lead_queue_deduplicates():
    leads = [
        make_lead("1"),
        make_lead("1"),
        make_lead("2", company="Beta"),
    ]

    result = build_lead_queue(leads)

    assert len(result) == 2


def test_build_lead_queue_normalizes():
    result = build_lead_queue(
        [make_lead("1")]
    )

    assert result[0]["contact_email"] == "test@example.com"


def test_build_lead_queue_assigns_priority():
    result = build_lead_queue(
        [make_lead("1", score=95)]
    )

    assert result[0]["priority"] == "Critical"


def test_build_lead_queue_preserves_order():
    leads = [
        make_lead("1", company="Alpha"),
        make_lead("2", company="Beta"),
        make_lead("3", company="Gamma"),
    ]

    result = build_lead_queue(leads)

    assert [
        lead["company"]
        for lead in result
    ] == [
        "Alpha",
        "Beta",
        "Gamma",
    ]


def test_build_lead_queue_does_not_mutate():
    lead = make_lead("1")

    build_lead_queue([lead])

    assert lead["company"] == "Acme"
    assert lead["contact_email"] == " TEST@EXAMPLE.COM "
    assert "priority" not in lead


def test_queue_size_counts_unique_leads():
    leads = [
        make_lead("1"),
        make_lead("1"),
        make_lead("2"),
    ]

    assert queue_size(leads) == 2


def test_queue_size_empty():
    assert queue_size([]) == 0


def test_queue_accepts_generator():
    leads = (
        make_lead(str(index))
        for index in range(4)
    )

    result = build_lead_queue(leads)

    assert len(result) == 4
