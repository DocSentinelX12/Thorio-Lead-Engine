import json
import sqlite3
from pathlib import Path


class LeadDB:
    def __init__(self, data_dir="data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.path = self.data_dir / "leads.sqlite3"

        self.conn = sqlite3.connect(
            self.path,
            timeout=30,
        )

        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")

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

        self.conn.commit()

    def insert_if_new(self, payload):
        cursor = self.conn.execute(
            """
            INSERT OR IGNORE INTO leads
            (fingerprint, payload)
            VALUES (?, ?)
            """,
            (
                payload["fingerprint"],
                json.dumps(payload, ensure_ascii=False),
            ),
        )

        self.conn.commit()

        return cursor.rowcount == 1

    def pending(self, limit=50):
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

    def mark_synced(self, fingerprint):
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

    def mark_error(self, fingerprint, error):
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

    def set_checkpoint(self, collector, checkpoint):
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
                collector,
                checkpoint,
            ),
        )

        self.conn.commit()

    def get_checkpoint(self, collector):
        row = self.conn.execute(
            """
            SELECT checkpoint
            FROM checkpoints
            WHERE collector = ?
            """,
            (collector,),
        ).fetchone()

        return row[0] if row else ""

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
