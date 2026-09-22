from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .database import LeadDB


class WorkerLeadDB(LeadDB):
    """Lightweight thread-local LeadDB connection for specialist execution.

    The primary LeadDB constructor performs integrity recovery and schema
    migration. Those are startup responsibilities and are unsafe to repeat for
    every concurrent specialist slot against a large production SQLite file.
    This worker connection reuses the already-initialized schema and opens only
    a thread-local WAL connection to the existing database.
    """

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "leads.sqlite3"
        self.recovered_corrupt_database = False
        self._batch_write_depth = 0
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA foreign_keys=ON")
