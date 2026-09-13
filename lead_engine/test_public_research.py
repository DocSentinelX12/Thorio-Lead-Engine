from __future__ import annotations

from lead_engine import public_research


def test_public_research_records_real_page_provenance(monkeypatch):
    class Response:
        status_code = 200
        encoding = "utf-8"
        headers = {"content-type": "text/html"}
        text = "User-agent: *\nAllow: /"

        def iter_content(self, chunk_size=16384):
            yield b"<html><head><title>Acme Platform</title><meta name='description' content='Enterprise software platform'></head><body><a href='/careers'>Careers</a><p>Acme builds software for enterprise customers and is hiring engineers.</p></body></html>"

    monkeypatch.setattr(public_research.requests, "get", lambda *args, **kwargs: Response())
    public_research._ROBOTS_CACHE.clear()
    public_research._PAGE_CACHE.clear()
    result = public_research.research_public_web({"company": "Acme", "website": "https://acme.example/"})
    assert result["status"] == "evidence_found"
    assert 1 <= result["pages_collected"] <= public_research.MAX_PAGES
    assert result["pages_attempted"] == result["pages_collected"]
    assert len(result["sources"]) == result["pages_attempted"]
    assert result["sources"][0]["url"].startswith("https://acme.example/")
    assert any(fact["field"] == "page_title" for fact in result["raw_pages"][0]["facts"])
    assert result["facts"]["hiring"]
    assert result["fabricated_fields"] == []


def test_public_research_does_not_claim_access_when_robots_disallow(monkeypatch):
    class Response:
        status_code = 200
        text = "User-agent: ThorioLeadResearch\nDisallow: /"

    monkeypatch.setattr(public_research.requests, "get", lambda *args, **kwargs: Response())
    public_research._ROBOTS_CACHE.clear()
    public_research._PAGE_CACHE.clear()
    result = public_research.research_public_web({"company": "Blocked", "website": "https://blocked.example/"})
    assert result["status"] == "no_public_evidence"
    assert result["pages_collected"] == 0
    assert result["raw_pages"][0]["reason"] == "robots_disallowed"
