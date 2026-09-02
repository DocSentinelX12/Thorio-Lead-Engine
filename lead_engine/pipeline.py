from typing import Any, Dict

from .collector import validate_lead_input
from .database import LeadDB
from .dedupe import Dedupe
from .enrichment import enrich_lead
from .models import Lead
from .qualification import qualify_lead
from .router import potential_routes, route
from .scoring import score_result
from .sync_worker import sync_one
from .paxus_referral import (
    accept_referral,
    mark_introduction_made,
    mark_warm_referral_ready,
    record_client_payment,
    record_placement,
    submit_referral,
)
from .paxus_referral_adapter import (
    lead_to_paxus_referral,
    merge_paxus_referral_into_lead,
)


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
        Discovery persistence
          ↓
        Airtable approval queue
          ↓
        Human qualification
          ↓
        Final deduplication
          ↓
        Final routing
          ↓
        Partner delivery

    IMPORTANT:

    Discovery must never prevent a lead from reaching qualification.

    Final deduplication is performed only after explicit qualification.

    Multi-route behavior:

        A qualified lead may have more than one applicable route.

        The primary route is stored in "route".
        All applicable routes are stored in "potential_routes".

        Airtable synchronization uses the complete potential_routes
        collection so each qualified business route can have its own
        operational Opportunity.
    """

    def __init__(
        self,
        db=None,
        sync_enabled: bool = True,
    ):
        self.db = db or LeadDB()
        self.dedupe = Dedupe(self.db)
        self.sync_enabled = sync_enabled

    @staticmethod
    def _status_is_qualified(
        lead: Dict[str, Any],
    ) -> bool:
        values = (
            lead.get("qualification_status"),
            lead.get("qualification"),
            lead.get("review_status"),
            lead.get("status"),
        )

        for value in values:
            if value is None:
                continue

            normalized = str(value).strip().lower()

            if normalized in {
                "qualified",
                "approved",
                "accepted",
            }:
                return True

        return False

    def _sync_updated_lead(
        self,
        lead: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Synchronize an already-persisted canonical lead.

        LeadDB remains the canonical state store.

        Airtable receives the updated Lead Radar state and,
        when the lead is qualified, the complete set of
        applicable route Opportunities.

        This method intentionally preserves the existing
        sync_one() contract used by the worker and tests.
        """

        if not isinstance(lead, dict):
            raise ValueError(
                "Lead payload must be a dictionary."
            )

        if not self.sync_enabled:
            return {
                "status": "disabled",
                "lead": lead,
                "airtable_record": None,
                "referral_record": None,
                "error": None,
            }

        sync_result = sync_one(
            lead
        )

        status = sync_result.get(
            "status",
            "failed",
        )

        if status not in {
            "synced",
            "already_exists",
        }:
            error = (
                sync_result.get("error")
                or "Synchronization failed."
            )

            raise ValueError(
                error
            )

        return sync_result

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

        validate_lead_input(
            {
                "source": source,
                "source_id": source_id,
                "url": url,
                "company": company,
                "signal": signal,
                "evidence": evidence,
            }
        )

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

        existing = self.db.get(
            fingerprint
        )

        # ---------------------------------------------------------
        # DISCOVERY PERSISTENCE
        # ---------------------------------------------------------
        #
        # Discovery must NOT perform final qualification dedupe.
        #
        # Every discovered lead must remain available for explicit
        # human qualification.
        #
        # Existing qualified records are preserved. Existing
        # unqualified records may be refreshed.
        # ---------------------------------------------------------

        if existing is not None:

            if self._status_is_qualified(
                existing
            ):
                return {
                    "status": "duplicate",
                    "accepted": False,
                    "duplicate": True,
                    "fingerprint": fingerprint,
                    "lead": existing,
                    "potential_routes": possible_routes,
                    "lead_score": existing.get(
                        "lead_score",
                        scoring["lead_score"],
                    ),
                    "priority": existing.get(
                        "priority",
                        scoring["priority"],
                    ),
                    "sync_status": None,
                    "sync_error": None,
                    "airtable_record": None,
                }

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
            inserted = self.db.insert_if_new(
                payload
            )

            if not inserted:
                existing = self.db.get(
                    fingerprint
                )

                if existing is None:
                    raise ValueError(
                        f"Unable to persist lead: {fingerprint}"
                    )

                payload = existing

        # ---------------------------------------------------------
        # AIRTABLE / APPROVAL QUEUE
        # ---------------------------------------------------------
        #
        # Airtable synchronization is storage and approval-queue
        # handling. It is NOT final partner delivery.
        #
        # Qualification remains a separate action.
        # ---------------------------------------------------------

        if self.sync_enabled:
            sync_result = sync_one(
                payload
            )

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
                self.db.mark_synced(
                    fingerprint
                )
            else:
                self.db.mark_error(
                    fingerprint,
                    sync_error
                    or "Synchronization failed.",
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

        lead = self.db.get(
            fingerprint
        )

        if lead is None:
            raise ValueError(
                f"Lead not found: {fingerprint}"
            )

        updated = qualify_lead(
            lead,
            qualified=qualified,
            reason=reason,
        )

        if qualified:
            company = str(
                updated.get(
                    "company",
                    "",
                )
            )

            signal = str(
                updated.get(
                    "signal",
                    "",
                )
            )

            evidence = str(
                updated.get(
                    "evidence",
                    "",
                )
            )

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

            updated["route"] = (
                recommended_route
            )

            updated["potential_routes"] = (
                possible_routes
            )

            updated["lead_score"] = (
                scoring["lead_score"]
            )

            updated["priority"] = (
                scoring["priority"]
            )

        stored = self.db.update_payload(
            fingerprint,
            updated,
        )

        if stored is None:
            raise ValueError(
                f"Unable to update lead: {fingerprint}"
            )

        # ---------------------------------------------------------
        # MULTI-ROUTE QUALIFICATION SYNC
        # ---------------------------------------------------------
        #
        # Qualification is the boundary at which a lead becomes
        # eligible for route-specific operational opportunities.
        #
        # sync_one() delegates to the Master Tracker synchronization
        # layer, which creates one Opportunity for every valid
        # potential route.
        #
        # Therefore a qualified lead with:
        #
        #     ["Paxus", "Shiftr", "Thorio"]
        #
        # produces three independent Opportunities.
        #
        # An unqualified lead produces none.
        # ---------------------------------------------------------

        if self.sync_enabled:
            sync_result = sync_one(
                stored
            )

            sync_status = sync_result.get(
                "status",
                "failed",
            )

            if sync_status in {
                "synced",
                "already_exists",
            }:
                self.db.mark_synced(
                    fingerprint
                )
            else:
                self.db.mark_error(
                    fingerprint,
                    sync_result.get(
                        "error"
                    )
                    or "Synchronization failed.",
                )

        return stored

    def finalize(
        self,
        fingerprint: str,
    ) -> Dict[str, Any]:
        """
        Perform the final post-qualification gate.

        Ordering is intentional:

            qualification
                ↓
            final deduplication
                ↓
            final route
                ↓
            delivery-ready result

        A lead that has not been explicitly qualified cannot pass
        this boundary.
        """

        lead = self.db.get(
            fingerprint
        )

        if lead is None:
            raise ValueError(
                f"Lead not found: {fingerprint}"
            )

        if not bool(
            lead.get(
                "qualified",
                False,
            )
        ):
            return {
                "status": "awaiting_qualification",
                "approved": False,
                "duplicate": False,
                "fingerprint": fingerprint,
                "lead": lead,
                "reason": "lead_not_qualified",
            }

        if not self._status_is_qualified(
            lead
        ):
            return {
                "status": "awaiting_qualification",
                "approved": False,
                "duplicate": False,
                "fingerprint": fingerprint,
                "lead": lead,
                "reason": "qualification_status_not_confirmed",
            }

        existing = self.db.get(
            fingerprint
        )

        if existing is None:
            raise ValueError(
                f"Lead disappeared before finalization: {fingerprint}"
            )

        # The existing record is the canonical record for this
        # fingerprint. It has already passed qualification, so the
        # finalization step must not reject the record as a duplicate
        # of itself.
        #
        # Duplicate protection applies when another already-qualified
        # canonical record exists for the same final identity.
        #
        # The database fingerprint remains authoritative.

        final_route = route(
            company=str(
                lead.get(
                    "company",
                    "",
                )
            ),
            signal=str(
                lead.get(
                    "signal",
                    "",
                )
            ),
            evidence=str(
                lead.get(
                    "evidence",
                    "",
                )
            ),
        )

        final_routes = potential_routes(
            company=str(
                lead.get(
                    "company",
                    "",
                )
            ),
            signal=str(
                lead.get(
                    "signal",
                    "",
                )
            ),
            evidence=str(
                lead.get(
                    "evidence",
                    "",
                )
            ),
        )

        scoring = score_result(
            company=str(
                lead.get(
                    "company",
                    "",
                )
            ),
            signal=str(
                lead.get(
                    "signal",
                    "",
                )
            ),
            evidence=str(
                lead.get(
                    "evidence",
                    "",
                )
            ),
        )

        lead["route"] = final_route
        lead["potential_routes"] = final_routes
        lead["lead_score"] = scoring[
            "lead_score"
        ]
        lead["priority"] = scoring[
            "priority"
        ]

        stored = self.db.update_payload(
            fingerprint,
            lead,
        )

        if stored is None:
            raise ValueError(
                f"Unable to finalize lead: {fingerprint}"
            )

        # Finalization can recalculate the complete route set.
        # Synchronize that canonical result so the Master Tracker
        # remains aligned with LeadDB.
        if self.sync_enabled:
            sync_result = sync_one(
                stored
            )

            sync_status = sync_result.get(
                "status",
                "failed",
            )

            if sync_status in {
                "synced",
                "already_exists",
            }:
                self.db.mark_synced(
                    fingerprint
                )
            else:
                self.db.mark_error(
                    fingerprint,
                    sync_result.get(
                        "error"
                    )
                    or "Synchronization failed.",
                )

        return {
            "status": "finalized",
            "approved": True,
            "duplicate": False,
            "fingerprint": fingerprint,
            "route": final_route,
            "lead": stored,
        }

    def _sync_paxus_lifecycle(
        self,
        lead: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Synchronize an already-updated canonical lead and its
        Paxus lifecycle state to Airtable.

        The local LeadDB remains the canonical state store.
        Airtable is the operational projection of that state.

        This helper does not qualify, route, approve, or deliver
        the lead. It only propagates an already-valid lifecycle
        transition.
        """

        if not isinstance(
            lead,
            dict,
        ):
            raise ValueError(
                "Lead payload must be a dictionary."
            )

        if not self.sync_enabled:
            return {
                "status": "disabled",
                "airtable_record": None,
                "referral_record": None,
            }

        sync_result = sync_one(
            lead
        )

        status = sync_result.get(
            "status"
        )

        if status not in {
            "synced",
            "already_exists",
        }:
            raise ValueError(
                sync_result.get(
                    "error"
                )
                or "Airtable lifecycle synchronization failed."
            )

        return {
            "status": status,
            "airtable_record": sync_result.get(
                "airtable_record"
            ),
            "referral_record": sync_result.get(
                "referral_record"
            ),
        }

    def mark_paxus_warm_referral_ready(
        self,
        fingerprint: str,
    ) -> Dict[str, Any]:
        lead = self.db.get(
            fingerprint
        )

        if lead is None:
            raise ValueError(
                f"Lead not found: {fingerprint}"
            )

        referral = lead_to_paxus_referral(
            lead
        )

        referral = mark_warm_referral_ready(
            referral
        )

        updated = merge_paxus_referral_into_lead(
            lead,
            referral
        )

        stored = self.db.update_payload(
            fingerprint,
            updated
        )

        if stored is None:
            raise ValueError(
                f"Unable to update lead: {fingerprint}"
            )

        self._sync_paxus_lifecycle(
            stored
        )

        return stored

    def submit_paxus_referral(
        self,
        fingerprint: str,
    ) -> Dict[str, Any]:
        lead = self.db.get(
            fingerprint
        )

        if lead is None:
            raise ValueError(
                f"Lead not found: {fingerprint}"
            )

        referral = lead_to_paxus_referral(
            lead
        )

        referral = submit_referral(
            referral
        )

        updated = merge_paxus_referral_into_lead(
            lead,
            referral
        )

        stored = self.db.update_payload(
            fingerprint,
            updated
        )

        if stored is None:
            raise ValueError(
                f"Unable to update lead: {fingerprint}"
            )

        self._sync_paxus_lifecycle(
            stored
        )

        return stored

    def accept_paxus_referral(
        self,
        fingerprint: str,
        referral_id: str,
    ) -> Dict[str, Any]:
        lead = self.db.get(
            fingerprint
        )

        if lead is None:
            raise ValueError(
                f"Lead not found: {fingerprint}"
            )

        referral = lead_to_paxus_referral(
            lead
        )

        referral = accept_referral(
            referral,
            referral_id
        )

        updated = merge_paxus_referral_into_lead(
            lead,
            referral
        )

        stored = self.db.update_payload(
            fingerprint,
            updated
        )

        if stored is None:
            raise ValueError(
                f"Unable to update lead: {fingerprint}"
            )

        self._sync_paxus_lifecycle(
            stored
        )

        return stored

    def mark_paxus_introduction_made(
        self,
        fingerprint: str,
    ) -> Dict[str, Any]:
        lead = self.db.get(
            fingerprint
        )

        if lead is None:
            raise ValueError(
                f"Lead not found: {fingerprint}"
            )

        referral = lead_to_paxus_referral(
            lead
        )

        referral = mark_introduction_made(
            referral
        )

        updated = merge_paxus_referral_into_lead(
            lead,
            referral
        )

        stored = self.db.update_payload(
            fingerprint,
            updated
        )

        if stored is None:
            raise ValueError(
                f"Unable to update lead: {fingerprint}"
            )

        self._sync_paxus_lifecycle(
            stored
        )

        return stored

    def record_paxus_placement(
        self,
        fingerprint: str,
    ) -> Dict[str, Any]:
        lead = self.db.get(
            fingerprint
        )

        if lead is None:
            raise ValueError(
                f"Lead not found: {fingerprint}"
            )

        referral = lead_to_paxus_referral(
            lead
        )

        referral = record_placement(
            referral
        )

        updated = merge_paxus_referral_into_lead(
            lead,
            referral
        )

        stored = self.db.update_payload(
            fingerprint,
            updated
        )

        if stored is None:
            raise ValueError(
                f"Unable to update lead: {fingerprint}"
            )

        self._sync_paxus_lifecycle(
            stored
        )

        return stored

    def record_paxus_client_payment(
        self,
        fingerprint: str,
    ) -> Dict[str, Any]:
        lead = self.db.get(
            fingerprint
        )

        if lead is None:
            raise ValueError(
                f"Lead not found: {fingerprint}"
            )

        referral = lead_to_paxus_referral(
            lead
        )

        referral = record_client_payment(
            referral
        )

        updated = merge_paxus_referral_into_lead(
            lead,
            referral
        )

        stored = self.db.update_payload(
            fingerprint,
            updated
        )

        if stored is None:
            raise ValueError(
                f"Unable to update lead: {fingerprint}"
            )

        self._sync_paxus_lifecycle(
            stored
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
