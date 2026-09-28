from .buyer_signal_intelligence import classify_buyer_signal, enrich_commercial_strategy
from .test_outreach_engine import lead


def test_generic_positive_reply_is_not_purchase_commitment():
    value = lead(
        outreach_state="replied",
        conversation_events=[
            {"outcome": "replied", "text": "Sounds good, thanks for reaching out.", "evidence_ref": "evt-1"},
        ],
    )
    signal = classify_buyer_signal(value)
    assert signal["category"] == "general_engagement"
    assert signal["commitment_level"] == "none_or_unestablished"
    assert signal["confidence"] == "low"
    assert signal["do_not_overstate"] is True
    assert signal["evidence_ref"] == "evt-1"


def test_explicit_commitment_is_distinguished_from_interest():
    value = lead(
        outreach_state="interested",
        conversation_events=[
            {"outcome": "replied", "text": "We are ready to sign. Please send the contract.", "evidence_ref": "evt-commit"},
        ],
    )
    signal = classify_buyer_signal(value)
    assert signal["category"] == "explicit_commitment"
    assert signal["commitment_level"] == "explicit"
    assert signal["confidence"] == "high"
    assert signal["evidence_ref"] == "evt-commit"
    assert signal["next_best_action"] == "confirm_commitment_details"


def test_proposal_request_is_active_evaluation_not_commitment():
    value = lead(
        outreach_state="replied",
        conversation_events=[
            {"outcome": "replied", "text": "Send the proposal and we will review it with procurement.", "evidence_ref": "evt-eval"},
        ],
    )
    signal = classify_buyer_signal(value)
    assert signal["category"] == "active_evaluation"
    assert signal["commitment_level"] == "evaluation"
    assert signal["do_not_overstate"] is True
    assert signal["next_best_action"] == "map_evaluation_process"


def test_interest_requires_explicit_interest_language_not_state_alone():
    value = lead(
        outreach_state="interested",
        conversation_events=[
            {"outcome": "replied", "text": "I understand.", "evidence_ref": "evt-plain"},
        ],
    )
    signal = classify_buyer_signal(value)
    assert signal["category"] == "general_engagement"
    assert signal["commitment_level"] == "none_or_unestablished"


def test_structured_budget_authority_and_timing_are_preserved_without_inference():
    value = lead(
        outreach_state="replied",
        conversation_events=[
            {
                "outcome": "replied",
                "text": "We are assessing this for next quarter.",
                "budget": "$50k approved range",
                "authority": "I make the final approval",
                "timing": "Q4 2026",
                "evidence_ref": "evt-context",
            },
        ],
    )
    signal = classify_buyer_signal(value)
    assert signal["category"] == "commercial_engagement"
    assert signal["budget_signal"] == "$50k approved range"
    assert signal["authority_signal"] == "I make the final approval"
    assert signal["timing_signal"] == "Q4 2026"
    assert signal["commitment_level"] == "none_or_unestablished"


def test_objection_dominates_generic_interest_language():
    value = lead(
        outreach_state="objection",
        conversation_events=[
            {"outcome": "objection", "text": "Sounds good, but we already have an internal team.", "evidence_ref": "evt-objection"},
        ],
    )
    signal = classify_buyer_signal(value)
    assert signal["category"] == "objection"
    assert signal["confidence"] == "high"
    assert signal["next_best_action"] == "diagnose_objection_before_persuading"


def test_enrichment_replaces_next_best_action_only_for_non_objection_buyer_signals():
    value = lead(
        outreach_state="replied",
        conversation_events=[
            {"outcome": "replied", "text": "Please send the proposal so our procurement team can review it.", "evidence_ref": "evt-eval"},
        ],
    )
    base = {"conversation_intelligence": {"next_best_action": "old_action", "next_best_question": "old_question"}, "verified_facts": ["kept"]}
    enriched = enrich_commercial_strategy(base, value)
    assert enriched["verified_facts"] == ["kept"]
    assert enriched["buying_signal_intelligence"]["category"] == "active_evaluation"
    assert enriched["conversation_intelligence"]["next_best_action"] == "map_evaluation_process"
    assert enriched["conversation_intelligence"]["next_best_question"] == "What criteria, people, and approval steps will determine whether you move forward?"


def test_signal_evidence_never_comes_from_untrusted_lead_signal():
    value = lead(
        signal="UNTRUSTED TEXT CLAIMING THEY ARE READY TO BUY",
        conversation_events=[],
    )
    signal = classify_buyer_signal(value)
    assert signal["category"] == "no_signal"
    assert signal["evidence_text"] == ""
    assert signal["evidence_ref"] == ""


def test_polite_sounds_good_reply_remains_general_engagement():
    value = lead(
        outreach_state="replied",
        conversation_events=[
            {"outcome": "replied", "text": "Sounds good, thanks for reaching out.", "evidence_ref": "evt-polite"},
        ],
    )
    signal = classify_buyer_signal(value)
    assert signal["category"] == "general_engagement"
    assert signal["do_not_overstate"] is True


def test_active_evaluation_is_not_a_purchase_commitment_and_allows_overstatement_guard():
    value = lead(
        outreach_state="replied",
        conversation_events=[
            {"outcome": "replied", "text": "Send the proposal and we will review it with procurement.", "evidence_ref": "evt-eval-guard"},
        ],
    )
    signal = classify_buyer_signal(value)
    assert signal["category"] == "active_evaluation"
    assert signal["commitment_level"] == "evaluation"
    assert signal["do_not_overstate"] is True
