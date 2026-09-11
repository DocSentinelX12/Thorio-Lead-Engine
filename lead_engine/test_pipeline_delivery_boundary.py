from unittest.mock import patch

from .pipeline import LeadPipeline


class FakeDB:
    def __init__(self):
        self.records = {}

    def get(self, fingerprint):
        return self.records.get(fingerprint)

    def all_leads(self):
        return list(self.records.values())

    def update_payload(self, fingerprint, payload):
        self.records[fingerprint] = payload
        return payload

    def insert_if_new(self, payload):
        fingerprint = payload["fingerprint"]
        if fingerprint in self.records:
            return False
        self.records[fingerprint] = payload
        return True

    def mark_synced(self, fingerprint):
        return None

    def mark_error(self, fingerprint, error):
        return None


def test_pipeline_keeps_discovery_unqualified():
    pipeline = LeadPipeline(db=FakeDB(), sync_enabled=False)
    result = pipeline.process(source="test", source_id="discovery-001", url="https://example.com/jobs/discovery-001", company="Acme", signal="remote software engineer", evidence="Remote software engineer opening.")
    assert result["lead"]["qualified"] is False
    assert result["lead"]["qualification_status"] == "unverified"


def test_qualification_is_explicit():
    db = FakeDB()
    db.records["test-fingerprint"] = {"fingerprint": "test-fingerprint", "company": "Acme", "status": "new", "qualification_status": "unqualified", "qualified": False}
    result = LeadPipeline(db=db).qualify("test-fingerprint", qualified=True, reason="Human review approved")
    assert result["status"] == "Qualified"
    assert result["qualified"] is True
    assert result["qualification_status"] == "qualified"


def test_unknown_lead_cannot_be_qualified():
    pipeline = LeadPipeline(db=FakeDB())
    try:
        pipeline.qualify("missing", qualified=True)
    except ValueError as exc:
        assert "Lead not found" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing lead")


def test_qualification_can_reject_lead():
    db = FakeDB()
    db.records["reject-me"] = {"fingerprint": "reject-me", "company": "Acme", "status": "new", "qualification_status": "unqualified", "qualified": False}
    result = LeadPipeline(db=db).qualify("reject-me", qualified=False, reason="Does not meet requirements")
    assert result["status"] != "Qualified"
    assert result["company"] == "Acme"
    assert result["qualified"] is False


def test_pipeline_exposes_qualification_as_separate_action():
    pipeline = LeadPipeline(db=FakeDB())
    assert callable(pipeline.qualify)
    assert callable(pipeline.process)


def test_unqualified_duplicate_discovery_is_not_blocked():
    pipeline = LeadPipeline(db=FakeDB(), sync_enabled=False)
    first = pipeline.process(source="test", source_id="same-lead-1", url="https://example.com/jobs/same-lead-1", company="Acme", person="Alex", signal="remote software engineer", evidence="Remote software engineer opening.")
    pipeline.qualify(first["fingerprint"], qualified=False, reason="Still unqualified")
    second = pipeline.process(source="test", source_id="same-lead-2", url="https://example.com/jobs/same-lead-2", company="Acme", person="Alex", signal="remote software engineer", evidence="Remote software engineer opening.")
    assert second["status"] == "accepted"
    assert second["duplicate"] is not True


def test_exact_duplicate_is_blocked_only_at_finalization_after_qualification():
    pipeline = LeadPipeline(db=FakeDB(), sync_enabled=False)
    first = pipeline.process(source="test", source_id="qualified-duplicate-1", url="https://example.com/jobs/qualified-duplicate-1", company="Acme", person="Alex", signal="remote software engineer", evidence="Remote software engineer opening.")
    pipeline.qualify(first["fingerprint"], qualified=True, reason="Human review approved", business_need="hire a remote software engineer")
    second = pipeline.process(source="test", source_id="qualified-duplicate-2", url="https://example.com/jobs/qualified-duplicate-2", company="Acme", person="Alex", signal="remote software engineer", evidence="Remote software engineer opening.")
    assert second["status"] == "accepted"
    pipeline.qualify(second["fingerprint"], qualified=True, reason="Human review approved", business_need="hire a remote software engineer")
    final = pipeline.finalize(second["fingerprint"])
    assert final["status"] == "duplicate"
    assert final["approved"] is False
    assert final["duplicate"] is True
    assert final["reason"] == "exact_company_person_need_match"


def test_rejected_lead_remains_available_for_audit():
    db = FakeDB()
    pipeline = LeadPipeline(db=db, sync_enabled=False)
    result = pipeline.process(source="test", source_id="rejected-001", url="https://example.com/jobs/rejected-001", company="Acme", signal="remote developer", evidence="Remote developer opening.")
    rejected = pipeline.qualify(result["fingerprint"], qualified=False, reason="No confirmed technology need.")
    assert rejected["qualified"] is False
    assert rejected["qualification_status"] == "not_qualified"
    assert rejected["status"] == "Not Qualified"
    stored = db.get(result["fingerprint"])
    assert stored is not None
    assert stored["qualified"] is False


def test_unqualified_lead_can_be_qualified_after_duplicate_discovery():
    db = FakeDB()
    pipeline = LeadPipeline(db=db, sync_enabled=False)
    first = pipeline.process(source="test", source_id="qualification-after-discovery-1", url="https://example.com/jobs/qualification-after-discovery-1", company="Acme", signal="remote engineer", evidence="Remote engineering opening.")
    second = pipeline.process(source="test", source_id="qualification-after-discovery-2", url="https://example.com/jobs/qualification-after-discovery-2", company="Acme", signal="remote engineer", evidence="Remote engineering opening.")
    assert second["status"] == "accepted"
    qualified = pipeline.qualify(first["fingerprint"], qualified=True, reason="Human review approved")
    assert qualified["qualified"] is True


def test_qualified_lead_is_the_only_duplicate_state():
    db = FakeDB()
    pipeline = LeadPipeline(db=db, sync_enabled=False)
    for qualification_status in ("unqualified", "in_review", "not_qualified"):
        fingerprint = f"status-{qualification_status}"
        db.records[fingerprint] = {"fingerprint": fingerprint, "company": "Acme", "status": "new", "qualification_status": qualification_status, "qualified": False}
        result = pipeline.process(source="test", source_id=fingerprint, url=f"https://example.com/jobs/{fingerprint}", company="Acme", signal="remote engineer", evidence="Remote engineering opening.")
        assert result["status"] != "duplicate"


def test_approval_queue_sync_does_not_equal_partner_delivery():
    db = FakeDB()
    pipeline = LeadPipeline(db=db, sync_enabled=True)
    with patch("lead_engine.pipeline.sync_one") as mock_sync:
        mock_sync.return_value = {"status": "synced", "lead": {}, "airtable_record": {"id": "rec_approval_001"}, "error": None}
        result = pipeline.process(source="test", source_id="approval-001", url="https://example.com/jobs/approval-001", company="Acme", signal="remote engineer", evidence="Remote engineering opening.")
    assert result["sync_status"] == "synced"
    assert result["lead"]["qualified"] is False
    assert result["lead"]["qualification_status"] == "unverified"
    mock_sync.assert_called_once()
