"""Deterministic routing from collected source evidence to specialist agents."""

from __future__ import annotations

from typing import Any, Mapping


_SOURCE_ALIASES = {
    "x_signal": ("x", "twitter", "x.com", "twitter.com"),
    "threads_signal": ("threads", "threads.net"),
    "reddit_signal": ("reddit", "reddit.com"),
    "linkedin_signal": ("linkedin", "linkedin.com"),
    "facebook_signal": ("facebook", "facebook.com", "fb.com"),
    "instagram_signal": ("instagram", "instagram.com"),
    "hacker_news_signal": ("hacker news", "hacker_news", "news.ycombinator.com", "hn.algolia.com"),
    "indie_hackers_signal": ("indie hackers", "indie_hackers", "indiehackers", "indiehackers.com"),
    "product_hunt_signal": ("product hunt", "product_hunt", "producthunt", "producthunt.com"),
}

_JOB_MARKERS = (
    "job", "jobs", "career", "careers", "hiring", "greenhouse", "lever",
    "workable", "ashby", "remote ok", "remotejobs", "jobicy", "himalayas",
    "arbeitnow", "muse", "job board", "job-board", "vacancy", "opening",
)


def discovery_agent_for(record: Mapping[str, Any]) -> str:
    """Return the permanent discovery specialist for one collected record.

    Source metadata is authoritative when ``discovery_agent`` is supplied.
    Otherwise the source/provider/URL is matched against the known specialist
    lanes. Unknown sources are rejected instead of being silently assigned to
    the wrong specialist.
    """
    if not isinstance(record, Mapping):
        raise ValueError("record must be a mapping")

    explicit = str(record.get("discovery_agent") or "").strip()
    if explicit.endswith("_signal"):
        return explicit

    text = " ".join(
        str(record.get(key) or "").strip().lower()
        for key in ("source", "provider", "source_url", "url")
    )

    for agent, aliases in _SOURCE_ALIASES.items():
        if any(alias in text for alias in aliases):
            return agent

    if any(marker in text for marker in _JOB_MARKERS):
        return "web_job_signal"

    raise ValueError(
        "No discovery specialist could be determined for source record; "
        "configure discovery_agent explicitly for this source."
    )


def attach_discovery_routing(record: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a normalized record and attach its permanent specialist lane."""
    result = dict(record)
    result["discovery_agent"] = discovery_agent_for(result)
    return result
