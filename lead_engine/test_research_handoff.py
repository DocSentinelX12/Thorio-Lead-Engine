from . import active_processing


class _DB:
    def __init__(self, company_verified=True):
        self.payload = {
            "fingerprint": "handoff-test",
            "company": "Acme",
            "company_research": {
                "company_verified": company_verified,
                "decision_maker": "Taylor",
                "decision_maker_evidence": "https://example.com/taylor",
            },
            "research_verified_fields": ["company_verified", "decision_maker"],
            "research_status": "in_progress",
        }

    def get(self, _fingerprint):
        return dict(self.payload)

    def update_payload(self, _fingerprint, payload):
        self.payload = dict(payload)
        return dict(payload)


def _verified_result(monkeypatch):
    monkeypatch.setattr(
        active_processing,
        "_verification",
        lambda agent, payload, ctx: {
            "decision_maker_verification": "verified",
            "decision_maker_role_evidence": "https://example.com/taylor-role",
        },
    )


def test_verified_decision_maker_persists_research_before_qualification(monkeypatch):
    db = _DB()
    calls = []

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.db = db

    _verified_result(monkeypatch)
    monkeypatch.setattr(
        active_processing,
        "sync_research",
        lambda lead: calls.append(dict(lead)) or {"status": "updated"},
    )
    monkeypatch.setattr(active_processing, "enqueue", lambda *args, **kwargs: None)

    result = active_processing.verification(
        "verification",
        {"lead": db.payload, "evidence_events": []},
        ctx,
    )

    assert result["research_sync"]["status"] == "updated"
    assert calls
    assert calls[0]["research_status"] == "complete"
    assert calls[0]["company_research"]["decision_maker_verification_status"] == "verified"
    assert calls[0]["company_research"]["decision_maker_role_evidence"] == "https://example.com/taylor-role"


def test_verified_decision_maker_cannot_complete_research_without_verified_company(monkeypatch):
    db = _DB(company_verified=False)

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.db = db

    _verified_result(monkeypatch)
    monkeypatch.setattr(active_processing, "enqueue", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("blocked verification must not enqueue downstream work")))

    result = active_processing.verification(
        "verification",
        {"lead": db.payload, "evidence_events": []},
        ctx,
    )

    assert result["decision_maker_handoff"] == "research_required"
    assert result["research_verification_blocked"] == "company_not_verified"
    assert result["handoff"] == "review_required"
    assert db.payload["research_status"] == "in_progress"
    assert "decision_maker_verification_status" not in db.payload["company_research"]
