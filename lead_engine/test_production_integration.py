from .application import LeadEngineApplication
from .config import LeadEngineConfig
from .sources import LeadSource, StaticLeadSource


class FailingSource(LeadSource):
    name = "failing"

    def collect(self):
        raise RuntimeError("source unavailable")


def _lead(source_id, company="Integration Corp", person="Alex"):
    return {
        "source": "integration",
        "source_id": source_id,
        "url": f"https://example.com/{source_id}",
        "company": company,
        "person": person,
        "signal": "remote software engineer",
        "evidence": "Company is hiring a remote software engineer.",
    }


def test_production_path_processes_multiple_sources_and_preserves_isolation(tmp_path):
    config = LeadEngineConfig(database_dir=str(tmp_path / "database"), sync_enabled=False, batch_size=50)
    application = LeadEngineApplication(config=config)
    successful_source = StaticLeadSource([_lead("integration-001", "Alpha Corp"), _lead("integration-002", "Beta Corp")])
    result = application.run_sources([FailingSource(), successful_source])
    assert result["source_count"] == 2
    assert result["failed_count"] == 1
    assert len(result["results"]) == 2
    status = application.status()
    assert status["total_leads"] == 2
    assert status["pending_leads"] == 2
    assert result["results"][0]["result"]["failed_count"] == 1
    assert result["results"][1]["result"]["accepted_count"] == 2


def test_production_path_allows_unqualified_lead_to_be_rechecked(tmp_path):
    config = LeadEngineConfig(database_dir=str(tmp_path / "database"), sync_enabled=False, batch_size=50)
    application = LeadEngineApplication(config=config)
    first = application.run_sources([StaticLeadSource([_lead("integration-observation-1")])])
    second = application.run_sources([StaticLeadSource([_lead("integration-observation-2")])])
    assert first["results"][0]["result"]["accepted_count"] == 1
    assert first["results"][0]["result"]["duplicate_count"] == 0
    assert second["results"][0]["result"]["accepted_count"] == 1
    assert second["results"][0]["result"]["duplicate_count"] == 0
    assert application.status()["total_leads"] == 2


def test_production_path_deduplicates_qualified_lead_only_at_finalization(tmp_path):
    config = LeadEngineConfig(database_dir=str(tmp_path / "database"), sync_enabled=False, batch_size=50)
    application = LeadEngineApplication(config=config)
    first = application.run_sources([StaticLeadSource([_lead("integration-qualified-1")])])
    assert first["results"][0]["result"]["accepted_count"] == 1
    first_fingerprint = application.db.conn.execute("SELECT fingerprint FROM leads ORDER BY rowid LIMIT 1").fetchone()[0]
    qualified = application.service.runner.pipeline.qualify(first_fingerprint, qualified=True, business_need="hire a remote software engineer")
    assert qualified["qualified"] is True

    # This is deliberately a fresh observation. Discovery must accept it.
    second = application.run_sources([StaticLeadSource([_lead("integration-qualified-2")])])
    assert second["results"][0]["result"]["accepted_count"] == 1
    assert second["results"][0]["result"]["duplicate_count"] == 0

    rows = application.db.conn.execute("SELECT fingerprint FROM leads ORDER BY rowid").fetchall()
    assert len(rows) == 2
    second_fingerprint = rows[1][0]
    second_qualified = application.service.runner.pipeline.qualify(second_fingerprint, qualified=True, business_need="hire a remote software engineer")
    assert second_qualified["qualified"] is True

    final = application.service.runner.pipeline.finalize(second_fingerprint)
    assert final["status"] == "duplicate"
    assert final["approved"] is False
    assert final["duplicate"] is True
    assert final["duplicate_of"] == first_fingerprint
    assert final["reason"] == "exact_company_person_need_match"

    status = application.status()
    assert status["total_leads"] == 2


def test_production_path_persists_database_across_application_instances(tmp_path):
    database_dir = tmp_path / "database"
    config = LeadEngineConfig(database_dir=str(database_dir), sync_enabled=False, batch_size=50)
    first_application = LeadEngineApplication(config=config)
    first_application.run_sources([StaticLeadSource([_lead("integration-persist")])])
    first_status = first_application.status()
    second_status = LeadEngineApplication(config=config).status()
    assert first_status["total_leads"] == 1
    assert first_status["pending_leads"] == 1
    assert second_status["total_leads"] == 1
    assert second_status["pending_leads"] == 1


def test_production_path_continues_after_a_failed_record(tmp_path):
    config = LeadEngineConfig(database_dir=str(tmp_path / "database"), sync_enabled=False, batch_size=50)
    application = LeadEngineApplication(config=config)
    result = application.process_records([_lead("integration-good-001"), "malformed-record", _lead("integration-good-002", "Second Corp")])
    assert result["accepted_count"] == 2
    assert result["failed_count"] == 1
    status = application.status()
    assert status["total_leads"] == 2
    assert status["pending_leads"] == 2


def test_production_path_marks_successful_sync_as_synced(tmp_path, monkeypatch):
    config = LeadEngineConfig(database_dir=str(tmp_path / "database"), sync_enabled=True, batch_size=50)
    monkeypatch.setattr("lead_engine.pipeline.sync_one", lambda payload: {"status": "synced", "error": None})
    application = LeadEngineApplication(config=config)
    result = application.run_sources([StaticLeadSource([_lead("integration-sync-success")])])
    assert result["results"][0]["result"]["accepted_count"] == 1
    status = application.status()
    assert status["total_leads"] == 1
    assert status["synced_leads"] == 1
    assert status["pending_leads"] == 0


def test_production_path_keeps_lead_pending_after_sync_failure(tmp_path, monkeypatch):
    config = LeadEngineConfig(database_dir=str(tmp_path / "database"), sync_enabled=True, batch_size=50)
    monkeypatch.setattr("lead_engine.pipeline.sync_one", lambda payload: {"status": "failed", "error": "temporary Airtable failure"})
    application = LeadEngineApplication(config=config)
    result = application.run_sources([StaticLeadSource([_lead("integration-sync-failure")])])
    assert result["results"][0]["result"]["accepted_count"] == 1
    status = application.status()
    assert status["total_leads"] == 1
    assert status["synced_leads"] == 0
    assert status["pending_leads"] == 1
    assert status["failed_sync_leads"] == 1
    assert status["failed_sync_attempts"] == 1


def test_production_path_local_database_remains_authoritative_when_sync_disabled(tmp_path):
    config = LeadEngineConfig(database_dir=str(tmp_path / "database"), sync_enabled=False, batch_size=50)
    application = LeadEngineApplication(config=config)
    application.run_sources([StaticLeadSource([_lead("integration-local-authority")])])
    fingerprint = application.db.conn.execute("SELECT fingerprint FROM leads LIMIT 1").fetchone()[0]
    stored = application.db.get(fingerprint)
    assert stored is not None
    assert stored["source_id"] == "integration-local-authority"
    assert stored["company"] == "Integration Corp"
    synced = application.db.conn.execute("SELECT synced FROM leads WHERE fingerprint = ?", (fingerprint,)).fetchone()[0]
    assert synced == 0


def test_production_end_to_end_scheduled_path(tmp_path, monkeypatch):
    config = LeadEngineConfig(database_dir=str(tmp_path / "database"), sync_enabled=True, batch_size=50)
    monkeypatch.setattr("lead_engine.scheduler.sync_pending", lambda db, limit=50: {"synced": [{"status": "synced"}], "already_exists": [], "failed": [], "synced_count": 1, "already_exists_count": 0, "failed_count": 0})
    application = LeadEngineApplication(config=config)
    source = StaticLeadSource([_lead("production-e2e-001", "Production E2E Corp")])
    from .runner import LeadEngineRunner
    from .scheduler import LeadScheduler
    scheduler = LeadScheduler(LeadEngineRunner(pipeline=application.service.runner.pipeline))
    result = scheduler.run_bounded(sources=[source], interval_seconds=0, max_cycles=1)
    assert result["status"] == "completed"
    assert result["cycles"] == 1
    assert result["source_count"] == 1
    assert result["successful_source_count"] == 1
    assert result["failed_count"] == 0
    assert result["discovered_count"] == 1
    assert result["accepted_count"] == 1
    assert result["processing_failed_count"] == 0
    assert len(result["results"]) == 1
    assert result["results"][0]["source"] == source.name
    assert result["sync"]["synced_count"] == 1
    assert result["sync"]["failed_count"] == 0
    assert result["sync"]["already_exists_count"] == 0
    status = application.status()
    assert status["total_leads"] == 1
    assert status["pending_leads"] == 1
