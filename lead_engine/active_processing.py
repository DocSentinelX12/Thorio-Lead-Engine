"""Persistent handoffs for the qualification, verification, routing, and revenue chain."""
from __future__ import annotations
from typing import Any, Dict, Mapping
from .agent_queue import enqueue
from .agent_stateful_handlers import airtable_integrity as _airtable_integrity
from .agent_stateful_handlers import routing as _routing
from .agent_stateful_handlers import verification as _verification
from .dedupe import Dedupe
from .research_package import finalize_research_readiness, research_readiness
from .research_sync import sync_research
from .sales_handoff import package_digest, package_is_ready


def _lead(payload: Mapping[str, Any]) -> Dict[str, Any]:
    lead = payload.get("lead", payload)
    if not isinstance(lead, Mapping): raise ValueError("lead must be a mapping")
    value = dict(lead)
    if not str(value.get("fingerprint") or "").strip(): raise ValueError("lead requires fingerprint")
    return value


def priority(agent: str, payload: Mapping[str, Any], ctx: Any) -> Dict[str, Any]:
    lead = _lead(payload); evidence = sum(1 for key in ("signal", "evidence", "job_title", "person", "company") if str(lead.get(key) or "").strip()); qualified = bool(lead.get("qualified") or lead.get("potential_routes")); freshness = bool(lead.get("need_at") or lead.get("current_need_at") or lead.get("inquiry_at") or lead.get("last_inquiry_at") or lead.get("intent_at") or lead.get("discovery_timestamp")); research_ready = str(lead.get("research_status") or "").strip().lower() in {"complete", "research_complete"}; decision_maker_ready = bool(lead.get("company_research", {}).get("decision_maker")) if isinstance(lead.get("company_research"), Mapping) else False; score = evidence + (5 if qualified else 0) + (3 if freshness else 0) + (2 if research_ready else 0) + (1 if decision_maker_ready else 0); fingerprint = lead["fingerprint"]
    enqueue(ctx.db, "verification", {"lead": lead, "evidence_events": payload.get("evidence_events", [])}, priority=8, dedupe_key=f"verification:{fingerprint}")
    return {"role": agent, "priority_score": score, "lead": lead, "research_ready": research_ready, "decision_maker_ready": decision_maker_ready, "actionability": "ready" if research_ready and decision_maker_ready else "research_required", "handoff": "verification"}


def verification(agent: str, payload: Mapping[str, Any], ctx: Any) -> Dict[str, Any]:
    lead = _lead(payload); fingerprint = lead["fingerprint"]

    def _verification_input(candidate: Mapping[str, Any]) -> Dict[str, Any]:
        value = dict(candidate)
        if not str(value.get("route") or "").strip():
            potential_routes = value.get("potential_routes")
            if isinstance(potential_routes, list) and potential_routes:
                value["route"] = str(potential_routes[0])
        return value

    validation_lead = _verification_input(lead)
    verification_payload = dict(payload); verification_payload["lead"] = validation_lead
    result = _verification(agent, verification_payload, ctx)

    # Verification is a durable state boundary. A queued verification task may
    # contain an older lead snapshot than the LeadDB record after qualification
    # or research completed. If the first evaluation is blocked by missing
    # qualification state, re-read the authoritative LeadDB record and evaluate
    # that state once before declaring the opportunity review-required. This
    # preserves every verification gate and only prevents stale payloads from
    # stranding a fully qualified opportunity.
    if result.get("verified") is not True:
        current = ctx.db.get(fingerprint)
        if isinstance(current, Mapping):
            current_lead = dict(current)
            current_validation = _verification_input(current_lead)
            current_payload = dict(payload); current_payload["lead"] = current_validation
            current_result = _verification(agent, current_payload, ctx)
            if current_result.get("verified") is True or current_result.get("decision_maker_verification") == "verified":
                result = current_result
                validation_lead = current_validation

    if result.get("decision_maker_verification") == "verified":
        current_lead = ctx.db.get(fingerprint) or validation_lead
        research = dict(current_lead.get("company_research") or {}) if isinstance(current_lead.get("company_research"), Mapping) else {}
        if not research.get("company_verified"):
            result.update({"decision_maker_handoff": "research_required", "research_verification_blocked": "company_not_verified", "handoff": "review_required"}); return result
        record = result.get("decision_maker_verification_record")
        if isinstance(record, Mapping):
            if str(record.get("person") or "").strip(): research["decision_maker"] = str(record["person"]).strip()
            if str(record.get("role_evidence") or "").strip(): research["decision_maker_evidence"] = str(record["role_evidence"]).strip()
            if str(record.get("source") or "").strip(): research["decision_maker_verification_source"] = str(record["source"]).strip()
            if str(record.get("verified_at") or "").strip(): research["decision_maker_verified_at"] = str(record["verified_at"]).strip()
        research["decision_maker_verification_status"] = "verified"
        if result.get("decision_maker_role_evidence") and isinstance(record, Mapping): research["decision_maker_role_evidence"] = result["decision_maker_role_evidence"]
        updated = dict(current_lead); updated["company_research"] = research
        updated, readiness = finalize_research_readiness(updated)
        stored = ctx.db.update_payload(fingerprint, updated) or updated
        research_sync_result = None
        if readiness["ready"]:
            try: research_sync_result = sync_research(stored)
            except Exception as exc: research_sync_result = {"status": "failed", "error": str(exc)}
            if isinstance(record, Mapping):
                enqueue(ctx.db, "qualification_a", {"lead": stored, "evidence_events": payload.get("evidence_events", []), "research_result": {"status": "complete", "verified_fields": stored.get("research_verified_fields", [])}}, priority=9, dedupe_key=f"qualification_a_verified:{fingerprint}")
                result.update({"decision_maker_handoff": "qualification_a", "lead": stored, "research_sync": research_sync_result})
            else:
                result.update({"decision_maker_handoff": "routing", "lead": stored, "research_sync": research_sync_result})
        else:
            result.update({"decision_maker_handoff": "research_required", "lead": stored, "research_readiness": readiness, "research_sync": {"status": "not_ready"}})

    verified_lead = ctx.db.get(fingerprint) or validation_lead
    verified_research = verified_lead.get("company_research"); company_verified = isinstance(verified_research, Mapping) and verified_research.get("company_verified") is True; dm_verified = isinstance(verified_research, Mapping) and bool(verified_research.get("decision_maker")) and bool(verified_research.get("decision_maker_evidence")) and str(verified_research.get("decision_maker_verification_status") or "").strip().lower() == "verified"; research_status = str(verified_lead.get("research_status") or "").strip().lower(); research_complete = research_status in {"complete", "research_complete"}; research_readiness_result = research_readiness(verified_lead)
    if result.get("verified") is True and research_complete and research_readiness_result["ready"] and company_verified and dm_verified:
        if research_status == "research_complete":
            normalized = dict(verified_lead); normalized["research_status"] = "complete"; verified_lead = ctx.db.update_payload(fingerprint, normalized) or normalized
        enqueue(ctx.db, "routing", {"lead": verified_lead, "verified": True}, priority=7, dedupe_key=f"routing:{fingerprint}"); result["handoff"] = "routing"
    elif result.get("decision_maker_verification") == "verified": result["handoff"] = "qualification_a"
    else: result["handoff"] = "review_required"
    return result


def routing(agent: str, payload: Mapping[str, Any], ctx: Any) -> Dict[str, Any]:
    result = _routing(agent, payload, ctx)
    lead = _lead(payload)
    if result.get("destinations"):
        stored = dict(lead)
        stored["routing_result"] = dict(result)
        stored = ctx.db.update_payload(lead["fingerprint"], stored) or stored
        enqueue(ctx.db, "airtable_integrity", {"lead": stored, "routing_result": dict(result)}, priority=6, dedupe_key=f"airtable_integrity:{lead['fingerprint']}")
    result["handoff"] = "airtable_integrity" if result.get("destinations") else "review_required"
    return result


def _has_verified_need(lead: Mapping[str, Any]) -> bool:
    for key in ("business_need_research", "current_intent_research", "route_research"):
        value = lead.get(key)
        if not isinstance(value, Mapping): continue
        status = str(value.get("verification_status") or value.get("status") or "").strip().lower()
        if value.get("verified") is not True and status not in {"verified", "research_verified", "complete"}: continue
        if any(str(value.get(field) or "").strip() for field in ("business_need", "current_need", "need", "service_need", "requirement", "intent")): return True
        if key == "route_research" and isinstance(value.get("routes"), Mapping):
            for route_item in value["routes"].values():
                if isinstance(route_item, Mapping) and (route_item.get("verified") is True or str(route_item.get("verification_status") or "").lower() == "verified") and any(str(route_item.get(field) or "").strip() for field in ("business_need", "current_need", "need", "service_need", "requirement", "evidence")): return True
    return False


def _sales_eligibility(lead: Mapping[str, Any], routing_result: Mapping[str, Any], integrity_result: Mapping[str, Any], db: Any = None) -> tuple[bool, str]:
    destinations = routing_result.get("destinations")
    if not isinstance(destinations, list) or not destinations: return False, "no_supported_revenue_route"
    if bool(routing_result.get("review_required")): return False, "routing_requires_review"
    if lead.get("qualified") is not True: return False, "not_qualified"
    if not str(lead.get("business_need") or "").strip(): return False, "missing_exact_opportunity"
    if not _has_verified_need(lead): return False, "missing_verified_researched_need"
    if db is not None and Dedupe(db).find_exact_duplicate(dict(lead)) is not None: return False, "exact_duplicate"
    research = lead.get("company_research")
    if not isinstance(research, Mapping): return False, "missing_company_research"
    if not research.get("company_verified"): return False, "company_not_verified"
    if not research.get("decision_maker") or not research.get("decision_maker_evidence"): return False, "decision_maker_not_verified"
    if str(research.get("decision_maker_verification_status") or "").strip().lower() != "verified": return False, "decision_maker_not_verified"
    if not str(lead.get("contact_email") or research.get("decision_maker_email") or "").strip(): return False, "missing_contact_email"
    if db is None:
        return False, "airtable_handoff_required"
    if not package_is_ready(lead):
        return False, "research_package_not_ready"
    digest = package_digest(lead)
    handoff = db.get_airtable_handoff(str(lead.get("fingerprint") or ""))
    if not isinstance(handoff, Mapping):
        return False, "airtable_handoff_required"
    if str(handoff.get("package_digest") or "").strip() != digest:
        return False, "airtable_handoff_stale"
    return True, "eligible"


def airtable_integrity(agent: str, payload: Mapping[str, Any], ctx: Any) -> Dict[str, Any]:
    result = _airtable_integrity(agent, payload, ctx); lead = _lead(payload); fingerprint = lead["fingerprint"]; current_lead = ctx.db.get(fingerprint) or lead; routing_result = payload.get("routing_result", {}); routing_result = routing_result if isinstance(routing_result, Mapping) else {}
    if current_lead.get("last_outreach_action_id") or str(current_lead.get("outreach_state") or "").lower() == "awaiting_response":
        result.update({"sales_eligibility": current_lead.get("sales_eligibility") or "eligible", "sales_eligibility_reason": current_lead.get("sales_eligibility_reason") or "eligible", "handoff": "outreach_already_active"})
        enqueue(ctx.db, "audit", {"lead": current_lead, "integrity_result": result, "routing_result": routing_result}, priority=4, dedupe_key=f"audit:{fingerprint}")
        return result
    eligible, eligibility_reason = _sales_eligibility(current_lead, routing_result, result, ctx.db)
    if eligible:
        updated = dict(current_lead); updated["revenue_lifecycle_state"] = "sales_eligible"; updated.update({"sales_eligibility": "eligible", "sales_eligibility_reason": eligibility_reason, "eligible_routes": list(routing_result.get("destinations", [])), "preserved_routes": list(routing_result.get("destinations", []))}); stored = ctx.db.update_payload(fingerprint, updated) or updated; enqueue(ctx.db, "outreach_closer", {"lead": stored, "routing_result": dict(routing_result), "integrity_result": dict(result)}, priority=10, dedupe_key=f"sales:{fingerprint}"); result.update({"sales_eligibility": "eligible", "sales_eligibility_reason": eligibility_reason, "handoff": "outreach_closer"})
    else:
        updated = dict(current_lead)
        if current_lead.get("qualified") is True: updated.update({"revenue_lifecycle_state": "qualified" if eligibility_reason not in {"exact_duplicate"} else "closed_lost", "sales_eligibility": "blocked", "sales_eligibility_reason": eligibility_reason}); ctx.db.update_payload(fingerprint, updated)
        result.update({"sales_eligibility": "blocked", "sales_eligibility_reason": eligibility_reason, "handoff": "audit"})
    enqueue(ctx.db, "audit", {"lead": ctx.db.get(fingerprint) or current_lead, "integrity_result": result, "routing_result": routing_result}, priority=4, dedupe_key=f"audit:{fingerprint}"); return result