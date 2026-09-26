from typing import Any, Dict, Iterable, List
SUPPORTED_ROUTES = ("Shiftr", "Paxus", "Thorio", "Astrivon Labs")

def _lead_routes(lead: Dict[str, Any]) -> List[str]:
    potential_routes = lead.get("potential_routes")
    if isinstance(potential_routes, str): potential_routes = [potential_routes]
    if isinstance(potential_routes, list):
        routes = [str(route or "").strip() for route in potential_routes if str(route or "").strip() in SUPPORTED_ROUTES]
        if routes: return list(dict.fromkeys(routes))
    route = str(lead.get("route", "") or "").strip()
    return [route] if route in SUPPORTED_ROUTES else []

def build_delivery_batches(leads: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    batches = {route: [] for route in SUPPORTED_ROUTES}
    for lead in leads:
        for route in _lead_routes(lead): batches[route].append(dict(lead))
    return batches

def delivery_counts(leads: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    batches = build_delivery_batches(leads)
    return {route: len(batches[route]) for route in SUPPORTED_ROUTES}
