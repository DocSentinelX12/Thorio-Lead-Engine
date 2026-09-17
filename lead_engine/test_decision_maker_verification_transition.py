from datetime import datetime, timezone

from .agent_stateful_handlers import verification


def _lead(*, evidence=None, observed_person="Taylor", company="Acme"):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "fingerprint": "decision-maker-transition-test",
        "company": company,
        "person": observed_person,
        "contact_name": observed_person,
        "signal": "Acme is hiring a CTO",
        "evidence": "Acme is hiring a CTO",
        "observed_at": now,
        "research_status": "research_required",
        "company_research": {
            "company_verified": True,
            "observed_decision_maker": observed_person,
            "decision_maker_verification_status": "observed_needs_role_verification",
        },
        "specialist_findings": {
            "social_decision_maker_research": {
                "findings": evidence or [],
            }
        },
    }


def test_decision_maker_transitions_from_observed_to_verified_from_independent_role_evidence():
    result = verification(
        "verification",
        {
            "lead": _lead(
                evidence=[
                    {
                        "source": "LinkedIn",
                        "url": "https://example.com/taylor-role",
                        "matches": ["cto"],
                        "evidence": "Taylor is CTO at Acme",
                    }
                ]
            ),
            "evidence_events": [],
        },
        None,
    )
    assert result["decision_maker_verification"] == "verified"
    assert result["decision_maker_role_evidence"] == "https://example.com/taylor-role"
    assert result["decision_maker_verification_record"]["person"] == "Taylor"
    assert result["decision_maker_verification_record"]["source"] == "LinkedIn"


def test_decision_maker_does_not_verify_from_name_and_email_alone():
    lead = _lead(evidence=[])
    lead["company_research"].update({
        "decision_maker_email": "taylor@example.com",
        "decision_maker_title": "Chief Technology Officer",
    })
    result = verification("verification", {"lead": lead, "evidence_events": []}, None)
    assert result["decision_maker_verification"] == "observed_needs_role_verification"
    assert result["decision_maker_role_evidence"] == ""


def test_decision_maker_rejects_role_evidence_for_wrong_company():
    result = verification(
        "verification",
        {
            "lead": _lead(
                evidence=[
                    {
                        "source": "LinkedIn",
                        "url": "https://example.com/taylor-role",
                        "matches": ["cto"],
                        "evidence": "Taylor is CTO at OtherCo",
                    }
                ]
            ),
            "evidence_events": [],
        },
        None,
    )
    assert result["decision_maker_verification"] == "observed_needs_role_verification"
    assert result["decision_maker_role_evidence"] == ""


def test_decision_maker_rejects_unrelated_person_role_evidence():
    result = verification(
        "verification",
        {
            "lead": _lead(
                evidence=[
                    {
                        "source": "LinkedIn",
                        "url": "https://example.com/jordan-role",
                        "matches": ["cto"],
                        "evidence": "Jordan is CTO at Acme",
                    }
                ]
            ),
            "evidence_events": [],
        },
        None,
    )
    assert result["decision_maker_verification"] == "observed_needs_role_verification"
    assert result["decision_maker_role_evidence"] == ""


def test_decision_maker_requires_role_evidence_url():
    result = verification(
        "verification",
        {
            "lead": _lead(
                evidence=[
                    {
                        "source": "LinkedIn",
                        "matches": ["cto"],
                        "evidence": "Taylor is CTO at Acme",
                    }
                ]
            ),
            "evidence_events": [],
        },
        None,
    )
    assert result["decision_maker_verification"] == "observed_needs_role_verification"
    assert result["decision_maker_role_evidence"] == ""
