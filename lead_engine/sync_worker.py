import json
from typing import Any, Dict, List

from .airtable_sync import (
    sync_followup,
    sync_lead_if_missing,
    sync_outreach,
    sync_paxus_referral_state,
)
from .database import LeadDB
from .paxus_referral_adapter import lead_to_paxus_referral


def _build_outreach_payload(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "fingerprint": lead.get(
            "fingerprint"
        ),
        "company": lead.get(
            "company"
        ),
        "platform": lead.get(
            "contact_method"
        ) or lead.get(
            "source"
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
    Synchronize one lead lifecycle state.

    Flow:

    Lead Radar
        ↓
    Outreach
        ↓
    Follow-ups
        ↓
    Referrals
    """

    if not isinstance(lead, dict):
        return {
            "status": "failed",
            "lead": {},
            "airtable_record": None,
            "outreach_record": None,
            "followup_record": None,
            "referral_record": None,
            "error": "Lead payload must be an object.",
        }

    try:
        result = sync_lead_if_missing(
            lead
        )

        outreach_result = sync_outreach(
            _build_outreach_payload(
                lead
            )
        )

        followup_result = sync_followup(
            _build_followup_payload(
                lead
            )
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

        return {
            "status": (
                "synced"
                if result["status"] == "created"
                else "already_exists"
            ),
            "lead": lead,
            "airtable_record": result.get(
                "record"
            ),
            "outreach_record": (
                outreach_result.get(
                    "record"
                )
                if outreach_result
                else None
            ),
            "followup_record": (
                followup_result.get(
                    "record"
                )
                if followup_result
                else None
            ),
            "referral_record": (
                referral_result.get(
                    "record"
                )
                if referral_result
                else None
            ),
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
            "error": str(exc),
        }


def sync_pending(
    db: LeadDB,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Retry locally stored leads that have not successfully
    synchronized.
    """

    rows = db.pending(limit=limit)

    synced: List[Dict[str, Any]] = []
    already_exists: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    for fingerprint, payload_json, attempts in rows:
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
                "error": (
                    f"Invalid stored lead payload: {exc}"
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
                "error": (
                    "Invalid stored lead payload: expected an object."
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
        "already_exists_count": len(already_exists),
        "failed_count": len(failed),
    }
