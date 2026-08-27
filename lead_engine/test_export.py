import json

from .database import LeadDB
from .export import export_pending_leads


def test_export_pending_leads(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path / "database")
    )

    db.insert_if_new(
        {
            "fingerprint": "export-001",
            "company": "Export Corp",
            "signal": "remote developer",
            "status": "Unverified",
        }
    )

    destination = tmp_path / "exports" / "leads.json"

    result = export_pending_leads(
        db,
        str(destination),
    )

    assert result["count"] == 1
    assert destination.exists()

    data = json.loads(
        destination.read_text(
            encoding="utf-8"
        )
    )

    assert len(data) == 1
    assert data[0]["company"] == "Export Corp"
    assert data[0]["fingerprint"] == "export-001"


def test_export_does_not_mark_lead_synced(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path / "database")
    )

    db.insert_if_new(
        {
            "fingerprint": "export-002",
            "company": "Still Pending Corp",
            "signal": "developer",
            "status": "Unverified",
        }
    )

    destination = tmp_path / "leads.json"

    export_pending_leads(
        db,
        str(destination),
    )

    stats = db.stats()

    assert stats[0] == 1
    assert stats[1] == 0
    assert stats[2] == 1
