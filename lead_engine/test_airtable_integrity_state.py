import tempfile
from pathlib import Path
from types import SimpleNamespace

from .agent_stateful_handlers import airtable_integrity
from .database import LeadDB


def test_airtable_integrity_reads_real_durable_sync_state():
    with tempfile.TemporaryDirectory() as directory:
        db = LeadDB(data_dir=Path(directory))
        lead = {"fingerprint": "airtable-state", "company": "Example"}
        assert db.insert_if_new(lead)
        ctx = SimpleNamespace(db=db)

        pending = airtable_integrity("airtable_integrity", {"lead": lead}, ctx)
        assert pending["sync_status"] == "pending"
        assert pending["airtable_verified"] is False

        db.mark_synced("airtable-state")
        synced = airtable_integrity("airtable_integrity", {"lead": lead}, ctx)
        assert synced["sync_status"] == "synced"
        assert synced["airtable_verified"] is True
        assert synced["sync_error_present"] is False

        db.mark_error("airtable-state", "Airtable unavailable")
        failed = airtable_integrity("airtable_integrity", {"lead": lead}, ctx)
        assert failed["sync_status"] == "pending"
        assert failed["sync_error_present"] is True
        assert failed["airtable_verified"] is False
