import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


DEFAULT_BATCH_SIZE = 50
DEFAULT_APPROVAL_POLL_INTERVAL_SECONDS = 60

DEFAULT_AIRTABLE_LEAD_TABLE = "Lead Radar"
DEFAULT_AIRTABLE_COMPANIES_TABLE = "Companies"
DEFAULT_AIRTABLE_OPPORTUNITIES_TABLE = "Opportunities"
DEFAULT_AIRTABLE_OUTREACH_TABLE = "Outreach"
DEFAULT_AIRTABLE_REFERRALS_TABLE = "Referrals"
DEFAULT_AIRTABLE_FOLLOWUPS_TABLE = "Follow-ups"
DEFAULT_AIRTABLE_COMMISSIONS_TABLE = "Commissions"
DEFAULT_AIRTABLE_LEAD_SOURCES_TABLE = "Lead Sources"


@dataclass
class LeadEngineConfig:
    """
    Central runtime configuration for the Lead Engine.

    Secrets are read from environment variables only.
    Secrets are never stored in source code or returned
    by safe_dict().

    Airtable table names are configurable independently so
    the complete Master Tracker can be addressed without
    hardcoding table names throughout the application.
    """

    database_dir: str = "data"
    airtable_base_id: str = ""

    airtable_table: str = DEFAULT_AIRTABLE_LEAD_TABLE
    airtable_companies_table: str = (
        DEFAULT_AIRTABLE_COMPANIES_TABLE
    )
    airtable_opportunities_table: str = (
        DEFAULT_AIRTABLE_OPPORTUNITIES_TABLE
    )
    airtable_outreach_table: str = (
        DEFAULT_AIRTABLE_OUTREACH_TABLE
    )
    airtable_referrals_table: str = (
        DEFAULT_AIRTABLE_REFERRALS_TABLE
    )
    airtable_followups_table: str = (
        DEFAULT_AIRTABLE_FOLLOWUPS_TABLE
    )
    airtable_commissions_table: str = (
        DEFAULT_AIRTABLE_COMMISSIONS_TABLE
    )
    airtable_lead_sources_table: str = (
        DEFAULT_AIRTABLE_LEAD_SOURCES_TABLE
    )

    batch_size: int = DEFAULT_BATCH_SIZE
    sync_enabled: bool = True
    approval_poll_interval_seconds: int = (
        DEFAULT_APPROVAL_POLL_INTERVAL_SECONDS
    )

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
                DEFAULT_AIRTABLE_LEAD_TABLE,
            ),
        )

        airtable_companies_table = os.getenv(
            "AIRTABLE_COMPANIES_TABLE",
            DEFAULT_AIRTABLE_COMPANIES_TABLE,
        )

        airtable_opportunities_table = os.getenv(
            "AIRTABLE_OPPORTUNITIES_TABLE",
            DEFAULT_AIRTABLE_OPPORTUNITIES_TABLE,
        )

        airtable_outreach_table = os.getenv(
            "AIRTABLE_OUTREACH_TABLE",
            DEFAULT_AIRTABLE_OUTREACH_TABLE,
        )

        airtable_referrals_table = os.getenv(
            "AIRTABLE_REFERRALS_TABLE",
            DEFAULT_AIRTABLE_REFERRALS_TABLE,
        )

        airtable_followups_table = os.getenv(
            "AIRTABLE_FOLLOWUPS_TABLE",
            DEFAULT_AIRTABLE_FOLLOWUPS_TABLE,
        )

        airtable_commissions_table = os.getenv(
            "AIRTABLE_COMMISSIONS_TABLE",
            DEFAULT_AIRTABLE_COMMISSIONS_TABLE,
        )

        airtable_lead_sources_table = os.getenv(
            "AIRTABLE_LEAD_SOURCES_TABLE",
            DEFAULT_AIRTABLE_LEAD_SOURCES_TABLE,
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

        raw_poll_interval = os.getenv(
            "LEAD_ENGINE_APPROVAL_POLL_INTERVAL",
            str(DEFAULT_APPROVAL_POLL_INTERVAL_SECONDS),
        )

        try:
            approval_poll_interval_seconds = int(
                raw_poll_interval
            )
        except (TypeError, ValueError):
            approval_poll_interval_seconds = (
                DEFAULT_APPROVAL_POLL_INTERVAL_SECONDS
            )

        if approval_poll_interval_seconds < 1:
            approval_poll_interval_seconds = (
                DEFAULT_APPROVAL_POLL_INTERVAL_SECONDS
            )

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
            airtable_companies_table=(
                airtable_companies_table
            ),
            airtable_opportunities_table=(
                airtable_opportunities_table
            ),
            airtable_outreach_table=(
                airtable_outreach_table
            ),
            airtable_referrals_table=(
                airtable_referrals_table
            ),
            airtable_followups_table=(
                airtable_followups_table
            ),
            airtable_commissions_table=(
                airtable_commissions_table
            ),
            airtable_lead_sources_table=(
                airtable_lead_sources_table
            ),
            batch_size=batch_size,
            sync_enabled=sync_enabled,
            approval_poll_interval_seconds=(
                approval_poll_interval_seconds
            ),
        )

    @property
    def database_path(self) -> Path:
        return Path(self.database_dir) / "leads.sqlite3"

    @property
    def airtable_tables(self) -> Dict[str, str]:
        """
        Return the complete Master Tracker table mapping.

        The API key is intentionally not part of this mapping.
        Authentication remains environment-variable based.
        """

        return {
            "lead_radar": self.airtable_table,
            "companies": self.airtable_companies_table,
            "opportunities": (
                self.airtable_opportunities_table
            ),
            "outreach": self.airtable_outreach_table,
            "referrals": self.airtable_referrals_table,
            "followups": self.airtable_followups_table,
            "commissions": (
                self.airtable_commissions_table
            ),
            "lead_sources": (
                self.airtable_lead_sources_table
            ),
        }

    def validate(self) -> None:
        """
        Validate the complete runtime configuration.

        This validates values, not merely the presence of
        configuration attributes.
        """

        if not isinstance(self.database_dir, str):
            raise ValueError(
                "database_dir must be a string."
            )

        if not self.database_dir.strip():
            raise ValueError(
                "database_dir must not be empty."
            )

        if not isinstance(self.airtable_base_id, str):
            raise ValueError(
                "airtable_base_id must be a string."
            )

        if not isinstance(self.batch_size, int) or isinstance(
            self.batch_size,
            bool,
        ):
            raise ValueError(
                "batch_size must be an integer."
            )

        if self.batch_size <= 0:
            raise ValueError(
                "batch_size must be greater than zero."
            )

        if (
            not isinstance(
                self.approval_poll_interval_seconds,
                int,
            )
            or isinstance(
                self.approval_poll_interval_seconds,
                bool,
            )
        ):
            raise ValueError(
                "approval_poll_interval_seconds "
                "must be an integer."
            )

        if self.approval_poll_interval_seconds < 1:
            raise ValueError(
                "approval_poll_interval_seconds "
                "must be at least 1."
            )

        required_tables = self.airtable_tables

        for table_key, table_name in required_tables.items():
            if not isinstance(table_name, str):
                raise ValueError(
                    f"Airtable table '{table_key}' "
                    "must be a string."
                )

            if not table_name.strip():
                raise ValueError(
                    f"Airtable table '{table_key}' "
                    "must not be empty."
                )

    def safe_dict(self):
        """
        Return operational configuration without secrets.
        """

        return {
            "database_dir": self.database_dir,
            "airtable_configured": bool(
                self.airtable_base_id
            ),
            "airtable_table": self.airtable_table,
            "airtable_tables": self.airtable_tables,
            "batch_size": self.batch_size,
            "sync_enabled": self.sync_enabled,
            "approval_poll_interval_seconds": (
                self.approval_poll_interval_seconds
            ),
          }
