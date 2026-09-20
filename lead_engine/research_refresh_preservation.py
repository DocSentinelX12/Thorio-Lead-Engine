from __future__ import annotations

from typing import Any, Dict, Mapping


def install() -> None:
    """Prevent a failed refresh from downgrading previously verified facts."""
    from . import advanced_agent_logic

    original = advanced_agent_logic.company_research
    if getattr(original, "_verified_refresh_preservation", False):
        return

    def company_research(payload: Mapping[str, Any], ctx: Any) -> Dict[str, Any]:
        original_lead = payload.get("lead") if isinstance(payload.get("lead"), Mapping) else payload
        original_company_research = original_lead.get("company_research") if isinstance(original_lead, Mapping) else None
        result = original(payload, ctx)
        if not isinstance(result, dict):
            return result
        acquired_research = result.get("research")
        if not isinstance(acquired_research, Mapping) or not isinstance(original_company_research, Mapping):
            return result

        merged_research = dict(acquired_research)
        if original_company_research.get("company_verified") is True:
            merged_research["company_verified"] = True
            if original_company_research.get("company_verification_evidence"):
                merged_research["company_verification_evidence"] = original_company_research["company_verification_evidence"]
        if str(original_company_research.get("decision_maker_verification_status") or "").strip().lower() == "verified":
            for key in ("decision_maker", "decision_maker_evidence", "decision_maker_verification_status", "decision_maker_email"):
                if original_company_research.get(key):
                    merged_research[key] = original_company_research[key]

        changed = merged_research != dict(acquired_research)
        if not changed:
            return result

        fingerprint = str(result.get("fingerprint") or original_lead.get("fingerprint") or "").strip()
        if not fingerprint:
            raise RuntimeError("company research refresh preservation requires a lead fingerprint")
        stored = ctx.db.update_payload(
            fingerprint,
            {
                "company_research": merged_research,
                "research_status": original_lead.get("research_status", result.get("research_status")),
                "research_verified_fields": original_lead.get("research_verified_fields", result.get("verified_fields", [])),
            },
        )
        if stored is None:
            raise RuntimeError(f"Lead not found while preserving verified research: {fingerprint}")
        result = dict(result)
        result["lead"] = stored
        result["research"] = merged_research
        result["research_status"] = stored.get("research_status", result.get("research_status"))
        result["verified_fields"] = stored.get("research_verified_fields", result.get("verified_fields", []))
        return result

    company_research._verified_refresh_preservation = True
    advanced_agent_logic.company_research = company_research
