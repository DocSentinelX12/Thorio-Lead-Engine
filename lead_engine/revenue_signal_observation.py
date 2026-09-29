"""Canonical observation contract for revenue signal intelligence.

This layer only assembles already observed collection and evidence fields into
one auditable contract. It does not score, route, qualify, research, or select
closer behavior.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .opportunity_provenance import canonical_evidence_key

OBSERVATION_CONTRACT_VERSION = "1"
_OBSERVED_AT_FIELDS = (
    "observed_at",
    "collected_at",
    "intent_at",
    "current_need_at",
    "last_inquiry_at",
    "inquiry_at",
    "discovered_at",
)
_ROUTE_FIELDS = ("eligible_routes", "potential_routes")
_PERSON_FIELDS = (
    ("name", "contact_name"),
    ("title", "contact_title"),
    ("email", "contact_email"),
    ("linkedin_url", "linkedin_url"),
)
_SUPPORTING_FIELDS = (
    "supporting_evidence_refs",
    "supporting_evidence_keys",
    "supporting_refs",
)
_CONTRADICTORY_FIELDS = (
    "contradictory_evidence_refs",
    "contradictory_evidence_keys",
    "contradictory_refs",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(mapping: Mapping[str, Any], fields: Iterable[str]) -> str:
    for field in fields:
        value = _text(mapping.get(field))
        if value:
            return value
    return ""


def _list_of_text(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return list(dict.fromkeys(_text(item) for item in value if _text(item)))


def _first_list(mapping: Mapping[str, Any], fields: Iterable[str]) -> list[str]:
    for field in fields:
        values = _list_of_text(mapping.get(field))
        if values:
            return values
    return []


def _person(lead: Mapping[str, Any]) -> dict[str, str]:
    person: dict[str, str] = {}
    for output, field in _PERSON_FIELDS:
        value = _first_text(lead, (field,))
        if value:
            person[output] = value
    return person


def _research_routes(lead: Mapping[str, Any]) -> list[str]:
    section = lead.get("route_research")
    if not isinstance(section, Mapping):
        return []
    routes = section.get("routes")
    if not isinstance(routes, Mapping):
        return []
    return sorted(_text(route) for route in routes if _text(route))


def _research_gaps(lead: Mapping[str, Any]) -> dict[str, Any]:
    value = lead.get("research_gaps")
    return dict(value) if isinstance(value, Mapping) else {}


def _observation_evidence(lead: Mapping[str, Any]) -> dict[str, Any]:
    evidence = _text(lead.get("evidence"))
    signal = _text(lead.get("signal"))
    source_url = _text(lead.get("source_url"))
    return {
        "text": evidence,
        "signal_text": signal,
        "url": source_url,
    }


def build_revenue_signal_observation(lead: Mapping[str, Any]) -> dict[str, Any]:
    """Build one canonical revenue signal observation without adding inference."""
    if not isinstance(lead, Mapping):
        raise ValueError("lead must be a mapping.")

    opportunity_id = _text(lead.get("opportunity_id") or lead.get("fingerprint"))
    if not opportunity_id:
        raise ValueError("revenue signal observation requires opportunity_id.")

    fingerprint = _text(lead.get("fingerprint")) or opportunity_id
    if fingerprint != opportunity_id:
        raise ValueError("opportunity_id and fingerprint must match.")

    evidence = _observation_evidence(lead)
    provenance_event = {
        "opportunity_id": opportunity_id,
        "fingerprint": fingerprint,
        "url": _text(lead.get("url") or lead.get("source_url")),
        "source": _text(lead.get("source")),
        "source_id": _text(lead.get("source_id")),
        "evidence": evidence["text"] or evidence["signal_text"],
        "observed_at": _first_text(lead, _OBSERVED_AT_FIELDS),
    }

    return {
        "observation_contract_version": OBSERVATION_CONTRACT_VERSION,
        "opportunity_id": opportunity_id,
        "fingerprint": fingerprint,
        "observed_at": provenance_event["observed_at"],
        "source": _text(lead.get("source")),
        "source_id": _text(lead.get("source_id")),
        "source_url": _text(lead.get("source_url") or lead.get("url")),
        "company": {"name": _text(lead.get("company"))},
        "person": _person(lead),
        "signal": {
            "type": _text(lead.get("signal_type")) or "unknown",
            "strength": _text(lead.get("signal_strength")) or "unknown",
            "text": evidence["signal_text"],
            "matches": _list_of_text(lead.get("signal_matches")),
            "context": _list_of_text(lead.get("signal_context")),
        },
        "evidence": evidence,
        "provenance": {
            "source": provenance_event["source"],
            "source_id": provenance_event["source_id"],
            "source_url": provenance_event["url"],
            "observed_at": provenance_event["observed_at"],
            "canonical_evidence_key": canonical_evidence_key(provenance_event),
            "verification_status": _text(lead.get("verification_status")) or "observed_evidence",
        },
        "route_relevance": {
            "eligible_routes": _first_list(lead, _ROUTE_FIELDS),
            "researched_routes": _research_routes(lead),
        },
        "supporting_evidence_refs": _first_list(lead, _SUPPORTING_FIELDS),
        "contradictory_evidence_refs": _first_list(lead, _CONTRADICTORY_FIELDS),
        "research_gaps": _research_gaps(lead),
    }


def build_revenue_signal_observations(
    leads: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(leads, (str, bytes, Mapping)):
        raise ValueError("leads must be an iterable of lead mappings.")
    return [
        build_revenue_signal_observation(lead)
        for lead in leads
        if isinstance(lead, Mapping)
    ]
