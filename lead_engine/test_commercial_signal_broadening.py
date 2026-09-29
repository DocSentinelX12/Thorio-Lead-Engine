import pytest

from .commercial_signal_broadening import extract_broadened_signals
from .collector import normalize_lead_input


def test_indirect_signal_is_promoted_only_when_attributed_current_and_technical():
    result = extract_broadened_signals("We are evaluating vendors for our AI platform.", company="Acme")
    assert result["promotion_eligible"] is True
    assert result["promotion_count"] == 1
    match = result["matches"][0]
    assert match["category"] == "vendor_evaluation"
    assert match["attribution"] == "first_person"
    assert match["temporal_status"] == "current_or_unspecified"
    assert match["certainty"] == "exploratory"
    assert match["technical_context"] is True
    assert "evaluating vendors" in match["evidence_context"].lower()


def test_exploring_options_is_promoted_when_company_owns_a_technical_evaluation():
    result = extract_broadened_signals("We are exploring options for our AI platform.", company="Acme")
    assert result["promotion_eligible"] is True
    assert result["promotion_count"] == 1
    match = result["matches"][0]
    assert match["category"] == "vendor_evaluation"
    assert match["phrase"].lower() == "exploring options"
    assert match["attribution"] == "first_person"
    assert match["technical_context"] is True


def test_generic_exploring_options_is_preserved_but_not_promoted():
    result = extract_broadened_signals("We are exploring options.", company="Acme")
    assert len(result["matches"]) == 1
    assert result["matches"][0]["phrase"].lower() == "exploring options"
    assert result["matches"][0]["promotion_eligible"] is False


def test_unattributed_exploring_options_is_preserved_but_not_promoted():
    result = extract_broadened_signals("Industry teams are exploring options for AI platforms.", company="Acme")
    assert len(result["matches"]) == 1
    assert result["matches"][0]["attribution"] == "unattributed"
    assert result["matches"][0]["promotion_eligible"] is False


def test_unattributed_indirect_signal_is_preserved_but_not_promoted():
    result = extract_broadened_signals("Industry teams are evaluating vendors for AI platforms.", company="Acme")
    assert len(result["matches"]) == 1
    assert result["matches"][0]["attribution"] == "unattributed"
    assert result["matches"][0]["promotion_eligible"] is False
    assert "unattributed_signal_preserved_not_promoted" in result["safety_reasons"]


def test_speculative_indirect_signal_is_preserved_but_not_promoted():
    result = extract_broadened_signals("We might be evaluating vendors for our AI platform.", company="Acme")
    assert len(result["matches"]) == 1
    assert result["matches"][0]["certainty"] == "speculative"
    assert result["matches"][0]["promotion_eligible"] is False
    assert "speculative_signal_preserved_not_promoted" in result["safety_reasons"]


def test_historical_indirect_signal_is_preserved_but_not_promoted():
    result = extract_broadened_signals("Last year, we were evaluating vendors for our AI platform.", company="Acme")
    assert len(result["matches"]) == 1
    assert result["matches"][0]["temporal_status"] == "historical"
    assert result["matches"][0]["promotion_eligible"] is False
    assert "historical_signal_preserved_not_promoted" in result["safety_reasons"]


def test_future_dated_indirect_signal_is_preserved_but_not_promoted():
    result = extract_broadened_signals("In 2099, we are evaluating vendors for our AI platform.", company="Acme")
    assert len(result["matches"]) == 1
    assert result["matches"][0]["temporal_status"] == "future"
    assert result["matches"][0]["promotion_eligible"] is False
    assert "future_signal_preserved_not_promoted" in result["safety_reasons"]


def test_cancelled_indirect_signal_is_preserved_but_not_promoted():
    result = extract_broadened_signals("We are evaluating vendors, but the project was cancelled.", company="Acme")
    assert len(result["matches"]) == 1
    assert result["matches"][0]["negated"] is True
    assert result["matches"][0]["promotion_eligible"] is False


def test_no_longer_indirect_signal_is_preserved_but_not_promoted():
    result = extract_broadened_signals("We are no longer evaluating vendors for our AI platform.", company="Acme")
    assert len(result["matches"]) == 1
    assert result["matches"][0]["negated"] is True
    assert result["matches"][0]["promotion_eligible"] is False


def test_company_name_requires_word_boundaries():
    result = extract_broadened_signals("The team is evaluating vendors for its maintainable platform.", company="AI")
    assert result["matches"][0]["attribution"] == "unattributed"
    assert result["matches"][0]["promotion_eligible"] is False


def test_technical_context_requires_word_boundaries():
    result = extract_broadened_signals("We are evaluating vendors for our maintainable workflows.", company="Acme")
    assert result["matches"][0]["technical_context"] is False
    assert result["matches"][0]["promotion_eligible"] is False


def test_record_extraction_preserves_two_distinct_occurrences_in_one_field():
    from .commercial_signal_broadening import extract_broadened_signals_from_record
    result = extract_broadened_signals_from_record({
        "company": "Acme",
        "signal": "We are evaluating vendors for our AI platform. Later, we are evaluating vendors for our data platform.",
        "evidence": "Founder update.",
    })
    assert len(result["matches"]) == 2
    assert len({match["observation_key"] for match in result["matches"]}) == 2


def test_negated_indirect_signal_is_preserved_but_not_promoted():
    result = extract_broadened_signals("We are not looking for a partner for our software platform.", company="Acme")
    assert len(result["matches"]) == 1
    assert result["matches"][0]["negated"] is True
    assert result["matches"][0]["promotion_eligible"] is False
    assert "negated_signal_preserved_not_promoted" in result["safety_reasons"]


def test_unrelated_technical_sentence_does_not_supply_context_for_indirect_signal():
    result = extract_broadened_signals("We are evaluating vendors. Our company builds software.", company="Acme")
    assert len(result["matches"]) == 1
    assert result["matches"][0]["technical_context"] is False
    assert result["promotion_eligible"] is False


def test_technical_context_in_same_sentence_remains_eligible():
    result = extract_broadened_signals("We are evaluating vendors for our software platform. Our hiring plan is unchanged.", company="Acme")
    assert len(result["matches"]) == 1
    assert result["matches"][0]["technical_context"] is True
    assert result["promotion_eligible"] is True


def test_attribution_does_not_cross_unrelated_sentences():
    result = extract_broadened_signals("Acme builds software. Industry teams are evaluating vendors.", company="Acme")
    assert len(result["matches"]) == 1
    assert result["matches"][0]["attribution"] == "unattributed"
    assert result["matches"][0]["promotion_eligible"] is False


def test_structural_event_is_extracted_without_becoming_direct_intent():
    result = extract_broadened_signals("Acme raised Series A and launched a new product for its software platform.", company="Acme")
    assert result["promotion_eligible"] is False
    assert {item["category"] for item in result["matches"]} == {"funding_execution", "product_event"}
    assert "structural_event_requires_current_need_or_corroboration" in result["safety_reasons"]


def test_speculation_after_signal_blocks_promotion():
    result = extract_broadened_signals("We are evaluating vendors, but we could decide to build it ourselves.", company="We")
    match = result["matches"][0]
    assert match["certainty"] == "speculative"
    assert match["promotion_eligible"] is False


def test_negation_after_signal_blocks_promotion():
    result = extract_broadened_signals("We are evaluating vendors, but this is not something we need.", company="We")
    match = result["matches"][0]
    assert match["negated"] is True
    assert match["promotion_eligible"] is False


def test_safety_marker_in_prior_sentence_does_not_contaminate_signal():
    result = extract_broadened_signals("We might be evaluating vendors someday. We are evaluating vendors for our AI platform.", company="We")
    match = result["matches"][1]
    assert match["certainty"] == "exploratory"
    assert match["negated"] is False
    assert match["promotion_eligible"] is True


def test_record_extraction_does_not_borrow_technical_context_from_job_title():
    from .commercial_signal_broadening import extract_broadened_signals_from_record
    result = extract_broadened_signals_from_record({"company": "Acme", "signal": "Company update", "evidence": "We are exploring options.", "job_title": "Senior Software Engineer"})
    assert len(result["matches"]) == 1
    match = result["matches"][0]
    assert match["source_field"] == "evidence"
    assert match["technical_context"] is False
    assert match["promotion_eligible"] is False


def test_record_extraction_preserves_field_provenance_for_technical_signal():
    from .commercial_signal_broadening import extract_broadened_signals_from_record
    result = extract_broadened_signals_from_record({"company": "Acme", "signal": "We are evaluating vendors for our software platform.", "evidence": "Founder update.", "job_title": "Senior Software Engineer"})
    assert len(result["matches"]) == 1
    match = result["matches"][0]
    assert match["source_field"] == "signal"
    assert match["technical_context"] is True
    assert match["promotion_eligible"] is True


def test_collector_carries_broadened_signal_contract_without_replacing_existing_signal_type():
    lead = {"source": "linkedin_signal", "source_id": "broadening-001", "url": "https://example.com/posts/broadening-001", "company": "Acme", "signal": "Founder update", "evidence": "We are evaluating vendors for our AI platform.", "signal_type": "business_intent"}
    result = normalize_lead_input(lead)
    assert result["signal_type"] == "commercial_intent"
    assert result["signal_strength"] == "explicit"
    assert result["signal_matches"] == ["evaluating vendors"]
    assert result["commercial_signal_broadening"]["promotion_eligible"] is True
    assert result["commercial_signal_broadening"]["matches"][0]["phrase"].lower() == "evaluating vendors"


def test_collector_keeps_structural_signal_as_context_only():
    lead = {"source": "product-hunt", "source_id": "broadening-002", "url": "https://example.com/posts/broadening-002", "company": "Acme", "signal": "Company announcement", "evidence": "Acme launched a new product for its software platform.", "signal_type": "discovery"}
    result = normalize_lead_input(lead)
    assert result["signal_type"] == "discovery"
    assert result["commercial_signal_broadening"]["promotion_eligible"] is False
    assert result["commercial_signal_broadening"]["matches"][0]["category"] == "product_event"
