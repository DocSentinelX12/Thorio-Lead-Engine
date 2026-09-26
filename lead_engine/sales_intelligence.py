from __future__ import annotations

"""Evidence grounded sales intelligence for the autonomous high ticket closer.

This module deliberately separates verified facts from inferences and hypotheses.
It never fabricates prospect facts. Every prospect specific fact exposed to the
closer must carry provenance from the exact opportunity research package.
"""

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

FORBIDDEN_DASHES = ("\u2013", "\u2014")
VERIFIED_STATUSES = frozenset({"verified", "research_verified", "complete"})


class SalesIntelligenceError(ValueError):
    """Raised when a closer package cannot be proven safe and opportunity scoped."""


@dataclass(frozen=True)
class IntelligenceClaim:
    claim: str
    kind: str
    evidence_refs: tuple[str, ...]
    source_section: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "kind": self.kind,
            "evidence_refs": list(self.evidence_refs),
            "source_section": self.source_section,
        }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _verified(section: Any) -> bool:
    if not isinstance(section, Mapping):
        return False
    if section.get("verified") is True:
        return True
    return _text(section.get("verification_status") or section.get("status")).lower() in VERIFIED_STATUSES


def _refs(section: Any) -> tuple[str, ...]:
    if not isinstance(section, Mapping):
        return ()
    raw = section.get("evidence", [])
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes, Mapping)):
        return ()
    refs: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            ref = _text(item.get("url") or item.get("source_url") or item.get("evidence_url") or item.get("source_id"))
        else:
            ref = _text(item)
        if ref and ref not in refs:
            refs.append(ref)
    return tuple(refs)


def _section_claims(lead: Mapping[str, Any], key: str, label: str) -> list[IntelligenceClaim]:
    section = lead.get(key)
    if not _verified(section):
        return []
    refs = _refs(section)
    if not refs:
        raise SalesIntelligenceError(f"{key} is verified but has no provenance")
    summary = _text(section.get("summary"))
    if summary:
        return [IntelligenceClaim(summary, "verified_fact", refs, label)]
    claims: list[IntelligenceClaim] = []
    for field in ("current_need", "business_need", "need", "summary", "intent", "signal"):
        value = _text(section.get(field))
        if value:
            claims.append(IntelligenceClaim(value, "verified_fact", refs, label))
    return claims


def _all_verified_claims(lead: Mapping[str, Any]) -> list[IntelligenceClaim]:
    claims: list[IntelligenceClaim] = []
    mapping = (
        ("company_research", "company"),
        ("business_need_research", "business_need"),
        ("current_intent_research", "current_intent"),
        ("technical_product_hiring_research", "technical_product_hiring"),
        ("commercial_research", "commercial"),
        ("route_research", "route"),
    )
    for key, label in mapping:
        claims.extend(_section_claims(lead, key, label))
    return claims


def _identity(lead: Mapping[str, Any]) -> tuple[str, str]:
    fingerprint = _text(lead.get("fingerprint"))
    company = _text(lead.get("company"))
    if not fingerprint or not company:
        raise SalesIntelligenceError("exact opportunity fingerprint and company are required")
    company_research = lead.get("company_research")
    if not isinstance(company_research, Mapping):
        raise SalesIntelligenceError("company research is required")
    if company_research.get("company_verified") is not True:
        raise SalesIntelligenceError("company identity is not explicitly verified")
    return fingerprint, company


def _decision_maker(lead: Mapping[str, Any]) -> dict[str, Any]:
    company = lead.get("company_research")
    if not isinstance(company, Mapping):
        raise SalesIntelligenceError("company research is required")
    name = _text(company.get("decision_maker"))
    evidence = _text(company.get("decision_maker_evidence"))
    status = _text(company.get("decision_maker_verification_status")).lower()
    email = _text(company.get("decision_maker_email") or company.get("contact_email") or lead.get("contact_email"))
    if not name or not evidence or status != "verified" or not email:
        raise SalesIntelligenceError("verified decision maker identity, evidence, and contact are required")
    return {
        "name": name,
        "email": email,
        "evidence_refs": [evidence],
        "verification_status": "verified",
    }


def _research_digest(lead: Mapping[str, Any]) -> list[dict[str, Any]]:
    claims = _all_verified_claims(lead)
    return [claim.as_dict() for claim in claims]


def _current_need(lead: Mapping[str, Any], claims: list[IntelligenceClaim]) -> IntelligenceClaim:
    preferred = {"current_intent", "business_need", "technical_product_hiring", "route"}
    for claim in claims:
        if claim.source_section in preferred:
            return claim
    raise SalesIntelligenceError("no evidence backed current need is available")


def _unknowns(lead: Mapping[str, Any]) -> list[str]:
    gaps = lead.get("research_gaps")
    unknowns = gaps.get("unknowns", []) if isinstance(gaps, Mapping) else []
    result = [_text(item) for item in unknowns if _text(item)]
    return list(dict.fromkeys(result))


def _objection_strategy(need: IntelligenceClaim) -> list[dict[str, Any]]:
    refs = list(need.evidence_refs)
    return [
        {
            "objection": "timing",
            "approach": "Ask whether the researched need is still active before presenting a solution.",
            "evidence_refs": refs,
        },
        {
            "objection": "fit",
            "approach": "Connect the offer only to the verified need and invite the prospect to correct the assumption.",
            "evidence_refs": refs,
        },
        {
            "objection": "price",
            "approach": "Establish the actual scope and desired outcome before discussing commercial terms. Do not invent a budget.",
            "evidence_refs": refs,
        },
        {
            "objection": "already_has_solution",
            "approach": "Ask what is working and what remains unresolved rather than attacking the existing approach.",
            "evidence_refs": refs,
        },
    ]


def _persuasion_strategy(need: IntelligenceClaim) -> list[dict[str, Any]]:
    refs = list(need.evidence_refs)
    return [
        {
            "principle": "relevance",
            "action": "Lead with the verified situation instead of a generic pitch.",
            "evidence_refs": refs,
        },
        {
            "principle": "discovery",
            "action": "Use open questions to establish whether the observed need, impact, urgency, and desired outcome are accurate.",
            "evidence_refs": refs,
        },
        {
            "principle": "value",
            "action": "Tie proposed value to the problem the prospect confirms, not to an invented pain point.",
            "evidence_refs": refs,
        },
        {
            "principle": "risk_reduction",
            "action": "Reduce uncertainty with specific evidence and a clear next step rather than pressure.",
            "evidence_refs": refs,
        },
        {
            "principle": "commitment",
            "action": "When the prospect shows a genuine buying signal, ask directly for the smallest appropriate commercial next step.",
            "evidence_refs": refs,
        },
    ]


def _discovery_questions(need: IntelligenceClaim) -> list[str]:
    return [
        "Is this still an active priority for you?",
        "What is the main outcome you need from solving it?",
        "What is making the current situation difficult or slower than you want?",
        "What have you already tried?",
        "What would make a solution worth moving forward with?",
    ]


def build_closer_intelligence(lead: Mapping[str, Any]) -> dict[str, Any]:
    """Build a deterministic, evidence backed intelligence package for one opportunity."""
    fingerprint, company = _identity(lead)
    decision_maker = _decision_maker(lead)
    claims = _all_verified_claims(lead)
    need = _current_need(lead, claims)
    evidence = _research_digest(lead)

    for claim in evidence:
        if claim["kind"] != "verified_fact" or not claim["evidence_refs"]:
            raise SalesIntelligenceError("every closer fact must be explicitly evidenced")

    return {
        "schema_version": "2",
        "opportunity_fingerprint": fingerprint,
        "company": company,
        "decision_maker": decision_maker,
        "verified_facts": evidence,
        "primary_need": need.as_dict(),
        "unknowns": _unknowns(lead),
        "persuasion_strategy": _persuasion_strategy(need),
        "objection_strategy": _objection_strategy(need),
        "discovery_questions": _discovery_questions(need),
        "conversation_rules": [
            "Use only facts belonging to this opportunity.",
            "Treat inferred motivations as hypotheses until the prospect confirms them.",
            "Never claim a budget, urgency, pain, authority, outcome, or relationship that research does not establish.",
            "Invite correction when an interpretation may be wrong.",
            "Stop when the prospect declines or opts out.",
            "Remain professional and respectful throughout the conversation.",
        ],
        "provenance": {
            "source": "canonical_research_sections",
            "evidence_refs": sorted({ref for claim in claims for ref in claim.evidence_refs}),
            "claim_count": len(claims),
        },
    }


def validate_outreach_copy(text: str) -> tuple[bool, list[str]]:
    """Validate basic integrity requirements before generated copy reaches transport."""
    value = _text(text)
    errors: list[str] = []
    if not value:
        errors.append("empty_copy")
        return False, errors
    if any(dash in value for dash in FORBIDDEN_DASHES):
        errors.append("forbidden_dash_character")
    if re.search(r"\s{2,}", value):
        errors.append("repeated_whitespace")
    if re.search(r"[!?]{3,}", value):
        errors.append("repeated_terminal_punctuation")
    if re.search(r"\.{4,}", value):
        errors.append("repeated_periods")
    return not errors, errors
