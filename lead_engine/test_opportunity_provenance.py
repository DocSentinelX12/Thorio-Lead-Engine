import pytest

from .opportunity_provenance import (
    canonical_evidence_key,
    normalize_evidence_event,
    validate_provenance_scope,
)


def test_normalize_evidence_event_preserves_identity_and_provenance():
    event = normalize_evidence_event(
        {
            "opportunity_id": "opp-1",
            "fingerprint": "opp-1",
            "source": "linkedin",
            "source_id": "post-1",
            "url": "https://example.com/post-1",
            "evidence": "Hiring an AI engineer",
            "observed_at": "2026-09-26T00:00:00+00:00",
            "verification_status": "observed_evidence",
            "collector_agent": "x_signal",
            "source_lane": "social",
        },
        opportunity_id="opp-1",
        research_section="current_intent_research",
    )

    assert event["opportunity_id"] == "opp-1"
    assert event["fingerprint"] == "opp-1"
    assert event["research_section"] == "current_intent_research"
    assert event["collector_agent"] == "x_signal"
    assert event["verification_status"] == "observed_evidence"


def test_normalize_evidence_event_never_promotes_observation_to_verified():
    event = normalize_evidence_event(
        {
            "opportunity_id": "opp-1",
            "fingerprint": "opp-1",
            "evidence": "Observed hiring signal",
        },
        opportunity_id="opp-1",
        research_section="business_need_research",
    )

    assert event["verification_status"] == "observed_evidence"
    assert event.get("verified") is not True


def test_cross_opportunity_evidence_is_rejected():
    with pytest.raises(ValueError, match="opportunity"):
        validate_provenance_scope(
            {"opportunity_id": "opp-2", "fingerprint": "opp-2"},
            opportunity_id="opp-1",
        )


def test_route_specific_provenance_is_isolated():
    event = normalize_evidence_event(
        {
            "opportunity_id": "opp-1",
            "fingerprint": "opp-1",
            "evidence": "Needs contract engineering team",
            "route": "Shiftr",
        },
        opportunity_id="opp-1",
        research_section="route_research",
        route="Shiftr",
    )

    assert event["route"] == "Shiftr"
    assert validate_provenance_scope(event, opportunity_id="opp-1", route="Shiftr") is None
    with pytest.raises(ValueError, match="route"):
        validate_provenance_scope(event, opportunity_id="opp-1", route="Paxus")


def test_evidence_key_keeps_distinct_observations_distinct():
    first = {"url": "https://example.com/a", "evidence": "Need", "observed_at": "2026-09-26T00:00:00+00:00"}
    second = {**first, "observed_at": "2026-09-26T01:00:00+00:00"}

    assert canonical_evidence_key(first) != canonical_evidence_key(second)


def test_evidence_deduplication_preserves_verified_upgrade():
    from .opportunity_provenance import validate_provenance_collection

    observed = {
        "opportunity_id": "opp-1",
        "fingerprint": "opp-1",
        "url": "https://example.com/evidence",
        "evidence": "Need",
        "observed_at": "2026-09-26T00:00:00+00:00",
        "verification_status": "observed_evidence",
    }
    verified = {**observed, "verification_status": "verified", "verified": True}

    result = validate_provenance_collection(
        [observed, verified],
        opportunity_id="opp-1",
        research_section="business_need_research",
    )

    assert len(result) == 1
    assert result[0]["verification_status"] == "verified"
    assert result[0]["verified"] is True
