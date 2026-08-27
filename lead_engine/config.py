import os
from dataclasses import dataclass


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
    batch_size: int = 50
    sync_enabled: bool = True

    @classmethod
    def from_environment(cls):
        return cls(
            database_dir=os.getenv(
                "LEAD_ENGINE_DATABASE_DIR",
                "data",
            ),
            airtable_base_id=os.getenv(
                "AIRTABLE_BASE_ID",
                "",
            ),
            airtable_table=os.getenv(
                "AIRTABLE_TABLE",
                "Lead Radar",
            ),
            batch_size=int(
                os.getenv(
                    "LEAD_ENGINE_BATCH_SIZE",
                    "50",
                )
            ),
            sync_enabled=os.getenv(
                "LEAD_ENGINE_SYNC_ENABLED",
                "true",
            ).lower()
            in {
                "1",
                "true",
                "yes",
                "on",
            },
        )

    @property
    def database_path(self):
        from pathlib import Path

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
