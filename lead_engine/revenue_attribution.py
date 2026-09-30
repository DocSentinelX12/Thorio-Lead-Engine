"""Evidence-grounded revenue attribution by discovery source and collected signal."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping

from .opportunity_signal_intelligence import detect_compound_opportunities
from .signal_outcome_feedback import build_signal_outcome_feedback
from .unified_opportunity_signal_graph import build_unified_opportunity_signal_graph

ATTRIBUTION_VERSION = "2"
SIGNAL_OUTCOME_LEARNING_VERSION = "1"

_COUNTERS = (
    "opportunities",
    "researched",
    "qualified",
    "sales_eligible",
    "outreach_sent",
    "responses_received",
    "conversations",
    "converted",
    "referred",
    "closed_lost",
    "disqualified",
)


def _bucket(value: Any) -> str:
    text = str(value or "").strip()
    return text if text else "unknown"


def _new_metrics() -> Dict[str, Any]:
    return {key: 0 for key in _COUNTERS} | {
        "qualification_rate": 0.0,
        "sales_eligibility_rate": 0.0,
        "response_rate": 0.0,
        "conversion_rate": 0.0,
    }


def _finalize(metrics: Dict[str, Any]) -> Dict[str, Any]:
    opportunities = int(metrics["opportunities"])
    if opportunities:
        metrics["qualification_rate"] = metrics["qualified"] / opportunities
        metrics["sales_eligibility_rate"] = metrics["sales_eligible"] / opportunities
        metrics["response_rate"] = metrics["responses_received"] / opportunities
        metrics["conversion_rate"] = metrics["converted"] / opportunities
    return metrics


def _has_outreach(lead: Mapping[str, Any]) -> bool:
    if str(lead.get("last_outreach_action_id") or "").strip():
        return True
    history = lead.get("outreach_history")
    return isinstance(history, list) and any(isinstance(item, Mapping) for item in history)


def _metric_flags(lead: Mapping[str, Any]) -> Dict[str, bool]:
    lifecycle = str(lead.get("revenue_lifecycle_state") or "").strip().lower()
    return {
        "researched": str(lead.get("research_status") or "").strip().lower() in {"complete", "research_complete"},
        "qualified": lead.get("qualified") is True,
        "sales_eligible": str(lead.get("sales_eligibility") or "").strip().lower() == "eligible",
        "outreach_sent": _has_outreach(lead),
        "responses_received": int(lead.get("response_count", 0) or 0) > 0,
        "conversations": bool(str(lead.get("conversation_id") or "").strip()) or lifecycle == "conversation_active",
        "converted": lifecycle == "converted" or str(lead.get("outreach_state") or "").strip().lower() == "converted",
        "referred": lifecycle == "referred",
        "closed_lost": lifecycle == "closed_lost",
        "disqualified": lifecycle == "disqualified",
    }


def _accumulate(metrics: Dict[str, Any], lead: Mapping[str, Any]) -> None:
    metrics["opportunities"] += 1
    for key, enabled in _metric_flags(lead).items():
        if enabled:
            metrics[key] += 1


def _group_by(leads: Iterable[Mapping[str, Any]], value_getter) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    for lead in leads:
        key = _bucket(value_getter(lead))
        metrics = groups.setdefault(key, _new_metrics())
        _accumulate(metrics, lead)
    return {key: _finalize(metrics) for key, metrics in sorted(groups.items())}


def _trigger_groups(leads: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    for lead in leads:
        matches = lead.get("signal_matches")
        if not isinstance(matches, list):
            continue
        seen = set()
        for raw in matches:
            trigger = str(raw or "").strip().lower()
            if not trigger or trigger in seen:
                continue
            seen.add(trigger)
            metrics = groups.setdefault(trigger, _new_metrics())
            _accumulate(metrics, lead)
    return {key: _finalize(metrics) for key, metrics in sorted(groups.items())}


def learn_signal_outcomes(db: Any) -> Dict[str, Any]:
    """Describe observed signal and lifecycle associations from the authoritative graph.

    This remains descriptive only. It does not infer causation, rank signals,
    change qualification, change routing, or mutate lead state.
    """
    leads = [lead for lead in db.all_leads() if isinstance(lead, Mapping)]
    graph = build_unified_opportunity_signal_graph(leads)
    feedback = build_signal_outcome_feedback(graph)
    overall = _finalize(_accumulate_metrics(leads))
    overall_opportunities = int(overall["opportunities"])
    overall_converted = int(overall["converted"])
    overall_conversion_rate = overall_converted / overall_opportunities if overall_opportunities else 0.0

    nodes = graph.get("nodes", {})
    edges = graph.get("edges", [])
    opportunity_by_observation: Dict[str, set[str]] = {}
    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        if edge.get("type") != "opportunity_has_signal_observation":
            continue
        opportunity_node = nodes.get(edge.get("from"))
        observation_id = str(edge.get("to") or "")
        if isinstance(opportunity_node, Mapping) and observation_id:
            opportunity_by_observation.setdefault(observation_id, set()).add(str(opportunity_node.get("opportunity_id") or ""))

    opportunity_ids_by_signal: Dict[str, set[str]] = {}
    for edge in edges:
        if not isinstance(edge, Mapping) or edge.get("type") != "observation_instantiates_signal":
            continue
        observation_id = str(edge.get("from") or "")
        signal_node = nodes.get(edge.get("to"))
        if not isinstance(signal_node, Mapping):
            continue
        signal_key = str(signal_node.get("signal_key") or "")
        if not signal_key:
            continue
        opportunity_ids_by_signal.setdefault(signal_key, set()).update(opportunity_by_observation.get(observation_id, set()))

    leads_by_opportunity = {
        str(lead.get("opportunity_id") or lead.get("fingerprint") or ""): lead
        for lead in leads
        if str(lead.get("opportunity_id") or lead.get("fingerprint") or "")
    }

    by_signal: Dict[str, Dict[str, Any]] = {}
    signal_keys = set(opportunity_ids_by_signal) | set((feedback.get("by_signal") or {}).keys())
    for signal_key in sorted(signal_keys):
        opportunity_ids = opportunity_ids_by_signal.get(signal_key, set())
        signal_leads = [
            lead for opportunity_id, lead in leads_by_opportunity.items()
            if opportunity_id in opportunity_ids
        ]
        metrics = _finalize(_accumulate_metrics(signal_leads))
        signal_feedback = (feedback.get("by_signal") or {}).get(signal_key)
        outcomes = signal_feedback.get("outcomes", {}) if isinstance(signal_feedback, Mapping) else {}
        signal_converted = int(metrics["converted"])
        signal_opportunities = int(metrics["opportunities"])
        delta = (
            (signal_converted * overall_opportunities - overall_converted * signal_opportunities)
            / (signal_opportunities * overall_opportunities)
            if signal_opportunities and overall_opportunities
            else 0.0
        )
        metrics.update({
            "observations": int(signal_feedback.get("observations", 0) or 0) if isinstance(signal_feedback, Mapping) else 0,
            "overall_conversion_rate": overall_conversion_rate,
            "conversion_rate_delta_vs_overall": delta,
            "outcomes": dict(outcomes),
            "association_only": True,
            "interpretation_note": "Observed association only. The signal is not established as a cause of any lifecycle outcome.",
            "research_priority": int(signal_feedback.get("research_priority", 0) or 0) if isinstance(signal_feedback, Mapping) else 0,
            "collection_priority": int(signal_feedback.get("collection_priority", 0) or 0) if isinstance(signal_feedback, Mapping) else 0,
        })
        public_signal = signal_key.split("|", 2)[-1] if signal_key.startswith("configured|") else signal_key
        by_signal[public_signal] = metrics

    return {
        "learning_version": SIGNAL_OUTCOME_LEARNING_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "association_note": "Historical lifecycle outcomes are descriptive associations with persisted exact signals. They do not establish causation.",
        "feedback_loop": feedback,
        "unified_graph": graph,
        "overall": overall,
        "by_signal": by_signal,
    }

def _accumulate_metrics(leads: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    metrics = _new_metrics()
    for lead in leads:
        _accumulate(metrics, lead)
    return metrics


def revenue_attribution(db: Any) -> Dict[str, Any]:
    """Return observed revenue attribution and analytical compound clusters."""
    leads = [lead for lead in db.all_leads() if isinstance(lead, Mapping)]
    compound = detect_compound_opportunities(leads)
    return {
        "attribution_version": ATTRIBUTION_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "attribution_note": (
            "Counts are observed lifecycle outcomes grouped by existing lead "
            "provenance. They do not establish causal effect."
        ),
        "multi_touch_trigger_note": (
            "Commercial trigger groups are multi-attributed. One opportunity "
            "with multiple exact signal_matches contributes to each matching trigger."
        ),
        "compound_opportunity_note": (
            "Compound clusters are analytical corroboration only. They do not "
            "merge opportunities or establish that one signal caused another."
        ),
        "total_opportunities": len(leads),
        "by_source": _group_by(leads, lambda lead: lead.get("source")),
        "by_signal_type": _group_by(leads, lambda lead: lead.get("signal_type")),
        "by_commercial_trigger": _trigger_groups(leads),
        "compound_opportunities": compound,
    }
