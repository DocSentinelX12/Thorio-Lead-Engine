"""Evidence-grounded revenue attribution by discovery source and collected signal."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping

from .opportunity_signal_intelligence import detect_compound_opportunities

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
    """Describe observed lifecycle associations for exact persisted signals.

    This function is descriptive only. It does not infer causation, rank signals,
    change qualification, change routing, or mutate lead state. Signal membership
    comes only from persisted exact ``signal_matches`` values.
    """
    leads = [lead for lead in db.all_leads() if isinstance(lead, Mapping)]
    overall = _finalize(_accumulate_metrics(leads))
    overall_conversion_rate = overall["conversion_rate"]
    by_signal: Dict[str, Dict[str, Any]] = {}
    for signal, metrics in _trigger_groups(leads).items():
        metrics = dict(metrics)
        metrics.update({
            "observations": metrics["opportunities"],
            "overall_conversion_rate": overall_conversion_rate,
            "conversion_rate_delta_vs_overall": metrics["conversion_rate"] - overall_conversion_rate,
            "association_only": True,
            "interpretation_note": (
                "Observed association only. The signal is not established as a "
                "cause of any lifecycle outcome."
            ),
        })
        by_signal[signal] = metrics
    return {
        "learning_version": SIGNAL_OUTCOME_LEARNING_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "association_note": (
            "Historical lifecycle outcomes are descriptive associations with "
            "persisted exact signals. They do not establish causation."
        ),
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
