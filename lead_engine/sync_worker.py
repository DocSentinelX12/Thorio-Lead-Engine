import json
from typing import Any, Dict, List

from .airtable_sync import (
    sync_followup,
    sync_lead_if_missing,
    sync_outreach,
    sync_paxus_referral_state,
)
from .database import LeadDB
from .master_tracker_sync import sync_master_tracker
from .paxus_referral_adapter import lead_to_paxus_referral


def _text(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def _delivery_approved(
    lead: Dict[str, Any],
) -> bool:
    return (
        _text(
            lead.get("delivery_status")
        ).lower()
        == "approved"
    )


def _outreach_ready(
    lead: Dict[str, Any],
) -> bool:
    """
    A lead is ready for Outreach only after the delivery
    approval gate has passed and a usable contact email exists.
    """

    return bool(
        _delivery_approved(lead)
        and _text(lead.get("company"))
        and _text(lead.get("route"))
        and _text(lead.get("contact_email"))
    )


def _followup_required(
    lead: Dict[str, Any],
) -> bool:
    """
    A Follow-up record is created only when the lead has an
    actual follow-up action scheduled or an existing follow-up
    lifecycle state that needs synchronization.

    A newly approved lead with no next action does not receive
    a fabricated Pending follow-up.
    """

    next_action_date = _text(
        lead.get("next_action_date")
    )

    follow_up_status = _text(
        lead.get("follow_up_status")
    ).lower()

    follow_up_notes = _text(
        lead.get("follow_up_notes")
    )

    follow_up_number = lead.get(
        "follow_up_number"
    )

    if next_action_date:
        return True

    if follow_up_notes:
        return True

    if follow_up_status not in {
        "",
        "pending",
    }:
        return True

    if follow_up_number not in {
        None,
        "",
        0,
        "0",
    }:
        return True

    return False


def _build_outreach_payload(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build an Outreach payload while preserving the original
    Lead fingerprint and explicitly carrying the route.

    The route is part of the Outreach lifecycle because one
    lead may legitimately have separate Outreach records for
    multiple applicable partners.
    """

    return {
        "fingerprint": lead.get(
            "fingerprint"
        ),
        "company": lead.get(
            "company"
        ),
        "route": lead.get(
            "route"
        ),
        "platform": (
            lead.get("contact_method")
            or lead.get("source")
        ),
        "follow_up_number": lead.get(
            "follow_up_number",
            0,
        ),
        "response": lead.get(
            "response",
            "",
        ),
        "outreach_status": lead.get(
            "outreach_status",
            "Not Contacted",
        ),
        "next_action_date": lead.get(
            "next_action_date",
        ),
    }


def _build_followup_payload(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "fingerprint": lead.get(
            "fingerprint"
        ),
        "company": lead.get(
            "company"
        ),
        "route": lead.get(
            "route"
        ),
        "due_date": lead.get(
            "next_action_date",
        ),
        "status": lead.get(
            "follow_up_status",
            "Pending",
        ),
        "follow_up_number": lead.get(
            "follow_up_number",
            0,
        ),
        "notes": lead.get(
            "follow_up_notes",
            "",
        ),
    }

                    
def sync_one(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Synchronize one complete Master Tracker state.

    Lead Radar must succeed first. Every downstream synchronization
    that is actually attempted must also explicitly confirm success.
    """

    if not isinstance(lead, dict):
        return {
            "status": "failed",
            "lead": {},
            "airtable_record": None,
            "outreach_record": None,
            "followup_record": None,
            "referral_record": None,
            "master_tracker": None,
            "error": "Lead payload must be an object.",
        }

    try:
        result = sync_lead_if_missing(
            lead
        )

        if not isinstance(
            result,
            dict,
        ):
            raise ValueError(
                "Lead Radar synchronization returned an invalid result."
            )

        lead_status = result.get(
            "status"
        )

        if lead_status not in {
            "created",
            "already_exists",
            "updated",
            "synced",
        }:
            raise ValueError(
                result.get("error")
                or (
                    "Lead Radar synchronization did not "
                    "confirm a successful write."
                )
            )

        airtable_record = result.get(
            "record"
        )

        if airtable_record is None:
            raise ValueError(
                "Lead Radar synchronization succeeded without "
                "returning an Airtable record."
            )

        outreach_result = None
        followup_result = None

        if _outreach_ready(lead):
            outreach_result = sync_outreach(
                _build_outreach_payload(
                    lead
                )
            )

            if not isinstance(
                outreach_result,
                dict,
            ):
                raise ValueError(
                    "Outreach synchronization returned an invalid result."
                )

            if outreach_result.get(
                "status"
            ) not in {
                "created",
                "updated",
                "synced",
                "already_exists",
            }:
                raise ValueError(
                    outreach_result.get("error")
                    or (
                        "Outreach synchronization did not "
                        "confirm a successful result."
                    )
                )

            if outreach_result.get(
                "record"
            ) is None:
                raise ValueError(
                    "Outreach synchronization succeeded without "
                    "returning an Airtable record."
                )

            if _followup_required(lead):
                followup_result = sync_followup(
                    _build_followup_payload(
                        lead
                    )
                )

                if not isinstance(
                    followup_result,
                    dict,
                ):
                    raise ValueError(
                        "Follow-up synchronization returned an invalid result."
                    )

                if followup_result.get(
                    "status"
                ) not in {
                    "created",
                    "updated",
                    "synced",
                    "already_exists",
                }:
                    raise ValueError(
                        followup_result.get("error")
                        or (
                            "Follow-up synchronization did not "
                            "confirm a successful result."
                        )
                    )

                if followup_result.get(
                    "record"
                ) is None:
                    raise ValueError(
                        "Follow-up synchronization succeeded without "
                        "returning an Airtable record."
                    )

        referral_result = None

        referral = lead_to_paxus_referral(
            lead
        )

        if (
            referral.referral_submitted
            or referral.contact_consent
            or referral.warm_referral_ready
            or referral.paxus_accepted
            or referral.introduction_made
            or referral.placement_count > 0
            or referral.client_payment_received
            or referral.commission_due
        ):
            referral_result = sync_paxus_referral_state(
                referral
            )

            if not isinstance(
                referral_result,
                dict,
            ):
                raise ValueError(
                    "Referral synchronization returned an invalid result."
                )

            if referral_result.get(
                "status"
            ) not in {
                "created",
                "updated",
                "synced",
                "already_exists",
            }:
                raise ValueError(
                    referral_result.get("error")
                    or (
                        "Referral synchronization did not "
                        "confirm a successful result."
                    )
                )

            if referral_result.get(
                "record"
            ) is None:
                raise ValueError(
                    "Referral synchronization succeeded without "
                    "returning an Airtable record."
                )

        master_tracker_result = sync_master_tracker(
            lead
        )

        if not isinstance(
            master_tracker_result,
            dict,
        ):
            raise ValueError(
                "Master Tracker synchronization returned an invalid result."
            )

        master_status = master_tracker_result.get(
            "status"
        )

        if master_status not in {
            "synced",
            "skipped",
        }:
            raise ValueError(
                master_tracker_result.get("error")
                or (
                    "Master Tracker synchronization did not "
                    "confirm a successful result."
                )
            )

        return {
            "status": (
                "synced"
                if lead_status != "already_exists"
                else "already_exists"
            ),
            "lead": lead,
            "airtable_record": airtable_record,
            "outreach_record": (
                outreach_result.get("record")
                if outreach_result
                else None
            ),
            "followup_record": (
                followup_result.get("record")
                if followup_result
                else None
            ),
            "referral_record": (
                referral_result.get("record")
                if referral_result
                else None
            ),
            "master_tracker": master_tracker_result,
            "error": None,
        }

    except Exception as exc:
        return {
            "status": "failed",
            "lead": lead,
            "airtable_record": None,
            "outreach_record": None,
            "followup_record": None,
            "referral_record": None,
            "master_tracker": None,
            "error": str(exc),
        }


def sync_pending(
    db: LeadDB,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Retry locally stored leads that have not successfully
    synchronized to the complete Master Tracker.
    """

    rows = db.pending(
        limit=limit
    )

    synced: List[Dict[str, Any]] = []
    already_exists: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    for (
        fingerprint,
        payload_json,
        attempts,
    ) in rows:

        try:
            lead = json.loads(
                payload_json
            )

        except (TypeError, ValueError) as exc:
            result = {
                "status": "failed",
                "lead": {},
                "airtable_record": None,
                "outreach_record": None,
                "followup_record": None,
                "referral_record": None,
                "master_tracker": None,
                "error": (
                    "Invalid stored lead payload: "
                    f"{exc}"
                ),
            }

            failed.append(result)

            db.mark_error(
                fingerprint,
                result["error"],
            )

            continue

        if not isinstance(
            lead,
            dict,
        ):
            result = {
                "status": "failed",
                "lead": {},
                "airtable_record": None,
                "outreach_record": None,
                "followup_record": None,
                "referral_record": None,
                "master_tracker": None,
                "error": (
                    "Invalid stored lead payload: "
                    "expected an object."
                ),
            }

            failed.append(result)

            db.mark_error(
                fingerprint,
                result["error"],
            )

            continue

        result = sync_one(
            lead
        )

        if result["status"] == "synced":
            synced.append(result)

            db.mark_synced(
                fingerprint
            )

        elif result["status"] == "already_exists":
            already_exists.append(result)

            db.mark_synced(
                fingerprint
            )

        else:
            failed.append(result)

            db.mark_error(
                fingerprint,
                result["error"],
            )

    return {
        "synced": synced,
        "already_exists": already_exists,
        "failed": failed,
        "synced_count": len(synced),
        "already_exists_count": len(
            already_exists
        ),
        "failed_count": len(
            failed
        ),
    }
