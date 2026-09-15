import json

from lead_engine.source_adapters import create_adapter
from lead_engine.source_definition import SourceDefinition


def _definition(name: str, url: str, collector_type: str = "html") -> SourceDefinition:
    return SourceDefinition(
        name=name,
        provider=name,
        collector_type=collector_type,
        url=url,
        pagination_type="none",
        max_pages=1,
        max_requests=1,
        max_records=10,
    )


def test_source_specific_html_adapter_uses_definition_url(monkeypatch):
    import lead_engine.source_specific_collectors as collectors

    requested = []

    def fake_fetch(request, timeout):
        requested.append(request.full_url)
        return b"<html><body>No job links</body></html>"

    monkeypatch.setattr(collectors, "fetch_url", fake_fetch)

    definition = _definition(
        "NoDesk",
        "https://nodesk.co/remote-jobs/",
    )
    adapter = create_adapter(definition=definition, timeout=12)

    adapter.collect()

    assert requested == ["https://nodesk.co/remote-jobs/"]


def test_renamed_html_detail_sources_keep_their_specialized_adapter(monkeypatch):
    import lead_engine.source_specific_collectors as collectors

    requested = []

    def fake_fetch(request, timeout):
        requested.append(request.full_url)
        return b"<html><body></body></html>"

    monkeypatch.setattr(collectors, "fetch_url", fake_fetch)

    definitions = (
        _definition(
            "USA Remote Work",
            "https://www.usaremotework.com/jobs",
        ),
        _definition(
            "Remote Landers",
            "https://remotelanders.com/jobs",
        ),
    )

    for definition in definitions:
        adapter = create_adapter(definition=definition, timeout=12)
        adapter.collect()

    assert requested == [
        "https://www.usaremotework.com/jobs",
        "https://remotelanders.com/jobs",
    ]


def test_json_replacement_sources_do_not_get_html_specialization(monkeypatch):
    import lead_engine.source_specific_collectors as collectors

    requested = []

    def fake_fetch(request, timeout):
        requested.append(request.full_url)
        return b'{"jobs": []}'

    monkeypatch.setattr(collectors, "fetch_url", fake_fetch)

    for name, url in (
        ("Rocketship", "https://remotelanders.com/api/jobs?limit=100&page=1"),
        ("Remote Landers", "https://remotelanders.com/api/jobs?limit=100&page=1"),
    ):
        definition = _definition(name, url, collector_type="json")
        adapter = create_adapter(definition=definition, timeout=12)
        result = adapter.collect()
        assert result.records == []

    assert requested == [
        "https://remotelanders.com/api/jobs?limit=100&page=1",
        "https://remotelanders.com/api/jobs?limit=100&page=1",
    ]


def test_welcome_to_the_jungle_extracts_credentials_from_javascript_env():
    from lead_engine.source_specific_collectors import _extract_algolia_credentials

    raw = b'window.__ENV__={"algoliaApplicationId":"CSEKHVMS53","algoliaSearchApiKey":"0123456789abcdef0123456789abcdef"};'

    assert _extract_algolia_credentials(raw) == (
        "CSEKHVMS53",
        "0123456789abcdef0123456789abcdef",
    )


def test_welcome_to_the_jungle_uses_current_algolia_query_shape(monkeypatch):
    import lead_engine.source_specific_collectors as collectors

    requests = []

    def fake_fetch(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/api/env"):
            return b'window.__ENV__={"algoliaApplicationId":"CSEKHVMS53","algoliaSearchApiKey":"0123456789abcdef0123456789abcdef"};'
        return json.dumps({
            "results": [{
                "hits": [{
                    "objectID": "job-1",
                    "name": "Senior Software Engineer",
                    "organization": {"name": "Example Co", "slug": "example-co"},
                    "slug": "senior-software-engineer",
                    "descriptions": {"en": "Build software."},
                    "office": {"city": "Remote"},
                }]
            }]
        }).encode("utf-8")

    monkeypatch.setattr(collectors, "fetch_url", fake_fetch)

    definition = SourceDefinition(
        name="Welcome to the Jungle",
        provider="Welcome to the Jungle",
        collector_type="json",
        url="https://www.welcometothejungle.com/en/pages/jobs",
        pagination_type="none",
        max_pages=1,
        max_requests=1,
        max_records=100,
    )
    adapter = create_adapter(definition=definition, timeout=12)
    result = adapter.collect()

    assert len(result.records) == 1
    algolia_request = requests[1]
    assert "/1/indexes/*/queries" in algolia_request.full_url
    assert algolia_request.headers["Content-type"] == "application/x-www-form-urlencoded"
    body = json.loads(algolia_request.data.decode("utf-8"))
    assert body["requests"][0]["indexName"] == "wk_cms_jobs_production"
    assert "hitsPerPage=100" in body["requests"][0]["params"]
