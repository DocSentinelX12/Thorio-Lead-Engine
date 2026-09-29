"""Evidence-grounded compound opportunity detection.

This layer correlates already-persisted observations without changing canonical
opportunity identity or declaring separate opportunities duplicates.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping


WINDOW_SECONDS = 30 * 24 * 60 * 60
INTELLIGENCE_VERSION = "1"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize(value: Any) -> str:
    return " ".join(_text(value).lower().split())


def _timestamp(lead: Mapping[str, Any]) -> float | None:
    raw = _text(lead.get("discovered_at") or lead.get("observed_at"))
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _entity_key(lead: Mapping[str, Any]) -> str:
    domain = _normalize(lead.get("company_website") or lead.get("domain") or "")
    if domain:
        return f"domain:{domain.removeprefix('https://').removeprefix('http://').rstrip('/')}"
    company = _normalize(lead.get("company"))
    return f"company:{company}" if company else ""


def _triggers(lead: Mapping[str, Any]) -> list[str]:
    values = lead.get("signal_matches")
    triggers = {
        _normalize(value)
        for value in values
        if isinstance(values, list) and _normalize(value)
    }
    broadening = lead.get("commercial_signal_broadening")
    matches = broadening.get("matches") if isinstance(broadening, Mapping) else []
    if isinstance(matches, list):
        structural_categories = {
            "funding_execution",
            "product_event",
            "enterprise_event",
            "market_expansion",
            "corporate_event",
        }
        for item in matches:
            if not isinstance(item, Mapping):
                continue
            category = _normalize(item.get("category") or item.get("signal_id"))
            if category in structural_categories:
                continue
            attribution = _normalize(item.get("attribution"))
            temporal = _normalize(item.get("temporal_status"))
            certainty = _normalize(item.get("certainty"))
            if attribution not in {"company_named", "first_person"}:
                continue
            if temporal != "current_or_unspecified":
                continue
            if certainty == "speculative" or item.get("negated") is True:
                continue
            phrase = _normalize(item.get("phrase"))
            if phrase:
                triggers.add(phrase)
    return sorted(triggers)


def _is_hiring_observation(lead: Mapping[str, Any]) -> bool:
    """Recognize an existing hiring observation without turning hiring into intent."""
    signal_type = _normalize(lead.get("signal_type"))
    if signal_type == "hiring":
        return bool(_normalize(lead.get("job_title") or lead.get("signal") or lead.get("evidence")))
    return False


def _structural_events(lead: Mapping[str, Any]) -> list[Dict[str, Any]]:
    """Return safe structural events with their category and observation time."""
    broadening = lead.get("commercial_signal_broadening")
    matches = broadening.get("matches") if isinstance(broadening, Mapping) else []
    if not isinstance(matches, list):
        return []

    observed_at = _text(lead.get("discovered_at") or lead.get("observed_at"))
    events: list[Dict[str, Any]] = []
    for item in matches:
        if not isinstance(item, Mapping):
            continue
        category = _normalize(item.get("category") or item.get("signal_id"))
        if category not in {
            "funding_execution",
            "product_event",
            "enterprise_event",
            "market_expansion",
            "corporate_event",
        }:
            continue
        if _normalize(item.get("temporal_status")) != "current_or_unspecified":
            continue
        if _normalize(item.get("certainty")) == "speculative" or item.get("negated") is True:
            continue
        phrase = _normalize(item.get("phrase"))
        if not phrase:
            continue
        events.append({
            "category": category,
            "phrase": phrase,
            "observed_at": observed_at,
            "opportunity_id": _text(lead.get("opportunity_id") or lead.get("fingerprint")),
            "source": _text(lead.get("source")),
            "evidence_context": _text(item.get("evidence_context")),
            "attribution": _text(item.get("attribution")),
            "temporal_status": _text(item.get("temporal_status")),
            "certainty": _text(item.get("certainty")),
            "negated": item.get("negated") is True,
        })
    return events


def detect_compound_opportunities(
    leads: Iterable[Mapping[str, Any]],
    *,
    window_seconds: int = WINDOW_SECONDS,
) -> Dict[str, Any]:
    """Find corroborating multi-source signal clusters while preserving identities."""
    if not isinstance(window_seconds, int) or isinstance(window_seconds, bool) or window_seconds < 0:
        raise ValueError("window_seconds must be a non-negative integer.")

    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for lead in leads:
        if not isinstance(lead, Mapping):
            continue
        key = _entity_key(lead)
        timestamp = _timestamp(lead)
        if key and timestamp is not None:
            grouped[key].append(lead)

    clusters: list[Dict[str, Any]] = []
    for entity_key, candidates in sorted(grouped.items()):
        candidates = sorted(candidates, key=lambda item: _timestamp(item) or 0.0)
        for index, anchor in enumerate(candidates):
            anchor_time = _timestamp(anchor)
            if anchor_time is None:
                continue
            members = [anchor]
            for candidate in candidates[index + 1:]:
                candidate_time = _timestamp(candidate)
                if candidate_time is None:
                    continue
                if candidate_time - anchor_time > window_seconds:
                    break
                members.append(candidate)

            opportunity_ids = sorted({_text(item.get("opportunity_id") or item.get("fingerprint")) for item in members if _text(item.get("opportunity_id") or item.get("fingerprint"))})
            sources = sorted({_text(item.get("source")) for item in members if _text(item.get("source"))})
            triggers = sorted({trigger for item in members for trigger in _triggers(item)})
            hiring_sources = {
                _text(item.get("source"))
                for item in members
                if _is_hiring_observation(item) and _text(item.get("source"))
            }
            if len(hiring_sources) >= 2:
                triggers.append("repeated_hiring_activity")
                triggers = sorted(set(triggers))

            structural_events = [
                event
                for item in members
                for event in _structural_events(item)
            ]
            qualifying_non_structural_triggers = {
                trigger
                for trigger in triggers
                if trigger != "repeated_hiring_activity"
            }
            if qualifying_non_structural_triggers:
                triggers.extend(
                    event["phrase"]
                    for event in structural_events
                    if event["phrase"]
                )
                triggers = sorted(set(triggers))
            funding_events = [
                event for event in structural_events
                if event["category"] == "funding_execution"
            ]
            execution_events = [
                event for event in structural_events
                if event["category"] != "funding_execution"
            ]
            funding_followed_by_execution = []
            for funding in funding_events:
                for execution in execution_events:
                    funding_time = _timestamp({"discovered_at": funding["observed_at"]})
                    execution_time = _timestamp({"discovered_at": execution["observed_at"]})
                    if funding_time is None or execution_time is None:
                        continue
                    if 0 <= execution_time - funding_time <= window_seconds:
                        if funding["source"] and execution["source"] and funding["source"] != execution["source"]:
                            funding_followed_by_execution.append({
                                "relationship": "funding_followed_by_execution",
                                "funding": funding,
                                "execution": execution,
                            })
            if funding_followed_by_execution:
                triggers.append("funding_followed_by_execution")
                triggers = sorted(set(triggers))

            if len(opportunity_ids) < 2 or len(sources) < 2 or len(triggers) < 2:
                continue

            clusters.append({
                "entity_key": entity_key,
                "opportunity_ids": opportunity_ids,
                "sources": sources,
                "commercial_triggers": triggers,
                "opportunity_count": len(opportunity_ids),
                "source_count": len(sources),
                "trigger_count": len(triggers),
                "structural_relationships": funding_followed_by_execution,
                "first_observed_at": _text(min(
                    (item.get("discovered_at") or item.get("observed_at") for item in members),
                    key=lambda value: _timestamp({"discovered_at": value}) or float("inf"),
                )),
                "last_observed_at": _text(max(
                    (item.get("discovered_at") or item.get("observed_at") for item in members),
                    key=lambda value: _timestamp({"discovered_at": value}) or float("-inf"),
                )),
                "evidence": [
                    {
                        "opportunity_id": _text(item.get("opportunity_id") or item.get("fingerprint")),
                        "source": _text(item.get("source")),
                        "url": _text(item.get("url")),
                        "signal_matches": _triggers(item),
                        "commercial_signal_broadening_matches": [
                            dict(match)
                            for match in (
                                item.get("commercial_signal_broadening", {}).get("matches", [])
                                if isinstance(item.get("commercial_signal_broadening"), Mapping)
                                else []
                            )
                            if isinstance(match, Mapping)
                        ],
                        "discovered_at": _text(item.get("discovered_at") or item.get("observed_at")),
                    }
                    for item in members
                ],
            })

    # Keep the strongest corroboration for a given opportunity/source/trigger set.
    unique: dict[tuple, Dict[str, Any]] = {}
    for cluster in clusters:
        key = (
            cluster["entity_key"],
            tuple(cluster["opportunity_ids"]),
            tuple(cluster["sources"]),
            tuple(cluster["commercial_triggers"]),
        )
        unique[key] = cluster

    return {
        "intelligence_version": INTELLIGENCE_VERSION,
        "window_seconds": window_seconds,
        "cluster_count": len(unique),
        "clusters": list(unique.values()),
        "identity_note": (
            "Clusters are analytical relationships only. They never merge "
            "opportunity IDs, rewrite fingerprints, or declare duplicates."
        ),
    }


def detect_compound_opportunities_from_db(db: Any, *, window_seconds: int = WINDOW_SECONDS) -> Dict[str, Any]:
    return detect_compound_opportunities(db.all_leads(), window_seconds=window_seconds)
