from typing import Any, Dict, Iterable, List
import re
from urllib.parse import urlparse

from .free_sources import HIGH_VALUE_COMMERCIAL_SIGNAL_TERMS
from .commercial_signal_broadening import extract_broadened_signals_from_record


REQUIRED_FIELDS = {
    "source",
    "source_id",
    "url",
    "company",
    "signal",
    "evidence",
}

OPTIONAL_TEXT_FIELDS = {
    "person",
    "contact_name",
    "contact_title",
    "contact_phone",
    "enrichment_status",
    "reason_not_qualified",
}

OPTIONAL_URL_FIELDS = {
    "linkedin_url",
    "company_website",
}

OPTIONAL_EMAIL_FIELDS = {
    "contact_email",
}


def _validate_text_field(field: str, value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError(f"Lead field '{field}' must be a string.")
    if not value.strip():
        raise ValueError(f"Lead field '{field}' cannot be empty.")
    if any(ord(character) < 32 and character not in ("\t", "\n", "\r") for character in value):
        raise ValueError(f"Lead field '{field}' contains invalid control characters.")


def _validate_url_field(field: str, value: Any) -> None:
    _validate_text_field(field, value)
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Lead field '{field}' must be an HTTP or HTTPS URL.")
    if not parsed.netloc:
        raise ValueError(f"Lead field '{field}' must contain a valid host.")


def _validate_email_field(field: str, value: Any) -> None:
    _validate_text_field(field, value)
    email = value.strip()
    if email.count("@") != 1:
        raise ValueError(f"Lead field '{field}' must contain a valid email address.")
    local_part, domain = email.split("@")
    if not local_part or not domain:
        raise ValueError(f"Lead field '{field}' must contain a valid email address.")
    if any(character.isspace() for character in email):
        raise ValueError(f"Lead field '{field}' must contain a valid email address.")
    if "." not in domain:
        raise ValueError(f"Lead field '{field}' must contain a valid email address.")


def validate_lead_input(lead: Dict[str, Any]) -> None:
    """
    Validate discovered lead data at the production input boundary.

    Discovery validation intentionally does not require contact,
    qualification, referral, consent, or routing fields. Those
    belong to later lifecycle boundaries.

    Invalid records raise ValueError so SourceRunner can isolate
    the bad record without stopping the source or remaining leads.
    """
    if not isinstance(lead, dict):
        raise ValueError("Lead input must be an object.")
    for field in REQUIRED_FIELDS:
        if field not in lead:
            raise ValueError(f"Lead field '{field}' is required.")
        _validate_text_field(field, lead[field])
    _validate_url_field("url", lead["url"])
    for field in OPTIONAL_TEXT_FIELDS:
        if field in lead and lead[field] is not None:
            _validate_text_field(field, lead[field])
    for field in OPTIONAL_URL_FIELDS:
        if field in lead and lead[field] is not None:
            _validate_url_field(field, lead[field])
    for field in OPTIONAL_EMAIL_FIELDS:
        if field in lead and lead[field] is not None:
            _validate_email_field(field, lead[field])


def _sanitize_text(value: str) -> str:
    """Remove non-JSON-safe ASCII control characters from source text."""
    return "".join(character for character in value if ord(character) >= 32 or character in ("\t", "\n", "\r"))


def _commercial_signal_matches(text: str) -> List[str]:
    """Extract only exact configured commercial triggers from observed source text."""
    normalized = " ".join(text.lower().split())
    return [term for term in HIGH_VALUE_COMMERCIAL_SIGNAL_TERMS if term in normalized]


def _commercial_signal_context(text: str, matches: List[str]) -> List[str]:
    """Preserve bounded observed context around each exact commercial trigger."""
    contexts: List[str] = []
    for term in matches:
        match = re.search(re.escape(term), text, flags=re.IGNORECASE)
        if not match:
            continue
        start = max(0, match.start() - 180)
        end = min(len(text), match.end() + 180)
        context = " ".join(text[start:end].split())
        if context and context not in contexts:
            contexts.append(context)
    return contexts


def _apply_universal_commercial_signals(normalized: Dict[str, Any]) -> None:
    """Apply the canonical commercial extraction contract to every ingestion lane."""
    observed = " ".join(
        str(normalized.get(field) or "").strip()
        for field in ("signal", "evidence", "job_title", "company")
        if str(normalized.get(field) or "").strip()
    )
    matches = _commercial_signal_matches(observed)
    if not matches:
        return

    existing_type = str(normalized.get("signal_type") or "").strip().lower()
    if existing_type in {"", "business_intent", "hiring", "discovery"}:
        normalized["signal_type"] = "commercial_intent"

    existing_strength = str(normalized.get("signal_strength") or "").strip().lower()
    if existing_strength not in {"compound", "explicit"}:
        normalized["signal_strength"] = "compound" if len(matches) >= 2 else "explicit"

    normalized["signal_matches"] = list(dict.fromkeys(matches))
    normalized["signal_context"] = _commercial_signal_context(observed, matches)


def normalize_lead_input(lead: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize incoming discovery data and apply the universal commercial
    signal extraction contract without making qualification, routing,
    or deduplication decisions.

    External sources can contain embedded ASCII control characters,
    especially copied HTML/text evidence. Clean those characters at
    the ingestion boundary so one malformed source record cannot
    interrupt the production collection stream.
    """
    if not isinstance(lead, dict):
        raise ValueError("Lead input must be an object.")
    normalized = dict(lead)
    text_fields = REQUIRED_FIELDS | OPTIONAL_TEXT_FIELDS | OPTIONAL_URL_FIELDS | OPTIONAL_EMAIL_FIELDS
    for field in text_fields:
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = _sanitize_text(value).strip()
    validate_lead_input(normalized)
    _apply_universal_commercial_signals(normalized)
    broadened = extract_broadened_signals_from_record(normalized)
    if broadened.get("matches"):
        normalized["commercial_signal_broadening"] = broadened
        eligible = [
            item
            for item in broadened["matches"]
            if item.get("promotion_eligible") is True
        ]
        if eligible:
            existing_type = str(normalized.get("signal_type") or "").strip().lower()
            if existing_type in {"", "business_intent", "hiring", "discovery"}:
                normalized["signal_type"] = "commercial_intent"
            existing_matches = normalized.get("signal_matches")
            if not isinstance(existing_matches, list):
                existing_matches = []
            broadened_matches = [
                str(item.get("phrase") or "").strip()
                for item in eligible
                if str(item.get("phrase") or "").strip()
            ]
            normalized["signal_matches"] = list(
                dict.fromkeys(existing_matches + broadened_matches)
            )
            normalized["signal_strength"] = (
                "compound"
                if len(normalized["signal_matches"]) >= 2
                else "explicit"
            )
            existing_context = normalized.get("signal_context")
            if not isinstance(existing_context, list):
                existing_context = []
            normalized["signal_context"] = list(
                dict.fromkeys(
                    existing_context
                    + [
                        str(item.get("evidence_context") or "").strip()
                        for item in eligible
                        if str(item.get("evidence_context") or "").strip()
                    ]
                )
            )
    # The collector's canonical field is company_website. Preserve that
    # exact observed URL under the website alias consumed by public research.
    if normalized.get("company_website") and not normalized.get("website"):
        normalized["website"] = normalized["company_website"]
    return normalized


def collect(leads: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize a batch of discovered leads.

    Invalid leads are rejected instead of silently entering
    the processing system. SourceRunner is responsible for
    isolating rejected records from the remaining source data.
    """
    collected = []
    for lead in leads:
        collected.append(normalize_lead_input(lead))
    return collected


if __name__ == "__main__":
    print("Lead collector loaded. Use collect() to normalize leads.")
