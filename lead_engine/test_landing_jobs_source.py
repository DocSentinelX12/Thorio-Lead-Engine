import json

from lead_engine.source_adapters import create_adapter
from lead_engine.source_definition import SourceDefinition


def test_landing_jobs_uses_public_json_endpoint_with_browser_compatible_request(monkeypatch):
    import lead_engine.source_specific_collectors as collectors

    requests = []

    def fake_fetch(request, timeout):
        requests.append(request)
        return json.dumps([
            {
                "id": 123,
                "title": "Senior Software Engineer",
                "company": "Example Co",
                "url": "https://landing.jobs/jobs/senior-software-engineer-123",
                "role_description": "Build software.",
                "city": "Remote",
            }
        ]).encode("utf-8")

    monkeypatch.setattr(collectors, "fetch_url", fake_fetch)
    definition = SourceDefinition(
        name="Landing Jobs",
        provider="Landing Jobs",
        collector_type="json",
        url="https://landing.jobs/api/v1/jobs",
        pagination_type="none",
        max_pages=1,
        max_requests=1,
        max_records=50,
    )

    result = create_adapter(definition=definition, timeout=12).collect()

    assert len(result.records) == 1
    assert result.records[0]["source"] == "Landing Jobs"
    assert result.records[0]["job_title"] == "Senior Software Engineer"
    assert result.records[0]["company"] == "Example Co"
    assert requests[0].full_url == "https://landing.jobs/api/v1/jobs"
    assert requests[0].headers["User-agent"] == "Mozilla/5.0 Thorio-Lead-Engine/1.0"
    assert requests[0].headers["Accept"] == "application/json,text/plain,*/*"
    assert requests[0].headers["Accept-language"] == "en-US,en;q=0.9"
    assert requests[0].headers["Referer"] == "https://landing.jobs/"
    assert requests[0].headers["Origin"] == "https://landing.jobs"
