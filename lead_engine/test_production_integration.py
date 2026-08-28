from .application import LeadEngineApplication
from .config import LeadEngineConfig
from .sources import LeadSource, StaticLeadSource


class FailingSource(LeadSource):
    name = "failing"

    def collect(self):
        raise RuntimeError("source unavailable")


def _lead(source_id, company="Integration Corp"):
    return {
        "source": "integration",
        "source_id": source_id,
        "url": f"https://example.com/{source_id}",
        "company": company,
        "signal": "remote software engineer",
        "evidence": "Company is hiring a remote software engineer.",
    }


def test_production_path_processes_multiple_sources_and_preserves_isolation(
    tmp_path,
):
    config = LeadEngineConfig(
        database_dir=str(tmp_path / "database"),
        sync_enabled=False,
        batch_size=50,
    )

    application = LeadEngineApplication(config=config)

    successful_source = StaticLeadSource(
        [
            _lead("integration-001", "Alpha Corp"),
            _lead("integration-002", "Beta Corp"),
        ]
    )

    result = application.run_sources(
        [FailingSource(), successful_source]
    )

    assert result["source_count"] == 2
    assert result["failed_count"] == 1
    assert len(result["results"]) == 2

    status = application.status()

    assert status["total_leads"] == 2
    assert status["pending_leads"] == 2

    failed_result = result["results"][0]["result"]
    successful_result = result["results"][1]["result"]

    assert failed_result["failed_count"] == 1
    assert successful_result["accepted_count"] == 2


def test_production_path_deduplicates_across_separate_runs(
    tmp_path,
):
    config = LeadEngineConfig(
        database_dir=str(tmp_path / "database"),
        sync_enabled=False,
        batch_size=50,
    )

    application = LeadEngineApplication(config=config)
    source = StaticLeadSource(
        [_lead("integration-duplicate")]
    )

    first = application.run_sources([source])
    second = application.run_sources([source])

    first_result = first["results"][0]["result"]
    second_result = second["results"][0]["result"]

    assert first_result["accepted_count"] == 1
    assert first_result["duplicate_count"] == 0
    assert second_result["accepted_count"] == 0
    assert second_result["duplicate_count"] == 1

    status = application.status()

    assert status["total_leads"] == 1
    assert status["pending_leads"] == 1


def test_production_path_persists_database_across_application_instances(
    tmp_path,
):
    database_dir = tmp_path / "database"

    config = LeadEngineConfig(
        database_dir=str(database_dir),
        sync_enabled=False,
        batch_size=50,
    )

    first_application = LeadEngineApplication(config=config)

    first_application.run_sources(
        [
            StaticLeadSource(
                [_lead("integration-persist")]
            )
        ]
    )

    first_status = first_application.status()

    second_application = LeadEngineApplication(config=config)
    second_status = second_application.status()

    assert first_status["total_leads"] == 1
    assert first_status["pending_leads"] == 1
    assert second_status["total_leads"] == 1
    assert second_status["pending_leads"] == 1


def test_production_path_continues_after_a_failed_record(
    tmp_path,
):
    config = LeadEngineConfig(
        database_dir=str(tmp_path / "database"),
        sync_enabled=False,
        batch_size=50,
    )

    application = LeadEngineApplication(config=config)

    records = [
        _lead("integration-good-001"),
        "malformed-record",
        _lead("integration-good-002", "Second Corp"),
    ]

    result = application.process_records(records)

    assert result["accepted_count"] == 2
    assert result["failed_count"] == 1

    status = application.status()

    assert status["total_leads"] == 2
    assert status["pending_leads"] == 2


def test_production_path_marks_successful_sync_as_synced(
    tmp_path,
    monkeypatch,
):
    config = LeadEngineConfig(
        database_dir=str(tmp_path / "database"),
        sync_enabled=True,
        batch_size=50,
    )

    def fake_sync_one(payload):
        return {
            "status": "synced",
            "error": None,
        }

    monkeypatch.setattr(
        "lead_engine.pipeline.sync_one",
        fake_sync_one,
    )

    application = LeadEngineApplication(config=config)

    result = application.run_sources(
        [
            StaticLeadSource(
                [_lead("integration-sync-success")]
            )
        ]
    )

    source_result = result["results"][0]["result"]

    assert source_result["accepted_count"] == 1

    status = application.status()

    assert status["total_leads"] == 1
    assert status["synced_leads"] == 1
    assert status["pending_leads"] == 0


def test_production_path_keeps_lead_pending_after_sync_failure(
    tmp_path,
    monkeypatch,
):
    config = LeadEngineConfig(
        database_dir=str(tmp_path / "database"),
        sync_enabled=True,
        batch_size=50,
    )

    def fake_sync_one(payload):
        return {
            "status": "failed",
            "error": "temporary Airtable failure",
        }

    monkeypatch.setattr(
        "lead_engine.pipeline.sync_one",
        fake_sync_one,
    )

    application = LeadEngineApplication(config=config)

    result = application.run_sources(
        [
            StaticLeadSource(
                [_lead("integration-sync-failure")]
            )
        ]
    )

    source_result = result["results"][0]["result"]

    assert source_result["accepted_count"] == 1

    status = application.status()

    assert status["total_leads"] == 1
    assert status["synced_leads"] == 0
    assert status["pending_leads"] == 1
    assert status["failed_sync_leads"] == 1
    assert status["failed_sync_attempts"] == 1


def test_production_path_local_database_remains_authoritative_when_sync_disabled(
    tmp_path,
):
    config = LeadEngineConfig(
        database_dir=str(tmp_path / "database"),
        sync_enabled=False,
        batch_size=50,
    )

    application = LeadEngineApplication(config=config)

    application.run_sources(
        [
            StaticLeadSource(
                [_lead("integration-local-authority")]
            )
        ]
    )

    fingerprint = application.db.conn.execute(
        "SELECT fingerprint FROM leads LIMIT 1"
    ).fetchone()[0]

    stored = application.db.get(fingerprint)

    assert stored is not None
    assert stored["source_id"] == "integration-local-authority"
    assert stored["company"] == "Integration Corp"

    synced = application.db.conn.execute(
        """
        SELECT synced
        FROM leads
        WHERE fingerprint = ?
        """,
        (fingerprint,),
    ).fetchone()[0]

    assert synced == 0


if __name__ == "__main__":
    print("Production integration tests loaded.")
