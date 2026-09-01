import os
from dataclasses import dataclass
from pathlib import Path


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
    Central configuration for the Lead Engine.

    Secrets are read from environment variables only.
    They are never stored in source code.

    Airtable table names describe the logical tables used by the
    Paxus + Shiftr Master Tracker. Existing deployments that only
    configure AIRTABLE_LEAD_TABLE continue to work unchanged.
    """

    database_dir: str = "data"
    airtable_base_id: str = ""

    # Existing Lead Radar configuration.
    airtable_table: str = DEFAULT_AIRTABLE_LEAD_TABLE

    # Master Tracker table configuration.
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
            batch_size = int(
                raw_batch_size
            )
        except (
            TypeError,
            ValueError,
        ):
            batch_size = DEFAULT_BATCH_SIZE

        if batch_size <= 0:
            batch_size = DEFAULT_BATCH_SIZE

        raw_poll_interval = os.getenv(
            "LEAD_ENGINE_APPROVAL_POLL_INTERVAL",
            str(
                DEFAULT_APPROVAL_POLL_INTERVAL_SECONDS
            ),
        )

        try:
            approval_poll_interval_seconds = int(
                raw_poll_interval
            )
        except (
            TypeError,
            ValueError,
        ):
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
        return (
            Path(self.database_dir)
            / "leads.sqlite3"
        )

    @property
    def airtable_tables(self):
        """
        Return the complete logical Airtable table mapping.

        This does not perform any Airtable writes. It only exposes
        the configured table names to the rest of the application.
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

    def safe_dict(self):
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
