"""Read-only production audit for qualified opportunities through outbound outreach.

This audit consumes the production SQLite database without opening LeadDB's
recovery/migration path. It never sends messages or mutates production state.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from .sales_handoff import package_digest


def audit_revenue_lifecycle(database_path: str | Path) -> dict[str, Any]:
    path = Path(database_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"production database does not exist: {path}")
    uri = f"file:{quote(path.as_posix(), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        lead_rows = connection.execute(
            "SELECT fingerprint, payload FROM leads"
        ).fetchall()
        leads: dict[str, dict[str, Any]] = {}
        for fingerprint, raw_payload in lead_rows:
            try:
                payload = json.loads(raw_payload)
            except (TypeError, ValueError):
                continue
            if isinstance(payload, Mapping):
                leads[str(fingerprint)] = dict(payload)

        handoffs = {
            str(fingerprint): str(package_hash or "").strip()
            for fingerprint, package_hash in connection.execute(
                "SELECT fingerprint, package_digest FROM airtable_handoffs"
            ).fetchall()
        }
        queue_rows = connection.execute(
            "SELECT agent, status, payload FROM agent_queue "
            "WHERE agent = 'outreach_closer' AND status IN ('queued','running','failed')"
        ).fetchall()
        pending_fingerprints: set[str] = set()
        pending_closer_tasks = 0
        failed_closer_tasks = 0
        for agent, status, raw_payload in queue_rows:
            try:
                payload = json.loads(raw_payload)
            except (TypeError, ValueError):
                payload = {}
            lead_payload = payload.get("lead") if isinstance(payload, Mapping) else None
            fingerprint = ""
            if isinstance(lead_payload, Mapping):
                fingerprint = str(lead_payload.get("fingerprint") or "").strip()
            if not fingerprint and isinstance(payload, Mapping):
                fingerprint = str(payload.get("fingerprint") or "").strip()
            if status in {"queued", "running"}:
                pending_closer_tasks += 1
                if fingerprint:
                    pending_fingerprints.add(fingerprint)
            elif status == "failed":
                failed_closer_tasks += 1

        state_row = connection.execute(
            "SELECT value FROM state WHERE key = 'revenue_execution'"
        ).fetchone()
        try:
            state = json.loads(state_row[0]) if state_row else {}
        except (TypeError, ValueError):
            state = {}
        raw_actions = state.get("actions") if isinstance(state, Mapping) else {}
        actions = [
            dict(action)
            for action in (raw_actions.values() if isinstance(raw_actions, Mapping) else [])
            if isinstance(action, Mapping)
        ]
        sent_initial_actions = [
            action for action in actions
            if str(action.get("status") or "").lower() == "sent"
            and str(action.get("idempotency_key") or "").startswith("outreach:")
        ]
        sent_followup_actions = [
            action for action in actions
            if str(action.get("status") or "").lower() == "sent"
            and str(action.get("idempotency_key") or "").startswith("followup:")
        ]
        sent_action_ids_by_opportunity: dict[str, set[str]] = {}
        for action in sent_initial_actions:
            opportunity_id = str(action.get("opportunity_id") or "").strip()
            action_id = str(action.get("action_id") or "").strip()
            if opportunity_id and action_id:
                sent_action_ids_by_opportunity.setdefault(opportunity_id, set()).add(action_id)

        qualified = [
            lead for lead in leads.values()
            if lead.get("qualified") is True
        ]
        eligible = [
            lead for lead in qualified
            if str(lead.get("sales_eligibility") or "").strip().lower() == "eligible"
        ]
        eligible_handoff_mismatch = 0
        orphaned_qualified_opportunities = 0
        for lead in eligible:
            fingerprint = str(lead.get("fingerprint") or "").strip()
            recorded_digest = handoffs.get(fingerprint, "")
            try:
                current_digest = package_digest(lead)
            except (TypeError, ValueError, KeyError):
                current_digest = ""
            if not recorded_digest or not current_digest or recorded_digest != current_digest:
                eligible_handoff_mismatch += 1
            last_action_id = str(lead.get("last_outreach_action_id") or "").strip()
            sent_is_durable = bool(
                last_action_id
                and last_action_id in sent_action_ids_by_opportunity.get(fingerprint, set())
            )
            if not sent_is_durable and fingerprint not in pending_fingerprints:
                orphaned_qualified_opportunities += 1

        responses_received = 0
        conversations_active = 0
        followups_due = 0
        converted = referred = closed_lost = disqualified = 0
        for lead in leads.values():
            events = lead.get("conversation_events")
            inbound_observed = bool(str(lead.get("last_inbound_event_id") or "").strip())
            if isinstance(events, list):
                inbound_observed = inbound_observed or any(
                    isinstance(event, Mapping)
                    and str(event.get("direction") or event.get("event_type") or "").lower()
                    in {"inbound", "incoming", "inbound_message", "response_received"}
                    for event in events
                )
            if inbound_observed:
                responses_received += 1
            outreach_state = str(lead.get("outreach_state") or "").strip().lower()
            lifecycle = str(lead.get("revenue_lifecycle_state") or "").strip().lower()
            if lifecycle == "conversation_active" or outreach_state in {
                "awaiting_response", "conversation_active", "follow_up_due"
            }:
                conversations_active += 1
            if lead.get("follow_up_due") is True or str(lead.get("next_follow_up_at") or "").strip():
                followups_due += 1
            outcome = lead.get("commercial_outcome")
            outcome_type = str(outcome.get("type") or "").lower() if isinstance(outcome, Mapping) else ""
            if lifecycle == "converted" or outreach_state == "converted" or outcome_type == "converted":
                converted += 1
            if lifecycle == "referred" or outreach_state == "referred" or outcome_type == "referred":
                referred += 1
            if lifecycle == "closed_lost" or outreach_state == "closed_lost":
                closed_lost += 1
            if lifecycle == "disqualified" or (lead.get("qualified") is False and bool(lead.get("qualification_results"))):
                disqualified += 1

        result = {
            "qualified_opportunities": len(qualified),
            "sales_eligible_opportunities": len(eligible),
            "outreach_actions_sent": len(sent_initial_actions),
            "opportunities_contacted": len(sent_action_ids_by_opportunity),
            "followups_executed": len(sent_followup_actions),
            "responses_received": responses_received,
            "conversations_active": conversations_active,
            "followups_due": followups_due,
            "converted": converted,
            "referred": referred,
            "closed_lost": closed_lost,
            "disqualified": disqualified,
            "pending_closer_tasks": pending_closer_tasks,
            "failed_closer_tasks": failed_closer_tasks,
            "eligible_handoff_mismatch": eligible_handoff_mismatch,
            "orphaned_qualified_opportunities": orphaned_qualified_opportunities,
        }
        return result
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="data/leads.sqlite3")
    args = parser.parse_args()
    try:
        result = audit_revenue_lifecycle(args.database)
    except Exception as exc:
        print(f"REVENUE LIFECYCLE AUDIT FAILURE: {type(exc).__name__}: {exc}")
        return 1
    print("REVENUE LIFECYCLE AUDIT: " + json.dumps(result, sort_keys=True))
    if result["eligible_handoff_mismatch"] or result["orphaned_qualified_opportunities"] or result["failed_closer_tasks"]:
        print("REVENUE LIFECYCLE FAILURE: every sales-eligible opportunity must have a current digest-bound Airtable handoff and either durable successful outreach or a live closer task; no failed closer tasks are allowed.")
        return 1
    print("REVENUE LIFECYCLE VERIFIED: no stale eligible handoffs, orphaned qualified opportunities, or failed closer tasks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
