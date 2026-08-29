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
        Local LeadDB
          ↓
        Human qualification
          ↓
        Final duplicate gate
          ↓
        Airtable synchronization / approval routing

    A discovered lead is stored for qualification, but discovery itself
    does not classify the lead as a true duplicate.

    The final duplicate gate is reserved for qualified leads.
    """

    def __init__(
        self,
        db=None,
        sync_enabled: bool = True,
    ):
        self.db = db or LeadDB()
        self.dedupe = Dedupe(self.db)
        self.sync_enabled = sync_enabled

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
        Process one newly discovered lead.

        Discovery is NOT the final duplicate decision.

        A lead is prepared and stored as an unqualified discovery so
        that qualification can happen first. A previously rejected or
        unqualified lead must not permanently block a later discovery.
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

        payload.setdefault("qualification_status", "unqualified")

        lead.compute_fingerprint()

        fingerprint = lead.fingerprint

        existing = self.db.get(fingerprint)

        if existing is not None:
            existing_status = str(
                existing.get(
                    "qualification_status",
                    existing.get("qualification", ""),
                )
            ).strip().lower()

            if existing_status in {
                "qualified",
                "true",
                "approved",
                "accepted",
            }:
                return {
                    "status": "duplicate",
                    "accepted": False,
                    "fingerprint": fingerprint,
                    "lead": existing,
                    "potential_routes": possible_routes,
                    "lead_score": scoring["lead_score"],
                    "priority": scoring["priority"],
                }

            # Existing discovery was not qualified.
            #
            # Refresh its discovery data instead of counting the new
            # discovery as a true duplicate.
            stored = self.db.update_payload(
                fingerprint,
                payload,
            )

            if stored is None:
                raise ValueError(
                    f"Unable to refresh existing lead: {fingerprint}"
                )

            payload = stored

        else:
            payload["qualification_status"] = "unqualified"

            if not self.db.insert_if_new(payload):
                existing = self.db.get(fingerprint)

                if existing is not None:
                    existing_status = str(
                        existing.get(
                            "qualification_status",
                            existing.get("qualification", ""),
                        )
                    ).strip().lower()

                    if existing_status in {
                        "qualified",
                        "true",
                        "approved",
                        "accepted",
                    }:
                        return {
                            "status": "duplicate",
                            "accepted": False,
                            "fingerprint": fingerprint,
                            "lead": existing,
                            "potential_routes": possible_routes,
                            "lead_score": scoring["lead_score"],
                            "priority": scoring["priority"],
                        }

                    payload = existing

        return {
            "status": "pending_qualification",
            "accepted": True,
            "fingerprint": fingerprint,
            "lead": payload,
            "potential_routes": possible_routes,
            "lead_score": scoring["lead_score"],
            "priority": scoring["priority"],
            "sync_status": "awaiting_qualification",
            "sync_error": None,
        }

    def qualify(
        self,
        fingerprint: str,
        *,
        qualified: bool,
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        Apply the explicit human qualification decision.

        Qualification is the point at which a discovered lead becomes
        eligible for the final duplicate/approval gate.
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
