from .database import LeadDB
from .advanced_agent_logic import company_research


def test_public_research_checkpoint_survives_failure_between_pages(tmp_path, monkeypatch):
    db = LeadDB(data_dir=tmp_path)
    lead = {"fingerprint": "public-page-checkpoint", "company": "Acme", "website": "https://acme.example"}
    db.insert_if_new(lead)

    def fake_research(value, checkpoint=None):
        checkpoint({"pages": [{"url": "https://acme.example/", "status": "collected", "facts": [{"field": "company", "value": "Acme"}]}], "sources": [{"url": "https://acme.example/", "status": "collected"}], "pages_attempted": 1, "pages_collected": 1})
        raise RuntimeError("worker died after first collected page")

    monkeypatch.setattr("lead_engine.advanced_agent_logic.research_public_web", fake_research)

    try:
        company_research({"lead": lead}, type("Ctx", (), {"db": db})())
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected simulated worker failure")

    stored = db.get("public-page-checkpoint")
    checkpoint = stored["company_research"]["public_web_research_checkpoint"]
    assert checkpoint["pages_collected"] == 1
    assert checkpoint["pages"][0]["status"] == "collected"


def test_public_research_checkpoint_is_updated_for_each_page(tmp_path, monkeypatch):
    db = LeadDB(data_dir=tmp_path)
    lead = {"fingerprint": "public-page-sequence", "company": "Acme"}
    db.insert_if_new(lead)
    seen = []

    def fake_research(value, checkpoint=None):
        for count in (1, 2, 3):
            progress = {"pages": [{"url": f"https://acme.example/{i}", "status": "collected"} for i in range(count)], "sources": [], "pages_attempted": count, "pages_collected": count}
            checkpoint(progress)
            seen.append(count)
        return {"status": "evidence_found", "facts": {}, "raw_pages": [], "sources": []}

    monkeypatch.setattr("lead_engine.advanced_agent_logic.research_public_web", fake_research)
    company_research({"lead": lead}, type("Ctx", (), {"db": db})())
    assert seen == [1, 2, 3]
    stored = db.get("public-page-sequence")
    assert stored["company_research"]["public_web_research_checkpoint"]["pages_attempted"] == 3
