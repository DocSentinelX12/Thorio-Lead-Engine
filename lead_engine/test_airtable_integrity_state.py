import tempfile
from pathlib import Path
from types import SimpleNamespace

from .agent_stateful_handlers import airtable_integrity
from .database import LeadDB
from .sales_handoff import package_digest
from .test_sales_handoff import _ready_lead


def test_airtable_integrity_reads_real_durable_sync_state(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        db = LeadDB(data_dir=Path(directory))
        lead = _ready_lead()
        assert db.insert_if_new(lead)
        ctx = SimpleNamespace(db=db)

        pending = airtable_integrity("airtable_integrity", {"lead": lead}, ctx)
        assert pending["sync_status"] == "pending"
        assert pending["airtable_verified"] is False

        db.mark_synced(lead["fingerprint"])
        db.record_airtable_handoff(
            lead["fingerprint"],
            package_digest(lead),
            "recLead",
            "recResearch",
            ["recCompany"],
            "2026-09-28T00:00:00+00:00",
        )
        monkeypatch.setattr(
            "lead_engine.sales_handoff.verify_persisted_airtable_handoff",
            lambda db, lead: (True, package_digest(lead)),
        )
        synced = airtable_integrity("airtable_integrity", {"lead": lead}, ctx)
        assert synced["sync_status"] == "synced"
        assert synced["airtable_verified"] is True
        assert synced["sync_error_present"] is False
        assert synced["verification_error"] == ""

        db.mark_error(lead["fingerprint"], "Airtable unavailable")
        failed = airtable_integrity("airtable_integrity", {"lead": lead}, ctx)
        assert failed["sync_status"] == "pending"
        assert failed["sync_error_present"] is True
        assert failed["airtable_verified"] is False


def test_airtable_integrity_requires_remote_readback(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        db = LeadDB(data_dir=Path(directory))
        lead = _ready_lead()
        assert db.insert_if_new(lead)
        db.mark_synced(lead["fingerprint"])
        db.record_airtable_handoff(
            lead["fingerprint"],
            package_digest(lead),
            "recLead",
            "recResearch",
            ["recCompany"],
            "2026-09-28T00:00:00+00:00",
        )
        monkeypatch.setattr(
            "lead_engine.sales_handoff.verify_persisted_airtable_handoff",
            lambda db, lead: (False, "research_record_package_mismatch"),
        )
        result = airtable_integrity(
            "airtable_integrity",
            {"lead": lead},
            SimpleNamespace(db=db),
        )
        assert result["airtable_verified"] is False
        assert result["verification_error"] == "research_record_package_mismatch"


def test_airtable_integrity_accepts_verified_remote_readback(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        db = LeadDB(data_dir=Path(directory))
        lead = _ready_lead()
        assert db.insert_if_new(lead)
        db.mark_synced(lead["fingerprint"])
        db.record_airtable_handoff(
            lead["fingerprint"],
            package_digest(lead),
            "recLead",
            "recResearch",
            ["recCompany"],
            "2026-09-28T00:00:00+00:00",
        )
        monkeypatch.setattr(
            "lead_engine.sales_handoff.verify_persisted_airtable_handoff",
            lambda db, lead: (True, package_digest(lead)),
        )
        result = airtable_integrity(
            "airtable_integrity",
            {"lead": lead},
            SimpleNamespace(db=db),
        )
        assert result["airtable_verified"] is True
        assert result["verification_error"] == ""


def test_airtable_integrity_fails_closed_when_remote_readback_raises(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        db = LeadDB(data_dir=Path(directory))
        lead = _ready_lead()
        assert db.insert_if_new(lead)
        db.mark_synced(lead["fingerprint"])
        db.record_airtable_handoff(
            lead["fingerprint"],
            package_digest(lead),
            "recLead",
            "recResearch",
            ["recCompany"],
            "2026-09-28T00:00:00+00:00",
        )
        def explode(db, lead):
            raise RuntimeError("Airtable unavailable")
        monkeypatch.setattr(
            "lead_engine.sales_handoff.verify_persisted_airtable_handoff",
            explode,
        )
        result = airtable_integrity(
            "airtable_integrity",
            {"lead": lead},
            SimpleNamespace(db=db),
        )
        assert result["airtable_verified"] is False
        assert result["verification_error"] == "airtable_handoff_verification_failed:Airtable unavailable"
