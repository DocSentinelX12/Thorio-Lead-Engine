from types import SimpleNamespace

from . import active_processing
from .database import LeadDB
from .master_tracker_sync import _opportunity_need, _routes
from .sales_handoff import verify_master_tracker
from .test_sales_eligibility_gate import _lead
from .airtable_sync import _work_queue


def test_astrivon_is_review_only_when_live_partner_selects_do_not_support_it(tmp_path, monkeypatch):
    db = LeadDB(data_dir=tmp_path)
    lead = _lead(qualified=True)
    lead["potential_routes"] = ["Astrivon Labs", "Shiftr"]
    lead["eligible_routes"] = ["Astrivon Labs", "Shiftr"]
    lead["preserved_routes"] = ["Astrivon Labs", "Shiftr"]
    lead["routing_result"] = {"destinations": ["Astrivon Labs", "Shiftr"], "review_required": False}
    db.insert_if_new(lead)
    monkeypatch.setattr(
        active_processing,
        "_routing",
        lambda agent, payload, ctx: {
            "destinations": ["Astrivon Labs", "Shiftr"],
            "review_required": False,
            "multi_route": True,
        },
    )

    result = active_processing.routing("routing", {"lead": lead, "verified": True}, SimpleNamespace(db=db))
    stored = db.get(lead["fingerprint"])

    assert result["destinations"] == ["Shiftr"]
    assert result["review_required"] is True
    assert result["unsupported_destinations"] == ["Astrivon Labs"]
    assert "schema_compatibility_blockers" in result
    assert stored["routing_result"]["destinations"] == ["Shiftr"]
    assert stored["routing_result"]["review_required"] is True
    assert _routes(stored) == ["Shiftr"]
    db.close()


def test_handoff_verification_checks_only_active_schema_supported_destinations():
    lead = _lead(qualified=True)
    lead["potential_routes"] = ["Astrivon Labs", "Shiftr"]
    lead["eligible_routes"] = ["Shiftr"]
    lead["preserved_routes"] = ["Shiftr"]
    lead["routing_result"] = {"destinations": ["Shiftr"], "review_required": False}
    master_result = {
        "status": "synced",
        "company": {"status": "created", "record": {"id": "rec-company", "fields": {"Company": "Acme"}}},
        "opportunities": [
            {"status": "created", "record": {"id": "rec-shiftr", "fields": {"Partner": "Shiftr", "Opportunity": f"{lead['fingerprint']}:Shiftr", "Company": "Acme"}}}
        ],
        "astrivon_referral": None,
    }
    assert verify_master_tracker(master_result, lead) is True


def test_b2b_opportunity_uses_existing_airtable_need_choice():
    lead = {"business_need_research": {"verified": True, "business_need": "B2B outreach and lead generation"}}
    assert _opportunity_need(lead, "Shiftr") == "Other"


def test_astrivon_work_queue_uses_existing_airtable_choice():
    assert _work_queue({"potential_routes": ["Astrivon Labs"]}) == "💰 Revenue / Referral"
