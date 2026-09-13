"""Surgical runtime upgrades for research fidelity and revenue copy.

These overrides preserve the existing worker graph and only strengthen two
boundaries: company research must incorporate the bounded public-web collector,
and the closer must use the verified research package when composing outreach.
No fact is synthesized when evidence is absent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping


def _text(value: Any) -> str:
    return str(value or "").strip()


def _evidence_lines(research: Mapping[str, Any], keys: tuple[str, ...]) -> list[str]:
    lines: list[str] = []
    for key in keys:
        value = research.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping):
                    evidence = _text(item.get("evidence"))
                    url = _text(item.get("url") or item.get("evidence_url"))
                    if evidence:
                        lines.append(f"{evidence[:700]}" + (f" [{url}]" if url else ""))
        elif value:
            text = _text(value)
            if text:
                lines.append(text[:900])
    return list(dict.fromkeys(lines))


def _research_handler(original):
    from .public_research import research_public_web
    from .agent_queue import enqueue

    def handler(agent: str, payload: Mapping[str, Any], ctx: Any) -> Dict[str, Any]:
        result = original(agent, payload, ctx)
        lead = result.get("lead")
        if not isinstance(lead, Mapping):
            return result
        lead = dict(lead)
        existing = lead.get("company_research")
        research = dict(existing) if isinstance(existing, Mapping) else {}

        public = research_public_web(lead)
        research["public_web_research"] = public
        research["public_web_sources"] = public.get("sources", [])
        facts = public.get("facts", {}) if isinstance(public, Mapping) else {}
        if isinstance(facts, Mapping):
            for category, key in (
                ("company", "public_company_facts"),
                ("product", "public_product_facts"),
                ("hiring", "public_hiring_facts"),
                ("decision_maker", "public_decision_maker_facts"),
                ("business_need", "public_business_need_facts"),
                ("commercial", "public_commercial_facts"),
            ):
                values = facts.get(category, [])
                if isinstance(values, list) and values:
                    research[key] = values

        research["research_method"] = "public_web_http"
        research["research_last_attempt_at"] = datetime.now(timezone.utc).isoformat()
        gaps = list(research.get("research_gaps") or []) if isinstance(research.get("research_gaps"), list) else []

        person = _text(research.get("decision_maker") or lead.get("person") or lead.get("contact_name"))
        role_evidence = _text(research.get("decision_maker_role_evidence") or research.get("decision_maker_title") or lead.get("contact_title"))
        contact_evidence = _text(research.get("decision_maker_evidence"))
        verified_status = _text(research.get("decision_maker_verification_status")).lower()

        if person and role_evidence and contact_evidence and verified_status != "verified":
            research["decision_maker_verification_status"] = "verified"
            verified_status = "verified"
        elif not person:
            if "decision_maker" not in gaps:
                gaps.append("decision_maker")
        elif not role_evidence:
            if "decision_maker_role" not in gaps:
                gaps.append("decision_maker_role")
        if not _text(research.get("business_context")):
            if "business_context" not in gaps:
                gaps.append("business_context")
        if not research.get("public_web_sources"):
            if "public_web_sources" not in gaps:
                gaps.append("public_web_sources")

        research["research_gaps"] = gaps
        research["fabricated_fields"] = []
        verified_fields = [key for key, value in research.items() if value not in (None, "", [], {}, ())]
        complete = bool(
            research.get("company_verified") is True
            and person
            and contact_evidence
            and verified_status == "verified"
        )

        lead["company_research"] = research
        lead["research_status"] = "complete" if complete else "research_required"
        lead["research_verified_fields"] = verified_fields
        stored = ctx.db.update_payload(str(lead.get("fingerprint") or ""), lead)
        if stored is None:
            raise ValueError(f"Lead not found for company research: {lead.get('fingerprint')}")

        if complete:
            fingerprint = str(stored.get("fingerprint") or "")
            enqueue(
                ctx.db,
                "qualification_a",
                {"lead": stored, "evidence_events": payload.get("evidence_events", []), "research_result": {"status": "complete", "verified_fields": verified_fields}},
                priority=9,
                dedupe_key=f"qualification_a:{fingerprint}",
            )

        result.update({
            "lead": stored,
            "research": research,
            "research_status": stored["research_status"],
            "verified_fields": verified_fields,
            "decision_maker_verified": verified_status == "verified",
            "fabricated_fields": [],
            "public_research_status": public.get("status") if isinstance(public, Mapping) else None,
            "handoff": "qualification_a" if complete else "research_required",
        })
        return result

    return handler


def _build_research_aware_sales_builder():
    from . import outreach_engine

    def sales_body(route: str, contact_name: str, company: str, signal: str, research: Mapping[str, Any] | None = None) -> str:
        research = research if isinstance(research, Mapping) else {}
        verified = []
        for key in ("business_context", "current_need_evidence", "recent_activity_evidence", "decision_maker_role_evidence"):
            value = _text(research.get(key))
            if value:
                verified.append(value)
        verified.extend(_evidence_lines(research, ("public_business_need_facts", "public_hiring_facts", "public_company_facts")))
        verified = list(dict.fromkeys(v for v in verified if v))
        need = _text(signal) or (verified[0] if verified else "the need you mentioned")
        offer = {
            "Thorio": "a verified remote tech hiring channel",
            "Shiftr": "AI, software, engineering, or dedicated-team support through the appropriate partner",
            "Paxus": "vetted technology talent through the appropriate referral process",
        }[route]
        context = ""
        if len(verified) > 1 and verified[1] != need:
            context = f" I also found public evidence around {verified[1][:500].rstrip('.!?')}."
        return (
            f"Hi {contact_name},\n\n"
            f"I reached out because of {need.rstrip('.!?')}."
            f" If that is still active at {company}, I would like to understand what is driving it and where the current approach is falling short.{context}\n\n"
            f"I work with {offer}. If there is a genuine fit, I can point you to the most relevant path rather than send a generic pitch.\n\n"
            f"Is this something you are actively working on now, or is the timing further out?\n\n"
            f"Best,\nThorio"
        )

    original_build = outreach_engine.build_outreach_decision

    def build_decision(lead: Mapping[str, Any], *, now=None):
        decision = original_build(lead, now=now)
        research = lead.get("company_research") if isinstance(lead.get("company_research"), Mapping) else {}
        new_body = sales_body(decision.route, decision.contact_name, _text(lead.get("company") or research.get("company")) or "your team", decision.buying_signal, research)
        return outreach_engine.OutreachDecision(
            route=decision.route,
            contact_name=decision.contact_name,
            contact_email=decision.contact_email,
            subject=decision.subject,
            body=new_body,
            evidence_refs=decision.evidence_refs,
            buying_signal=decision.buying_signal,
            next_state=decision.next_state,
            next_follow_up_at=decision.next_follow_up_at,
            stop_reason=decision.stop_reason,
        )

    outreach_engine.build_outreach_decision = build_decision
    return sales_body


def install() -> None:
    from . import agent_workers

    processor = agent_workers._PROCESSORS.get("company_research")
    if processor is not None and not getattr(processor, "_thorio_research_upgrade", False):
        patched = _research_handler(processor)
        patched._thorio_research_upgrade = True
        agent_workers._PROCESSORS["company_research"] = patched

    from . import outreach_engine
    if not getattr(outreach_engine.build_outreach_decision, "_thorio_sales_upgrade", False):
        upgraded = _build_research_aware_sales_builder()
        upgraded._thorio_sales_upgrade = True
