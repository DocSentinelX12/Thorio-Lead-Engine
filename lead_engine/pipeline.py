from typing import Any, Dict

from .queue import LeadQueue
from .router import route
from .sync_worker import sync_one


class LeadPipeline:
    """
    Main lead-processing pipeline.

    Flow:

        signal
          ↓
        router
          ↓
        local persistent queue
          ↓
        Airtable synchronization

    Human review remains the final qualification decision.
    """

    def __init__(self, queue: LeadQueue | None = None):
        self.queue = queue or LeadQueue()

    def process(
        self,
        company: str,
        signal: str,
        evidence: str,
        **extra_fields: Any,
    ) -> Dict[str, Any]:
        """
        Process one discovered lead.

        The router provides a recommendation only.
        The lead is persisted locally before Airtable synchronization.
        """

        recommended_partner = route(
            company=company,
            signal=signal,
            evidence=evidence,
        )

        lead = {
            "company": company,
            "signal": signal,
            "evidence": evidence,
            "recommended_partner": recommended_partner,
            "review_status": "Review",
            "qualified": False,
            **extra_fields,
        }

        if not lead.get("duplicate_key"):
            raise ValueError(
                "A duplicate_key is required before a lead "
                "can enter the pipeline."
            )

        queue_record = self.queue.add(lead)

        sync_result = sync_one(queue_record)

        if sync_result["status"] == "synced":
            self.queue.mark_synced(
                lead_id=queue_record["_queue_id"],
                airtable_record_id=(
                    sync_result["airtable_record"] or {}
                ).get("id"),
            )
        else:
            self.queue.mark_failed(
                lead_id=queue_record["_queue_id"],
                error=sync_result["error"] or "Unknown sync error",
            )

        return {
            "lead": queue_record,
            "recommended_partner": recommended_partner,
            "sync_status": sync_result["status"],
            "sync_error": sync_result["error"],
        }


def process_lead(
    company: str,
    signal: str,
    evidence: str,
    duplicate_key: str,
    **extra_fields: Any,
) -> Dict[str, Any]:
    """
    Convenience function for processing a single lead.
    """

    pipeline = LeadPipeline()

    return pipeline.process(
        company=company,
        signal=signal,
        evidence=evidence,
        duplicate_key=duplicate_key,
        **extra_fields,
    )


if __name__ == "__main__":
    print(
        "Lead pipeline loaded. "
        "Use process_lead() to process discovered opportunities."
)
