from typing import Any, Dict

from .database import LeadDB
from .dedupe import Dedupe
from .enrichment import enrich_lead
from .models import Lead
from .qualification import qualify_lead
from .router import potential_routes, route
from .scoring import score_result
from .sync_worker import sync_one


class LeadPipeline:
    """
    Main lead-processing pipeline.

    Discovery flow:

        Lead
          ↓
        Router
          ↓
        Scoring
          ↓
        Enrichment
          ↓
        Dedupe
          ↓
        Local LeadDB
          ↓
        Airtable synchronization

    Qualification remains an explicit human-review action.

    The local database remains the source of truth.
    """

    def __init__(self, db=None):
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

        Discovery never qualifies a lead automatically.
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

        scoring = score_result(
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

        payload = lead.to_dict()

        payload["lead_score"] = scoring["lead_score"]
        payload["priority"] = scoring["priority"]

        payload = enrich_lead(payload)

        payload["route"] = recommended_route
        payload["potential_routes"] = possible_routes
        payload["lead_score"] = scoring["lead_score"]
        payload["priority"] = scoring["priority"]

        lead.compute_fingerprint()

        fingerprint = lead.fingerprint

        accepted = self.dedupe.accept(lead)

        if not accepted:
            return {
                "status": "duplicate",
                "accepted": False,
                "fingerprint": fingerprint,
                "lead": payload,
                "potential_routes": possible_routes,
                "lead_score": scoring["lead_score"],
                "priority": scoring["priority"],
            }

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
            "lead_score": scoring["lead_score"],
            "priority": scoring["priority"],
            "sync_status": sync_result["status"],
            "sync_error": sync_result["error"],
        }

    def qualify(
        self,
        fingerprint: str,
        *,
        qualified: bool,
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        Apply an explicit human qualification decision.

        Scoring, routing, and discovery never qualify a lead automatically.
        """

        lead = self.db.get(fingerprint)

        if lead is None:
            raise ValueError(
                f"Lead not found: {fingerprint}"
            )

        updated = qualify_lead(
            lead,
            qualified=qualified,
            reason=reason,
        )

        stored = self.db.update_payload(
            fingerprint,
            updated,
        )

        if stored is None:
            raise ValueError(
                f"Unable to update lead: {fingerprint}"
            )

        return stored


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
