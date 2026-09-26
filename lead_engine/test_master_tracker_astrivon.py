from unittest.mock import patch

from .master_tracker_sync import (
    sync_astrivon_commissions,
    sync_astrivon_referral,
)


def test_astrivon_referral_sync_uses_independent_partner_identity():
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
        "lead_engine.master_tracker_sync.find_master_records",
        return_value=[],
    ), patch(
        "lead_engine.master_tracker_sync.create_master_record",
        return_value={"records": [{"id": "rec-ref"}]},
    ) as create:
        result = sync_astrivon_referral(lead)

    assert result["status"] == "created"
    fields = create.call_args.args[1]
    assert fields["Partner"] == "Astrivon Labs"
    assert fields["Referral"] == "fp-astrivon:Astrivon Labs"
    assert fields["Commission Rate"] == 0.20


def test_astrivon_commissions_are_recorded_per_received_payment_event():
    lead = {
        "fingerprint": "fp-astrivon",
        "company": "Acme",
        "potential_routes": ["Astrivon Labs"],
        "astrivon_payment_events": [
            {
                "event_id": "payment-001",
                "received_at": "2026-09-26T12:00:00+00:00",
                "revenue_amount": 1000,
            },
            {
                "event_id": "payment-002",
                "received_at": "2026-10-26T12:00:00+00:00",
                "revenue_amount": 500,
            },
        ],
    }
    with patch(
        "lead_engine.master_tracker_sync.find_master_records",
        return_value=[],
    ), patch(
        "lead_engine.master_tracker_sync.create_master_record",
        return_value={"records": [{"id": "rec-commission"}]},
    ) as create:
        results = sync_astrivon_commissions(lead)

    assert len(results) == 2
    first_fields = create.call_args_list[0].args[1]
    second_fields = create.call_args_list[1].args[1]
    assert first_fields["Partner"] == "Astrivon Labs"
    assert first_fields["Expected Commission"] == 200.0
    assert second_fields["Expected Commission"] == 100.0
    assert first_fields["Referral"] != second_fields["Referral"]
