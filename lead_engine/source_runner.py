from typing import Any, Dict, Iterable, Optional
import logging

from .pipeline import LeadPipeline
from .collector import normalize_lead_input
from .agent_queue import enqueue_many

logger = logging.getLogger(__name__)


_PRIORITY_MAP = {
    "critical": 3,
    "urgent": 3,
    "high": 2,
    "medium": 1,
    "normal": 1,
    "low": 0,
    "review": 0,
}

_DISCOVERY_SOURCE_ALIASES = {
    "x_signal": ("x", "twitter"),
    "threads_signal": ("threads",),
    "reddit_signal": ("reddit",),
    "linkedin_signal": ("linkedin",),
    "facebook_signal": ("facebook",),
    "instagram_signal": ("instagram",),
    "hacker_news_signal": ("hacker news", "hacker_news", "news.ycombinator.com", "hn"),
    "indie_hackers_signal": ("indie hackers", "indie_hackers", "indiehackers"),
    "product_hunt_signal": ("product hunt", "product_hunt", "producthunt"),
}


def _queue_priority(value: Any) -> int:
    """Normalize pipeline priority into the integer queue contract."""
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower()
    if text in _PRIORITY_MAP:
        return _PRIORITY_MAP[text]
    try:
        return int(float(text))
    except (TypeError, ValueError):
        logger.warning("Unknown lead priority %r; defaulting to queue priority 0", value)
        return 0


def _discovery_agent(record: Dict[str, Any]) -> str:
    """Select the permanent discovery lane from explicit source metadata."""
    configured = str(record.get("discovery_agent") or "").strip()
    if configured:
        return configured

    source_text = " ".join(
        str(record.get(key) or "").strip().lower()
        for key in ("source", "provider", "source_url", "url")
        if str(record.get(key) or "").strip()
    )

    for agent, aliases in _DISCOVERY_SOURCE_ALIASES.items():
        if any(alias in source_text for alias in aliases):
            return agent

    return "web_job_signal"


class SourceRunner:
    """Run normalized source records through the lead pipeline and workforce."""

    def __init__(self, pipeline: LeadPipeline):
        self.pipeline = pipeline

    def process(self, records: Iterable[Dict[str, Any]]) -> Dict[str, int]:
        accepted = 0
        duplicates = 0
        failed = 0
        discovered = 0
        qualified = 0
        research_queued = 0
        agent_tasks_queued = 0
        queue_tasks = []

        for record in records:
            discovered += 1
            if not isinstance(record, dict):
                failed += 1
                logger.error(
                    "Lead pipeline rejected non-object source record: type=%s",
                    type(record).__name__,
                )
                continue
            try:
                normalized_record = normalize_lead_input(record)
                result = self.pipeline.process(**normalized_record)
            except Exception:
                failed += 1
                source = str(record.get("source", "unknown"))
                source_id = str(record.get("source_id", "unknown"))
                logger.exception(
                    "Lead pipeline failed while processing source record: source=%s source_id=%s",
                    source,
                    source_id,
                )
                continue

            if result.get("status") == "duplicate":
                duplicates += 1
            elif result.get("accepted") is True:
                accepted += 1
                fingerprint = str(result.get("fingerprint") or "").strip()
                lead = result.get("lead")
                if fingerprint and isinstance(lead, dict):
                    agent = _discovery_agent(normalized_record)
                    queue_tasks.append({
                        "agent": agent,
                        "payload": {
                            "record": dict(normalized_record),
                            "lead": dict(lead),
                            "fingerprint": fingerprint,
                        },
                        "priority": _queue_priority(result.get("priority")),
                        "dedupe_key": f"discovery:{agent}:{fingerprint}",
                    })

            if result.get("qualification_status") == "qualified":
                qualified += 1
            if result.get("paxus_research_status") == "research_required":
                research_queued += 1

        if queue_tasks:
            enqueue_many(self.pipeline.db, queue_tasks)
            agent_tasks_queued = len(queue_tasks)

        summary = {
            "discovered_count": discovered,
            "accepted_count": accepted,
            "duplicate_count": duplicates,
            "failed_count": failed,
        }
        if qualified:
            summary["qualified_count"] = qualified
        if research_queued:
            summary["paxus_research_queued_count"] = research_queued
        if agent_tasks_queued:
            summary["agent_tasks_queued_count"] = agent_tasks_queued
        return summary

    def run_source(
        self,
        source: Any,
        checkpoint: Optional[str] = None,
    ) -> Dict[str, int]:
        """Collect one source and process every returned record independently."""
        if checkpoint is None:
            records = source.collect()
        else:
            try:
                records = source.collect(checkpoint=checkpoint)
            except TypeError as exc:
                message = str(exc)
                if "checkpoint" not in message or "unexpected keyword argument" not in message:
                    raise
                records = source.collect()
        return self.process(records)
