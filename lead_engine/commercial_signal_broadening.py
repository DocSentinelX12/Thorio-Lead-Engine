"""Evidence-grounded Phase 2 commercial signal broadening."""

BROADENING_CONTRACT_VERSION = "1"

INDIRECT_SIGNAL_PATTERNS = (
    ("vendor_evaluation", "evaluating vendors"),
    ("vendor_evaluation", "evaluating providers"),
    ("vendor_evaluation", "evaluating solutions"),
    ("vendor_evaluation", "exploring vendors"),
    ("vendor_evaluation", "exploring providers"),
    ("vendor_evaluation", "exploring solutions"),
    ("vendor_evaluation", "exploring options"),
    ("vendor_evaluation", "evaluating options"),
    ("vendor_evaluation", "reviewing vendors"),
    ("vendor_evaluation", "reviewing providers"),
    ("vendor_evaluation", "reviewing solutions"),
    ("partner_evaluation", "looking for a partner"),
    ("partner_evaluation", "looking for partners"),
    ("partner_evaluation", "evaluating partners"),
    ("partner_evaluation", "exploring partnership options"),
    ("delivery_planning", "planning a rebuild"),
    ("delivery_planning", "planning to rebuild"),
    ("delivery_planning", "preparing for launch"),
    ("delivery_planning", "preparing to launch"),
    ("engineering_capacity", "scaling the engineering team"),
    ("engineering_capacity", "expanding the engineering team"),
    ("engineering_capacity", "adding engineering capacity"),
    ("technology_change", "replacing our legacy system"),
    ("technology_change", "modernizing our stack"),
    ("technology_change", "migrating our infrastructure"),
    ("technology_change", "moving our infrastructure to the cloud"),
)

STRUCTURAL_SIGNAL_PATTERNS = (
    ("funding_execution", "raised seed funding"),
    ("funding_execution", "raised a seed round"),
    ("funding_execution", "raised series a"),
    ("funding_execution", "raised series b"),
    ("funding_execution", "new funding"),
    ("funding_execution", "recent funding"),
    ("funding_execution", "recently funded"),
    ("product_event", "new product launch"),
    ("product_event", "product launch"),
    ("product_event", "launching a new product"),
    ("product_event", "launched a new product"),
    ("enterprise_event", "new enterprise customer"),
    ("enterprise_event", "new enterprise contract"),
    ("enterprise_event", "enterprise contract"),
    ("enterprise_event", "enterprise rollout"),
    ("enterprise_event", "enterprise expansion"),
    ("market_expansion", "expanding into a new market"),
    ("market_expansion", "expanding into new markets"),
    ("market_expansion", "entered a new market"),
    ("market_expansion", "entering a new market"),
    ("market_expansion", "international expansion"),
    ("corporate_event", "acquisition"),
    ("corporate_event", "acquired"),
)

TECHNICAL_CONTEXT_TERMS = (
    "software", "engineering", "developer", "developers", "engineer",
    "technology", "technical", "platform", "product", "saas", "api",
    "application", "app", "mobile", "cloud", "infrastructure", "data",
    "ai", "artificial intelligence", "machine learning", "llm", "automation",
    "integration", "system", "systems", "digital", "website", "web",
)

SPECULATIVE_MARKERS = (
    "might", "may", "could", "possibly", "potentially", "perhaps",
    "thinking about", "considering",
)

NEGATION_MARKERS = (
    "not", "no", "never", "don't", "do not", "doesn't", "does not",
    "isn't", "is not", "wasn't", "was not", "without",
)

HISTORICAL_MARKERS = (
    "last year", "previously", "historically", "years ago", "had announced",
    "was acquired", "were acquired", "previous announcement",
    "in 2020", "in 2021", "in 2022", "in 2023", "in 2024", "in 2025",
)

FIRST_PERSON_MARKERS = ("we ", "we're", "we are", "our ", "us ", "i'm", "i am", "my ")


def _text(value):
    return str(value or "").strip()


def _normalize(value):
    return " ".join(_text(value).lower().split())


def _dedupe(values):
    return list(dict.fromkeys(value for value in values if value))


def _context(text, start, end, radius=220):
    return " ".join(text[max(0, start-radius):min(len(text), end+radius)].split())


def _sentence_bounds(text, start, end):
    left = max(text.rfind(".", 0, start), text.rfind("!", 0, start), text.rfind("?", 0, start), text.rfind("\\n", 0, start)) + 1
    right_candidates = [value for value in (text.find(".", end), text.find("!", end), text.find("?", end), text.find("\\n", end)) if value >= 0]
    right = min(right_candidates) if right_candidates else len(text)
    return left, right


def _sentence(text, start, end):
    left, right = _sentence_bounds(text, start, end)
    return text[left:right], left, right


def _near(text, start, markers, radius):
    window = _normalize(text[max(0, start-radius):start])
    return next((marker for marker in markers if marker in window), "")


def _attribution(text, company, start, end):
    sentence, _, _ = _sentence(text, start, end)
    window = _normalize(sentence)
    company_name = _normalize(company)
    if company_name and company_name in window:
        return "company_named", True
    if any(marker in window for marker in FIRST_PERSON_MARKERS):
        return "first_person", True
    return "unattributed", False

