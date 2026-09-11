import json

from .application import LeadEngineApplication
from .config import LeadEngineConfig
from .json_source import JsonLeadSource


def test_json_import_persists_lead_locally(tmp_path):
    source_path = tmp_path / "leads.json"
    source_path.write_text(json.dumps([{
        "source": "end-to-end",
        "source_id": "e2e-001",
        "url": "https://example.com/e2e-001",
        "company": "End To End Corp",
        "signal": "remote software engineer",
        "evidence": "Remote software engineer opening.",
    }]), encoding="utf-8")
    config = LeadEngineConfig(database_dir=str(tmp_path / "database"), sync_enabled=False)
    application = LeadEngineApplication(config=config)
    source = JsonLeadSource(str(source_path))
    result = application.run_sources([source])
    assert isinstance(result, dict)
    status = application.status()
    assert status["total_leads"] == 1
    assert status["pending_leads"] == 1


def test_repeated_json_observation_is_persisted_for_later_qualification(tmp_path):
    source_path = tmp_path / "duplicates.json"
    lead = {
        "source": "end-to-end",
        "source_id": "e2e-duplicate-001",
        "url": "https://example.com/e2e-duplicate-001",
        "company": "Duplicate Corp",
        "person": "Alex",
        "signal": "remote developer",
        "evidence": "Remote developer opening.",
    }
    source_path.write_text(json.dumps([lead]), encoding="utf-8")
    config = LeadEngineConfig(database_dir=str(tmp_path / "database"), sync_enabled=False)
    application = LeadEngineApplication(config=config)
    first = application.run_sources([JsonLeadSource(str(source_path))])
    second = application.run_sources([JsonLeadSource(str(source_path))])
    assert first["results"][0]["result"]["accepted_count"] == 1
    assert second["results"][0]["result"]["accepted_count"] == 1
    assert second["results"][0]["result"]["duplicate_count"] == 0
    status = application.status()
    assert status["total_leads"] == 2
    assert status["pending_leads"] == 2
