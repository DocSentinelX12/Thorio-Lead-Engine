"""Evidence-grounded temporal signal intelligence.

This module measures observed commercial-signal recency, cadence, and acceleration
from durable lead records. It never infers urgency or causality from timing alone.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping
from urllib.parse import urlparse


TEMPORAL_INTELLIGENCE_VERSION = "1"
DEFAULT_WINDOW_SECONDS = 30 * 24 * 60 * 60


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize(value: Any) -> str:
    return " ".join(_text(value).lower().split())


def _parse(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _timestamp(lead: Mapping[str, Any]) -> datetime | None:
    for key in ("current_need_at", "last_inquiry_at", "inquiry_at", "intent_at", "need_at", "discovered_at"):
        parsed = _parse(lead.get(key))
        if parsed is not None:
            return parsed
    return None


def _company_key(lead: Mapping[str, Any]) -> str:
    raw_domain = _text(lead.get("company_website") or lead.get("domain"))
    if raw_domain:
        candidate = raw_domain if "://" in raw_domain else f"https://{raw_domain}"
        parsed = urlparse(candidate)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if hostname.startswith("www."):
            hostname = hostname[4:]
        if hostname:
            return f"domain:{hostname}"
    company = _normalize(lead.get("company"))
    return f"company:{company}" if company else ""


def _triggers(lead: Mapping[str, Any]) -> set[str]:
    raw = lead.get("signal_matches")
    if not isinstance(raw, list):
        return set()
    return {_normalize(item) for item in raw if _normalize(item)}


def analyze_temporal_signals(
    leads: Iterable[Mapping[str, Any]],
    *,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    now: datetime | None = None,
) -> Dict[str, Any]:
    """Measure observed temporal patterns without converting timing into intent."""
    if not isinstance(window_seconds, int) or isinstance(window_seconds, bool) or window_seconds < 0:
        raise ValueError("window_seconds must be a non-negative integer.")
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    grouped: dict[str, list[tuple[datetime, Mapping[str, Any]]]] = defaultdict(list)
    for lead in leads:
        if not isinstance(lead, Mapping):
            continue
        timestamp = _timestamp(lead)
        key = _company_key(lead)
        if (
            timestamp is not None
            and key
            and timestamp <= reference
            and (reference - timestamp).total_seconds() <= window_seconds
        ):
            grouped[key].append((timestamp, lead))

    profiles: list[Dict[str, Any]] = []
    for company_key, observations in sorted(grouped.items()):
        observations.sort(key=lambda item: item[0])
        unique_sources = sorted({_text(item.get("source")) for _, item in observations if _text(item.get("source"))})
        opportunity_ids = sorted({_text(item.get("opportunity_id") or item.get("fingerprint")) for _, item in observations if _text(item.get("opportunity_id") or item.get("fingerprint"))})
        triggers = sorted({trigger for _, item in observations for trigger in _triggers(item)})
        gaps = [
            (observations[index][0] - observations[index - 1][0]).total_seconds()
            for index in range(1, len(observations))
        ]
        median_gap = sorted(gaps)[len(gaps) // 2] if gaps else None
        recent_count = sum(1 for timestamp, _ in observations if (reference - timestamp).total_seconds() <= 7 * 24 * 60 * 60)
        older_count = len(observations) - recent_count
        cadence_acceleration = (
            recent_count > older_count
            if len(observations) >= 3 and older_count > 0
            else False
        )

        profiles.append({
            "company_key": company_key,
            "observation_count": len(observations),
            "unique_opportunity_count": len(opportunity_ids),
            "unique_source_count": len(unique_sources),
            "unique_trigger_count": len(triggers),
            "sources": unique_sources,
            "commercial_triggers": triggers,
            "first_observed_at": observations[0][0].isoformat(),
            "last_observed_at": observations[-1][0].isoformat(),
            "days_since_last_observation": (reference - observations[-1][0]).total_seconds() / 86400,
            "median_observation_gap_seconds": median_gap,
            "recent_7d_observations": recent_count,
            "prior_window_observations": older_count,
            "observed_cadence_acceleration": cadence_acceleration,
            "opportunity_ids": opportunity_ids,
        })

    return {
        "temporal_intelligence_version": TEMPORAL_INTELLIGENCE_VERSION,
        "window_seconds": window_seconds,
        "generated_at": reference.isoformat(),
        "profiles": profiles,
        "interpretation_note": (
            "Temporal measures describe observed collection timing only. They "
            "do not establish urgency, buying intent, causality, or future behavior."
        ),
    }


def temporal_signal_intelligence(db: Any, *, window_seconds: int = DEFAULT_WINDOW_SECONDS, now: datetime | None = None) -> Dict[str, Any]:
    return analyze_temporal_signals(db.all_leads(), window_seconds=window_seconds, now=now)
