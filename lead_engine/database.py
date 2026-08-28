import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional


class LeadDB:
    def __init__(self, data_dir="data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.path = self.data_dir / "leads.sqlite3"

        self.conn = sqlite3.connect(
            self.path,
            timeout=30,
        )

        self.conn.execute(
            "PRAGMA journal_mode=WAL"
        )
        self.conn.execute(
            "PRAGMA synchronous=FULL"
        )
        self.conn.execute(
            "PRAGMA foreign_keys=ON"
        )

        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                fingerprint TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                synced INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checkpoints (
                collector TEXT PRIMARY KEY,
                checkpoint TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        self.conn.commit()

    def insert_if_new(
        self,
        payload: Dict[str, Any],
    ) -> bool:
        if not isinstance(payload, dict):
            raise ValueError(
                "Lead payload must be an object."
            )

        fingerprint = payload.get("fingerprint")

        if not fingerprint:
            raise ValueError(
                "Lead payload must contain a fingerprint."
            )

        serialized = json.dumps(
            payload,
            ensure_ascii=False,
        )

        cursor = self.conn.execute(
            """
            INSERT OR IGNORE INTO leads
            (fingerprint, payload)
            VALUES (?, ?)
            """,
            (
                str(fingerprint),
                serialized,
            ),
        )

        self.conn.commit()

        return cursor.rowcount == 1

    def get(
        self,
        fingerprint: str,
    ) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """
            SELECT payload
            FROM leads
            WHERE fingerprint = ?
            """,
            (fingerprint,),
        ).fetchone()

        if not row:
            return None

        payload = json.loads(row[0])

        if not isinstance(payload, dict):
            raise ValueError(
                "Stored lead payload must be an object."
            )

        return payload

    def update_payload(
        self,
        fingerprint: str,
        updates: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(updates, dict):
            raise ValueError(
                "Lead updates must be an object."
            )

        current = self.get(fingerprint)

        if current is None:
            return None

        current.update(updates)

        self.conn.execute(
            """
            UPDATE leads
            SET payload = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE fingerprint = ?
            """,
            (
                json.dumps(
                    current,
                    ensure_ascii=False,
                ),
                fingerprint,
            ),
        )

        self.conn.commit()

        return current

    def pending(self, limit=50):
        if not isinstance(limit, int) or isinstance(
            limit,
            bool,
        ):
            raise ValueError(
                "Pending limit must be an integer."
            )

        if limit <= 0:
            raise ValueError(
                "Pending limit must be greater than zero."
            )

        return self.conn.execute(
            """
            SELECT fingerprint, payload, attempts
            FROM leads
            WHERE synced = 0
            ORDER BY rowid
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def mark_synced(
        self,
        fingerprint,
    ):
        self.conn.execute(
            """
            UPDATE leads
            SET synced = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE fingerprint = ?
            """,
            (fingerprint,),
        )

        self.conn.commit()

    def mark_error(
        self,
        fingerprint,
        error,
    ):
        self.conn.execute(
            """
            UPDATE leads
            SET attempts = attempts + 1,
                last_error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE fingerprint = ?
            """,
            (
                str(error)[:4000],
                fingerprint,
            ),
        )

        self.conn.commit()

    def set_checkpoint(
        self,
        collector,
        checkpoint,
    ):
        if not collector:
            raise ValueError(
                "Checkpoint collector is required."
            )

        if checkpoint is None:
            raise ValueError(
                "Checkpoint value is required."
            )

        self.conn.execute(
            """
            INSERT INTO checkpoints
            (collector, checkpoint)
            VALUES (?, ?)

            ON CONFLICT(collector)
            DO UPDATE SET
                checkpoint = excluded.checkpoint,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                str(collector),
                str(checkpoint),
            ),
        )

        self.conn.commit()

    def get_checkpoint(
        self,
        collector,
    ):
        row = self.conn.execute(
            """
            SELECT checkpoint
            FROM checkpoints
            WHERE collector = ?
            """,
            (collector,),
        ).fetchone()

        return row[0] if row else ""

    def get_state(
        self,
        key: str,
    ) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """
            SELECT value
            FROM state
            WHERE key = ?
            """,
            (key,),
        ).fetchone()

        if not row:
            return None

        value = json.loads(row[0])

        if not isinstance(value, dict):
            raise ValueError(
                "Stored state value must be an object."
            )

        return value

    def set_state(
        self,
        key: str,
        value: Dict[str, Any],
    ) -> None:
        if not key:
            raise ValueError(
                "State key is required."
            )

        if not isinstance(value, dict):
            raise ValueError(
                "State value must be an object."
            )

        self.conn.execute(
            """
            INSERT INTO state
            (key, value)
            VALUES (?, ?)

            ON CONFLICT(key)
            DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                key,
                json.dumps(
                    value,
                    ensure_ascii=False,
                ),
            ),
        )

        self.conn.commit()

    def stats(self):
        return self.conn.execute(
            """
            SELECT
                COUNT(*),
                COALESCE(SUM(synced), 0),
                COALESCE(
                    SUM(
                        CASE
                            WHEN synced = 0 THEN 1
                            ELSE 0
                        END
                    ),
                    0
                )
            FROM leads
            """
        ).fetchone()

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        self.close()
        return False


if __name__ == "__main__":
    print(
        "Lead database loaded. "
        "SQLite persistence is ready."
    )
