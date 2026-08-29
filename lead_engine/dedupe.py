from typing import Optional

from .models import Lead


class Dedupe:
    """
    Qualification-aware deduplication.

    A lead is only considered a true duplicate when the existing
    database record represents an already-established lead.

    A previously seen lead that has not yet been qualified must
    remain eligible for qualification rather than being counted as
    a duplicate.
    """

    QUALIFIED_STATUSES = {
        "Qualified",
    }

    REJECTED_STATUSES = {
        "Not Qualified",
    }

    REVIEW_STATUSES = {
        "In Review",
        "Review",
    }

    UNVERIFIED_STATUSES = {
        "",
        "Unverified",
        "Unknown",
        None,
    }

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _status(payload: dict) -> Optional[str]:
        """
        Return the normalized qualification status.
        """

        status = payload.get("status")

        if status is None:
            return None

        return str(status).strip()

    @staticmethod
    def _is_qualified(payload: dict) -> bool:
        """
        Return True only for an explicitly qualified lead.
        """

        if payload.get("qualified") is True:
            return True

        status = Dedupe._status(payload)

        return status in Dedupe.QUALIFIED_STATUSES

    @staticmethod
    def _is_rejected(payload: dict) -> bool:
        """
        Return True only for an explicitly rejected lead.
        """

        if payload.get("qualified") is False:
            status = Dedupe._status(payload)

            return status in Dedupe.REJECTED_STATUSES

        return False

    def accept(self, lead: Lead) -> bool:
        """
        Determine whether a discovered lead should enter processing.

        IMPORTANT:

        A matching fingerprint does NOT automatically mean duplicate.

        If the existing record is still unverified or in review, the
        newly discovered lead is allowed through so it can continue
        through qualification.

        A lead that is already Qualified is a true duplicate and is
        rejected.

        A lead that is explicitly Not Qualified is also not re-created,
        preventing previously rejected records from being endlessly
        reintroduced.

        New leads are inserted normally.
        """

        payload = lead.to_dict()

        fingerprint = payload.get("fingerprint")

        if not fingerprint:
            raise ValueError(
                "Lead payload must contain a fingerprint."
            )

        existing = self.db.get(str(fingerprint))

        # Brand-new lead.
        if existing is None:
            return self.db.insert_if_new(payload)

        # Already-qualified lead.
        #
        # This is the strongest definition of a true duplicate because
        # the system has already established this lead as a positive.
        if self._is_qualified(existing):
            return False

        # Explicitly rejected lead.
        #
        # Do not create another copy of a lead that has already been
        # reviewed and rejected.
        if self._is_rejected(existing):
            return False

        # Existing lead is still unverified or under review.
        #
        # It has NOT been established as a positive or negative.
        # Therefore it must remain eligible for qualification.
        #
        # Update the existing record with the newest discovered payload
        # while preserving its qualification state.
        status = self._status(existing)

        if (
            status in self.UNVERIFIED_STATUSES
            or status in self.REVIEW_STATUSES
            or not existing.get("qualified", False)
        ):
            updates = dict(payload)

            # Never overwrite an existing qualification decision.
            if "qualified" in existing:
                updates.pop("qualified", None)

            if "status" in existing:
                updates.pop("status", None)

            if "review_status" in existing:
                updates.pop("review_status", None)

            if "reason_not_qualified" in existing:
                updates.pop("reason_not_qualified", None)

            self.db.update_payload(
                str(fingerprint),
                updates,
            )

            return True

        # Defensive default.
        #
        # If an existing record has an unexpected state, do not silently
        # treat it as a positive lead.
        return True


if __name__ == "__main__":
    print(
        "Qualification-aware dedupe module loaded."
    )
