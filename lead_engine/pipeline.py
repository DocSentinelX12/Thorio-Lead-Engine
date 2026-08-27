from typing import Any, Dict

from .database import LeadDB
from .dedupe import Dedupe
from .models import Lead
from .router import potential_routes, route
from .sync_worker import sync_one


class LeadPipeline:
    """
    Main lead-processing pipeline.

    Flow:

        Lead
          ↓
        Router
          ↓
        Dedupe
          ↓
        Local LeadDB
          ↓
        Airtable synchronization

    The local database remains the source of truth.
    Human review remains the final qualification decision.
    """

    def __init__(self, db: LeadDB | None = None):
        self.db = db or LeadDB()
        self.dedupe = Dedupe(self.db)

    def process(
        self,
        source: str,
        source_id: str,
        url: str,
        company: str = "",
        person: str = "",
        signal: str = "",
        evidence: str = "",
        **extra_fields: Any,
    ) -> Dict[str, Any]:
        """
        Process one discovered lead.
        """

        recommended_route = route(
            company=company,
            signal=signal,
            evidence=evidence,
        )

        possible_routes = potential_routes(
            company=company,
            signal=signal,
            evidence=evidence,
        )

        lead = Lead(
            source=source,
            source_id=source_id,
            url=url,
            company=company,
            person=person,
            signal=signal,
            route=recommended_route,
            potential_routes=possible_routes,
            evidence=evidence,
            **extra_fields,
        )

        lead.ensure_timestamp()
        fingerprint = lead.compute_fingerprint()

        accepted = self.dedupe.accept(lead)

        if not accepted:
            return {
                "status": "duplicate",
                "accepted": False,
                "fingerprint": fingerprint,
                "lead": lead.to_dict(),
                "potential_routes": possible_routes,
            }

        payload = lead.to_dict()

        sync_result = sync_one(payload)

        if sync_result["status"] == "synced":
            self.db.mark_synced(fingerprint)

        else:
            self.db.mark_error(
                fingerprint,
                sync_result["error"] or "Unknown sync error",
            )

        return {
            "status": "accepted",
            "accepted": True,
            "fingerprint": fingerprint,
            "lead": payload,
            "potential_routes": possible_routes,
            "sync_status": sync_result["status"],
            "sync_error": sync_result["error"],
        }


def process_lead(
    source: str,
    source_id: str,
    url: str,
    company: str = "",
    person: str = "",
    signal: str = "",
    evidence: str = "",
    **extra_fields: Any,
) -> Dict[str, Any]:
    """
    Convenience function for processing one discovered lead.
    """

    pipeline = LeadPipeline()

    return pipeline.process(
        source=source,
        source_id=source_id,
        url=url,
        company=company,
        person=person,
        signal=signal,
        evidence=evidence,
        **extra_fields,
    )


if __name__ == "__main__":
    print(
        "Lead pipeline loaded. "
        "Use process_lead() to process discovered opportunities."
    )
