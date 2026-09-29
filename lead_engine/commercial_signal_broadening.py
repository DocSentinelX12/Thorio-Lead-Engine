"""Evidence-grounded Phase 2 commercial signal broadening."""

from datetime import datetime, timezone
import re

BROADENING_CONTRACT_VERSION = "1"

INDIRECT_SIGNAL_PATTERNS = (
    ("vendor_evaluation", "evaluating vendors"), ("vendor_evaluation", "evaluating providers"), ("vendor_evaluation", "evaluating solutions"),
    ("vendor_evaluation", "exploring vendors"), ("vendor_evaluation", "exploring providers"), ("vendor_evaluation", "exploring solutions"), ("vendor_evaluation", "exploring options"),
    ("partner_evaluation", "looking for a partner"), ("partner_evaluation", "looking for partners"), ("partner_evaluation", "evaluating partners"), ("partner_evaluation", "exploring partnership options"),
    ("delivery_planning", "planning a rebuild"), ("delivery_planning", "planning to rebuild"), ("delivery_planning", "preparing for launch"), ("delivery_planning", "preparing to launch"),
    ("engineering_capacity", "scaling the engineering team"), ("engineering_capacity", "expanding the engineering team"), ("engineering_capacity", "adding engineering capacity"),
    ("technology_change", "replacing our legacy system"), ("technology_change", "modernizing our stack"), ("technology_change", "migrating our infrastructure"), ("technology_change", "moving our infrastructure to the cloud"),
)

STRUCTURAL_SIGNAL_PATTERNS = (
    ("funding_execution", "raised seed funding"), ("funding_execution", "raised a seed round"), ("funding_execution", "raised series a"), ("funding_execution", "raised series b"), ("funding_execution", "new funding"), ("funding_execution", "recent funding"), ("funding_execution", "recently funded"),
    ("product_event", "new product launch"), ("product_event", "product launch"), ("product_event", "launching a new product"), ("product_event", "launched a new product"),
    ("enterprise_event", "new enterprise customer"), ("enterprise_event", "new enterprise contract"), ("enterprise_event", "enterprise contract"), ("enterprise_event", "enterprise rollout"), ("enterprise_event", "enterprise expansion"),
    ("market_expansion", "expanding into a new market"), ("market_expansion", "expanding into new markets"), ("market_expansion", "entered a new market"), ("market_expansion", "entering a new market"), ("market_expansion", "international expansion"),
    ("corporate_event", "acquisition"), ("corporate_event", "acquired"),
)

TECHNICAL_CONTEXT_TERMS = ("software", "engineering", "developer", "developers", "engineer", "technology", "technical", "platform", "product", "saas", "api", "application", "app", "mobile", "cloud", "infrastructure", "data", "ai", "artificial intelligence", "machine learning", "llm", "automation", "integration", "system", "systems", "digital", "website", "web")
SPECULATIVE_MARKERS = ("might", "may", "could", "possibly", "potentially", "perhaps", "thinking about", "considering")
NEGATION_MARKERS = ("not", "no", "never", "don't", "do not", "doesn't", "does not", "isn't", "is not", "wasn't", "was not", "without", "no longer", "stopped", "ended", "cancelled", "canceled", "decided against", "decided not to")
HISTORICAL_MARKERS = ("last year", "previously", "historically", "years ago", "had announced", "was acquired", "were acquired", "previous announcement", "in 2020", "in 2021", "in 2022", "in 2023", "in 2024", "in 2025")
FIRST_PERSON_MARKERS = ("we ", "we're", "we are", "our ", "us ", "i'm", "i am", "my ")


def _text(value):
    return str(value or "").strip()


def _normalize(value):
    return " ".join(_text(value).lower().split())


def _dedupe(values):
    return list(dict.fromkeys(value for value in values if value))


def _context(text, start, end, radius=220):
    return " ".join(text[max(0, start-radius):min(len(text), end+radius)].split())


def _sentence_context(text, start, end):
    left = max(text.rfind(".", 0, start), text.rfind("!", 0, start), text.rfind("?", 0, start))
    right_candidates = [position for position in (text.find(".", end), text.find("!", end), text.find("?", end)) if position >= 0]
    right = min(right_candidates) if right_candidates else len(text)
    return " ".join(text[left + 1:right + 1].split())


def _near(text, start, markers, radius):
    window = _normalize(text[max(0, start-radius):start])
    return next((marker for marker in markers if marker in window), "")


def _sentence_has_marker(text, start, end, markers):
    sentence = _normalize(_sentence_context(text, start, end))
    return next((marker for marker in markers if marker in sentence), "")


def _has_technical_context(sentence):
    normalized = _normalize(sentence)
    return any(
        re.search(r"(?<!\\w)" + re.escape(term) + r"(?!\\w)", normalized)
        for term in TECHNICAL_CONTEXT_TERMS
    )


def _temporal_status(sentence, *, historical_markers):
    normalized = _normalize(sentence)
    current_year = datetime.now(timezone.utc).year
    years = [int(value) for value in re.findall(r"\b(?:19|20|21)\d{2}\b", normalized)]
    historical = any(marker in normalized for marker in historical_markers) or any(year < current_year for year in years)
    future = any(year > current_year for year in years)
    if historical:
        return "historical"
    if future:
        return "future"
    return "current_or_unspecified"


def _attribution(text, company, start, end):
    window = _normalize(_sentence_context(text, start, end))
    company_name = _normalize(company)
    if company_name and re.search(rf"(?<!\w){re.escape(company_name)}(?!\w)", window):
        return "company_named", True
    if any(marker in window for marker in FIRST_PERSON_MARKERS):
        return "first_person", True
    return "unattributed", False


def extract_broadened_signals(text, *, company=""):
    """Extract indirect and structural signals with fail-closed safety metadata."""
    raw = _text(text)
    matches = []
    if not raw:
        return {"contract_version": BROADENING_CONTRACT_VERSION, "matches": [], "promotion_eligible": False}

    def add(category, phrase, indirect):
        for found in re.finditer(re.escape(phrase), raw, flags=re.IGNORECASE):
            sentence = _sentence_context(raw, found.start(), found.end())
            attribution, attributed = _attribution(raw, company, found.start(), found.end())
            speculative = bool(_sentence_has_marker(raw, found.start(), found.end(), SPECULATIVE_MARKERS))
            temporal = _temporal_status(sentence, historical_markers=HISTORICAL_MARKERS)
            negated = bool(_sentence_has_marker(raw, found.start(), found.end(), NEGATION_MARKERS))
            technical = _has_technical_context(sentence)
            certainty = "speculative" if speculative else ("exploratory" if indirect else "observed")
            promotion = indirect and attributed and not speculative and temporal == "current_or_unspecified" and not negated and technical
            matches.append({
                "signal_id": category, "category": category, "phrase": found.group(0),
                "evidence_context": _context(raw, found.start(), found.end()),
                "__dedupe_context": sentence,
                "observation_key": f"{category}|{_normalize(found.group(0))}|{_normalize(sentence)}",
                "attribution": attribution, "temporal_status": temporal, "certainty": certainty,
                "negated": negated, "technical_context": technical, "promotion_eligible": promotion,
            })

    for category, phrase in INDIRECT_SIGNAL_PATTERNS:
        add(category, phrase, True)
    for category, phrase in STRUCTURAL_SIGNAL_PATTERNS:
        add(category, phrase, False)

    deduped, seen = [], set()
    for item in matches:
        key = item["observation_key"]
        if key not in seen:
            seen.add(key)
            item.pop("__dedupe_context", None)
            deduped.append(item)

    eligible = [item for item in deduped if item["promotion_eligible"]]
    reasons = []
    if any(item["attribution"] == "unattributed" for item in deduped): reasons.append("unattributed_signal_preserved_not_promoted")
    if any(item["temporal_status"] == "historical" for item in deduped): reasons.append("historical_signal_preserved_not_promoted")
    if any(item["temporal_status"] == "future" for item in deduped): reasons.append("future_signal_preserved_not_promoted")
    if any(item["certainty"] == "speculative" for item in deduped): reasons.append("speculative_signal_preserved_not_promoted")
    if any(item["negated"] for item in deduped): reasons.append("negated_signal_preserved_not_promoted")
    if any(item["category"] in {"funding_execution", "product_event", "enterprise_event", "market_expansion", "corporate_event"} for item in deduped): reasons.append("structural_event_requires_current_need_or_corroboration")
    return {"contract_version": BROADENING_CONTRACT_VERSION, "matches": deduped, "promotion_eligible": bool(eligible), "promotion_count": len(eligible), "promotion_reason": "verified_attributed_current_or_unspecified_signal" if eligible else "no_single_observation_safe_for_commercial_intent_promotion", "safety_reasons": _dedupe(reasons)}


def extract_broadened_signals_from_record(record):
    if not hasattr(record, "get"):
        raise ValueError("record must be a mapping.")
    company = _text(record.get("company"))
    matches = []
    for field in ("signal", "evidence", "job_title"):
        observed = _text(record.get(field))
        if not observed:
            continue
        extracted = extract_broadened_signals(observed, company=company)
        for item in extracted.get("matches", []):
            enriched = dict(item)
            enriched["source_field"] = field
            matches.append(enriched)
    deduped, seen = [], set()
    for item in matches:
        key = (item.get("source_field"), item.get("observation_key"))
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    eligible = [item for item in deduped if item.get("promotion_eligible") is True]
    reasons = []
    if any(item.get("attribution") == "unattributed" for item in deduped): reasons.append("unattributed_signal_preserved_not_promoted")
    if any(item.get("temporal_status") == "historical" for item in deduped): reasons.append("historical_signal_preserved_not_promoted")
    if any(item.get("temporal_status") == "future" for item in deduped): reasons.append("future_signal_preserved_not_promoted")
    if any(item.get("certainty") == "speculative" for item in deduped): reasons.append("speculative_signal_preserved_not_promoted")
    if any(item.get("negated") is True for item in deduped): reasons.append("negated_signal_preserved_not_promoted")
    if any(item.get("category") in {"funding_execution", "product_event", "enterprise_event", "market_expansion", "corporate_event"} for item in deduped): reasons.append("structural_event_requires_current_need_or_corroboration")
    return {"contract_version": BROADENING_CONTRACT_VERSION, "matches": deduped, "promotion_eligible": bool(eligible), "promotion_count": len(eligible), "promotion_reason": "verified_attributed_current_or_unspecified_signal" if eligible else "no_single_observation_safe_for_commercial_intent_promotion", "safety_reasons": _dedupe(reasons)}
