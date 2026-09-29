import pytest

from .commercial_signal_broadening import extract_broadened_signals
from .collector import normalize_lead_input


def test_indirect_signal_is_promoted_only_when_attributed_current_and_technical():
    result = extract_broadened_signals(
        "We are evaluating vendors for our AI platform.",
        company="Acme",
    )

    assert result["promotion_eligible"] is True
    assert result["promotion_count"] == 1
    match = result["matches"][0]
    assert match["category"] == "vendor_evaluation"
    assert match["attribution"] == "first_person"
    assert match["temporal_status"] == "current_or_unspecified"
    assert match["certainty"] == "exploratory"
    assert match["technical_context"] is True
    assert "evaluating vendors" in match["evidence_context"].lower()


def test_unattributed_indirect_signal_is_preserved_but_not_promoted():
    result = extract_broadened_signals(
        "Industry teams are evaluating vendors for AI platforms.",
        company="Acme",
    )

    assert len(result["matches"]) == 1
    assert result["matches"][0]["attribution"] == "unattributed"
    assert result["matches"][0]["promotion_eligible"] is False
    assert "unattributed_signal_preserved_not_promoted" in result["safety_reasons"]


def test_speculative_indirect_signal_is_preserved_but_not_promoted():
    result = extract_broadened_signals(
        "We might be evaluating vendors for our AI platform.",
        company="Acme",
    )

    assert len(result["matches"]) == 1
    assert result["matches"][0]["certainty"] == "speculative"
    assert result["matches"][0]["promotion_eligible"] is False
    assert "speculative_signal_preserved_not_promoted" in result["safety_reasons"]


def test_historical_indirect_signal_is_preserved_but_not_promoted():
    result = extract_broadened_signals(
        "Last year, we were evaluating vendors for our AI platform.",
        company="Acme",
    )

    assert len(result["matches"]) == 1
    assert result["matches"][0]["temporal_status"] == "historical"
    assert result["matches"][0]["promotion_eligible"] is False
    assert "historical_signal_preserved_not_promoted" in result["safety_reasons"]


def test_negated_indirect_signal_is_preserved_but_not_promoted():
    result = extract_broadened_signals(
        "We are not looking for a partner for our software platform.",
        company="Acme",
    )

    assert len(result["matches"]) == 1
    assert result["matches"][0]["negated"] is True
    assert result["matches"][0]["promotion_eligible"] is False
    assert "negated_signal_preserved_not_promoted" in result["safety_reasons"]


def test_structural_event_is_extracted_without_becoming_direct_intent():
    result = extract_broadened_signals(
        "Acme raised Series A and launched a new product for its software platform.",
        company="Acme",
    )

    assert result["promotion_eligible"] is False
    assert {item["category"] for item in result["matches"]} == {
        "funding_execution",
        "product_event",
    }
    assert "structural_event_requires_current_need_or_corroboration" in result["safety_reasons"]


def test_collector_carries_broadened_signal_contract_without_replacing_existing_signal_type():
    lead = {
        "source": "linkedin_signal",
        "source_id": "broadening-001",
        "url": "https://example.com/posts/broadening-001",
        "company": "Acme",
        "signal": "Founder update",
        "evidence": "We are evaluating vendors for our AI platform.",
        "signal_type": "business_intent",
    }

    result = normalize_lead_input(lead)

    assert result["signal_type"] == "commercial_intent"
    assert result["signal_strength"] == "explicit"
    assert result["signal_matches"] == ["evaluating vendors"]
    assert result["commercial_signal_broadening"]["promotion_eligible"] is True
    assert result["commercial_signal_broadening"]["matches"][0]["phrase"].lower() == "evaluating vendors"


def test_collector_keeps_structural_signal_as_context_only():
    lead = {
        "source": "product-hunt",
        "source_id": "broadening-002",
        "url": "https://example.com/posts/broadening-002",
        "company": "Acme",
        "signal": "Company announcement",
        "evidence": "Acme launched a new product for its software platform.",
        "signal_type": "discovery",
    }

    result = normalize_lead_input(lead)

    assert result["signal_type"] == "discovery"
    assert result["commercial_signal_broadening"]["promotion_eligible"] is False
    assert result["commercial_signal_broadening"]["matches"][0]["category"] == "product_event"
