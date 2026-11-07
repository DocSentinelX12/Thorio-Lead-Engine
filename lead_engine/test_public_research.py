from __future__ import annotations

from lead_engine import public_research


def test_public_research_records_real_page_provenance(monkeypatch):
    class Response:
        status_code = 200
        encoding = "utf-8"
        headers = {"content-type": "text/html"}
        text = "User-agent: *\nAllow: /"
        is_redirect = False
        is_permanent_redirect = False

        def iter_content(self, chunk_size=16384):
            yield b"<html><head><title>Acme Platform</title><meta name='description' content='Enterprise software platform'></head><body><a href='/careers'>Careers</a><p>Acme builds software for enterprise customers and is hiring engineers.</p></body></html>"

    monkeypatch.setattr(public_research, "_public_host", lambda url: (True, "public_address"))
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
        headers = {"content-type": "text/plain"}
        is_redirect = False
        is_permanent_redirect = False

    monkeypatch.setattr(public_research, "_public_host", lambda url: (True, "public_address"))
    monkeypatch.setattr(public_research.requests, "get", lambda *args, **kwargs: Response())
    public_research._ROBOTS_CACHE.clear()
    public_research._PAGE_CACHE.clear()
    result = public_research.research_public_web({"company": "Blocked", "website": "https://blocked.example/"})
    assert result["status"] == "no_public_evidence"
    assert result["pages_collected"] == 0
    assert result["raw_pages"][0]["reason"] == "robots_disallowed"


def test_public_research_allows_safe_www_apex_redirect(monkeypatch):
    calls = []

    class RedirectResponse:
        status_code = 301
        encoding = "utf-8"
        headers = {"Location": "https://nomado24.de/en/remote-jobs/job"}
        is_redirect = True
        is_permanent_redirect = False

    class PageResponse:
        status_code = 200
        encoding = "utf-8"
        headers = {"content-type": "text/html"}
        is_redirect = False
        is_permanent_redirect = False

        def iter_content(self, chunk_size=16384):
            yield b"<html><head><title>Remote DevOps role</title></head><body>Remote engineering role at Acme.</body></html>"

    responses = [RedirectResponse(), PageResponse()]

    def fake_get(url, *args, **kwargs):
        calls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(public_research, "_allowed", lambda url: (True, "robots_checked:public_address"))
    monkeypatch.setattr(public_research, "_throttle", lambda domain: None)
    monkeypatch.setattr(public_research.requests, "get", fake_get)
    public_research._PAGE_CACHE.clear()

    result = public_research._fetch("https://www.nomado24.de/en/remote-jobs/job")

    assert result["status"] == "collected"
    assert calls == [
        "https://www.nomado24.de/en/remote-jobs/job",
        "https://nomado24.de/en/remote-jobs/job",
    ]
    assert result["facts"][0]["value"] == "Remote DevOps role"


def test_public_research_still_blocks_unrelated_redirect_hosts():
    assert public_research._same_site_redirect(
        "https://www.nomado24.de/job",
        "https://nomado24.com/job",
    ) is False
    assert public_research._same_site_redirect(
        "https://www.nomado24.de/job",
        "https://attacker.example/job",
    ) is False
    assert public_research._same_site_redirect(
        "https://www.nomado24.de/job",
        "http://nomado24.de/job",
    ) is False
