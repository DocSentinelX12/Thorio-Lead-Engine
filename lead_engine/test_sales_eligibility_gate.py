from lead_engine.active_processing import _sales_eligibility


def _lead(qualified=True):
    return {
        "fingerprint": "sales-gate-test",
        "company": "Acme",
        "person": "Alex CTO",
        "business_need": "remote software engineer hiring",
        "qualified": qualified,
        "potential_routes": ["thorio"],
        "company_research": {
            "decision_maker": "Alex CTO",
            "decision_maker_evidence": "company leadership page",
            "decision_maker_email": "alex@example.com",
        },
    }


def _routing():
    return {"destinations": ["thorio"]}


def test_potential_routes_alone_cannot_enter_sales_execution():
    eligible, reason = _sales_eligibility(_lead(qualified=False), _routing(), {})
    assert eligible is False
    assert reason == "not_qualified"


def test_explicit_qualification_allows_sales_eligibility():
    eligible, reason = _sales_eligibility(_lead(qualified=True), _routing(), {})
    assert eligible is True
    assert reason == "eligible"


def test_qualified_opportunity_survives_airtable_sync_failure():
    eligible, reason = _sales_eligibility(
        _lead(qualified=True), _routing(), {"sync_error_present": True}
    )
    assert eligible is True
    assert reason == "airtable_sync_retryable"
