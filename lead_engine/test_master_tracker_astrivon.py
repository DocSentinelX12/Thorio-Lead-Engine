from unittest.mock import patch

from .master_tracker_sync import (
    sync_astrivon_commissions,
    sync_astrivon_referral,
)


def test_astrivon_referral_is_review_only_until_airtable_partner_schema_supports_it():
    lead = {
        "fingerprint": "fp-astrivon",
        "company": "Acme",
        "potential_routes": ["Astrivon Labs"],
        "astrivon_referral": {
            "introduced_at": "2026-09-26T12:00:00+00:00",
            "referral_id": "astr-001",
            "partner_confirmed": True,
        },
    }
    with patch(
        "lead_engine.master_tracker_sync.atomic_upsert_master_record",
        return_value={"records": [{"id": "rec-ref"}]},
    ) as upsert:
        result = sync_astrivon_referral(lead)

    assert result is None
    upsert.assert_not_called()


def test_astrivon_commissions_are_not_written_until_airtable_partner_schema_supports_them():
    lead = {
        "fingerprint": "fp-astrivon",
        "company": "Acme",
        "potential_routes": ["Astrivon Labs"],
        "astrivon_status": "active",
        "astrivon_partner_confirmed": True,
        "astrivon_payment_events": [
            {"event_id": "payment-001", "received_at": "2026-09-26T12:00:00+00:00", "revenue_amount": 1000},
            {"event_id": "payment-002", "received_at": "2026-10-26T12:00:00+00:00", "revenue_amount": 500},
        ],
    }
    with patch(
        "lead_engine.master_tracker_sync.atomic_upsert_master_record",
        return_value={"records": [{"id": "rec-commission"}]},
    ) as upsert:
        results = sync_astrivon_commissions(lead)

    assert results == []
    upsert.assert_not_called()
