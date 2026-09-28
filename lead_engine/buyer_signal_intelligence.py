"""Evidence-grounded buyer signal classification for the sales closer.

This module classifies what the buyer actually communicated. It does not infer
budget, authority, urgency, sentiment, or purchase intent from job title,
politeness, or generic positive language.
"""
from __future__ import annotations

from typing import Any, Mapping


def _text(value: Any) -> str:
    return str(value or "").strip()


def _event_ref(event: Mapping[str, Any], index: int) -> str:
    return _text(
        event.get("evidence_ref")
        or event.get("source_id")
        or event.get("source_url")
        or event.get("event_id")
    ) or f"conversation_event:{index}"


def _latest_event(lead: Mapping[str, Any]) -> tuple[Mapping[str, Any], int | None]:
    events = lead.get("conversation_events")
    if not isinstance(events, list):
        return {}, None
    for index in range(len(events) - 1, -1, -1):
        if isinstance(events[index], Mapping):
            return events[index], index
    return {}, None


def _explicit_field(event: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = _text(event.get(key))
        if value:
            return value
    return ""


def classify_buyer_signal(lead: Mapping[str, Any]) -> dict[str, Any]:
    """Classify the strongest signal in the latest buyer event with provenance."""
    event, index = _latest_event(lead)
    raw_text = _text(event.get("text"))
    text = raw_text.lower()
    ref = _event_ref(event, index if index is not None else 0)
    outcome = _text(event.get("outcome")).lower()

    explicit_commitment_phrases = (
        "ready to sign", "ready for signature", "send the contract", "send the agreement",
        "let's move forward", "lets move forward", "move forward with this", "approve this",
        "approved to proceed", "start the engagement", "start the project", "book the kickoff",
    )
    evaluation_phrases = (
        "send a proposal", "send the proposal", "send a quote", "send pricing", "review the proposal",
        "compare options", "compare providers", "comparing options", "comparing providers", "evaluate this", "evaluate the fit",
        "compare options", "compare providers", "evaluate this", "evaluate the fit",
        "legal review", "security review", "reviewing proposals", "reviewing the proposal", "who needs to approve", "approval process",
        "legal review", "security review", "who needs to approve", "approval process",
    )
    interest_phrases = (
        "interested", "tell me more", "let's talk", "lets talk", "happy to talk",
        "open to a conversation", "schedule a call", "book a call", "worth discussing",
    )
    objection = outcome == "objection" or any(
        phrase in text
        for phrase in (
            "not interested", "too expensive", "already have", "in-house", "not now", "maybe later",
            "need to think", "concern", "worried about", "can't justify", "cannot justify",
        )
    )
    commitment_type = _explicit_field(event, "commitment_type", "commercial_commitment", "next_step_commitment")
    authority_signal = _explicit_field(event, "authority", "decision_authority", "approval_authority", "decision_role")
    budget_signal = _explicit_field(event, "budget", "budget_signal", "commercial_constraint")
    timing_signal = _explicit_field(event, "timing", "timeline", "start_date", "decision_date")
    desired_outcome = _explicit_field(event, "desired_outcome", "success_metric", "priority")

    if any(phrase in text for phrase in explicit_commitment_phrases) or commitment_type:
        category, confidence, next_action, next_question, evidence_basis = (
            "explicit_commitment", "high", "confirm_commitment_details",
            "What specific next step should we put in motion, and who needs to be involved to complete it?",
            "explicit commercial action or commitment",
        )
    elif any(phrase in text for phrase in evaluation_phrases):
        category, confidence, next_action, next_question, evidence_basis = (
            "active_evaluation", "high", "map_evaluation_process",
            "What criteria, people, and approval steps will determine whether you move forward?",
            "explicit evaluation activity",
        )
    elif objection:
        category, confidence, next_action, next_question, evidence_basis = (
            "objection", "high", "diagnose_objection_before_persuading",
            "What specifically would need to change or be clarified for you to consider moving forward?",
            "explicit concern or objection",
        )
    elif any(phrase in text for phrase in interest_phrases):
        category, confidence, next_action, next_question, evidence_basis = (
            "interest", "medium", "clarify_business_outcome",
            "What outcome would make a next conversation worthwhile for you?",
            "explicit interest without purchase commitment",
        )
    elif desired_outcome or budget_signal or timing_signal or authority_signal:
        category, confidence, next_action, next_question, evidence_basis = (
            "commercial_engagement", "medium", "complete_missing_qualification",
            "Which of the remaining decision factors is most important to clarify next?",
            "buyer supplied a concrete commercial context signal",
        )
    elif raw_text:
        category, confidence, next_action, next_question, evidence_basis = (
            "general_engagement", "low", "discover_business_outcome",
            "What outcome matters most to your team here?",
            "buyer replied, but no stronger commercial signal was stated",
        )
    else:
        category, confidence, next_action, next_question, evidence_basis = (
            "no_signal", "none", "discover_active_need",
            "Is this need still active, and what outcome would make solving it worthwhile?",
            "no buyer-stated signal available",
        )

    commitment_level = {"explicit_commitment": "explicit", "active_evaluation": "evaluation", "interest": "interest"}.get(category, "none_or_unestablished")
    return {
        "category": category,
        "confidence": confidence,
        "commitment_level": commitment_level,
        "commitment_type": commitment_type,
        "authority_signal": authority_signal,
        "budget_signal": budget_signal,
        "timing_signal": timing_signal,
        "desired_outcome_signal": desired_outcome,
        "evidence_text": raw_text,
        "evidence_ref": ref if raw_text or event else "",
        "event_index": index,
        "evidence_basis": evidence_basis,
        "next_best_action": next_action,
        "next_best_question": next_question,
        "do_not_overstate": category != "explicit_commitment",
        "unsupported_inferences_blocked": [
            "budget existence or amount unless buyer explicitly supplied it",
            "decision authority unless buyer explicitly supplied it",
            "urgency unless buyer explicitly supplied a timing condition",
            "purchase intent from politeness or generic positive language",
            "sentiment or motivation that the buyer did not state",
        ],
    }


def enrich_commercial_strategy(strategy: Mapping[str, Any], lead: Mapping[str, Any]) -> dict[str, Any]:
    """Apply buyer-signal intelligence without destroying more specific conversation context."""
    signal = classify_buyer_signal(lead)
    existing = strategy.get("conversation_intelligence")
    existing_ci = dict(existing) if isinstance(existing, Mapping) else {}
    category = signal["category"]

    if category in {"explicit_commitment", "active_evaluation", "interest", "commercial_engagement", "general_engagement", "no_signal"}:
        protected_actions = {
            "map_decision_process",
            "diagnose_capacity_gap",
            "establish_value_and_fit_before_price",
            "provide_verified_proof_or_offer_discovery",
            "answer_and_advance",
            "clarify_timing",
        }
        existing_action = _text(existing_ci.get("next_best_action"))
        preserve_specific_context = existing_action in protected_actions and _text(existing_ci.get("action_basis")) in {
            "observed_conversation_context",
            "buyer_intent_progression",
            "buyer_confirmed_underlying_concern",
            "concern_state_evolution",
        }
        if not preserve_specific_context:
            existing_ci.update(
                {
                    "next_best_action": signal["next_best_action"],
                    "next_best_question": signal["next_best_question"],
                    "action_basis": "buyer_signal_intelligence",
                }
            )
        existing_ci.update({"buyer_signal_category": category, "buyer_signal_confidence": signal["confidence"]})
    elif category == "objection" and not _text(existing_ci.get("action_basis")):
        existing_ci["action_basis"] = "observed_conversation_context"

    return {**dict(strategy), "buying_signal_intelligence": signal, "conversation_intelligence": existing_ci}
