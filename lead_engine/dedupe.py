from .models import Lead


QUALIFIED_STATUSES = {
    "qualified",
    "approved",
    "accepted",
}


class Dedupe:
    """
    Final duplicate gate.

    A lead is a true duplicate only when the same fingerprint already
    belongs to a lead that has been explicitly qualified/approved.

    Unverified, in-review, and not-qualified discoveries are NOT treated
    as duplicates. They must remain eligible to be evaluated again.
    """

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _qualification_status(payload):
        """
        Read qualification state from the supported fields used by the
        lead lifecycle.

        Older records may use qualification_status or qualification.
        Human qualification currently writes status/review_status.
        """
        values = (
            payload.get("qualification_status"),
            payload.get("qualification"),
            payload.get("review_status"),
            payload.get("status"),
        )

        for value in values:
            if value is None:
                continue

            normalized = str(value).strip().lower()

            if normalized:
                return normalized

        return ""

    def accept(self, lead: Lead) -> bool:
        """
        Return True when this lead is allowed through the duplicate gate.

        Important:
        - New lead -> accepted.
        - Existing unverified lead -> accepted.
        - Existing in-review lead -> accepted.
        - Existing not-qualified lead -> accepted.
        - Existing qualified/approved lead -> rejected as duplicate.
        """
        payload = lead.to_dict()

        fingerprint = payload.get("fingerprint")

        if not fingerprint:
            lead.compute_fingerprint()
            fingerprint = lead.fingerprint
            payload = lead.to_dict()

        existing = self.db.get(fingerprint)

        if existing is None:
            return self.db.insert_if_new(payload)

        status = self._qualification_status(existing)

        if status in QUALIFIED_STATUSES:
            return False

        # The existing record has not been qualified.
        #
        # Do NOT reject this discovery. Refresh the stored discovery so
        # the lead can continue through qualification.
        updated = self.db.update_payload(
            fingerprint,
            payload,
        )

        return updated is not None
