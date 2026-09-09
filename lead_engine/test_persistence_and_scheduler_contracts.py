import os
import tempfile
from pathlib import Path

import pytest

from .compute_worker import ComputeWorkerClient
from .database import LeadDB
from .scheduler import LeadScheduler


def test_changed_lead_state_reopens_airtable_sync_until_resynchronized():
    with tempfile.TemporaryDirectory() as directory:
        db = LeadDB(data_dir=Path(directory))
        lead = {"fingerprint": "sync-lead", "company": "Example", "signal": "initial"}
        assert db.insert_if_new(lead)
        db.mark_synced("sync-lead")
        assert db.pending(10) == []
        db.update_payload("sync-lead", {"signal": "updated"})
        rows = db.pending(10)
        assert len(rows) == 1
        assert rows[0][0] == "sync-lead"
        db.update_payload("sync-lead", {"signal": "updated"})
        assert len(db.pending(10)) == 1


def test_scheduler_remote_configuration_requires_both_coordinator_settings(monkeypatch):
    monkeypatch.delenv("THORIO_COMPUTE_COORDINATOR_URL", raising=False)
    monkeypatch.delenv("THORIO_COMPUTE_AUTH_TOKEN", raising=False)
    assert LeadScheduler._remote_client_from_environment() is None

    monkeypatch.setenv("THORIO_COMPUTE_COORDINATOR_URL", "https://coordinator.example")
    monkeypatch.delenv("THORIO_COMPUTE_AUTH_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="configured together"):
        LeadScheduler._remote_client_from_environment()

    monkeypatch.setenv("THORIO_COMPUTE_AUTH_TOKEN", "secret")
    client = LeadScheduler._remote_client_from_environment()
    assert isinstance(client, ComputeWorkerClient)
    assert client.coordinator_url == "https://coordinator.example"
