from lead_engine.delivery_policy import MIN_DELIVERY_SCORE
from lead_engine.partner_delivery import (
    deliverable_partner,
    delivery_counts,
    partition_leads,
)


def make_lead(route, signal="remote software engineer"):
    return {
        "company": "Acme",
        "route": route,
        "lead_score": MIN_DELIVERY_SCORE,
        "signal": signal,
        "evidence": f"Acme has a {signal} opening.",
        "url": "https://example.com/jobs/123",
    }


def test_shiftr_lead_is_deliverable():
    lead = make_lead("Shiftr")

    assert deliverable_partner(lead) == "Shiftr"


def test_paxus_lead_is_deliverable():
    lead = make_lead("Paxus")
    lead["signal"] = "contract staffing need"
    lead["evidence"] = "Acme needs contractors for a technology project."

    assert deliverable_partner(lead) == "Paxus"


def test_thorio_lead_is_deliverable():
    lead = make_lead("Thorio")

    assert deliverable_partner(lead) == "Thorio"


def test_review_lead_has_no_partner():
    lead = make_lead("Review")

    assert deliverable_partner(lead) == ""


def test_rejected_lead_has_no_partner():
    lead = make_lead("Shiftr", "office manager")
    lead["evidence"] = "Acme is hiring an office manager."

    assert deliverable_partner(lead) == ""


def test_partition_leads_separates_partners():
    leads = [
        make_lead("Shiftr"),
        make_lead("Paxus", "contract staffing need"),
        make_lead("Thorio"),
        make_lead("Review"),
    ]

    leads[1]["evidence"] = "Acme needs contractors for a technology project."

    result = partition_leads(leads)

    assert len(result["Shiftr"]) == 1
    assert len(result["Paxus"]) == 1
    assert len(result["Thorio"]) == 1
    assert len(result["Review"]) == 1


def test_partition_preserves_lead_data():
    lead = make_lead("Thorio")

    result = partition_leads([lead])

    assert result["Thorio"][0]["company"] == "Acme"
    assert result["Thorio"][0]["route"] == "Thorio"
    assert result["Thorio"][0]["url"] == lead["url"]


def test_delivery_counts():
    leads = [
        make_lead("Shiftr"),
        make_lead("Shiftr"),
        make_lead("Paxus", "contract staffing need"),
        make_lead("Thorio"),
        make_lead("Review"),
    ]

    leads[2]["evidence"] = "Acme needs contractors for a technology project."

    counts = delivery_counts(leads)

    assert counts == {
        "Shiftr": 2,
        "Paxus": 1,
        "Thorio": 1,
        "Review": 1,
    }
