from .models import Lead


QUALIFIED_STATUSES = {
    "qualified",
    "approved",
    "accepted",
}


class Dedupe:
    """
    Final duplicate gate.

    Dedupe is intentionally strict.

    This class answers one question only:

        "Has this exact lead fingerprint already been accepted?"

    It does NOT decide whether a lead is qualified.
    It does NOT reject leads because they are unqualified.
    The pipeline is responsible for keeping discovered leads available
    for qualification before this final gate is used for delivery.
    """

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _qualification_status(payload):
        """
        Return the normalized qualification status stored on a lead.
        """

        if not isinstance(payload, dict):
            return ""

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
        Strict duplicate acceptance.

        A new fingerprint is accepted and persisted.

        An existing fingerprint is rejected.

        Qualification is NOT performed here.

        This preserves the original database invariant:
        one fingerprint = one stored discovery.
        """

        payload = lead.to_dict()

        fingerprint = payload.get("fingerprint")

        if not fingerprint:
            lead.compute_fingerprint()
            fingerprint = lead.fingerprint
            payload = lead.to_dict()

        return self.db.insert_if_new(payload)
