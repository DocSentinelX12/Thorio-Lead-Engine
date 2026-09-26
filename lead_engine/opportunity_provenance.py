from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping

from .lead_identity import normalize_identity_value, validate_opportunity_identity


OBSERVED_STATUS = "observed_evidence"
VERIFIED_STATUSES = {"verified", "research_verified", "complete"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def canonical_evidence_key(event: Mapping[str, Any]) -> str:
    """Return the deterministic key for one distinct evidence observation."""
    values = (
        normalize_identity_value(event.get("url") or event.get("source_url") or event.get("evidence_url")),
        normalize_identity_value(event.get("source") or event.get("source_lane")),
        normalize_identity_value(event.get("source_id") or event.get("source_record_id")),
        normalize_identity_value(event.get("evidence") or event.get("signal")),
        normalize_identity_value(event.get("observed_at") or event.get("collected_at")),
        normalize_identity_value(event.get("research_section")),
        normalize_identity_value(event.get("route")),
    )
    raw = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_provenance_scope(
    event: Mapping[str, Any],
    *,
    opportunity_id: str,
    route: str | None = None,
) -> None:
    if not isinstance(event, Mapping):
        raise ValueError("Evidence provenance must be an object.")
    expected = _text(opportunity_id)
    if not expected:
        raise ValueError("Evidence provenance requires an opportunity_id.")
    event_opportunity = _text(event.get("opportunity_id") or event.get("fingerprint"))
    event_fingerprint = _text(event.get("fingerprint") or event.get("opportunity_id"))
    if event_opportunity and event_opportunity != expected:
        raise ValueError("Evidence provenance opportunity does not match containing opportunity.")
    if event_fingerprint and event_fingerprint != expected:
        raise ValueError("Evidence provenance fingerprint does not match containing opportunity.")
    supplied_route = _text(event.get("route"))
    expected_route = _text(route)
    if expected_route and supplied_route and supplied_route != expected_route:
        raise ValueError("Evidence provenance route does not match containing route.")
    if supplied_route and not expected_route and _text(event.get("research_section")) != "route_research":
        raise ValueError("Route-specific evidence must remain in route_research.")


def normalize_evidence_event(
    event: Mapping[str, Any],
    *,
    opportunity_id: str,
    research_section: str,
    route: str | None = None,
    collector: str | None = None,
) -> Dict[str, Any]:
    if not isinstance(event, Mapping):
        raise ValueError("Evidence provenance must be an object.")
    expected = _text(opportunity_id)
    section = _text(research_section)
    if not expected:
        raise ValueError("Evidence provenance requires an opportunity_id.")
    if not section:
        raise ValueError("Evidence provenance requires a research_section.")

    candidate = dict(event)
    validate_provenance_scope(candidate, opportunity_id=expected, route=route)
    candidate["opportunity_id"] = _text(candidate.get("opportunity_id")) or expected
    candidate["fingerprint"] = _text(candidate.get("fingerprint")) or expected
    candidate["research_section"] = section
    if route is not None:
        expected_route = _text(route)
        if not expected_route:
            raise ValueError("Route provenance cannot be empty.")
        candidate["route"] = _text(candidate.get("route")) or expected_route
    elif _text(candidate.get("route")) and section != "route_research":
        raise ValueError("Route-specific evidence must remain in route_research.")

    if collector is not None and _text(collector):
        candidate["collector_agent"] = _text(collector)

    status = _text(candidate.get("verification_status")).lower()
    if not status or status not in VERIFIED_STATUSES:
        candidate["verification_status"] = OBSERVED_STATUS
    elif status in VERIFIED_STATUSES and candidate.get("verified") is not True:
        candidate["verification_status"] = status

    validate_provenance_scope(candidate, opportunity_id=expected, route=route)
    candidate["canonical_evidence_key"] = canonical_evidence_key(candidate)
    return candidate


def validate_provenance_collection(
    events: Any,
    *,
    opportunity_id: str,
    research_section: str,
    route: str | None = None,
) -> list[Dict[str, Any]]:
    if not isinstance(events, list):
        return []
    normalized: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        item = normalize_evidence_event(
            event,
            opportunity_id=opportunity_id,
            research_section=research_section,
            route=route,
        )
        key = item["canonical_evidence_key"]
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)
    return normalized
