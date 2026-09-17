from . import active_processing


class _DB:
    def __init__(self):
        self.payload = {
            "fingerprint": "decision-maker-persistence-test",
            "company": "Acme",
            "contact_name": "Taylor",
            "person": "Taylor",
            "company_research": {
                "company_verified": True,
                "observed_decision_maker": "Taylor",
                "decision_maker_verification_status": "observed_needs_role_verification",
            },
            "specialist_findings": {
                "social_decision_maker_research": {
                    "findings": [
                        {
                            "source": "LinkedIn",
                            "url": "https://example.com/taylor-role",
                            "matches": ["cto"],
                            "evidence": "Taylor is CTO at Acme",
                        }
                    ]
                }
            },
            "research_status": "research_required",
        }

    def get(self, _fingerprint):
        return dict(self.payload)

    def update_payload(self, _fingerprint, payload):
        self.payload = dict(payload)
        return dict(payload)


def test_real_decision_maker_verification_persists_verified_identity_before_handoff(monkeypatch):
    db = _DB()
    queued = []
    synced = []

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.db = db

    monkeypatch.setattr(
        active_processing,
        "sync_research",
        lambda lead: synced.append(dict(lead)) or {"status": "updated"},
    )
    monkeypatch.setattr(active_processing, "enqueue", lambda *args, **kwargs: queued.append((args, kwargs)))

    result = active_processing.verification(
        "verification",
        {
            "lead": db.payload,
            "evidence_events": [],
        },
        ctx,
    )

    stored = db.payload
    research = stored["company_research"]
    assert result["decision_maker_verification"] == "verified"
    assert result["decision_maker_handoff"] == "qualification_a"
    assert research["decision_maker"] == "Taylor"
    assert research["decision_maker_evidence"] == "https://example.com/taylor-role"
    assert research["decision_maker_role_evidence"] == "https://example.com/taylor-role"
    assert research["decision_maker_verification_status"] == "verified"
    assert research["decision_maker_verification_source"] == "LinkedIn"
    assert stored["research_status"] == "complete"
    assert synced and synced[0]["company_research"]["decision_maker"] == "Taylor"
    assert any(args[1] == "qualification_a" for args, _ in queued)
