from __future__ import annotations
from typing import Any, Dict, Iterable, List
SUPPORTED_ROUTES = ("Shiftr", "Paxus", "Thorio", "Astrivon Labs")

def _get_routes(lead: Dict[str, Any]) -> List[str]:
    potential = lead.get("potential_routes")
    if isinstance(potential, str): potential = [potential]
    if isinstance(potential, list):
        routes = [str(route).strip() for route in potential if str(route).strip() in SUPPORTED_ROUTES]
        if routes: return list(dict.fromkeys(routes))
    route = str(lead.get("route", "") or "").strip()
    if route in SUPPORTED_ROUTES: return [route]
    qualification = lead.get("qualification_results")
    if isinstance(qualification, dict): return [name for name in SUPPORTED_ROUTES if isinstance(qualification.get(name), dict) and qualification[name].get("qualified") is True]
    return []

def _route_independently_verified(lead: Dict[str, Any], route: str) -> bool:
    qualification = lead.get("qualification_results")
    if not isinstance(qualification, dict): return False
    result = qualification.get(route)
    if not isinstance(result, dict) or result.get("qualified") is not True: return False
    route_research = result.get("route_research")
    if not isinstance(route_research, dict) or route_research.get("verified") is not True: return False
    if route == "Paxus" and result.get("true_referral") is not True: return False
    if route == "Astrivon Labs" and result.get("service_fit_verified") is not True: return False
    return True

def _final_routes(lead: Dict[str, Any]) -> List[str]:
    routes = _get_routes(lead)
    if isinstance(lead.get("potential_routes"), list): return [route for route in routes if _route_independently_verified(lead, route)]
    if str(lead.get("route", "") or "").strip(): return routes
    return [route for route in routes if _route_independently_verified(lead, route)]

def route_leads(leads: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = {route: [] for route in SUPPORTED_ROUTES}; result["Review"] = []
    for lead in leads:
        routes = _final_routes(lead)
        if not routes: result["Review"].append(dict(lead)); continue
        for route in routes: result[route].append(dict(lead))
    return result

def route_state(lead: Dict[str, Any]) -> Dict[str, Any]:
    potential = _get_routes(lead); final = _final_routes(lead)
    qualification = lead.get("qualification_results") if isinstance(lead.get("qualification_results"), dict) else {}
    states: Dict[str, Dict[str, Any]] = {}
    for route in SUPPORTED_ROUTES:
        result = qualification.get(route) if isinstance(qualification.get(route), dict) else {}
        if route in potential and route not in final:
            if route == "Paxus" and result.get("qualified") is True and result.get("true_referral") is not True: state = "paxus_research_required"
            elif route == "Astrivon Labs" and result.get("qualified") is True and result.get("service_fit_verified") is not True: state = "astrivon_service_fit_required"
            else: state = "route_research_required" if result.get("qualified") is True else "not_qualified"
        elif route in final: state = "ready_for_human_action"
        else: state = "not_qualified"
        states[route] = {"matched": route in potential, "final": route in final, "state": state}
    return {"potential_routes": potential, "final_routes": final, "destinations": states, "review_required": not bool(final), "multi_route": len(final) > 1}

def route_counts(leads: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    routed = route_leads(leads)
    return {route: len(records) for route, records in routed.items()}
