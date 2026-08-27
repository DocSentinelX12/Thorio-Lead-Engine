import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LeadEngineConfig:
    """
    Central configuration for the lead engine.

    Secrets are read from environment variables and are never
    stored in source code.
    """

    database_dir: str = "data"
    airtable_base_id: str = ""
    airtable_table: str = "Lead Radar"
    batch_size: int = 50
    sync_enabled: bool = True

    @classmethod
    def from_environment(cls):
        """
        Build configuration from environment variables.
        """

        sync_enabled = os.getenv(
            "LEAD_ENGINE_SYNC_ENABLED",
            "true",
        ).strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }

        batch_size_raw = os.getenv(
            "LEAD_ENGINE_BATCH_SIZE",
            "50",
        )

        try:
            batch_size = int(batch_size_raw)
        except ValueError:
            batch_size = 50

        if batch_size < 1:
            batch_size = 50

        return cls(
            database_dir=os.getenv(
                "LEAD_ENGINE_DATA_DIR",
                "data",
            ),
            airtable_base_id=os.getenv(
                "AIRTABLE_BASE_ID",
                "",
            ),
            airtable_table=os.getenv(
                "AIRTABLE_LEAD_TABLE",
                "Lead Radar",
            ),
            batch_size=batch_size,
            sync_enabled=sync_enabled,
        )


if __name__ == "__main__":
    print(
        LeadEngineConfig.from_environment()
    )
