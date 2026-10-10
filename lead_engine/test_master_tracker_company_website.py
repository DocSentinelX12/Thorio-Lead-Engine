from lead_engine import master_tracker_sync


def test_sync_company_does_not_treat_job_listing_url_as_company_website(monkeypatch):
    captured = {}

    def fake_upsert(table_key, lookup_field, lookup_value, fields):
        captured.update(
            table_key=table_key,
            lookup_field=lookup_field,
            lookup_value=lookup_value,
            fields=dict(fields),
        )
        return {"status": "created", "record": {"id": "rec_company"}}

    monkeypatch.setattr(master_tracker_sync, "_upsert", fake_upsert)
    result = master_tracker_sync.sync_company({
        "company": "Example Corp",
        "source": "job board",
        "url": "https://remotejobs.org/remote-jobs/example-role",
    })

    assert result["status"] == "created"
    assert captured["table_key"] == "companies"
    assert captured["fields"]["Website"] is None


def test_sync_company_uses_only_explicit_company_website(monkeypatch):
    captured = {}

    def fake_upsert(table_key, lookup_field, lookup_value, fields):
        captured.update(fields=dict(fields))
        return {"status": "created", "record": {"id": "rec_company"}}

    monkeypatch.setattr(master_tracker_sync, "_upsert", fake_upsert)
    master_tracker_sync.sync_company({
        "company": "Example Corp",
        "source": "job board",
        "url": "https://remotejobs.org/remote-jobs/example-role",
        "company_website": "https://example.com",
    })

    assert captured["fields"]["Website"] == "https://example.com"
