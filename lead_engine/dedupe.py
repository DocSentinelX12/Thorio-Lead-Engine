from __future__ import annotations
import re
from typing import Any, Dict, Optional
from .models import Lead
QUALIFIED_STATUSES = {"qualified", "approved", "accepted"}
def _norm(value: Any) -> str: return re.sub(r"\s+", " ", str(value or "").strip().lower())
class Dedupe:
    def __init__(self, db): self.db = db
    @staticmethod
    def _qualified(payload: Dict[str, Any]) -> bool:
        if payload.get("qualified") is True: return True
        return any(_norm(payload.get(key)) in QUALIFIED_STATUSES for key in ("qualification_status", "review_status", "status"))
    @staticmethod
    def exact_need_key(payload: Dict[str, Any]) -> str:
        company, person, need = _norm(payload.get("company")), _norm(payload.get("person") or payload.get("contact_name")), _norm(payload.get("business_need"))
        if not company or not person or not need: return ""
        return f"company:{company}|person:{person}|need:{need}"
    def find_exact_duplicate(self, lead: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._qualified(lead): return None
        key = self.exact_need_key(lead)
        if not key: return None
        current = str(lead.get("fingerprint") or "")
        for existing in self.db.all_leads():
            if isinstance(existing, dict) and str(existing.get("fingerprint") or "") != current and self._qualified(existing) and self.exact_need_key(existing) == key: return existing
        return None
    def accept(self, lead: Lead) -> bool: return self.db.insert_if_new(lead.to_dict())
