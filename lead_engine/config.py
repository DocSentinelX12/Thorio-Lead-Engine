import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BATCH_SIZE = 50


@dataclass
class LeadEngineConfig:
    """
    Central configuration for the Lead Engine.

    Secrets are read from environment variables only.
    They are never stored in source code.
    """

    database_dir: str = "data"
    airtable_base_id: str = ""
    airtable_table: str = "Lead Radar"
    batch_size: int = DEFAULT_BATCH_SIZE
    sync_enabled: bool = True

    @classmethod
    def from_environment(cls):
        database_dir = os.getenv(
            "LEAD_ENGINE_DATA_DIR",
            os.getenv(
                "LEAD_ENGINE_DATABASE_DIR",
                "data",
            ),
        )

        airtable_table = os.getenv(
            "AIRTABLE_LEAD_TABLE",
            os.getenv(
                "AIRTABLE_TABLE",
                "Lead Radar",
            ),
        )

        raw_batch_size = os.getenv(
            "LEAD_ENGINE_BATCH_SIZE",
            str(DEFAULT_BATCH_SIZE),
        )

        try:
            batch_size = int(raw_batch_size)
        except (TypeError, ValueError):
            batch_size = DEFAULT_BATCH_SIZE

        if batch_size <= 0:
            batch_size = DEFAULT_BATCH_SIZE

        sync_enabled = os.getenv(
            "LEAD_ENGINE_SYNC_ENABLED",
            "true",
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        return cls(
            database_dir=database_dir,
            airtable_base_id=os.getenv(
                "AIRTABLE_BASE_ID",
                "",
            ),
            airtable_table=airtable_table,
            batch_size=batch_size,
            sync_enabled=sync_enabled,
        )

    @property
    def database_path(self) -> Path:
        return (
            Path(self.database_dir)
            / "leads.sqlite3"
        )

    def safe_dict(self):
        """
        Return configuration suitable for logs.

        Secrets are intentionally excluded.
        """

        return {
            "database_dir": self.database_dir,
            "airtable_configured": bool(
                self.airtable_base_id
            ),
            "airtable_table": self.airtable_table,
            "batch_size": self.batch_size,
            "sync_enabled": self.sync_enabled,
        }
