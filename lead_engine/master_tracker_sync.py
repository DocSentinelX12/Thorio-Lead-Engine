from __future__ import annotations
from typing import Any, Dict, List, Optional
from .airtable_sync import AirtableSyncError, create_master_record, find_master_records, update_master_record
from .paxus_referral_adapter import lead_to_paxus_referral, paxus_commission_tracking_enabled
MASTER_TRACKER_TABLE_KEYS = ("lead_radar", "companies", "opportunities", "outreach", "referrals", "followups", "commissions", "lead_sources")
def _text(value: Any) -> str: return "" if value is None else str(value).strip()
def _clean_fields(fields: Dict[str, Any]) -> Dict[str, Any]: return {key: value for key, value in fields.items() if value is not None}
def _first_record(records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]: return records[0] if records and isinstance(records[0], dict) else None
def _upsert(table_key: str, lookup_field: str, lookup_value: Any, fields: Dict[str, Any]) -> Dict[str, Any]:
    lookup_value = _text(lookup_value)
    if not lookup_value: raise ValueError(f"{table_key} synchronization requires a value for {lookup_field}.")
    existing_record = _first_record(find_master_records(table_key, lookup_field, lookup_value)); clean_fields = _clean_fields(fields)
    if existing_record is not None:
        record_id = _text(existing_record.get("id"))
        if not record_id: raise AirtableSyncError(f"Existing {table_key} record has no Airtable record ID.")
        result = update_master_record(table_key, record_id, clean_fields); record = _first_record(result.get("records", []))
        if record is None: raise AirtableSyncError(f"Airtable returned no updated record for {table_key}.")
        return {"status": "updated", "record": record}
    result = create_master_record(table_key, clean_fields); record = _first_record(result.get("records", []))
    if record is None: raise AirtableSyncError(f"Airtable returned no created record for {table_key}.")
    return {"status": "created", "record": record}
def _routes(lead: Dict[str, Any]) -> List[str]:
    value = lead.get("potential_routes", [])
    if isinstance(value, str): value = [value]
    allowed = {"Paxus", "Shiftr", "Thorio", "Astrivon Labs"}
    if isinstance(value, (list, tuple, set)):
        routes = list(dict.fromkeys(_text(route) for route in value if _text(route) in allowed))
        if routes: return routes
    route = _text(lead.get("route"))
    return [route] if route in allowed else []
def _company_source(lead: Dict[str, Any]) -> str:
    source = _text(lead.get("source")).lower()
    if source in {"x", "twitter"}: return "X"
    if source == "linkedin": return "LinkedIn"
    if source == "facebook": return "Facebook"
    if source in {"google", "google search", "google news"}: return "Google"
    if source in {"referral", "partner referral"}: return "Referral"
    return "Other"
def sync_company(lead: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(lead, dict): raise ValueError("Lead payload must be a dictionary.")
    company = _text(lead.get("company"))
    if not company: raise ValueError("Company synchronization requires a company.")
    research = lead.get("company_research") if isinstance(lead.get("company_research"), dict) else {}
    verified_dm = research.get("company_verified") is True and str(research.get("decision_maker_verification_status") or "").lower() == "verified"
    fields = {"Company": company, "Website": _text(lead.get("company_website")) or _text(lead.get("url")) or None, "Industry": _text(lead.get("industry")) or None, "Decision Maker": _text(research.get("decision_maker")) if verified_dm else None, "Title": _text(lead.get("contact_title")) if verified_dm else None, "Email": _text(research.get("decision_maker_email")) if verified_dm else None, "Phone": _text(lead.get("contact_phone")) or None, "LinkedIn / X": _text(lead.get("linkedin_url")) or _text(lead.get("x_url")) or None, "Source": _company_source(lead), "Notes": _text(lead.get("notes")) or None}
    return _upsert("companies", "Company", company, fields)
def _opportunity_key(lead: Dict[str, Any], route: str) -> str:
    fingerprint = _text(lead.get("fingerprint"))
    if not fingerprint: raise ValueError("Opportunity synchronization requires a fingerprint.")
    return f"{fingerprint}:{route}"
def _section_verified(value: Dict[str, Any]) -> bool:
    status = str(value.get("verification_status") or value.get("status") or "").strip().lower()
    return value.get("verified") is True or status in {"verified", "research_verified", "complete"}
def _verified_need_text(lead: Dict[str, Any], route: str | None = None) -> str:
    parts: list[str] = []
    for key in ("business_need_research", "current_intent_research"):
        value = lead.get(key)
        if isinstance(value, dict) and _section_verified(value):
            for field in ("business_need", "current_need", "need", "service_need", "requirement"):
                text = _text(value.get(field))
                if text: parts.append(text)
    route_research = lead.get("route_research")
    if isinstance(route_research, dict) and _section_verified(route_research) and route:
        routes = route_research.get("routes")
        item = routes.get(route) if isinstance(routes, dict) else None
        if isinstance(item, dict) and _section_verified(item):
            for field in ("business_need", "current_need", "need", "service_need", "requirement", "evidence"):
                text = _text(item.get(field))
                if text: parts.append(text)
    return " ".join(parts)
def _opportunity_need(lead: Dict[str, Any], route: str) -> str:
    combined = _verified_need_text(lead, route=route).lower()
    if not combined: raise ValueError("Opportunity synchronization requires explicitly verified researched need.")
    if any(term in combined for term in ("hiring", "talent", "recruit", "engineer", "developer")): return "Tech Talent"
    if any(term in combined for term in ("ai", "automation", "agent", "llm")): return "AI / Automation"
    if any(term in combined for term in ("mobile", "ios", "android", "app")): return "Mobile App"
    if any(term in combined for term in ("saas", "product")): return "SaaS / Product"
    if any(term in combined for term in ("staff augmentation", "augmentation")): return "Staff Augmentation"
    if any(term in combined for term in ("software", "development", "build", "custom")): return "Software Development"
    if any(term in combined for term in ("b2b", "sales", "lead generation", "outreach")): return "B2B Outreach / Lead Generation"
    return "Other"
def _opportunity_fields(lead: Dict[str, Any], route: str) -> Dict[str, Any]:
    fingerprint = _text(lead.get("fingerprint")); company = _text(lead.get("company"))
    return {"Opportunity": _opportunity_key(lead, route), "Company": company, "Partner": route, "Need": _opportunity_need(lead, route), "Stage": _text(lead.get("opportunity_stage")) or "Qualified", "Priority": _text(lead.get("priority")) or None, "Estimated Value": lead.get("estimated_value"), "Referral Date": _text(lead.get("submitted_at"))[:10] if lead.get("submitted_at") else None, "Next Follow-up": _text(lead.get("next_action_date"))[:10] if lead.get("next_action_date") else None, "Referral Confirmed": bool(lead.get("paxus_accepted")) if route == "Paxus" else bool(lead.get("partner_confirmed") or lead.get("astrivon_partner_confirmed")), "Partner Contact": _text(lead.get("partner_contact")) or None, "Notes": f"Lead fingerprint: {fingerprint}" if fingerprint else None}
def sync_opportunities(lead: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(lead, dict): raise ValueError("Lead payload must be a dictionary.")
    if lead.get("qualified") is not True: return []
    results: List[Dict[str, Any]] = []
    for route in _routes(lead):
        if route == "Thorio": continue
        results.append(_upsert("opportunities", "Opportunity", _opportunity_key(lead, route), _opportunity_fields(lead, route)))
    return results
def sync_lead_source(lead: Dict[str, Any]) -> Dict[str, Any]: return {"status": "skipped", "reason": "Lead Sources is a source-configuration table; discovered leads use Lead Radar and downstream lifecycle tables."}
def sync_astrivon_referral(lead: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(lead, dict): raise ValueError("Lead payload must be a dictionary.")
    if "Astrivon Labs" not in _routes(lead): return None
    fingerprint = _text(lead.get("fingerprint")); company = _text(lead.get("company"))
    if not fingerprint or not company: raise ValueError("Astrivon referral synchronization requires a fingerprint and company.")
    referral = lead.get("astrivon_referral") if isinstance(lead.get("astrivon_referral"), dict) else {}
    referral_key = f"{fingerprint}:Astrivon Labs"
    fields = {"Referral": referral_key, "Company": company, "Opportunity": _opportunity_key(lead, "Astrivon Labs"), "Partner": "Astrivon Labs", "Submitted Date": _text(referral.get("introduced_at") or lead.get("astrivon_introduced_at"))[:10] or None, "Partner Confirmed": referral.get("partner_confirmed") is True or lead.get("astrivon_partner_confirmed") is True, "Partner Confirmation / ID": _text(referral.get("referral_id") or lead.get("astrivon_referral_id")) or None, "Outcome": _text(referral.get("status") or lead.get("astrivon_status") or ("Active" if referral.get("partner_confirmed") is True or lead.get("astrivon_partner_confirmed") is True else "Qualified")), "Commission Rate": 0.20, "Notes": _text(lead.get("notes")) or None}
    return _upsert("referrals", "Referral", referral_key, fields)
def sync_astrivon_commissions(lead: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(lead, dict): raise ValueError("Lead payload must be a dictionary.")
    if "Astrivon Labs" not in _routes(lead): return []
    if _text(lead.get("astrivon_status") or "qualified") != "active" or lead.get("astrivon_partner_confirmed") is not True:
        return []
    fingerprint = _text(lead.get("fingerprint")); company = _text(lead.get("company"))
    events = lead.get("astrivon_payment_events", [])
    if not isinstance(events, (list, tuple)): return []
    results: List[Dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict): continue
        event_id = _text(event.get("event_id"))
        if not event_id: raise ValueError("Astrivon payment events require event_id.")
        try: revenue = float(event.get("revenue_amount"))
        except (TypeError, ValueError): raise ValueError("Astrivon payment events require numeric revenue_amount.")
        if revenue <= 0: raise ValueError("Astrivon payment event revenue must be greater than zero.")
        referral_key = f"{fingerprint}:Astrivon Labs:{event_id}"
        fields = {"Company": company, "Referral": referral_key, "Partner": "Astrivon Labs", "Deal / Placement Value": revenue, "Commission Rate": 0.20, "Expected Commission": round(revenue * 0.20, 2), "Eligible / Trigger Date": _text(event.get("received_at"))[:10] or None, "Paid": event.get("paid") is True, "Actual Amount": event.get("actual_commission"), "Payment Date": _text(event.get("commission_payment_date"))[:10] or None, "Payment Method": _text(event.get("commission_payment_method")) or None, "Notes": _text(event.get("notes")) or None}
        results.append(_upsert("commissions", "Referral", referral_key, fields))
    return results
def sync_commission(lead: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(lead, dict): raise ValueError("Lead payload must be a dictionary.")
    if not paxus_commission_tracking_enabled(lead): return None
    referral = lead_to_paxus_referral(lead); fingerprint = _text(referral.fingerprint)
    if not fingerprint: raise ValueError("Commission synchronization requires a fingerprint.")
    try: placement_count = int(referral.placement_count)
    except (TypeError, ValueError): raise ValueError("Commission synchronization requires a valid placement count.")
    if placement_count <= 0 or referral.client_payment_received is not True: return None
    placement_value = lead.get("placement_value"); expected_commission = lead.get("expected_commission")
    if expected_commission is None and placement_value is not None:
        try: expected_commission = float(placement_value) * 0.25
        except (TypeError, ValueError): expected_commission = None
    fields = {"Company": _text(referral.company), "Referral": fingerprint, "Partner": "Paxus", "Deal / Placement Value": placement_value, "Commission Rate": 0.25, "Expected Commission": expected_commission, "Eligible / Trigger Date": _text(lead.get("payment_received_at"))[:10] if lead.get("payment_received_at") else None, "Expected Payment Date": _text(lead.get("expected_payment_date"))[:10] if lead.get("expected_payment_date") else None, "Notes": _text(lead.get("notes")) or None}
    if "commission_paid" in lead: fields["Paid"] = lead.get("commission_paid") is True
    if "actual_commission" in lead: fields["Actual Amount"] = lead.get("actual_commission")
    if "commission_payment_date" in lead: fields["Payment Date"] = _text(lead.get("commission_payment_date"))[:10] if lead.get("commission_payment_date") else None
    if "commission_payment_method" in lead: fields["Payment Method"] = _text(lead.get("commission_payment_method")) or None
    return _upsert("commissions", "Referral", fingerprint, fields)
def sync_master_tracker(lead: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(lead, dict): raise ValueError("Lead payload must be a dictionary.")
    return {"status": "synced", "reason": None, "company": sync_company(lead), "opportunities": sync_opportunities(lead), "astrivon_referral": sync_astrivon_referral(lead), "astrivon_commissions": sync_astrivon_commissions(lead), "lead_source": {"status": "skipped", "reason": "Lead Sources is configuration-only."}, "commission": sync_commission(lead)}
