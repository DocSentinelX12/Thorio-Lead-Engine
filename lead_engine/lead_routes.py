from __future__ import annotations

from typing import Any, Dict, Iterable, List

SUPPORTED_ROUTES = ("Shiftr", "Paxus", "Thorio")


def _get_routes(lead: Dict[str, Any]) -> List[str]:
    potential = lead.get("potential_routes")
    if isinstance(potential, list):
        routes = [str(route).strip() for route in potential if str(route).strip() in SUPPORTED_ROUTES]
        if routes:
            return list(dict.fromkeys(routes))
    route = str(lead.get("route", "") or "").strip()
    return [route] if route in SUPPORTED_ROUTES else []


def _final_routes(lead: Dict[str, Any]) -> List[str]:
    routes = _get_routes(lead)
    qualification = lead.get("qualification_results")
    paxus = qualification.get("Paxus", {}) if isinstance(qualification, dict) else {}
    if "Paxus" in routes and paxus.get("true_referral") is not True:
        routes.remove("Paxus")
    return routes


def route_leads(leads: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = {route: [] for route in SUPPORTED_ROUTES}
    result["Review"] = []
    for lead in leads:
        routes = _final_routes(lead)
        if not routes:
            result["Review"].append(dict(lead))
            continue
        for route in routes:
            result[route].append(dict(lead))
    return result


def route_state(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Return explicit per-destination state without losing base qualification."""
    potential = _get_routes(lead)
    final = _final_routes(lead)
    qualification = lead.get("qualification_results")
    paxus = qualification.get("Paxus", {}) if isinstance(qualification, dict) else {}
    states: Dict[str, Dict[str, Any]] = {}
    for route in SUPPORTED_ROUTES:
        if route == "Paxus" and route in potential and route not in final:
            state = "paxus_research_required" if paxus.get("qualified") else "not_qualified"
        elif route in final:
            state = "ready_for_human_action"
        elif route in potential:
            state = "qualified_pending_final_verification"
        else:
            state = "not_qualified"
        states[route] = {"matched": route in potential, "final": route in final, "state": state}
    return {"potential_routes": potential, "final_routes": final, "destinations": states, "review_required": not bool(final), "multi_route": len(final) > 1}


def route_counts(leads: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    routed = route_leads(leads)
    return {route: len(records) for route, records in routed.items()}
