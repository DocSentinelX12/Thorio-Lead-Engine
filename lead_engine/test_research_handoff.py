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
            "research_verified_fields": ["business_need_research", "current_intent_research", "technical_product_hiring_research", "commercial_research", "route_research"],
            "business_need_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/need", "evidence": "Verified need"}]},
            "current_intent_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/intent", "evidence": "Verified intent"}]},
            "technical_product_hiring_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/technical", "evidence": "Verified technical need"}]},
            "commercial_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/commercial", "evidence": "Verified commercial context"}]},
            "route_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/route", "evidence": "Verified route"}]},
            "closer_package": {"ready": False, "verification_status": "research_required", "evidence": [{"url": "https://example.com/need", "evidence": "Verified need"}]},
            "research_status": "research_required",
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


def test_verified_decision_maker_does_not_mark_incomplete_research_complete(monkeypatch):
    db = _DB()
    db.payload["company_research"]["decision_maker_verification_status"] = "observed"
    db.payload["closer_package"] = {
        "ready": False,
        "verification_status": "research_required",
        "evidence": [{"url": "https://example.com/research", "evidence": "Observed research"}],
    }
    db.payload["business_need_research"] = {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/need", "evidence": "Need"}]}
    db.payload["current_intent_research"] = {"verified": False, "verification_status": "observed_evidence", "evidence": [{"url": "https://example.com/intent", "evidence": "Intent"}]}
    db.payload["technical_product_hiring_research"] = {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/technical", "evidence": "Technical"}]}
    db.payload["commercial_research"] = {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/commercial", "evidence": "Commercial"}]}
    db.payload["route_research"] = {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/route", "evidence": "Route"}]}

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.db = db
    _verified_result(monkeypatch)
    monkeypatch.setattr(active_processing, "sync_research", lambda lead: {"status": "updated"})
    monkeypatch.setattr(active_processing, "enqueue", lambda *args, **kwargs: None)

    result = active_processing.verification(
        "verification",
        {"lead": db.payload, "evidence_events": []},
        ctx,
    )

    assert result["decision_maker_handoff"] == "research_required"
    assert db.payload["research_status"] == "research_required"
    assert db.payload["closer_package"]["ready"] is False
