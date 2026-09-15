import json

from .database import LeadDB
from .research_queue import enqueue_legacy_company_research
from .public_research import _candidate_urls


def _lead(fingerprint, *, research_status=None):
    lead = {
        "fingerprint": fingerprint,
        "source": "job-board",
        "source_id": fingerprint,
        "url": "https://jobs.example.com/roles/1",
        "source_url": "https://jobs.example.com/roles/1",
        "company": "ExampleCo",
        "signal": "Hiring software engineers",
        "evidence": "ExampleCo is hiring software engineers.",
    }
    if research_status is not None:
        lead["research_status"] = research_status
    return lead


def test_legacy_research_backfill_queues_only_synced_leads_without_research(tmp_path):
    db = LeadDB(data_dir=str(tmp_path))
    try:
        legacy = _lead("legacy-1")
        researched = _lead("legacy-2", research_status="research_required")
        pending = _lead("legacy-3")
        assert db.insert_if_new(legacy)
        assert db.insert_if_new(researched)
        assert db.insert_if_new(pending)
        db.mark_synced("legacy-1")
        db.mark_synced("legacy-2")

        result = enqueue_legacy_company_research(db, limit=50)

        assert result["queued_count"] == 1
        queued = db.queue_pending("company_research")
        assert len(queued) == 1
        payload = json.loads(queued[0][5])
        assert payload["lead"]["fingerprint"] == "legacy-1"
        assert payload["legacy_backfill"] is True
    finally:
        db.close()


def test_candidate_urls_researches_exact_observed_source_when_company_url_is_missing():
    urls = _candidate_urls({"source_url": "https://jobs.example.com/roles/1"})
    assert urls == ["https://jobs.example.com/roles/1"]


def test_candidate_urls_does_not_replace_verified_company_domain_with_source_domain():
    urls = _candidate_urls({
        "website": "https://acme.example.com",
        "source_url": "https://jobs.example.com/roles/1",
    })
    assert "https://jobs.example.com/roles/1" not in urls
    assert "https://acme.example.com/" in urls
