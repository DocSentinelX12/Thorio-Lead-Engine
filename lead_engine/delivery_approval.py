from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
PARTNER_ROUTES = {"Shiftr", "Paxus", "Thorio", "Astrivon Labs"}
APPROVAL_PENDING = "pending"; APPROVAL_APPROVED = "approved"; APPROVAL_REJECTED = "rejected"
def _normalize_routes(lead: Dict[str, Any]) -> List[str]:
    routes=[]; raw_routes=lead.get("routes")
    if isinstance(raw_routes,str): raw_routes=[raw_routes]
    if isinstance(raw_routes,Iterable) and not isinstance(raw_routes,(str,bytes,dict)):
        for route in raw_routes:
            name=str(route).strip()
            if name in PARTNER_ROUTES and name not in routes: routes.append(name)
    for key in ("route","delivery_route"):
        name=str(lead.get(key," ") or "").strip()
        if name in PARTNER_ROUTES and name not in routes: routes.append(name)
    return routes
def approval_state(lead: Dict[str, Any]) -> str:
    value=str(lead.get("approval_status","") or lead.get("human_approval_status","") or "").strip().lower()
    if value in {APPROVAL_APPROVED,"human_approved","approved_by_human"}: return APPROVAL_APPROVED
    if value in {APPROVAL_REJECTED,"human_rejected","rejected_by_human"}: return APPROVAL_REJECTED
    if lead.get("human_approved") is True: return APPROVAL_APPROVED
    if lead.get("human_approved") is False: return APPROVAL_REJECTED
    return APPROVAL_PENDING
def mark_pending(lead: Dict[str, Any]) -> Dict[str, Any]:
    result=deepcopy(lead); result["approval_status"]=APPROVAL_PENDING; result["human_approved"]=False; result["approval_required"]=True; routes=_normalize_routes(result)
    if routes: result["routes"]=routes
    return result
def approve_lead(lead: Dict[str, Any], approved_routes: Optional[Iterable[str]]=None) -> Dict[str, Any]:
    result=deepcopy(lead); existing_routes=_normalize_routes(result)
    routes=existing_routes if approved_routes is None else [str(route).strip() for route in approved_routes if str(route).strip() in PARTNER_ROUTES and str(route).strip() in existing_routes]
    result["approval_status"]=APPROVAL_APPROVED; result["human_approved"]=True; result["approval_required"]=False; result["approved_at"]=datetime.now(timezone.utc).isoformat(); result["approved_routes"]=list(dict.fromkeys(routes)); return result
def reject_lead(lead: Dict[str, Any], reason: str="") -> Dict[str, Any]:
    result=deepcopy(lead); result["approval_status"]=APPROVAL_REJECTED; result["human_approved"]=False; result["approval_required"]=False; result["rejection_reason"]=str(reason or "").strip(); result["rejected_at"]=datetime.now(timezone.utc).isoformat(); return result
def is_route_approved(lead: Dict[str, Any], route: str) -> bool:
    name=str(route or "").strip()
    if name not in PARTNER_ROUTES or approval_state(lead)!=APPROVAL_APPROVED: return False
    approved=lead.get("approved_routes")
    if approved is None: return name in _normalize_routes(lead)
    if isinstance(approved,str): approved=[approved]
    return name in {str(value).strip() for value in approved}
def delivery_authorized(lead: Dict[str, Any], route: Optional[str]=None) -> bool:
    if approval_state(lead)!=APPROVAL_APPROVED: return False
    routes=_normalize_routes(lead)
    if not routes: return False
    if route is None:
        approved=lead.get("approved_routes")
        if approved is None: return True
        if isinstance(approved,str): approved=[approved]
        return any(str(value).strip() in PARTNER_ROUTES for value in approved)
    return is_route_approved(lead,route)
def filter_approved_for_route(leads: Iterable[Dict[str, Any]], route: str) -> List[Dict[str, Any]]:
    return [deepcopy(lead) for lead in leads if delivery_authorized(lead,str(route or "").strip())]
def build_approval_queue(leads: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]: return [mark_pending(lead) for lead in leads if approval_state(lead)==APPROVAL_PENDING]
def approval_summary(leads: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    summary={"pending":0,"approved":0,"rejected":0,"routes":{route:0 for route in PARTNER_ROUTES}}
    for lead in leads:
        state=approval_state(lead); summary[state]+=1
        if state==APPROVAL_APPROVED:
            for route in lead.get("approved_routes",_normalize_routes(lead)):
                if route in PARTNER_ROUTES: summary["routes"][route]+=1
    return summary
