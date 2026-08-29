import time
from typing import Any, Callable, Dict, List, Optional

from .airtable_approval import (
    fetch_approval_candidates,
)
from .airtable_approval_worker import (
    process_approval_batch,
)
from .database import LeadDB


class AirtableApprovalPoller:
    def __init__(
        self,
        db: LeadDB,
        fetch_pending: Optional[
            Callable[[], List[Dict[str, Any]]]
        ] = None,
        interval_seconds: int = 60,
    ):
        if interval_seconds < 1:
            raise ValueError(
                "interval_seconds must be at least 1"
            )

        self.db = db

        self.fetch_pending = (
            fetch_pending
            if fetch_pending is not None
            else fetch_approval_candidates
        )

        self.interval_seconds = interval_seconds
        self.running = False

    def poll_once(self) -> Dict[str, Any]:
        items = self.fetch_pending()

        if not items:
            return {
                "approved": [],
                "pending": [],
                "rejected": [],
                "already_processed": [],
                "approved_count": 0,
                "pending_count": 0,
                "rejected_count": 0,
                "already_processed_count": 0,
            }

        return process_approval_batch(
            db=self.db,
            items=items,
        )

    def run_once_safely(self) -> Dict[str, Any]:
        try:
            return self.poll_once()

        except Exception as exc:
            return {
                "status": "failed",
                "error": str(exc),
                "approved": [],
                "pending": [],
                "rejected": [],
                "already_processed": [],
                "approved_count": 0,
                "pending_count": 0,
                "rejected_count": 0,
                "already_processed_count": 0,
            }

    def run(
        self,
        max_cycles: Optional[int] = None,
        sleep: Callable[
            [float],
            None,
        ] = time.sleep,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        self.running = True
        cycles = 0

        try:
            while self.running:
                results.append(
                    self.run_once_safely()
                )

                cycles += 1

                if (
                    max_cycles is not None
                    and cycles >= max_cycles
                ):
                    break

                sleep(
                    self.interval_seconds
                )

        finally:
            self.running = False

        return results

    def stop(self) -> None:
        self.running = False
