"""Persistent handoffs for the qualification, verification, routing, and revenue chain."""
from __future__ import annotations
from typing import Any, Dict, Mapping
from .agent_queue import enqueue
from .agent_stateful_handlers import airtable_integrity as _airtable_integrity
from .agent_stateful_handlers import routing as _routing
from .agent_stateful_handlers import verification as _verification
from .dedupe import Dedupe
from .research_sync import sync_research


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
    lead = _lead(payload); fingerprint = lead["fingerprint"]; validation_lead = dict(lead)
    potential_routes = validation_lead.get("potential_routes")
    if not isinstance(potential_routes, list) or not potential_routes:
        qualification = validation_lead.get("qualification_results")
        if isinstance(qualification, Mapping):
            verified_routes = []
            for route_name in ("Shiftr", "Paxus", "Thorio"):
                result = qualification.get(route_name)
                if not isinstance(result, Mapping) or result.get("qualified") is not True:
                    continue
                route_research = result.get("route_research")
                if not isinstance(route_research, Mapping) or route_research.get("verified") is not True:
                    continue
                if route_name == "Paxus" and result.get("true_referral") is not True:
                    continue
                verified_routes.append(route_name)
            if verified_routes:
                validation_lead["potential_routes"] = verified_routes
                if not str(validation_lead.get("route") or "").strip(): validation_lead["route"] = verified_routes[0]
    if not str(validation_lead.get("route") or "").strip() and isinstance(validation_lead.get("potential_routes"), list) and validation_lead["potential_routes"]: validation_lead["route"] = str(validation_lead["potential_routes"][0])
    verification_payload = dict(payload); verification_payload["lead"] = validation_lead; result = _verification(agent, verification_payload, ctx)
    if result.get("decision_maker_verification") == "verified":
        current_lead = ctx.db.get(fingerprint) or lead; research = dict(current_lead.get("company_research") or {}) if isinstance(current_lead.get("company_research"), Mapping) else {}
        if not research.get("company_verified"):
            result.update({"decision_maker_handoff": "research_required", "research_verification_blocked": "company_not_verified", "handoff": "review_required"}); return result
        research["decision_maker_verification_status"] = "verified"
        if result.get("decision_maker_role_evidence"): research["decision_maker_role_evidence"] = result["decision_maker_role_evidence"]
        updated = dict(current_lead); updated["company_research"] = research; updated["research_status"] = "complete"; stored = ctx.db.update_payload(fingerprint, updated) or updated
        try: research_sync_result = sync_research(stored)
        except Exception as exc: research_sync_result = {"status": "failed", "error": str(exc)}
        enqueue(ctx.db, "qualification_a", {"lead": stored, "evidence_events": payload.get("evidence_events", []), "research_result": {"status": "complete", "verified_fields": stored.get("research_verified_fields", [])}}, priority=9, dedupe_key=f"qualification_a_verified:{fingerprint}")
        result.update({"decision_maker_handoff": "qualification_a", "lead": stored, "research_sync": research_sync_result})
    verified_lead = ctx.db.get(fingerprint) or lead; verified_research = verified_lead.get("company_research"); company_verified = isinstance(verified_research, Mapping) and verified_research.get("company_verified") is True; dm_verified = isinstance(verified_research, Mapping) and bool(verified_research.get("decision_maker")) and bool(verified_research.get("decision_maker_evidence")) and str(verified_research.get("decision_maker_verification_status") or "").strip().lower() == "verified"; research_status = str(verified_lead.get("research_status") or "").strip().lower(); research_complete = research_status in {"complete", "research_complete"}
    if result.get("verified") is True and research_complete and company_verified and dm_verified:
        if research_status == "research_complete":
            normalized = dict(verified_lead); normalized["research_status"] = "complete"; verified_lead = ctx.db.update_payload(fingerprint, normalized) or normalized
        enqueue(ctx.db, "routing", {"lead": verified_lead, "verified": True}, priority=7, dedupe_key=f"routing:{fingerprint}"); result["handoff"] = "routing"
    elif result.get("decision_maker_verification") == "verified": result["handoff"] = "qualification_a"
    else: result["handoff"] = "review_required"
    return result


def routing(agent: str, payload: Mapping[str, Any], ctx: Any) -> Dict[str, Any]:
    result = _routing(agent, payload, ctx); lead = _lead(payload)
    if result.get("destinations"): enqueue(ctx.db, "airtable_integrity", {"lead": lead, "routing_result": result}, priority=6, dedupe_key=f"airtable_integrity:{lead['fingerprint']}")
    result["handoff"] = "airtable_integrity" if result.get("destinations") else "review_required"; return result


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
    if integrity_result.get("sync_error_present"): return True, "airtable_sync_retryable"
    return True, "eligible"


def airtable_integrity(agent: str, payload: Mapping[str, Any], ctx: Any) -> Dict[str, Any]:
    result = _airtable_integrity(agent, payload, ctx); lead = _lead(payload); fingerprint = lead["fingerprint"]; current_lead = ctx.db.get(fingerprint) or lead; routing_result = payload.get("routing_result", {}); routing_result = routing_result if isinstance(routing_result, Mapping) else {}
    if str(current_lead.get("sales_eligibility") or "").strip().lower() == "eligible":
        result.update({"sales_eligibility": "eligible", "sales_eligibility_reason": current_lead.get("sales_eligibility_reason") or "eligible", "handoff": "outreach_already_active" if current_lead.get("last_outreach_action_id") or str(current_lead.get("outreach_state") or "").lower() == "awaiting_response" else "sales_already_eligible"}); enqueue(ctx.db, "audit", {"lead": current_lead, "integrity_result": result, "routing_result": routing_result}, priority=4, dedupe_key=f"audit:{fingerprint}"); return result
    eligible, eligibility_reason = _sales_eligibility(current_lead, routing_result, result, ctx.db)
    if eligible:
        updated = dict(current_lead); updated["revenue_lifecycle_state"] = "sales_eligible"; updated.update({"sales_eligibility": "eligible", "sales_eligibility_reason": eligibility_reason, "eligible_routes": list(routing_result.get("destinations", [])), "preserved_routes": list(routing_result.get("destinations", []))}); stored = ctx.db.update_payload(fingerprint, updated) or updated; enqueue(ctx.db, "outreach_closer", {"lead": stored, "routing_result": dict(routing_result), "integrity_result": dict(result)}, priority=10, dedupe_key=f"sales:{fingerprint}"); result.update({"sales_eligibility": "eligible", "sales_eligibility_reason": eligibility_reason, "handoff": "outreach_closer"})
    else:
        updated = dict(current_lead)
        if current_lead.get("qualified") is True: updated.update({"revenue_lifecycle_state": "qualified" if eligibility_reason not in {"exact_duplicate"} else "closed_lost", "sales_eligibility": "blocked", "sales_eligibility_reason": eligibility_reason}); ctx.db.update_payload(fingerprint, updated)
        result.update({"sales_eligibility": "blocked", "sales_eligibility_reason": eligibility_reason, "handoff": "audit"})
    enqueue(ctx.db, "audit", {"lead": ctx.db.get(fingerprint) or current_lead, "integrity_result": result, "routing_result": routing_result}, priority=4, dedupe_key=f"audit:{fingerprint}"); return result
