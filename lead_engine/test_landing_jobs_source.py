from lead_engine.source_adapters import RssSourceAdapter, create_adapter
from lead_engine.source_definition import SourceDefinition


def test_landing_jobs_atom_adapter_parses_author_company(monkeypatch):
    import lead_engine.source_specific_collectors as source_specific_collectors

    requests = []

    def fake_fetch(request, timeout):
        requests.append(request)
        return b"""<?xml version='1.0' encoding='utf-8'?>
        <feed xmlns='http://www.w3.org/2005/Atom'>
          <entry>
            <id>landing-123</id>
            <title>Senior Software Engineer</title>
            <link href='https://landing.jobs/jobs/senior-software-engineer-123'/>
            <summary>Build software.</summary>
            <author><name>Example Co</name></author>
          </entry>
        </feed>"""

    monkeypatch.setattr(source_specific_collectors, "fetch_url", fake_fetch)
    definition = SourceDefinition(
        name="Landing Jobs",
        provider="Landing Jobs",
        collector_type="atom",
        url="https://landing.jobs/feed?remote=true",
        pagination_type="none",
        max_pages=1,
        max_requests=1,
        max_records=55,
    )

    adapter = create_adapter(definition=definition, timeout=12)

    assert isinstance(adapter.adapter, RssSourceAdapter)
    result = adapter.collect()
    assert len(result) == 1
    assert result[0]["source"] == "Landing Jobs"
    assert result[0]["job_title"] == "Senior Software Engineer"
    assert result[0]["company"] == "Example Co"
    assert requests[0].full_url == "https://landing.jobs/feed?remote=true"
    assert requests[0].headers["Accept"] == "application/atom+xml, application/xml, text/xml"
