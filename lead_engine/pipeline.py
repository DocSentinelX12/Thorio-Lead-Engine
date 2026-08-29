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
        Duplicate gate
          ↓
        Local LeadDB
          ↓
        Airtable approval queue
          ↓
        Human qualification
          ↓
        Final delivery gate

    IMPORTANT:

    The discovery duplicate gate does NOT treat an unqualified lead as
    a true duplicate.

    A fingerprint only becomes a true duplicate when the existing lead
    has already been explicitly qualified/approved.

    This preserves every legitimate discovery for qualification while
    preventing already-qualified positives from being submitted again.
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

        payload.setdefault(
            "qualification_status",
            "unqualified",
        )

        lead.compute_fingerprint()

        fingerprint = lead.fingerprint

        existing = self.db.get(fingerprint)

        # ---------------------------------------------------------
        # TRUE DUPLICATE CHECK
        # ---------------------------------------------------------
        #
        # Only an already-qualified positive is a true duplicate.
        #
        # Existing unqualified / in-review / not-qualified records
        # must NOT block this discovery.
        #
        if existing is not None:

            status_values = (
                existing.get("qualification_status"),
                existing.get("qualification"),
                existing.get("review_status"),
                existing.get("status"),
            )

            existing_status = ""

            for value in status_values:
                if value is None:
                    continue

                normalized = str(value).strip().lower()

                if normalized:
                    existing_status = normalized
                    break

            if existing_status in {
                "qualified",
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

            # Existing record is NOT a qualified positive.
            #
            # Refresh the discovery data and allow it to continue.
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

            inserted = self.db.insert_if_new(payload)

            if not inserted:
                # Race-safe fallback.
                existing = self.db.get(fingerprint)

                if existing is None:
                    raise ValueError(
                        f"Unable to persist lead: {fingerprint}"
                    )

                status_values = (
                    existing.get("qualification_status"),
                    existing.get("qualification"),
                    existing.get("review_status"),
                    existing.get("status"),
                )

                existing_status = ""

                for value in status_values:
                    if value is None:
                        continue

                    normalized = str(value).strip().lower()

                    if normalized:
                        existing_status = normalized
                        break

                if existing_status in {
                    "qualified",
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

        # ---------------------------------------------------------
        # EXISTING SYNC / APPROVAL QUEUE BEHAVIOR
        # ---------------------------------------------------------
        #
        # Do not move this behind qualification.
        #
        # Airtable synchronization is storage/approval-queue handling,
        # not permission to deliver the lead to a partner.
        #
        if self.sync_enabled:
            sync_result = sync_one(payload)

            sync_status = sync_result.get(
                "status",
                "failed",
            )

            sync_error = sync_result.get(
                "error"
            )

            if sync_status in {
                "synced",
                "already_exists",
            }:
                self.db.mark_synced(fingerprint)

            else:
                self.db.mark_error(
                    fingerprint,
                    sync_error or "Synchronization failed.",
                )

            return {
                "status": "accepted",
                "accepted": True,
                "fingerprint": fingerprint,
                "lead": payload,
                "potential_routes": possible_routes,
                "lead_score": scoring["lead_score"],
                "priority": scoring["priority"],
                "sync_status": sync_status,
                "sync_error": sync_error,
                "airtable_record": sync_result.get(
                    "airtable_record"
                ),
            }

        return {
            "status": "accepted",
            "accepted": True,
            "fingerprint": fingerprint,
            "lead": payload,
            "potential_routes": possible_routes,
            "lead_score": scoring["lead_score"],
            "priority": scoring["priority"],
            "sync_status": None,
            "sync_error": None,
            "airtable_record": None,
        }

    def qualify(
        self,
        fingerprint: str,
        *,
        qualified: bool,
        reason: str = "",
    ) -> Dict[str, Any]:

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
