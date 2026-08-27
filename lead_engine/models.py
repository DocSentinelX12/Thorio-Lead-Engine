from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import re


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


@dataclass
class Lead:
    source: str
    source_id: str
    url: str
    company: str = ""
    person: str = ""
    signal: str = ""
    discovered_at: str = ""
    route: str = "Review"
    status: str = "Unverified"
    evidence: str = ""
    possible_duplicate: bool = False
    fingerprint: str = ""

    def ensure_timestamp(self):
        if not self.discovered_at:
            self.discovered_at = datetime.now(timezone.utc).isoformat()

    def compute_fingerprint(self):
        self.ensure_timestamp()

        canonical = "|".join(
            [
                normalize(self.source),
                normalize(self.source_id),
                normalize(self.url),
                normalize(self.company),
                normalize(self.signal),
            ]
        )

        self.fingerprint = hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()

        return self.fingerprint

    def to_dict(self):
        self.compute_fingerprint()
        return asdict(self)
