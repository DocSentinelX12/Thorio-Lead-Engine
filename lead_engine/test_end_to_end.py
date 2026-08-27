import json

from .application import LeadEngineApplication
from .config import LeadEngineConfig


def test_json_import_persists_lead_locally(tmp_path):
    source_path = tmp_path / "leads.json"

    source_path.write_text(
        json.dumps(
            [
                {
                    "source": "end-to-end",
                    "source_id": "e2e-001",
                    "url": "https://example.com/e2e-001",
                    "company": "End To End Corp",
                    "signal": "remote software engineer",
                    "evidence": "Remote software engineer opening.",
                }
            ]
        ),
        encoding="utf-8",
    )

    config = LeadEngineConfig(
        database_dir=str(tmp_path / "database"),
        sync_enabled=False,
    )

    application = LeadEngineApplication(
        config=config
    )

    from .json_source import JsonLeadSource

    source = JsonLeadSource(
        str(source_path)
    )

    result = application.run_sources(
        [source]
    )

    assert result["source_count"] == 1
    assert result["failed_count"] == 0
    assert result["accepted_count"] == 1

    status = application.status()

    assert status["total_leads"] == 1
    assert status["pending_leads"] == 1


def test_duplicate_json_import_is_not_persisted_twice(
    tmp_path,
):
    source_path = tmp_path / "duplicates.json"

    lead = {
        "source": "end-to-end",
        "source_id": "e2e-duplicate-001",
        "url": "https://example.com/e2e-duplicate-001",
        "company": "Duplicate Corp",
        "signal": "remote developer",
        "evidence": "Remote developer opening.",
    }

    source_path.write_text(
        json.dumps(
            [lead]
        ),
        encoding="utf-8",
    )

    config = LeadEngineConfig(
        database_dir=str(tmp_path / "database"),
        sync_enabled=False,
    )

    application = LeadEngineApplication(
        config=config
    )

    from .json_source import JsonLeadSource

    source = JsonLeadSource(
        str(source_path)
    )

    first = application.run_sources(
        [source]
    )

    second = application.run_sources(
        [source]
    )

    assert first["accepted_count"] == 1
    assert second["duplicate_count"] == 1

    status = application.status()

    assert status["total_leads"] == 1
