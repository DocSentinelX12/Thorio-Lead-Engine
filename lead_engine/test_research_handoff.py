from . import active_processing


class _DB:
    def __init__(self):
        self.payload = {
            "fingerprint": "handoff-test",
            "company": "Acme",
            "company_research": {
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


def test_verified_decision_maker_persists_research_before_qualification(monkeypatch):
    db = _DB()
    calls = []

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.db = db

    monkeypatch.setattr(
        active_processing,
        "_verification",
        lambda agent, payload, ctx: {
            "decision_maker_verification": "verified",
            "decision_maker_role_evidence": "https://example.com/taylor-role",
        },
    )
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
