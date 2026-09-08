from .lead_identity import lead_identity
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re
from typing import Any, Dict, List


def normalize(value: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        (value or "").strip().lower(),
    )


@dataclass
class Lead:
    source: str
    source_id: str
    url: str

    company: str = ""
    person: str = ""
    signal: str = ""
    signal_type: str = ""
    source_url: str = ""
    job_title: str = ""
    discovered_at: str = ""

    # Explicit business-intent timestamps used by the qualification engine.
    # Discovery/update timestamps are deliberately separate from intent.
    need_at: str = ""
    current_need_at: str = ""
    hiring_need_at: str = ""
    inquiry_at: str = ""
    inquired_at: str = ""
    last_inquiry_at: str = ""
    last_contact_at: str = ""
    intent_at: str = ""

    route: str = "Review"
    potential_routes: List[str] = None

    # Company-specific qualification is authoritative for the three
    # businesses. The legacy fields remain for backward compatibility.
    qualification_results: Dict[str, Any] = None
    research_status: str = "not_started"

    status: str = "Unverified"
    evidence: str = ""

    possible_duplicate: bool = False
    fingerprint: str = ""

    qualified: bool = False
    review_status: str = "Review"
    qualification_status: str = "unverified"
    reason_not_qualified: str = ""

    contact_name: str = ""
    contact_title: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    linkedin_url: str = ""
    company_website: str = ""
    enrichment_status: str = "pending"

    # Paxus referral lifecycle state. These fields mirror the existing
    # PaxusReferral workflow so Lead records can carry the state durably.
    contact_communicated: bool = False
    contact_consent: bool = False
    warm_referral_ready: bool = False
    referral_submitted: bool = False
    paxus_accepted: bool = False
    referral_id: str = ""
    introduction_made: bool = False
    recruiting_status: str = "not_started"
    placement_count: int = 0
    client_payment_received: bool = False
    commission_due: bool = False
    submitted_at: str = ""
    accepted_at: str = ""
    introduction_deadline: str = ""
    introduced_at: str = ""

    def __post_init__(self):
        if self.potential_routes is None:
            self.potential_routes = []
        if self.qualification_results is None:
            self.qualification_results = {}

    def ensure_timestamp(self):
        if not self.discovered_at:
            self.discovered_at = datetime.now(
                timezone.utc
            ).isoformat()

    def compute_fingerprint(self):
        self.ensure_timestamp()

        identity_payload = {
            "source": self.source,
            "source_id": self.source_id,
            "url": self.url,
            "company": self.company,
            "person": self.person,
            "signal": self.signal,
        }

        self.fingerprint = lead_identity(identity_payload)

        return self.fingerprint

    def to_dict(self):
        self.compute_fingerprint()
        return asdict(self)
