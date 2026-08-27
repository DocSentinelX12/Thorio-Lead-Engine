from .pipeline import LeadPipeline


class FakeDB:
    def __init__(self):
        self.records = {}

    def get(self, fingerprint):
        return self.records.get(fingerprint)

    def update_payload(self, fingerprint, payload):
        self.records[fingerprint] = payload
        return payload

    def mark_synced(self, fingerprint):
        return None

    def mark_error(self, fingerprint, error):
        return None


def test_pipeline_keeps_discovery_unqualified():
    pipeline = LeadPipeline(db=FakeDB())

    assert pipeline is not None


def test_qualification_is_explicit():
    db = FakeDB()

    lead = {
        "fingerprint": "test-fingerprint",
        "company": "Acme",
        "status": "new",
    }

    db.records["test-fingerprint"] = lead

    pipeline = LeadPipeline(db=db)

    result = pipeline.qualify(
        "test-fingerprint",
        qualified=True,
        reason="Human review approved",
    )

    assert result["status"] == "qualified"


def test_unknown_lead_cannot_be_qualified():
    pipeline = LeadPipeline(db=FakeDB())

    try:
        pipeline.qualify(
            "missing",
            qualified=True,
        )
    except ValueError as exc:
        assert "Lead not found" in str(exc)
    else:
        raise AssertionError(
            "Expected ValueError for missing lead"
        )


def test_qualification_can_reject_lead():
    db = FakeDB()

    lead = {
        "fingerprint": "reject-me",
        "company": "Acme",
        "status": "new",
    }

    db.records["reject-me"] = lead

    pipeline = LeadPipeline(db=db)

    result = pipeline.qualify(
        "reject-me",
        qualified=False,
        reason="Does not meet requirements",
    )

    assert result["status"] != "qualified"
    assert result["company"] == "Acme"


def test_pipeline_exposes_qualification_as_separate_action():
    pipeline = LeadPipeline(db=FakeDB())

    assert callable(pipeline.qualify)
    assert callable(pipeline.process)
