from typing import Any, Dict
DELIVERY_STATES = ("pending", "approved", "rejected", "review", "queued", "attempting", "delivered", "failed", "retryable", "permanently_failed")
TERMINAL_STATES = {"delivered", "permanently_failed"}
SUPPORTED_ROUTES = {"Shiftr", "Paxus", "Thorio", "Astrivon Labs"}
def normalize_delivery_state(value: Any) -> str:
    state = str(value or "").strip().lower()
    return state if state in DELIVERY_STATES else "review"
def get_delivery_state(lead: Dict[str, Any]) -> str: return normalize_delivery_state(lead.get("delivery_status"))
def set_delivery_state(lead: Dict[str, Any], state: str, reason: str = "") -> Dict[str, Any]:
    result = dict(lead); result["delivery_status"] = normalize_delivery_state(state); result["delivery_reason"] = str(reason or "").strip(); return result
def is_delivery_complete(lead: Dict[str, Any]) -> bool: return get_delivery_state(lead) in TERMINAL_STATES
def is_ready_for_delivery(lead: Dict[str, Any]) -> bool:
    if get_delivery_state(lead) != "approved": return False
    route = str(lead.get("route", "") or "").strip()
    if route not in SUPPORTED_ROUTES: return False
    from .delivery_policy import is_delivery_ready
    return is_delivery_ready(lead)
