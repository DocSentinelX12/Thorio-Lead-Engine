import json
import os
import sqlite3
from typing import Any, Dict, List, Optional


DEFAULT_DB_PATH = os.getenv(
    "LEAD_ENGINE_DB",
    "data/lead_engine.db",
)


class LeadQueue:
    """
    Persistent local queue for lead records.

    SQLite is used so leads survive:
    - application restarts
    - Airtable outages
    - network failures
    - interrupted synchronization

    Airtable is a downstream review system, not the source of truth.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path

        directory = os.path.dirname(db_path)

        if directory:
            os.makedirs(directory, exist_ok=True)

        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)

        connection.row_factory = sqlite3.Row

        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    duplicate_key TEXT UNIQUE,
                    lead_json TEXT NOT NULL,
                    sync_status TEXT NOT NULL DEFAULT 'pending',
                    sync_attempts INTEGER NOT NULL DEFAULT 0,
                    last_sync_error TEXT,
                    airtable_record_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_leads_sync_status
                ON leads(sync_status)
                """
            )

            connection.commit()

    def add(
        self,
        lead: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Add a lead to the permanent local queue.

        Duplicate keys prevent the same lead from being inserted twice.
        """

        duplicate_key = lead.get("duplicate_key")

        if not duplicate_key:
            raise ValueError(
                "Lead must contain a duplicate_key before entering the queue."
            )

        lead_json = json.dumps(
            lead,
            ensure_ascii=False,
            sort_keys=True,
        )

        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT *
                FROM leads
                WHERE duplicate_key = ?
                """,
                (duplicate_key,),
            ).fetchone()

            if existing:
                return self._row_to_dict(existing)

            cursor = connection.execute(
                """
                INSERT INTO leads (
                    duplicate_key,
                    lead_json,
                    sync_status
                )
                VALUES (?, ?, 'pending')
                """,
                (
                    duplicate_key,
                    lead_json,
                ),
            )

            connection.commit()

            row = connection.execute(
                """
                SELECT *
                FROM leads
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()

            return self._row_to_dict(row)

    def get(
        self,
        lead_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve one lead from the local queue.
        """

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM leads
                WHERE id = ?
                """,
                (lead_id,),
            ).fetchone()

            if not row:
                return None

            return self._row_to_dict(row)

    def pending(
        self,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Return leads that still need Airtable synchronization.
        """

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM leads
                WHERE sync_status IN ('pending', 'failed')
                ORDER BY id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            return [
                self._row_to_dict(row)
                for row in rows
            ]

    def mark_synced(
        self,
        lead_id: int,
        airtable_record_id: Optional[str] = None,
    ) -> None:
        """
        Mark a local lead as successfully synchronized.
        """

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE leads
                SET
                    sync_status = 'synced',
                    airtable_record_id = ?,
                    last_sync_error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    airtable_record_id,
                    lead_id,
                ),
            )

            connection.commit()

    def mark_failed(
        self,
        lead_id: int,
        error: str,
    ) -> None:
        """
        Record a synchronization failure without removing the lead.
        """

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE leads
                SET
                    sync_status = 'failed',
                    sync_attempts = sync_attempts + 1,
                    last_sync_error = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    error,
                    lead_id,
                ),
            )

            connection.commit()

    def count(
        self,
        status: Optional[str] = None,
    ) -> int:
        """
        Count local leads.

        If status is supplied, count only that status.
        """

        with self._connect() as connection:
            if status:
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM leads
                    WHERE sync_status = ?
                    """,
                    (status,),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM leads
                    """
                ).fetchone()

            return int(row["count"])

    @staticmethod
    def _row_to_dict(
        row: sqlite3.Row,
    ) -> Dict[str, Any]:
        """
        Convert a database row into a normal Python dictionary.
        """

        lead = json.loads(row["lead_json"])

        lead["_queue_id"] = row["id"]
        lead["_sync_status"] = row["sync_status"]
        lead["_sync_attempts"] = row["sync_attempts"]
        lead["_last_sync_error"] = row["last_sync_error"]
        lead["_airtable_record_id"] = row["airtable_record_id"]
        lead["_created_at"] = row["created_at"]
        lead["_updated_at"] = row["updated_at"]

        return lead


if __name__ == "__main__":
    queue = LeadQueue()

    print(
        "Lead queue initialized."
        f" Total leads: {queue.count()}"
        f" | Pending: {queue.count('pending')}"
        f" | Failed: {queue.count('failed')}"
        f" | Synced: {queue.count('synced')}"
  )
